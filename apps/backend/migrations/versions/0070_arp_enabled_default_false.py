"""change arp_enabled default to false

Revision ID: 0070_arp_enabled_default_false
Revises: 0069_hardware_connection_source
Create Date: 2026-03-30

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

revision = "0070_arp_enabled_default_false"
down_revision = "0069_hardware_connection_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "arp_enabled" in cols:
        op.alter_column(
            "app_settings",
            "arp_enabled",
            server_default=sa.text("false"),
            existing_type=sa.Boolean(),
            existing_nullable=False,
        )
        op.execute(text("UPDATE app_settings SET arp_enabled = false WHERE arp_enabled = true"))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "arp_enabled" in cols:
        op.alter_column(
            "app_settings",
            "arp_enabled",
            server_default=sa.text("true"),
            existing_type=sa.Boolean(),
            existing_nullable=False,
        )
