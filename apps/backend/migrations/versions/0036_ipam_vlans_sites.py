"""Add IPAM (ip_addresses), VLANs, and Sites tables for network management.

Revision ID: 0036_ipam_vlans_sites
Revises: 0035_performance_indexes_v2
Create Date: 2026-03-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB

revision = "0036_ipam_vlans_sites"
down_revision = "0035_performance_indexes_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("ip_addresses"):
        op.create_table(
            "ip_addresses",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "team_id",
                sa.Integer,
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "network_id",
                sa.Integer,
                sa.ForeignKey("networks.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("address", INET, nullable=False),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="free",
            ),
            sa.Column(
                "hardware_id",
                sa.Integer,
                sa.ForeignKey("hardware.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "service_id",
                sa.Integer,
                sa.ForeignKey("services.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("hostname", sa.String(255), nullable=True),
            sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.UniqueConstraint("team_id", "address", name="uq_ip_addresses_team_address"),
        )
        op.create_index("ix_ipaddr_team_net", "ip_addresses", ["team_id", "network_id"])
        op.create_index("ix_ipaddr_address", "ip_addresses", ["address"])
        op.create_index("ix_ipaddr_status", "ip_addresses", ["status"])

    if not insp.has_table("vlans"):
        op.create_table(
            "vlans",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "team_id",
                sa.Integer,
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("vlan_id", sa.Integer, nullable=False),
            sa.Column("name", sa.String(64), nullable=True),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("network_ids", JSONB, server_default="[]"),
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
            sa.UniqueConstraint("team_id", "vlan_id", name="uq_vlans_team_vlan"),
        )
        op.create_index("ix_vlans_team", "vlans", ["team_id"])

    if not insp.has_table("sites"):
        op.create_table(
            "sites",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "team_id",
                sa.Integer,
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("location", sa.String(128), nullable=True),
            sa.Column("latitude", sa.Float, nullable=True),
            sa.Column("longitude", sa.Float, nullable=True),
            sa.Column("notes", sa.Text, nullable=True),
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
        op.create_index("ix_sites_team", "sites", ["team_id"])


def downgrade() -> None:
    op.drop_table("sites")
    op.drop_table("vlans")
    op.drop_table("ip_addresses")
