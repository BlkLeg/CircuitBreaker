"""add daily uptime stats

Revision ID: 0021_daily_uptime_stats
Revises: 0020_merge_heads
Create Date: 2026-03-08 14:18:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_daily_uptime_stats"
down_revision = "0020_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "daily_uptime_stats" in tables:
        return

    if "hardware" not in tables:
        return

    op.create_table(
        "daily_uptime_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hardware_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("total_minutes", sa.Integer(), nullable=False),
        sa.Column("uptime_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["hardware_id"], ["hardware.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hardware_id", "date"),
    )
    op.create_index(
        op.f("ix_daily_uptime_stats_hardware_id"),
        "daily_uptime_stats",
        ["hardware_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_uptime_stats_hardware_id"), table_name="daily_uptime_stats")
    op.drop_table("daily_uptime_stats")
