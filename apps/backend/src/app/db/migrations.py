"""Lightweight SQL migration runner.

Reads every ``*.sql`` file from the ``migrations/`` subdirectory (next to this
module) in lexicographic order and executes each statement against the provided
SQLAlchemy engine.  All statements are written to be idempotent (``IF NOT
EXISTS``, ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``) so this runner is safe
to call on every application startup.

Design rationale
----------------
SQLAlchemy's ``Base.metadata.create_all()`` handles the initial schema.  These
SQL files capture *additive* changes (new columns, new tables, new indexes) that
are applied on top of an existing database without wiping data.  No down-migrations
are provided; schema changes are additive-only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

_logger = logging.getLogger(__name__)
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations(engine: Engine) -> None:
    """Apply all pending SQL migration files to *engine* in order."""
    sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        _logger.debug("No SQL migration files found in %s", _MIGRATIONS_DIR)
        return

    is_sqlite = engine.dialect.name == "sqlite"

    with engine.connect() as conn:
        for sql_file in sql_files:
            _logger.info("Applying migration: %s", sql_file.name)
            statements = sql_file.read_text(encoding="utf-8")
            for stmt in _iter_statements(statements):
                if is_sqlite and "ADD COLUMN IF NOT EXISTS" in stmt.upper():
                    match = re.search(
                        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)",
                        stmt,
                        re.IGNORECASE,
                    )
                    if match:
                        table_name = match.group(1)
                        column_name = match.group(2)

                        cols = [
                            row[1]
                            for row in conn.execute(
                                text(f"PRAGMA table_info({table_name})")
                            ).fetchall()
                        ]
                        if column_name in cols:
                            continue

                        stmt = re.sub(
                            r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS",
                            "ADD COLUMN",
                            stmt,
                            flags=re.IGNORECASE,
                        )
                try:
                    conn.execute(text(stmt))
                except Exception as exc:
                    _logger.warning(
                        "Migration statement failed (may already be applied): %s — %s",
                        stmt[:80],
                        exc,
                    )
        conn.commit()
    _logger.info("SQL migrations complete (%d file(s))", len(sql_files))


def _iter_statements(sql: str):
    """Yield individual SQL statements split on semicolons, skipping blanks/comments."""
    for raw in sql.split(";"):
        stmt = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("--")
        ).strip()
        if stmt:
            yield stmt
