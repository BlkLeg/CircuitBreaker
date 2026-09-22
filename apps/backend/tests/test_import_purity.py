"""Importing the application must not touch the filesystem.

`--selftest` is run by `cb doctor` and `cb diag bundle` as whatever user
invoked them, from whatever directory they happened to be in, with none of
`conftest.py`'s temp-directory redirection in effect. Three modules used to
`mkdir` a relative, cwd-derived path at import time
(`app.api.assets`, `app.api.static_spa`, `app.db.cve_session`), so importing
the application from a cwd the caller could not write to raised
`PermissionError: 'data'` — exactly what the installer journey's
`runuser -u breaker -- circuit-breaker --selftest` assertion caught.

These tests run in a **subprocess**, deliberately: `conftest.py` sets
`UPLOADS_DIR` and `CB_DATA_DIR` to temp directories before any app module is
imported (see its `pytest_configure`), which is exactly the workaround that
would mask this class if the check ran in-process.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
_START_PY = _BACKEND_SRC / "app" / "start.py"


def _bare_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment `cb doctor` actually runs under: no CB_* redirection."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(_BACKEND_SRC),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra:
        env.update(extra)
    return env


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permission bits")
def test_selftest_passes_from_a_read_only_cwd_with_a_bare_environment(tmp_path: Path) -> None:
    """The exact shape the installer journey's runuser check exercises."""
    ro_dir = tmp_path / "ro"
    ro_dir.mkdir()
    ro_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write
    try:
        result = subprocess.run(
            [sys.executable, str(_START_PY), "--selftest"],
            cwd=ro_dir,
            env=_bare_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        ro_dir.chmod(stat.S_IRWXU)  # restore so tmp_path cleanup can remove it

    assert result.returncode == 0, (
        f"--selftest failed from a read-only cwd:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip().startswith("selftest OK")


def test_resolving_every_selftest_target_writes_nothing_to_cwd(tmp_path: Path) -> None:
    """The stronger invariant: works as any user, in a writable directory too.

    A directory that CAN be written to must still end up empty — resolving
    the self-test's targets should create nothing, anywhere.
    """
    before = set(tmp_path.iterdir())

    result = subprocess.run(
        [sys.executable, str(_START_PY), "--selftest"],
        cwd=tmp_path,
        env=_bare_env({"CB_DB_URL": "postgresql://selftest:dummy@localhost/selftest"}),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"--selftest failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    after = set(tmp_path.iterdir())
    assert after == before, f"--selftest wrote to its cwd: {after - before}"
