"""Evolve monitor_items into first-class monitors; add monitor_events.

Revision ID: 0086_native_monitors
Revises: 0085_bootstrap_domain_fqdn
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086_native_monitors"
down_revision = "0085_bootstrap_domain_fqdn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitor_items",
        sa.Column("name", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "monitor_items",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "monitor_items",
        sa.Column("retry_interval_secs", sa.Integer(), nullable=True),
    )
    op.add_column(
        "monitor_items",
        sa.Column("last_status_change_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("monitor_items", "target_type", nullable=True)
    # Backfill names for engine-created rows; normalize legacy status values
    op.execute("UPDATE monitor_items SET name = host || ' (' || check_type || ')' WHERE name = ''")
    op.execute(
        "UPDATE monitor_items SET last_status = 'pending' "
        "WHERE last_status IS NULL OR last_status NOT IN ('up','down','pending','maintenance')"
    )

    op.create_table(
        "monitor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("monitor_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status_from", sa.String(), nullable=True),
        sa.Column("status_to", sa.String(), nullable=False),
        sa.Column("msg", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_secs", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_monitor_events_item_time",
        "monitor_events",
        ["item_id", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_events_item_time", table_name="monitor_events", if_exists=True)
    op.drop_table("monitor_events", if_exists=True)
    # Standalone monitors (target_type IS NULL) can't exist pre-0086; drop them
    # before restoring the NOT NULL constraint.
    op.execute("DELETE FROM monitor_items WHERE target_type IS NULL")
    op.alter_column("monitor_items", "target_type", nullable=False)
    op.drop_column("monitor_items", "last_status_change_at")
    op.drop_column("monitor_items", "retry_interval_secs")
    op.drop_column("monitor_items", "max_retries")
    op.drop_column("monitor_items", "name")
