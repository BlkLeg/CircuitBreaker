"""Regression tests for the SCHEDULED daily pg_dump backup (B11, second half).

``db_backup.backup_postgres`` is registered as the daily ``db_backup`` job in
main.py:1017 and is also reachable from ``POST /admin/db/backup`` (admin_db.py:153).
It shipped with exactly the shape B11 describes::

    proc = subprocess.run(["pg_dump", ...], capture_output=True, check=True)
    with gzip.open(out_path, "wb") as f:
        f.write(proc.stdout)

which materialises the ENTIRE dump as one Python bytes object before a byte of it is
compressed. On a 1 GB database inside the 2 GB mono container that is an OOM-kill, on
a daily schedule — the snapshot builder that got the first half of this fix runs no
more often than this job does.

None of these tests need Postgres: they put a fake ``pg_dump`` first on PATH, which is
how the real binary is resolved (``shutil.which`` and the child's own exec both read
PATH out of ``os.environ``), so ``backup_postgres`` runs unmodified — real fork/exec,
real pipe, real streaming.
"""

from __future__ import annotations

import os
import subprocess
import time
import tracemalloc
from pathlib import Path

import pytest

from app.services import db_backup

# What the fake dump emits, and the ceiling the streaming implementation must stay under.
# The gap has to be wide enough that ordinary interpreter churn during the backup cannot
# close it, and narrow enough that buffering the dump whole cannot hide under it:
# 64 MiB dumped against a 16 MiB ceiling is a 4x margin in both directions.
_DUMP_BYTES = 64 * 1024 * 1024
_PEAK_CEILING_BYTES = 16 * 1024 * 1024


def _install_fake_pg_dump(
    monkeypatch: pytest.MonkeyPatch,
    bin_dir: Path,
    *,
    payload_bytes: int = 4096,
    exit_code: int = 0,
    stderr_text: str = "",
    source: str = "/dev/zero",
) -> None:
    """Put a fake ``pg_dump`` first on PATH."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "pg_dump"
    script.write_text(
        "#!/bin/sh\n"
        f'[ -n "{stderr_text}" ] && printf %s "{stderr_text}" >&2\n'
        f"head -c {payload_bytes} {source}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture()
def backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module-level BACKUP_DIR at a scratch directory."""
    d = tmp_path / "backups"
    monkeypatch.setattr(db_backup, "BACKUP_DIR", d)
    return d


