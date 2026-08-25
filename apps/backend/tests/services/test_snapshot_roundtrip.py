"""Snapshot → restore → the data is there.

INC-15 shipped a backup nothing could restore. Every other test in this batch checks a
refusal path; this one checks that the happy path actually works end to end: build a
snapshot of the suite's live Postgres, verify it, then replay its dump into a scratch
database on that same server and read the row back out.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import text

from app.db.session import db_url, engine
from app.services.backup.snapshot import build_snapshot
from app.services.backup.verify import verify_archive

# Same reasoning as tests/services/test_snapshot.py's `requires_pg_dump`: both binaries
# ship in the postgresql-client OS package, not in the Python dependency set, so a
# workstation without them would fail here for a reason that says nothing about the code
# under test. `createdb`/`dropdb` are deliberately NOT used — the scratch database is
# created over the connection SQLAlchemy already holds, which is two fewer binaries to
# depend on.
requires_pg_client = pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("psql") is None,
    reason="pg_dump/psql not installed (postgresql-client); required to round-trip a snapshot",
)

SCRATCH_DB = "cb_roundtrip_scratch"


def _libpq_url(database: str) -> str:
    """Rewrite the SQLAlchemy URL into a libpq one pointing at `database`."""
    parsed = urlparse(db_url)
    scheme = parsed.scheme.split("+", 1)[0]
    return urlunparse((scheme, parsed.netloc, f"/{database}", "", "", ""))


def _psql(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["psql", "-d", _libpq_url(SCRATCH_DB), *args],
        input=stdin,
        text=True,
        capture_output=True,
        env={**os.environ, "PGPASSWORD": urlparse(db_url).password or ""},
    )


def _drop_scratch() -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)'))


def _replay_into_scratch(sql: str) -> str:
    """Restore `sql` into a throwaway database and read the probe row back."""
    _drop_scratch()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{SCRATCH_DB}"'))
    try:
        restored = _psql("-v", "ON_ERROR_STOP=1", stdin=sql)
        assert restored.returncode == 0, restored.stderr

        check = _psql("-tAc", "SELECT note FROM roundtrip_probe WHERE id = 1")
        return check.stdout.strip()
    finally:
        _drop_scratch()


@requires_pg_client
@pytest.mark.asyncio
async def test_snapshot_restores_into_a_scratch_database(setup_db: None, tmp_path: Path) -> None:
    """Uses the Postgres the suite already runs against; restores into a scratch database."""
    # Written on a genuinely committing connection: pg_dump reads the database over its
    # own connection, so anything left inside the `db_session` fixture's rolled-back
    # SAVEPOINT would be invisible to the dump.
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS roundtrip_probe (id int primary key, note text)")
        )
        conn.execute(
            text("INSERT INTO roundtrip_probe VALUES (1, 'survives') ON CONFLICT DO NOTHING")
        )

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "probe.txt").write_text("upload survives", encoding="utf-8")

    try:
        archive = await build_snapshot(
            backup_dir=tmp_path / "out",
            db_url=db_url,
            vault_key="a-vault-key",
            uploads_dir=uploads,
            cb_version="1.0.0",
        )

        manifest = verify_archive(archive, installed_version="1.0.0")
        assert manifest["format_version"] == 1

        extracted = tmp_path / "x"
        with tarfile.open(archive) as tf:
            tf.extractall(extracted)  # noqa: S202 — archive this test just built
        inner = next(extracted.iterdir())

        sql = gzip.decompress((inner / "db.sql.gz").read_bytes()).decode()
        assert "roundtrip_probe" in sql
        assert "survives" in sql
        assert (inner / "uploads" / "probe.txt").read_text() == "upload survives"

        assert _replay_into_scratch(sql) == "survives"
    finally:
        # The probe table was committed for real, so it outlives the test unless dropped.
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS roundtrip_probe"))
