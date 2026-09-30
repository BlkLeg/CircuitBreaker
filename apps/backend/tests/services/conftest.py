"""Shared fixtures for the service tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.backup import snapshot


@pytest.fixture(autouse=True)
def _no_host_install_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the snapshot's native config paths at an empty temporary directory.

    Left at /etc, a host with Circuit Breaker installed made snapshot builds copy
    its real (root-only) /etc/circuitbreaker/.env, so these tests passed or
    failed depending on the machine rather than the code.
    """
    host = tmp_path / "no-host-install"
    monkeypatch.setattr(
        snapshot,
        "CONFIG_PATHS",
        {arc: host / Path(src).name for arc, src in snapshot.CONFIG_PATHS.items()},
    )


def _pg_dump_major() -> int | None:
    """Major version of the pg_dump on PATH, or None when there is none."""
    exe = shutil.which("pg_dump")
    if exe is None:
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=False).stdout
    match = re.search(r"(\d+)(?:\.\d+)*", out)
    return int(match.group(1)) if match else None


@pytest.fixture
def pg_dump_matches_server(setup_db: None) -> None:
    """Skip, with the reason, when the local pg_dump is older than the test server.

    pg_dump refuses to dump a newer server ("aborting because of server version
    mismatch"). A host whose client tools come from an installed Circuit Breaker
    (PostgreSQL 15) testing against the dev database (16) failed every real-dump
    test on that, which says nothing about the code under test.
    """
    from app.db.session import engine

    with engine.connect() as conn:
        server = int(conn.exec_driver_sql("SHOW server_version_num").scalar_one()) // 10000
    client = _pg_dump_major()
    if client is not None and client < server:
        pytest.skip(
            f"pg_dump {client} cannot dump PostgreSQL {server}; needs postgresql-client {server}+"
        )
