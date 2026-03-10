"""Fix JSONB columns whose server defaults blocked the 0026 type cast.

Revision ID: 0029_fix_jsonb_column_defaults
Revises: 0028_api_tokens
Create Date: 2026-03-10

Migration 0026 attempted to cast all Text-as-JSON columns to JSONB.
Columns with a TEXT server_default (e.g. events_enabled DEFAULT '[]') could
not be cast automatically because PostgreSQL refuses to coerce a TEXT default
expression to jsonb implicitly.  This migration completes those casts by
explicitly dropping the default, altering the type, then restoring a
jsonb-typed default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_fix_jsonb_column_defaults"
down_revision = "0028_api_tokens"
branch_labels = None
depends_on = None

# Columns known to have had a server_default that blocked the 0026 JSONB cast.
# Each entry: (table, column, jsonb_default_or_None)
_BLOCKED = [
    ("webhook_rules", "events_enabled", "'[]'::jsonb"),
    ("webhook_rules", "headers_json", None),
]


def _fix_column(bind, table: str, column: str, jsonb_default: str | None) -> None:
    """Drop default → cast to jsonb → restore jsonb default (idempotent)."""
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return
    cols = {c["name"]: c for c in insp.get_columns(table)}
    col = cols.get(column)
    if col is None:
        return
    # Already jsonb — nothing to do
    if type(col["type"]).__name__.lower() == "jsonb":
        return

    # Drop existing server default so the ALTER TYPE can proceed
    bind.execute(sa.text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"))

    bind.execute(
        sa.text(
            f"""
            ALTER TABLE {table}
                ALTER COLUMN {column} TYPE jsonb
                USING COALESCE(
                    CASE
                        WHEN {column} IS NULL THEN NULL
                        WHEN TRIM({column}::text) = '' THEN NULL
                        ELSE {column}::text::jsonb
                    END,
                    NULL
                )
            """
        )
    )

    if jsonb_default is not None:
        bind.execute(
            sa.text(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {jsonb_default}")
        )


def upgrade() -> None:
    bind = op.get_bind()
    for table, column, jsonb_default in _BLOCKED:
        _fix_column(bind, table, column, jsonb_default)


def downgrade() -> None:
    # Reverting JSONB → TEXT is lossy and unnecessary; omitted intentionally.
    pass
