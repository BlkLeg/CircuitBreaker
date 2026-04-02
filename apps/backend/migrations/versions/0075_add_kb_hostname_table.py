"""add_kb_hostname_table

Revision ID: 0075_add_kb_hostname_table
Revises: 0060_add_kb_oui_table
Create Date: 2026-04-01 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision: str = "0075_add_kb_hostname_table"
down_revision: str | Sequence[str] | None = "0060_add_kb_oui_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    if "kb_hostname" not in insp.get_table_names():
        op.create_table(
            "kb_hostname",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("pattern", sa.String(128), nullable=False),
            sa.Column("match_type", sa.String(32), nullable=False, server_default="prefix"),
            sa.Column("vendor", sa.String(128), nullable=True),
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
    op.drop_table("kb_hostname")
