"""create_network_privacy_snapshots

Revision ID: 7c41a90d55e1
Revises: 21f5eaea0483
Create Date: 2026-07-15 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c41a90d55e1"
down_revision: str | Sequence[str] | None = "21f5eaea0483"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "network_privacy_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=1), nullable=False),
        sa.Column("deductions", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("checks", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_network_privacy_snapshots")),
    )
    op.create_index(
        op.f("ix_network_privacy_snapshots_created_at"),
        "network_privacy_snapshots",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_network_privacy_snapshots_created_at"),
        table_name="network_privacy_snapshots",
    )
    op.drop_table("network_privacy_snapshots")
