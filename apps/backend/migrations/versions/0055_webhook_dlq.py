"""Add DLQ columns to webhook_deliveries.

Revision ID: 0055_webhook_dlq
Revises: 0054_status_page_integration_id
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_webhook_dlq"
down_revision = "0054_status_page_integration_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("is_dlq", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("dlq_at", sa.String(), nullable=True),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("replayed_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_is_dlq",
        "webhook_deliveries",
        ["is_dlq"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_is_dlq", table_name="webhook_deliveries")
    op.drop_column("webhook_deliveries", "replayed_at")
    op.drop_column("webhook_deliveries", "dlq_at")
    op.drop_column("webhook_deliveries", "is_dlq")
