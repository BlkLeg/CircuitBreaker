"""Self-update: binary manifest lookup and Redis-queued update triggers.

The manifest and binaries themselves are populated by the packaging build
step (apps/agent's Makefile target, Task 17) — this module only reads them."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

AGENT_BINARIES_DIR = Path(os.getenv("CB_AGENT_BINARIES_DIR", "/opt/circuitbreaker/agent-binaries"))

# version/os_name/arch reach binary_path() straight from an unauthenticated
# URL (GET /binary/{version}/{os}/{arch}) — reject anything but a plain
# identifier segment before it's anywhere near a filesystem path.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")

Manifest = dict[str, dict[str, str]]


def load_manifest() -> Manifest:
    path = AGENT_BINARIES_DIR / "manifest.json"
    if not path.exists():
        return {}
    return cast(Manifest, json.loads(path.read_text()))


def get_binary_sha256(version: str, os_name: str, arch: str) -> str | None:
    return load_manifest().get(version, {}).get(f"{os_name}-{arch}")


def binary_path(version: str, os_name: str, arch: str) -> Path:
    """Raises ValueError for any segment that isn't a plain identifier or
    that would resolve outside AGENT_BINARIES_DIR (path traversal) — the
    regex above already excludes '/', but the resolve()/is_relative_to()
    check is the authoritative guard (e.g. against a bare '..' segment)."""
    for segment in (version, os_name, arch):
        if not _SAFE_SEGMENT.match(segment) or segment in (".", ".."):
            raise ValueError(f"invalid path segment: {segment!r}")

    base = AGENT_BINARIES_DIR.resolve()
    path = (base / version / f"cb-agent-{os_name}-{arch}").resolve()
    if not path.is_relative_to(base):
        raise ValueError("resolved binary path escapes AGENT_BINARIES_DIR")
    return path


_SEMVER_COMPONENT = re.compile(r"\d+")


def semver_key(version: str) -> tuple[int, ...]:
    """Sort key that orders dotted version strings numerically per
    component (e.g. "1.10.0" > "1.9.0"), unlike a plain lexicographic string
    sort — where "1.10.0" < "1.9.0" because "1" < "9" at the first differing
    character. Each dot-separated component is read for its leading run of
    digits; a component with no leading digits (e.g. a "-rc1" suffix glued
    onto the last segment) contributes 0 for that position. This is
    deliberately not a full SemVer 2.0 precedence implementation (pre-release/
    build-metadata ordering) — the packaging step (Task 17) only ever
    produces plain x.y.z tags, so component-wise numeric comparison is
    sufficient."""
    return tuple(
        int(m.group()) if (m := _SEMVER_COMPONENT.match(part)) else 0
        for part in version.split(".")
    )


def latest_version(*, os_name: str | None = None, arch: str | None = None) -> str | None:
    """Returns the highest semver-ordered version key in the manifest.

    When os_name and arch are both given, only versions that actually carry
    a `{os_name}-{arch}` binary are considered — an update auto-selected for
    an agent must be one that agent can actually install, not merely the
    globally-newest version. Returns None if the manifest is empty, or (when
    os_name/arch are given) if no version has a matching binary — the caller
    must treat that as "no compatible update available" rather than an
    error."""
    manifest = load_manifest()
    if not manifest:
        return None

    candidates: list[str] = list(manifest.keys())
    if os_name is not None and arch is not None:
        key = f"{os_name}-{arch}"
        candidates = [v for v in candidates if key in manifest[v]]
        if not candidates:
            return None

    return max(candidates, key=semver_key)


async def request_update(
    agent_id: int, *, version: str, sha256: str, arch: str, os_name: str
) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot queue an agent update")
    payload = json.dumps({"version": version, "sha256": sha256, "arch": arch, "os": os_name})
    await r.set(f"agent_pending_update:{agent_id}", payload)


async def pop_pending_update(agent_id: int) -> dict[str, Any] | None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    key = f"agent_pending_update:{agent_id}"
    val = await r.get(key)
    if val is None:
        return None
    await r.delete(key)
    return cast(dict[str, Any], json.loads(val))
