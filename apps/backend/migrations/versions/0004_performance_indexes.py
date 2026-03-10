"""Phase 5 — performance indexes on scan_results and scan_jobs

Revision ID: f1a2b3c4d5e6
Revises: e7f2a1c3b4d5
Create Date: 2026-03-07 00:00:00.000000

Adds indexes that become important as scan data grows:
  scan_results: scan_job_id (join), state (filter), created_at (sort)
  scan_jobs:    status (polling), created_at (sort)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e7f2a1c3b4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {i["name"] for i in insp.get_indexes("scan_results")} | {
        i["name"] for i in insp.get_indexes("scan_jobs")
    }

    to_create = [
        ("ix_scan_results_scan_job_id", "scan_results", ["scan_job_id"]),
        ("ix_scan_results_state", "scan_results", ["state"]),
        ("ix_scan_results_created_at", "scan_results", ["created_at"]),
        ("ix_scan_jobs_status", "scan_jobs", ["status"]),
        ("ix_scan_jobs_created_at", "scan_jobs", ["created_at"]),
    ]
    for name, table, cols in to_create:
        if name not in existing:
            op.create_index(name, table, cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {i["name"] for i in insp.get_indexes("scan_results")} | {
        i["name"] for i in insp.get_indexes("scan_jobs")
    }

    to_drop = [
        ("ix_scan_jobs_created_at", "scan_jobs"),
        ("ix_scan_jobs_status", "scan_jobs"),
        ("ix_scan_results_created_at", "scan_results"),
        ("ix_scan_results_state", "scan_results"),
        ("ix_scan_results_scan_job_id", "scan_results"),
    ]
    for name, table in to_drop:
        if name in existing:
            op.drop_index(name, table_name=table)
