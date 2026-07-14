"""Create monitor_items table for the continuous polling engine.

Revision ID: 0081_monitor_items
Revises: 0080_app_role_schema_grants
Create Date: 2026-07-13

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0081_monitor_items"
down_revision = "0080_app_role_schema_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("check_type", sa.String(), nullable=False),
        sa.Column("params", JSONB(), nullable=False, server_default="{}"),
        sa.Column("interval_secs", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_monitor_items_due", "monitor_items", ["enabled", "next_due_at"])


def downgrade() -> None:
    op.drop_index("ix_monitor_items_due", table_name="monitor_items")
    op.drop_table("monitor_items")
