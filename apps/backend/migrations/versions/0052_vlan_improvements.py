"""Add Network.vlan_pk FK and vlan_trunks table.

Revision ID: 0052_vlan_improvements
Revises: 0051_dhcp_pools_leases
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_vlan_improvements"
down_revision = "0051_dhcp_pools_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Add vlan_pk FK column to networks
    net_cols = {c["name"] for c in insp.get_columns("networks")}
    if "vlan_pk" not in net_cols:
        op.add_column(
            "networks",
            sa.Column(
                "vlan_pk",
                sa.Integer,
                sa.ForeignKey("vlans.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        # Data migration: match existing vlan_id integers to VLAN rows
        bind.execute(
            sa.text("""
                UPDATE networks n
                SET vlan_pk = v.id
                FROM vlans v
                WHERE n.vlan_id = v.vlan_id
                  AND n.vlan_id IS NOT NULL
                  AND (n.tenant_id = v.tenant_id OR (n.tenant_id IS NULL AND v.tenant_id IS NULL))
            """)
        )

    # VLAN trunks table
    if not insp.has_table("vlan_trunks"):
        op.create_table(
            "vlan_trunks",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "hardware_id",
                sa.Integer,
                sa.ForeignKey("hardware.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "vlan_id",
                sa.Integer,
                sa.ForeignKey("vlans.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("port_label", sa.String(64), nullable=True),
            sa.Column("tagged", sa.Boolean, nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint("hardware_id", "vlan_id", name="uq_vlan_trunk_hw_vlan"),
        )
        op.create_index("ix_vlan_trunks_tenant", "vlan_trunks", ["tenant_id"])
        op.create_index("ix_vlan_trunks_hw", "vlan_trunks", ["hardware_id"])


def downgrade() -> None:
    op.drop_table("vlan_trunks")
    op.drop_column("networks", "vlan_pk")
