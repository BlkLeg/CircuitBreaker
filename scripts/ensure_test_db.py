#!/usr/bin/env python3
"""
Ensure the integration-test database exists, creating it only if absent.

Run from the repo root with the project venv:
    .venv/bin/python scripts/ensure_test_db.py [DB_URL]

DB_URL defaults to $CB_TEST_DB_URL, then to the local dev Postgres
(postgresql://breaker:breaker@localhost:5432/circuitbreaker_test) — the same
default tests/integration/conftest.py falls back to.

Why a Python helper instead of `docker exec ... psql`: the Makefile supports two
dependency modes — `deps-up` (Postgres in the circuitbreaker-postgres-1
container) and `deps-native-up` (systemd Postgres). Both listen on
localhost:5432 with the same credentials, so connecting over TCP with the venv's
driver works for either one, while `docker exec` only works for the first and
`psql` is not guaranteed to be installed on the host at all.

This only ever CREATEs. It never drops: the session-scoped db_engine fixture in
tests/integration/conftest.py already does drop_all()/create_all() on the schema,
so wiping the database here would be redundant and would throw away any
hand-loaded fixture data a developer left behind.
"""

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError

DEFAULT_URL = "postgresql://breaker:breaker@localhost:5432/circuitbreaker_test"


def main() -> int:
    url = make_url(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("CB_TEST_DB_URL") or DEFAULT_URL
    )
    dbname = url.database
    if not dbname:
        print(
            f"ERROR: no database name in URL {url.render_as_string(hide_password=True)}",
            file=sys.stderr,
        )
        return 1

    # CREATE DATABASE cannot run from inside the database being created, so
    # connect to the always-present `postgres` maintenance database instead.
    admin_url = url.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)

    try:
        with engine.connect() as conn:
            # Postgres has no CREATE DATABASE IF NOT EXISTS, so probe the catalog first.
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": dbname},
            ).scalar()
            if exists:
                print(f"Test database '{dbname}' already exists.")
                return 0

            # The name is quoted rather than bound: CREATE DATABASE takes an
            # identifier, and identifiers cannot be parameterised.
            quoted = '"' + dbname.replace('"', '""') + '"'
            try:
                conn.execute(text(f"CREATE DATABASE {quoted}"))
            except ProgrammingError as exc:
                # A parallel `make test` may have won the race between the probe
                # and the CREATE; someone else creating it is still success.
                if "already exists" not in str(exc):
                    raise
                print(f"Test database '{dbname}' already exists.")
                return 0
            print(f"Created test database '{dbname}'.")
            return 0
    except OperationalError as exc:
        print(
            f"ERROR: cannot reach Postgres at {admin_url.render_as_string(hide_password=True)}\n"
            f"  {exc.orig}\n"
            "Start the dependencies first: `make deps-up` (Docker) or `make deps-native-up` (systemd).",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
