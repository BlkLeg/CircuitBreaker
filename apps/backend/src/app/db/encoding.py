"""The client encoding every libpq-backed PostgreSQL connection must declare.

A libpq session's `client_encoding` defaults to the *server's* encoding, and a
cluster initialised under the POSIX locale is `SQL_ASCII`. psycopg2 maps that to
Python's `ascii` codec, so every bind parameter carrying a single non-ASCII
character — an em dash in a generated name, an accented hostname, any freeform
text a user types — fails at flush with `'ascii' codec can't encode character`.

That is exactly what the mono image produced from v0.4.4 on: its runtime base
moved from `python:*-slim` (which sets `LANG=C.UTF-8`) to `debian:12-slim`
(which sets no locale), and `docker/10-init-postgres.sh` ran `initdb` with no
explicit encoding. The image and the init script now pin UTF-8 for new
clusters, but a deployment that was initialised in between already has a
`SQL_ASCII` cluster, and an encoding cannot be changed in place. Declaring UTF-8
on the client side is what makes those installs work without a dump and
reload: against a `SQL_ASCII` server PostgreSQL performs no conversion and
stores the UTF-8 bytes as given, and against a UTF-8 server this is a no-op.

Passed as a libpq connection option rather than as SQLAlchemy's psycopg2-only
`client_encoding=` engine argument, so it holds for any libpq driver the URL
names and survives pgbouncer, which forwards `client_encoding` as a tracked
startup parameter. asyncpg does not use libpq and always negotiates UTF-8.
"""

from __future__ import annotations

from typing import Final

CLIENT_ENCODING: Final = "UTF8"

# Merge into `connect_args` for every `create_engine` on a PostgreSQL URL.
LIBPQ_CONNECT_ARGS: Final[dict[str, str]] = {"client_encoding": CLIENT_ENCODING}


def libpq_connect_args(**extra: object) -> dict[str, object]:
    """`connect_args` for a libpq-backed engine: the pinned encoding plus `extra`."""
    return {**LIBPQ_CONNECT_ARGS, **extra}
