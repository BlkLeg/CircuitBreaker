"""`alembic upgrade head` must succeed against a genuinely empty database.

Every automated suite in this repo builds its schema with
`Base.metadata.create_all()` — `apps/backend/tests/conftest.py` and
`tests/integration/conftest.py` both do, and `tests/integration/conftest.py`
sets `CB_AUTO_MIGRATE=false` on top of that. So until this file existed, nothing
ever ran the migration chain the way a real install runs it, and the only place
the fresh-install path got exercised was a user's machine.

That gap shipped 0105_backup_age_recipient with an unguarded `op.add_column`.
`0001_init` bootstraps a fresh schema straight from live `app.db.models` minus
an explicit `_EXCLUDED_COLUMNS` list, so any column added to the models but not
to that list is already present when the later migration that "adds" it runs.
On a fresh 0.4.0 install the backend died in a restart loop at
`DuplicateColumn: column "backup_age_recipient" of relation "app_settings"
already exists`, and because `deploy/setup.sh` gates nginx behind the backend
health check, the install ended with no web server either.

The two assertions here are the two directions that drift can go:

* the chain reaching head proves no migration re-adds something `0001_init`
  already created (fresh installs work);
* the schema covering every model column proves no column reached the models
  without a migration to add it (upgrades of existing installs work).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.db.models import Base
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from .conftest import TEST_DB_URL

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "apps" / "backend"

# Its own database, not the shared integration one: the chain has to start from
# nothing, and the session-scoped `db_engine` fixture has already populated
# TEST_DB_URL via create_all().
_SCRATCH_DB = f"cb_migration_chain_{os.getpid()}"


def _admin_engine() -> Engine:
    """Connect to the `postgres` maintenance DB — CREATE/DROP DATABASE cannot
    run from inside the database it targets."""
    admin_url = make_url(TEST_DB_URL).set(database="postgres")
    return create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)


@pytest.fixture(scope="module")
def empty_database() -> Iterator[str]:
    # Deliberately no skip guard. This suite is backend-scoped and `make
    # test-backend` provisions the database; a fresh-install check that opts
    # itself out when the database is missing is the same silence that let the
    # 0105 defect reach a release.
    engine = _admin_engine()
    quoted = '"' + _SCRATCH_DB.replace('"', '""') + '"'
    try:
        with engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {quoted}"))
            conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        engine.dispose()

    yield (
        make_url(TEST_DB_URL)
        .set(database=_SCRATCH_DB)
        .render_as_string(hide_password=False)
    )

    engine = _admin_engine()
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
    engine.dispose()


@pytest.fixture(scope="module")
def migrated_database(empty_database: str) -> str:
    """Run the real `alembic upgrade head`, in a subprocess against the scratch DB.

    A subprocess, because `migrations/env.py` binds `db_url` from
    `app.db.session` at import time: in-process this would migrate whichever
    database the test session is already connected to.
    """
    env = {**os.environ, "CB_DB_URL": empty_database, "DATABASE_URL": empty_database}
    env.pop("CB_TEST_DB_URL", None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        "`alembic upgrade head` failed on an empty database — a fresh install of "
        "this build would not start.\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )
    return empty_database


def test_migration_chain_runs_on_an_empty_database(migrated_database: str) -> None:
    """The chain reaches head, and head is the newest revision on disk."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    expected = ScriptDirectory.from_config(
        Config(str(BACKEND_DIR / "alembic.ini"))
    ).get_current_head()

    engine = create_engine(migrated_database)
    try:
        with engine.connect() as conn:
            stamped = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    assert stamped == expected, (
        f"database stamped at {stamped}, newest revision is {expected}"
    )


def test_migrated_schema_covers_every_model_column(migrated_database: str) -> None:
    """A model column with no migration behind it breaks every existing install:
    the code queries it, the upgraded database does not have it."""
    engine = create_engine(migrated_database)
    try:
        inspector = inspect(engine)
        present = {
            table: {column["name"] for column in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }
    finally:
        engine.dispose()

    missing_tables = sorted(
        name for name in Base.metadata.tables if name not in present
    )
    missing_columns = sorted(
        f"{name}.{column.name}"
        for name, table in Base.metadata.tables.items()
        if name in present
        for column in table.columns
        if column.name not in present[name]
    )

    assert not missing_tables, (
        f"models declare tables no migration creates: {missing_tables}"
    )
    assert not missing_columns, (
        f"models declare columns no migration adds: {missing_columns}"
    )
