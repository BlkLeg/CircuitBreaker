"""Security hardening: scan ACL, air-gap mode, WS CIDR whitelist, mTLS FK.

Revision ID: 0034_security_hardening
Revises: 0033_certificates
Create Date: 2026-03-11

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_security_hardening"
down_revision = "0033_certificates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    app_cols = (
        {c["name"] for c in insp.get_columns("app_settings")}
        if insp.has_table("app_settings")
        else set()
    )
    ic_cols = (
        {c["name"] for c in insp.get_columns("integration_configs")}
        if insp.has_table("integration_configs")
        else set()
    )

    if "scan_allowed_networks" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "scan_allowed_networks",
                sa.Text,
                nullable=False,
                server_default='["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]',
            ),
        )
    if "airgap_mode" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "airgap_mode",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if "ws_allowed_cidrs" not in app_cols:
        op.add_column(
            "app_settings",
            sa.Column(
                "ws_allowed_cidrs",
                sa.Text,
                nullable=False,
                server_default="[]",
            ),
        )
    if "tls_cert_id" not in ic_cols:
        op.add_column(
            "integration_configs",
            sa.Column(
                "tls_cert_id",
                sa.Integer,
                sa.ForeignKey("certificates.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("integration_configs", "tls_cert_id")
    op.drop_column("app_settings", "ws_allowed_cidrs")
    op.drop_column("app_settings", "airgap_mode")
    op.drop_column("app_settings", "scan_allowed_networks")
