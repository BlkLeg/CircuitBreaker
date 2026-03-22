"""Add is_public to status_pages and create integration_monitor_events table.

Revision ID: 0053_public_status_page_and_monitor_events
Revises: 0052_add_slug_to_integrations
Create Date: 2026-03-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_public_status_page_and_monitor_events"
down_revision = "0052_add_slug_to_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "status_pages",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "integration_monitor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=False),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["integration_monitors.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        op.f("ix_integration_monitor_events_monitor_id"),
        "integration_monitor_events",
        ["monitor_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_integration_monitor_events_monitor_id"),
        table_name="integration_monitor_events",
    )
    op.drop_table("integration_monitor_events")
    op.drop_column("status_pages", "is_public")
