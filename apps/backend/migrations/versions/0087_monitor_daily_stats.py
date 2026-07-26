"""Generalize daily uptime rollup to every monitor target type.

Revision ID: 0087_monitor_daily_stats
Revises: 0086_native_monitors
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0087_monitor_daily_stats"
down_revision = "0086_native_monitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "daily_uptime_stats" not in set(insp.get_table_names()):
        return

    # Existing rows aggregate every monitor on a hardware node into one row;
    # that can't be faithfully remapped to per-item granularity. Rollups
    # regenerate daily going forward, so clear stale rows rather than migrate.
    op.execute("DELETE FROM daily_uptime_stats")

    for fk in insp.get_foreign_keys("daily_uptime_stats"):
        if "hardware_id" in fk["constrained_columns"]:
            op.drop_constraint(fk["name"], "daily_uptime_stats", type_="foreignkey")
    for uq in insp.get_unique_constraints("daily_uptime_stats"):
        if "hardware_id" in uq["column_names"]:
            op.drop_constraint(uq["name"], "daily_uptime_stats", type_="unique")
    for idx in insp.get_indexes("daily_uptime_stats"):
        if "hardware_id" in idx["column_names"]:
            op.drop_index(idx["name"], table_name="daily_uptime_stats")

    op.drop_column("daily_uptime_stats", "hardware_id")
    op.rename_table("daily_uptime_stats", "monitor_daily_stats")

    op.add_column(
        "monitor_daily_stats",
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("monitor_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_monitor_daily_stats_item_id", "monitor_daily_stats", ["item_id"], if_not_exists=True
    )
    op.create_unique_constraint(
        "uq_monitor_daily_stats_item_date", "monitor_daily_stats", ["item_id", "date"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "monitor_daily_stats" not in set(insp.get_table_names()):
        return

    op.execute("DELETE FROM monitor_daily_stats")
    op.drop_constraint("uq_monitor_daily_stats_item_date", "monitor_daily_stats", type_="unique")
    op.drop_index("ix_monitor_daily_stats_item_id", table_name="monitor_daily_stats")
    op.drop_column("monitor_daily_stats", "item_id")

    op.add_column("monitor_daily_stats", sa.Column("hardware_id", sa.Integer(), nullable=False))
    op.rename_table("monitor_daily_stats", "daily_uptime_stats")

    op.create_foreign_key(
        "daily_uptime_stats_hardware_id_fkey",
        "daily_uptime_stats",
        "hardware",
        ["hardware_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_daily_uptime_stats_hardware_id", "daily_uptime_stats", ["hardware_id"], unique=False
    )
    op.create_unique_constraint(
        "daily_uptime_stats_hardware_id_date_key", "daily_uptime_stats", ["hardware_id", "date"]
    )
