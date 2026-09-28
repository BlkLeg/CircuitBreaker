"""Non-ASCII text must round-trip even on a SQL_ASCII cluster.

Mono images from v0.4.4 initialised PostgreSQL under the POSIX locale, which
yields a SQL_ASCII cluster; libpq then defaults the session's client encoding
to SQL_ASCII and psycopg2 refuses to encode any non-ASCII bind parameter. The
composed agent E2E caught it as the zero-configuration discovery bootstrap
never creating a profile: its generated name, "<agent> — <cidr>", carries an
em dash. Those clusters cannot be re-encoded in place, so the application's own
connections have to declare UTF-8 (`app.db.encoding`).

These tests build a real SQL_ASCII database in the suite's PostgreSQL rather
than asserting on a connection argument, so they fail for the actual defect.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import StatementError

from app.db.encoding import CLIENT_ENCODING, LIBPQ_CONNECT_ARGS, libpq_connect_args

_NON_ASCII = "agent-1 — 10.77.0.0/24 · café"


@pytest.fixture
def sql_ascii_url() -> Iterator[str]:
    """A throwaway SQL_ASCII database on the suite's server, dropped afterwards."""
    admin_url = make_url(os.environ["CB_DB_URL"])
    name = f"cb_sql_ascii_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE \"{name}\" ENCODING 'SQL_ASCII' "
                    "LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
                )
            )
        yield admin_url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _round_trip(url: str, **engine_kwargs: object) -> str:
    engine = create_engine(url, **engine_kwargs)
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SHOW server_encoding")).scalar() == "SQL_ASCII"
            conn.execute(text("CREATE TEMP TABLE t (name text)"))
            conn.execute(text("INSERT INTO t (name) VALUES (:name)"), {"name": _NON_ASCII})
            return str(conn.execute(text("SELECT name FROM t")).scalar_one())
    finally:
        engine.dispose()


def test_without_the_pinned_encoding_a_sql_ascii_cluster_rejects_non_ascii(sql_ascii_url):
    """The defect itself, so the fixture is proven to reproduce it."""
    with pytest.raises((StatementError, UnicodeEncodeError), match="ascii"):
        _round_trip(sql_ascii_url)


def test_with_the_pinned_encoding_non_ascii_round_trips_on_sql_ascii(sql_ascii_url):
    assert _round_trip(sql_ascii_url, connect_args=libpq_connect_args()) == _NON_ASCII


def test_the_application_engine_declares_utf8():
    from app.db.session import engine

    with engine.connect() as conn:
        assert conn.execute(text("SHOW client_encoding")).scalar() == CLIENT_ENCODING


def test_extra_connect_args_keep_the_encoding():
    assert libpq_connect_args(connect_timeout=3) == {**LIBPQ_CONNECT_ARGS, "connect_timeout": 3}
