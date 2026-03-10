"""High-level DuckDB analytics client.

Wraps the engine returned by :func:`db_client.get_engine("analytics")` with a
convenience API so callers never import engine internals.  When DuckDB is not
installed or configured the client falls back gracefully — ``is_available()``
returns ``False`` and ``query()`` routes through the primary SQLite engine.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.db_client import get_engine

_logger = logging.getLogger(__name__)

# Safe SQL identifier: letter or underscore, then alphanumeric or underscore only.
_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_table_name(table: str) -> None:
    """Raise ValueError if table is not a safe SQL identifier (prevents SQL injection)."""
    if not _TABLE_NAME_RE.match(table):
        raise ValueError(f"Invalid table name: {table!r}; must match [a-zA-Z_][a-zA-Z0-9_]*")


def is_available() -> bool:
    """Return ``True`` when the analytics engine is actually DuckDB (not the SQLite fallback)."""
    try:
        engine = get_engine("analytics")
        return engine.dialect.name == "duckdb"
    except Exception:
        return False


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a read-only SQL statement and return rows as a list of dicts."""
    engine = get_engine("analytics")
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = list(result.keys())
        return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    """Execute a write statement (CREATE TABLE, INSERT, etc.)."""
    engine = get_engine("analytics")
    with engine.connect() as conn:
        conn.execute(text(sql), params or {})
        conn.commit()


def ingest_csv(path: str, table: str) -> int:
    """Bulk-load a CSV file into *table* via DuckDB's ``read_csv_auto``.

    Returns the number of rows inserted.  Raises ``RuntimeError`` when DuckDB
    is unavailable — callers should check :func:`is_available` first.
    Raises ``ValueError`` if *table* is not a safe SQL identifier.
    """
    _validate_table_name(table)
    if not is_available():
        raise RuntimeError("DuckDB is not available; cannot ingest CSV")
    engine = get_engine("analytics")
    with engine.connect() as conn:
        # table name is validated above as a safe identifier; dynamic SQL below is not user-controlled.
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
            )
        )
        conn.execute(
            text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
        )
        row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
        conn.commit()
    return row_count
