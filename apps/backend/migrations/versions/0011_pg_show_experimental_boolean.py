"""Fix PostgreSQL type for app_settings.show_experimental_features

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-03-07 18:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"]: c for c in inspector.get_columns("app_settings")}
    col = cols.get("show_experimental_features")
    if not col:
        return

    # Fresh databases created after the model fix will already be BOOLEAN.
    if conn.dialect.name == "postgresql":
        col_type = type(col["type"]).__name__.lower()
        if "integer" in col_type:
            op.alter_column(
                "app_settings",
                "show_experimental_features",
                existing_type=sa.Integer(),
                type_=sa.Boolean(),
                postgresql_using=(
                    "CASE WHEN show_experimental_features = 0 THEN FALSE ELSE TRUE END"
                ),
                existing_nullable=False,
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    cols = {c["name"]: c for c in inspector.get_columns("app_settings")}
    col = cols.get("show_experimental_features")
    if not col:
        return

    if conn.dialect.name == "postgresql":
        col_type = type(col["type"]).__name__.lower()
        if "boolean" in col_type:
            op.alter_column(
                "app_settings",
                "show_experimental_features",
                existing_type=sa.Boolean(),
                type_=sa.Integer(),
                postgresql_using="CASE WHEN show_experimental_features THEN 1 ELSE 0 END",
                existing_nullable=False,
            )
