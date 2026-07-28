"""Self-update: binary manifest lookup and Redis-queued update triggers.

The manifest and binaries themselves are populated by the packaging build
step (apps/agent's Makefile target, Task 17) — this module only reads them."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

AGENT_BINARIES_DIR = Path(os.getenv("CB_AGENT_BINARIES_DIR", "/opt/circuitbreaker/agent-binaries"))

# version/os_name/arch reach binary_path() straight from an unauthenticated
# URL (GET /binary/{version}/{os}/{arch}) — reject anything but a plain
# identifier segment before it's anywhere near a filesystem path.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_manifest() -> dict:
    path = AGENT_BINARIES_DIR / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


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


def latest_version() -> str | None:
    manifest = load_manifest()
    if not manifest:
        return None
    return sorted(manifest.keys())[-1]


async def request_update(
    agent_id: int, *, version: str, sha256: str, arch: str, os_name: str
) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot queue an agent update")
    payload = json.dumps({"version": version, "sha256": sha256, "arch": arch, "os": os_name})
    await r.set(f"agent_pending_update:{agent_id}", payload)


async def pop_pending_update(agent_id: int) -> dict | None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    key = f"agent_pending_update:{agent_id}"
    val = await r.get(key)
    if val is None:
        return None
    await r.delete(key)
    return json.loads(val)
