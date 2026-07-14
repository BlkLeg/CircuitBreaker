"""Add item_id dimension to telemetry_timeseries for monitor-item samples.

Revision ID: 0082_telemetry_item_id
Revises: 0081_monitor_items
Create Date: 2026-07-14

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082_telemetry_item_id"
down_revision = "0081_monitor_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telemetry_timeseries", sa.Column("item_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_telemetry_timeseries_item_id", "telemetry_timeseries", ["item_id", "metric", "ts"]
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_timeseries_item_id", table_name="telemetry_timeseries")
    op.drop_column("telemetry_timeseries", "item_id")
