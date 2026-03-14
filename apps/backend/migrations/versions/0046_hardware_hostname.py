"""Add hostname column to hardware table.

Revision ID: 0046_hardware_hostname
Revises: 0045_app_settings_max_concurrent_scans
Create Date: 2026-03-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_hardware_hostname"
down_revision = "0045_app_settings_max_concurrent_scans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("hardware"):
        return
    cols = {c["name"] for c in insp.get_columns("hardware")}
    if "hostname" not in cols:
        op.add_column(
            "hardware",
            sa.Column("hostname", sa.String(), nullable=True),
        )
    # RFC 1035: fully-qualified hostname max 253 chars
    try:
        op.create_check_constraint(
            "ck_hardware_hostname_length",
            "hardware",
            "hostname IS NULL OR length(hostname) <= 253",
        )
    except Exception:
        pass  # idempotent — constraint may already exist


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("hardware"):
        return
    cols = {c["name"] for c in insp.get_columns("hardware")}
    try:
        op.drop_constraint("ck_hardware_hostname_length", "hardware", type_="check")
    except Exception:
        pass
    if "hostname" in cols:
        op.drop_column("hardware", "hostname")
