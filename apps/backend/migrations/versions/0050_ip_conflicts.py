"""Add ip_conflicts table for persistent conflict tracking.

Revision ID: 0050_ip_conflicts
Revises: 0049_ipam_auto_reserve
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

revision = "0050_ip_conflicts"
down_revision = "0049_ipam_auto_reserve"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("ip_conflicts"):
        op.create_table(
            "ip_conflicts",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("address", INET, nullable=False),
            sa.Column("entity_a_type", sa.String(32), nullable=False),
            sa.Column("entity_a_id", sa.Integer, nullable=False),
            sa.Column("entity_b_type", sa.String(32), nullable=False),
            sa.Column("entity_b_id", sa.Integer, nullable=False),
            sa.Column("conflict_type", sa.String(16), nullable=False, server_default="ip_overlap"),
            sa.Column("port", sa.Integer, nullable=True),
            sa.Column("protocol", sa.String(8), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("resolution", sa.String(32), nullable=True),
            sa.Column(
                "resolved_by",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_ip_conflicts_tenant", "ip_conflicts", ["tenant_id"])
        op.create_index("ix_ip_conflicts_address", "ip_conflicts", ["address"])
        op.create_index("ix_ip_conflicts_status", "ip_conflicts", ["status"])


def downgrade() -> None:
    op.drop_table("ip_conflicts")
