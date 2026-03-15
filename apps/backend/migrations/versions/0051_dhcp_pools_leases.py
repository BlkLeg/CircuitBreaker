"""Add DHCP pools and leases tables.

Revision ID: 0051_dhcp_pools_leases
Revises: 0050_ip_conflicts
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

revision = "0051_dhcp_pools_leases"
down_revision = "0050_ip_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("dhcp_pools"):
        op.create_table(
            "dhcp_pools",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "network_id",
                sa.Integer,
                sa.ForeignKey("networks.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("start_ip", INET, nullable=False),
            sa.Column("end_ip", INET, nullable=False),
            sa.Column("lease_duration_seconds", sa.Integer, nullable=False, server_default="86400"),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_dhcp_pools_tenant", "dhcp_pools", ["tenant_id"])

    if not insp.has_table("dhcp_leases"):
        op.create_table(
            "dhcp_leases",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "pool_id",
                sa.Integer,
                sa.ForeignKey("dhcp_pools.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("ip_address", INET, nullable=False),
            sa.Column("mac_address", sa.String(17), nullable=True),
            sa.Column("hostname", sa.String(255), nullable=True),
            sa.Column("lease_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expiry", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint("tenant_id", "ip_address", name="uq_dhcp_lease_tenant_ip"),
        )
        op.create_index("ix_dhcp_leases_tenant", "dhcp_leases", ["tenant_id"])
        op.create_index("ix_dhcp_leases_ip", "dhcp_leases", ["ip_address"])
        op.create_index("ix_dhcp_leases_expiry", "dhcp_leases", ["lease_expiry"])


def downgrade() -> None:
    op.drop_table("dhcp_leases")
    op.drop_table("dhcp_pools")
