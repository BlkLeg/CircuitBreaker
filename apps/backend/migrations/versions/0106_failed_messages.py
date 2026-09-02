"""failed_messages: parked JetStream work

Revision ID: 0106_failed_messages
Revises: 0105_backup_age_recipient
Create Date: 2026-09-01

Route F14. Both JetStream consumers redelivered a failing message forever
because neither set `max_deliver`; bounding delivery without somewhere to put
the exhausted message would trade an infinite loop for a silent drop. This table
is that somewhere.

Purely additive: it creates one new table and touches nothing existing, so a
deployment that has not run this migration is unaffected — nothing reads
`failed_messages` except the operator surface added alongside it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0106_failed_messages"
down_revision: str | Sequence[str] | None = "0105_backup_age_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "failed_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stream", sa.String(length=128), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        # Raw bytes, not JSON: a message that failed to parse is exactly the
        # kind that parks here, and re-encoding it would destroy the evidence of
        # why it failed.
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requeued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failed_messages")),
        if_not_exists=True,
    )
    # The operator listing filters unresolved rows and orders by id; this index
    # serves the "what is currently parked" question, which is the one the page
    # asks on every load.
    op.create_index(
        op.f("ix_failed_messages_parked_at"),
        "failed_messages",
        ["parked_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_failed_messages_parked_at"),
        table_name="failed_messages",
        if_exists=True,
    )
    op.drop_table("failed_messages", if_exists=True)
