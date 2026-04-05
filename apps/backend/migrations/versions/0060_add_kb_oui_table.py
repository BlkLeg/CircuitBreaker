"""add_kb_oui_table

Revision ID: 0060_add_kb_oui_table
Revises: 0074_scan_result_device_type
Create Date: 2026-04-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0060_add_kb_oui_table"
down_revision: str | Sequence[str] | None = "0074_scan_result_device_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name='kb_oui'")
    ).fetchone()
    if exists:
        return
    op.create_table(
        "kb_oui",
        sa.Column("prefix", sa.String(6), primary_key=True),
        sa.Column("vendor", sa.String(128), nullable=False),
        sa.Column("device_type", sa.String(64), nullable=True),
        sa.Column("os_family", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="learned"),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("kb_oui")
