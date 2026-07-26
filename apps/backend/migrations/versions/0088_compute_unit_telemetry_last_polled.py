"""Add telemetry_last_polled column to compute_units table.

Revision ID: 0088_compute_unit_telemetry_last_polled
Revises: 0087_monitor_daily_stats
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0088_compute_unit_telemetry_last_polled"
down_revision = "0087_monitor_daily_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("compute_units")}
    if "telemetry_last_polled" not in cols:
        op.add_column(
            "compute_units",
            sa.Column("telemetry_last_polled", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("compute_units", "telemetry_last_polled")
