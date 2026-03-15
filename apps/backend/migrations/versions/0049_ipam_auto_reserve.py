"""Add IPAM auto-reserve settings + reservation queue table.

Revision ID: 0049_ipam_auto_reserve
Revises: 0048_scan_result_dedup_unique
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

revision = "0049_ipam_auto_reserve"
down_revision = "0048_scan_result_dedup_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # AppSettings columns
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "ipam_auto_reserve" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("ipam_auto_reserve", sa.Boolean, nullable=False, server_default="false"),
        )
    if "ipam_reserve_mode" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("ipam_reserve_mode", sa.String(16), nullable=False, server_default="auto"),
        )
    if "ipam_release_on_delete" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("ipam_release_on_delete", sa.Boolean, nullable=False, server_default="true"),
        )

    # Reservation queue table
    if not insp.has_table("ip_reservation_queue"):
        op.create_table(
            "ip_reservation_queue",
            sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "hardware_id",
                sa.Integer,
                sa.ForeignKey("hardware.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ip_address", INET, nullable=False),
            sa.Column("hostname", sa.String(255), nullable=True),
            sa.Column(
                "network_id",
                sa.Integer,
                sa.ForeignKey("networks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column(
                "reviewed_by",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_ip_resq_tenant", "ip_reservation_queue", ["tenant_id"])
        op.create_index("ix_ip_resq_status", "ip_reservation_queue", ["status"])


def downgrade() -> None:
    op.drop_table("ip_reservation_queue")
    op.drop_column("app_settings", "ipam_release_on_delete")
    op.drop_column("app_settings", "ipam_reserve_mode")
    op.drop_column("app_settings", "ipam_auto_reserve")
