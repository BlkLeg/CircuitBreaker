"""add_privacy_finding_ignores

Revision ID: ec2fa30c05d1
Revises: 7c41a90d55e1
Create Date: 2026-07-15 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ec2fa30c05d1"
down_revision: str | Sequence[str] | None = "7c41a90d55e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "privacy_finding_ignores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("hardware_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["hardware_id"],
            ["hardware.id"],
            name=op.f("fk_privacy_finding_ignores_hardware_id_hardware"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_privacy_finding_ignores_created_by_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_finding_ignores")),
        sa.UniqueConstraint("rule_id", "hardware_id", name="uq_privacy_ignore_rule_hw"),
    )
    # Postgres treats every NULL as distinct, so the composite unique constraint
    # above doesn't dedupe network-level findings (hardware_id is null there).
    op.create_index(
        "uq_privacy_ignore_rule_network",
        "privacy_finding_ignores",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("hardware_id IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_privacy_ignore_rule_network",
        table_name="privacy_finding_ignores",
        postgresql_where=sa.text("hardware_id IS NULL"),
    )
    op.drop_table("privacy_finding_ignores")
