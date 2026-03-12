"""Add scan_jobs.error_reason column for discovery failures.

Revision ID: 0044_scan_job_error_reason
Revises: 0043_hardware_live_metrics
Create Date: 2026-03-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_scan_job_error_reason"
down_revision = "0043_hardware_live_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("scan_jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("scan_jobs")}
    if "error_reason" not in cols:
        op.add_column("scan_jobs", sa.Column("error_reason", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("scan_jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("scan_jobs")}
    if "error_reason" in cols:
        op.drop_column("scan_jobs", "error_reason")
