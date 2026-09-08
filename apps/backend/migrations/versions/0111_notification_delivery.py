"""Add retry-safe notification delivery receipts.

Revision ID: 0111_notification_delivery
Revises: 0110_agent_spool_evictions
Create Date: 2026-09-07

Receipts retain no alert body, provider response body, or credential. The
immutable sink_key preserves the event/destination replay identity if the
destination is later removed and sink_id is set to NULL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0111_notification_delivery"
down_revision = "0110_agent_spool_evictions"
branch_labels = None
depends_on = None

_TABLE = "notification_deliveries"


def upgrade() -> None:
    """Create the notification delivery receipt table if it is absent."""
    conn = op.get_bind()
    if _TABLE in set(sa_inspect(conn).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("sink_key", sa.Integer(), nullable=False),
        sa.Column("sink_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("safe_message", sa.String(length=300), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("claim_owner", sa.String(length=160), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["sink_id"], ["notification_sinks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "sink_key", name="uq_notification_delivery_event_sink"),
    )
    op.create_index(
        "ix_notification_deliveries_state_retry",
        _TABLE,
        ["state", "next_retry_at"],
        unique=False,
    )
    op.create_index("ix_notification_deliveries_updated_at", _TABLE, ["updated_at"], unique=False)


def downgrade() -> None:
    """Drop notification delivery receipts if present."""
    conn = op.get_bind()
    if _TABLE in set(sa_inspect(conn).get_table_names()):
        op.drop_table(_TABLE)
