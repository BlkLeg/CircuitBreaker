"""E2E supervisord overlay must track docker/supervisord.mono.conf Python cmds.

``apps/agent/e2e/docker-compose.yml`` mounts ``supervisord-e2e.conf`` over the
mono image's supervisord config. When Dockerfile.mono / supervisord.mono.conf
moved Python onto ``/opt/circuitbreaker/bin/cb-python``, the overlay still
called ``/usr/local/bin/uvicorn`` and ``/usr/bin/python``, so every e2e
container exited workers with 127 and never answered bootstrap/status.

The only intentional drift is uvicorn ``--workers 1`` (vault-rotation
workaround documented on the compose volume mount).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MONO = (ROOT / "docker" / "supervisord.mono.conf").read_text(encoding="utf-8")
E2E = (ROOT / "apps" / "agent" / "e2e" / "supervisord-e2e.conf").read_text(
    encoding="utf-8"
)

_PROGRAM_COMMAND = re.compile(
    r"^\[program:(?P<name>[^\]]+)\]\n(?:(?!^\[).*\n)*?^command=(?P<cmd>.+)$",
    re.M,
)
_CB_PYTHON = "/opt/circuitbreaker/bin/cb-python"
_WORKERS = re.compile(r"--workers\s+\d+")


def _python_program_commands(text: str) -> dict[str, str]:
    """Map supervisord program name → command line for Python/uvicorn programs."""
    out: dict[str, str] = {}
    for match in _PROGRAM_COMMAND.finditer(text):
        name = match.group("name")
        cmd = match.group("cmd").strip()
        if "python" in cmd or "uvicorn" in cmd:
            out[name] = cmd
    return out


def _normalize_workers(command: str) -> str:
    """Collapse uvicorn worker count so mono (--workers 2) and e2e (1) compare equal."""
    return _WORKERS.sub("--workers N", command)


def test_e2e_python_programs_use_cb_python() -> None:
    commands = _python_program_commands(E2E)
    assert commands, "e2e supervisord runs no Python programs?"
    for name, command in commands.items():
        assert _CB_PYTHON in command, f"{name}: {command}"
        assert "/usr/local/bin/uvicorn" not in command, name
        assert "/usr/bin/python" not in command, name
    assert "directory=/app/backend" not in E2E


def test_e2e_overlay_python_commands_match_mono_except_workers_count() -> None:
    mono = _python_program_commands(MONO)
    e2e = _python_program_commands(E2E)
    assert set(e2e) == set(mono), (
        f"program set drift: e2e-only={sorted(set(e2e) - set(mono))} "
        f"mono-only={sorted(set(mono) - set(e2e))}"
    )
    assert "--workers 1" in e2e["backend-api"]
    assert "--workers 2" in mono["backend-api"]
    for name in mono:
        assert _normalize_workers(e2e[name]) == _normalize_workers(mono[name]), name
