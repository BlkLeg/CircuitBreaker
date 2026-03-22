"""Add intelligence models: capacity_forecasts, resource_efficiency_recommendations,
flap_incidents; AppSettings telemetry retention columns.

Revision ID: 0058_intel_models
Revises: 0057_backup_settings
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058_intel_models"
down_revision = "0057_backup_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_forecasts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "hardware_id",
            sa.Integer,
            sa.ForeignKey("hardware.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("slope_per_day", sa.Float, nullable=False),
        sa.Column("current_value", sa.Float, nullable=False),
        sa.Column("projected_full_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warning_threshold_days", sa.Integer, server_default="7", nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("hardware_id", "metric", name="uq_capacity_forecast_hw_metric"),
    )
    op.create_table(
        "resource_efficiency_recommendations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer, nullable=False, index=True),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("cpu_avg_pct", sa.Float, nullable=True),
        sa.Column("cpu_peak_pct", sa.Float, nullable=True),
        sa.Column("mem_avg_pct", sa.Float, nullable=True),
        sa.Column("recommendation", sa.Text, nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("asset_type", "asset_id", name="uq_resource_efficiency_asset"),
    )
    op.create_table(
        "flap_incidents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer, nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transition_count", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("app_settings", sa.Column("telemetry_hot_days", sa.Integer, nullable=True))
    op.add_column("app_settings", sa.Column("telemetry_warm_days", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "telemetry_warm_days")
    op.drop_column("app_settings", "telemetry_hot_days")
    op.drop_table("flap_incidents")
    op.drop_table("resource_efficiency_recommendations")
    op.drop_table("capacity_forecasts")
