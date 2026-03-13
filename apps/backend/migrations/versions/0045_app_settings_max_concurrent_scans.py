"""Ensure app_settings.max_concurrent_scans exists.

Revision ID: 0045_app_settings_max_concurrent_scans
Revises: 0044_scan_job_error_reason
Create Date: 2026-03-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_app_settings_max_concurrent_scans"
down_revision = "0044_scan_job_error_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("app_settings"):
        return
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "max_concurrent_scans" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("max_concurrent_scans", sa.Integer(), nullable=False, server_default="2"),
        )
    op.execute(sa.text("ALTER TABLE app_settings ALTER COLUMN max_concurrent_scans DROP DEFAULT"))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("app_settings"):
        return
    cols = {c["name"] for c in insp.get_columns("app_settings")}
    if "max_concurrent_scans" in cols:
        op.drop_column("app_settings", "max_concurrent_scans")