def test_backup_postgres_streams_the_dump_instead_of_buffering_it(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B11: peak Python heap during the daily backup must not scale with the dump size.

    tracemalloc sees the bytes object ``subprocess.run(capture_output=True)`` builds,
    because large allocations pass through the traced raw allocator. Streaming the pipe
    into gzip in fixed blocks keeps the peak at block size; buffering the dump whole puts
    the entire database on the heap at once, which is the OOM.
    """
    # Warm-up run with a trivial payload. The first call reaches _prune_old_backups,
    # which imports app.db.models and builds the SQLAlchemy session factory — tens of
    # MiB of one-time allocation that has nothing to do with the size of the dump and
    # would otherwise sit inside the measured window. Measure the second call.
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin", payload_bytes=1024)
    db_backup.backup_postgres()
    for leftover in backup_dir.glob("cb-*"):
        leftover.unlink()

    _install_fake_pg_dump(monkeypatch, tmp_path / "bin", payload_bytes=_DUMP_BYTES)

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        db_backup.backup_postgres()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    written = list(backup_dir.glob("cb-*.sql.gz"))
    assert len(written) == 1, f"expected exactly one backup file, got {written}"
    assert peak < _PEAK_CEILING_BYTES, (
        f"peak heap was {peak / 1024 / 1024:.1f} MiB while dumping "
        f"{_DUMP_BYTES / 1024 / 1024:.0f} MiB — the scheduled backup is buffering "
        "pg_dump output in memory instead of streaming it, which OOMs the 2 GB mono "
        "container on a real database"
    )


def test_backup_postgres_never_pipes_stderr(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stderr must be a FILE, and stdout must be a pipe this code drains itself.

    Two defects in one assertion. ``capture_output=True`` reaches Popen as
    ``stderr=PIPE``, so restoring B11's buffered form fails here. And the obvious
    "just add stderr=PIPE" rewrite deadlocks pg_dump the first time it is chatty:
    draining stdout to EOF while stderr sits in an undrained 64 KB pipe blocks the
    child forever, and a hung daily job is a backup that silently stops existing.
    """
    seen: list[dict[str, object]] = []
    real_popen = subprocess.Popen

    def spy(*args: object, **kwargs: object) -> subprocess.Popen:  # type: ignore[type-arg]
        seen.append(dict(kwargs))
        return real_popen(*args, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(subprocess, "Popen", spy)
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin", stderr_text="NOTICE: chatty")

    db_backup.backup_postgres()

    assert seen, "backup_postgres no longer launches pg_dump through subprocess.Popen"
    kwargs = seen[0]
    assert kwargs.get("stdout") is subprocess.PIPE, (
        "pg_dump stdout is not a pipe — the dump is not being streamed"
    )
    stderr = kwargs.get("stderr")
    assert stderr is not subprocess.PIPE, (
        "pg_dump stderr is a PIPE. Either capture_output=True is back (B11: the whole "
        "dump lands on the heap), or stderr was piped without a reader (deadlock)."
    )
    assert hasattr(stderr, "fileno"), f"pg_dump stderr must be a real file, got {stderr!r}"


def test_failed_backup_leaves_no_half_written_archive(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A dump that dies mid-stream must not leave a file the restore path will trust.

    Streaming means bytes are on disk before the exit status is known. If the partial
    output keeps the ``cb-*.sql.gz`` name it becomes ``latest_backup_info``'s answer and
    the newest thing retention keeps — an operator restores from a truncated dump and
    finds out then. Write to a name nothing globs, rename only after a clean exit.
    """
    _install_fake_pg_dump(
        monkeypatch,
        tmp_path / "bin",
        payload_bytes=1024 * 1024,
        exit_code=1,
        stderr_text="FATAL: database does not exist",
    )

    with caplog.at_level("ERROR"):
        db_backup.backup_postgres()

    assert list(backup_dir.glob("cb-*.sql.gz")) == [], "a failed dump was left in place"
    assert list(backup_dir.glob("*.part")) == [], "partial dump not cleaned up"
    assert "database does not exist" in caplog.text, (
        "pg_dump's stderr never reached the log — an operator sees a failed backup with "
        "no reason, which is how a broken backup goes unnoticed for a month"
    )


def test_stale_partial_dumps_are_swept(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OOM-killed backup leaves its partial behind; the next run must clear it.

    SIGKILL runs no ``finally``. Without a sweep every kill leaks a partial dump the
    size of the database onto the same volume pgdata lives on, forever.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stale = backup_dir / "cb-20200101_000000.sql.gz.part"
    stale.write_bytes(b"x" * 4096)
    old = 1_600_000_000
    os.utime(stale, (old, old))
    fresh = backup_dir / "cb-20990101_000000.sql.gz.part"
    fresh.write_bytes(b"x" * 4096)
    stale_err = backup_dir / "cb-20200101_000000.err"
    stale_err.write_bytes(b"FATAL: ...")
    os.utime(stale_err, (old, old))

    # A finished backup, older than the sweep cutoff but well inside the 30-day retention
    # window _prune_old_backups enforces. The sweep's globs must never reach a restorable
    # file.
    keeper = backup_dir / "cb-20200101_000000.sql.gz"
    keeper.write_bytes(b"a real backup")
    sweepable_age = time.time() - 7 * 3600
    os.utime(keeper, (sweepable_age, sweepable_age))

    _install_fake_pg_dump(monkeypatch, tmp_path / "bin")
    db_backup.backup_postgres()

    assert not stale.exists(), "a stale partial dump from a killed run was never swept"
    assert fresh.exists(), "the sweep removed a partial that could belong to a live run"
    assert not stale_err.exists(), "a stale pg_dump stderr file from a killed run was never swept"
    assert keeper.exists(), "the sweep deleted a finished, restorable backup"
