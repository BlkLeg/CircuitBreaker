"""Dockerfile.mono assembles the application exactly as the native build does."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile.mono").read_text(encoding="utf-8")
SUPERVISOR = (ROOT / "docker" / "supervisord.mono.conf").read_text(encoding="utf-8")
MIGRATE = (ROOT / "docker" / "20-migrate.sh").read_text(encoding="utf-8")


def test_the_image_builds_the_tree_with_the_shared_script() -> None:
    assert "scripts/pbs_tree.py" in DOCKERFILE
    assert "packaging/python-build-standalone.pin" in DOCKERFILE
    assert "pip install" not in DOCKERFILE, "dependencies come from the tree, not a second pip install"
    assert "pyinstaller" not in DOCKERFILE.lower()


def test_the_runtime_stage_is_debian_slim_and_starts_as_root() -> None:
    stages = re.findall(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", DOCKERFILE, re.M)
    assert stages[-1][0].startswith("debian:12-slim"), stages[-1]
    assert not re.search(r"^USER\s", DOCKERFILE, re.M), "the mono image starts as root on purpose (CLAUDE.md)"
    assert "CMD curl -fsS --max-time 4 http://127.0.0.1:8080/api/v1/livez" in DOCKERFILE


def test_every_python_process_runs_through_the_tree() -> None:
    commands = re.findall(r"^command=(.+)$", SUPERVISOR, re.M)
    python_commands = [c for c in commands if "python" in c or "uvicorn" in c]
    assert python_commands, "supervisord runs no Python programs?"
    for command in python_commands:
        assert "/opt/circuitbreaker/bin/cb-python" in command, command
    assert "directory=/app/backend" not in SUPERVISOR
    assert "/opt/circuitbreaker/bin/cb-python -m alembic" in MIGRATE
