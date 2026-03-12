"""Add certificates table for TLS cert management.

Revision ID: 0033_certificates
Revises: 0032_onboarding
Create Date: 2026-03-11

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_certificates"
down_revision = "0032_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("certificates"):
        return
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("domain", sa.String, nullable=False, unique=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="selfsigned"),
        sa.Column("cert_pem", sa.Text, nullable=False),
        sa.Column("key_pem", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default=sa.text("true")),
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


def downgrade() -> None:
    op.drop_table("certificates")
