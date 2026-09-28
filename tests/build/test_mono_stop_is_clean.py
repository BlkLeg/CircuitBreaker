"""A mono container must be able to stop cleanly.

supervisord runs as root (docker/supervisord.mono.conf) and every program it
supervises runs as `breaker`. Compose starts the mono service with
`cap_drop: [ALL]`. A root process without CAP_KILL cannot signal a process
owned by another uid. So on `docker stop` supervisord's `os.kill(pid,
SIGTERM)` raised `PermissionError: [Errno 1] Operation not permitted` for
every program, and it logged `CRIT unknown problem killing <prog>`. Nothing
received SIGTERM. Docker SIGKILLed the lot 10 seconds later, and Postgres ran
crash recovery ("database system was not properly shut down") after every
stop, upgrade and recreate.

Two properties, both derived from the files rather than restated here:

1. Every compose service running the mono image with `cap_drop: ALL` adds
   back `KILL`.
2. Its `stop_grace_period` exceeds the largest `stopwaitsecs` any supervised
   program is given. Otherwise Docker's timer, 10s by default, cuts off a
   program supervisord is still correctly waiting on.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MONO_IMAGE = "ghcr.io/blkleg/circuitbreaker"
MONO_DOCKERFILE = "Dockerfile.mono"
SUPERVISORD_CONFS = (
    ROOT / "docker" / "supervisord.mono.conf",
    # The composed E2E mounts this over the mono config (see its compose file).
    ROOT / "apps" / "agent" / "e2e" / "supervisord-e2e.conf",
)
#: supervisord's own default when a program sets no stopwaitsecs.
SUPERVISORD_DEFAULT_STOPWAITSECS = 10
_SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "build", ".claude"}
_DURATION = re.compile(r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+)s)?$")


def _compose_files() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*compose*.y*ml")):
        rel = path.relative_to(ROOT)
        if _SKIP_DIRS.intersection(rel.parts[:-1]) or rel.parts[0] == ".github":
            continue
        found.append(path)
    return found


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _effective(path: Path, name: str, depth: int = 0) -> dict[str, Any]:
    """The service as compose resolves `extends`: sequences such as cap_add
    merge, scalars from the extending service win."""
    spec = dict(_load(path).get("services", {}).get(name) or {})
    extends = spec.pop("extends", None)
    if not extends or depth > 5:
        return spec
    if isinstance(extends, str):
        base_path, base_name = path, extends
    else:
        base_path = (
            (path.parent / extends["file"]).resolve() if "file" in extends else path
        )
        base_name = extends["service"]
    merged = _effective(base_path, base_name, depth + 1)
    for key, value in spec.items():
        if key in {"cap_add", "cap_drop"} and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
        else:
            merged[key] = value
    return merged


def _runs_mono(spec: dict[str, Any]) -> bool:
    image = str(spec.get("image", ""))
    build = spec.get("build")
    dockerfile = build.get("dockerfile", "") if isinstance(build, dict) else ""
    return MONO_IMAGE in image or Path(dockerfile).name == MONO_DOCKERFILE


def _mono_services() -> list[tuple[str, dict[str, Any]]]:
    services = []
    for path in _compose_files():
        for name in _load(path).get("services") or {}:
            spec = _effective(path, name)
            if _runs_mono(spec):
                services.append((f"{path.relative_to(ROOT)}:{name}", spec))
    return services


def _seconds(value: str) -> int:
    match = _DURATION.match(str(value).strip())
    assert match and any(match.groupdict().values()), f"unparseable duration {value!r}"
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["h"] * 3600 + parts["m"] * 60 + parts["s"]


def _max_stopwaitsecs() -> int:
    longest = 0
    for conf in SUPERVISORD_CONFS:
        parser = configparser.RawConfigParser(inline_comment_prefixes=(";",))
        parser.read(conf, encoding="utf-8")
        programs = [s for s in parser.sections() if s.startswith("program:")]
        assert programs, f"{conf} defines no programs; the parser is blind"
        for section in programs:
            longest = max(
                longest,
                parser.getint(
                    section, "stopwaitsecs", fallback=SUPERVISORD_DEFAULT_STOPWAITSECS
                ),
            )
    return longest


def _hardened(spec: dict[str, Any]) -> bool:
    return "ALL" in [str(c).upper() for c in spec.get("cap_drop") or []]


def test_mono_services_are_found() -> None:
    """Positive control: the root deployment file and the composed E2E overlay."""
    names = [name for name, _ in _mono_services()]
    assert "docker-compose.yml:circuitbreaker" in names, names
    assert "apps/agent/e2e/docker-compose.yml:circuitbreaker" in names, names
    assert all(_hardened(spec) for _, spec in _mono_services()), names


def test_root_supervisord_can_signal_breaker_programs() -> None:
    missing = [
        name
        for name, spec in _mono_services()
        if _hardened(spec)
        and "KILL" not in [str(c).upper() for c in spec.get("cap_add") or []]
    ]
    assert not missing, (
        "cap_drop: ALL without cap_add: KILL leaves root supervisord unable to "
        f"SIGTERM its breaker-owned programs on stop: {missing}"
    )


def test_stop_grace_period_outlasts_supervisord() -> None:
    longest = _max_stopwaitsecs()
    assert longest >= 30, (
        f"max stopwaitsecs parsed as {longest}; postgres alone asks 30"
    )
    short = []
    for name, spec in _mono_services():
        if not _hardened(spec):
            continue
        grace = spec.get("stop_grace_period")
        seconds = _seconds(grace) if grace is not None else 10
        if seconds <= longest:
            short.append(f"{name}: stop_grace_period={grace!r} ({seconds}s)")
    assert not short, (
        f"supervisord waits up to {longest}s for a program to stop; Docker must "
        f"wait longer or it SIGKILLs mid-shutdown: {short}"
    )
