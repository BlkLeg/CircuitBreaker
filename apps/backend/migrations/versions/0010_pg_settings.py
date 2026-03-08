"""Phase 7.5 — PostgreSQL backup retention setting

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-03-07 18:00:00.000000

Adds:
  - app_settings: db_backup_retention_days (INTEGER, default 30)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    app_cols = {c["name"] for c in inspector.get_columns("app_settings")}

    if "db_backup_retention_days" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "db_backup_retention_days",
                sa.Integer(),
                nullable=True,
                server_default="30",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    app_cols = {c["name"] for c in inspector.get_columns("app_settings")}

    if "db_backup_retention_days" in app_cols:
        op.drop_column("app_settings", "db_backup_retention_days")
