"""The client encoding every psycopg2 engine asks PostgreSQL for.

QUAR-001 / #162. Until the mono image named `--encoding=UTF8`, its `initdb` ran
with no LANG, so every cluster it created is SQL_ASCII. A psycopg2 connection
that does not request an encoding inherits the server's, and psycopg2 maps
SQL_ASCII to Python's `ascii` codec: the first non-ASCII character a user typed
raised UnicodeEncodeError on INSERT, which breaks "freeform first" for every
name, vendor and note.

A cluster's encoding cannot be changed in place, so upgraded deployments keep
their SQL_ASCII cluster. Requesting UTF8 from the client side fixes them without
a migration: SQL_ASCII performs no conversion, so the UTF-8 bytes are stored and
returned exactly as sent. On a UTF8 cluster the request is a no-op.

`client_encoding` is a startup parameter, so it also survives PgBouncer, which
tracks it per client and re-applies it to every server connection it lends.

Deliberately free of application imports: `app.cli` reaches this before the
application is configured, and `tests/build` loads it by path.
"""

from __future__ import annotations

from typing import Any

#: What psycopg2 sends as the `client_encoding` startup parameter.
PG_CLIENT_ENCODING = "utf8"


def pg_connect_args(**extra: Any) -> dict[str, Any]:
    """`connect_args` for a psycopg2 engine: the UTF8 client encoding plus *extra*.

    Every PostgreSQL `create_engine` in the backend passes this;
    `tests/build/test_postgres_utf8_policy.py` names each one.
    """
    return {**extra, "client_encoding": PG_CLIENT_ENCODING}
