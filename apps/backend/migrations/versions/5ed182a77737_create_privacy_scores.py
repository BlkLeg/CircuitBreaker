"""create_privacy_scores

Revision ID: 5ed182a77737
Revises: f61dd2dc9ade
Create Date: 2026-07-14 14:05:38.480730

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ed182a77737"
down_revision: str | Sequence[str] | None = "f61dd2dc9ade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add columns to hardware
    op.add_column("hardware", sa.Column("privacy_score", sa.Integer(), nullable=True))
    op.add_column(
        "hardware", sa.Column("threat_profile", sa.dialects.postgresql.JSONB(), nullable=True)
    )

    # Create privacy_score_history table
    op.create_table(
        "privacy_score_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hardware_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("threat_profile", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["hardware_id"],
            ["hardware.id"],
            name=op.f("fk_privacy_score_history_hardware_id_hardware"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_score_history")),
    )
    op.create_index(
        op.f("ix_privacy_score_history_hardware_id"),
        "privacy_score_history",
        ["hardware_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_privacy_score_history_hardware_id"), table_name="privacy_score_history")
    op.drop_table("privacy_score_history")
    op.drop_column("hardware", "threat_profile")
    op.drop_column("hardware", "privacy_score")
