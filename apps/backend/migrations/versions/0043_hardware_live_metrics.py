"""Add hardware_live_metrics table for telemetry samples.

Revision ID: 0043_hardware_live_metrics
Revises: 0042_db_permissions
Create Date: 2026-03-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_hardware_live_metrics"
down_revision = "0042_db_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("hardware_live_metrics"):
        op.create_table(
            "hardware_live_metrics",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "hardware_id",
                sa.Integer(),
                sa.ForeignKey("hardware.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "collected_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.Column("cpu_pct", sa.Float(), nullable=True),
            sa.Column("mem_pct", sa.Float(), nullable=True),
            sa.Column("mem_used_mb", sa.Float(), nullable=True),
            sa.Column("mem_total_mb", sa.Float(), nullable=True),
            sa.Column("disk_pct", sa.Float(), nullable=True),
            sa.Column("temp_c", sa.Float(), nullable=True),
            sa.Column("power_w", sa.Float(), nullable=True),
            sa.Column("uptime_s", sa.BigInteger(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=24),
                nullable=False,
                server_default=sa.text("'unknown'"),
            ),
            sa.Column("source", sa.String(length=32), nullable=True),
            sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("error_msg", sa.Text(), nullable=True),
        )

    existing_idx = {i["name"] for i in insp.get_indexes("hardware_live_metrics")}
    if "idx_hw_live_metrics_hw_time" not in existing_idx:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS idx_hw_live_metrics_hw_time "
                "ON hardware_live_metrics (hardware_id, collected_at DESC)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("hardware_live_metrics"):
        return

    existing_idx = {i["name"] for i in insp.get_indexes("hardware_live_metrics")}
    if "idx_hw_live_metrics_hw_time" in existing_idx:
        op.drop_index("idx_hw_live_metrics_hw_time", table_name="hardware_live_metrics")

    op.drop_table("hardware_live_metrics")
