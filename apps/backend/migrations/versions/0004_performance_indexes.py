"""Phase 5 — performance indexes on scan_results and scan_jobs

Revision ID: f1a2b3c4d5e6
Revises: e7f2a1c3b4d5
Create Date: 2026-03-07 00:00:00.000000

Adds indexes that become important as scan data grows:
  scan_results: scan_job_id (join), state (filter), created_at (sort)
  scan_jobs:    status (polling), created_at (sort)
"""

from __future__ import annotations

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e7f2a1c3b4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_scan_results_scan_job_id", "scan_results", ["scan_job_id"], unique=False)
    op.create_index("ix_scan_results_state", "scan_results", ["state"], unique=False)
    op.create_index("ix_scan_results_created_at", "scan_results", ["created_at"], unique=False)
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"], unique=False)
    op.create_index("ix_scan_jobs_created_at", "scan_jobs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scan_jobs_created_at", table_name="scan_jobs")
    op.drop_index("ix_scan_jobs_status", table_name="scan_jobs")
    op.drop_index("ix_scan_results_created_at", table_name="scan_results")
    op.drop_index("ix_scan_results_state", table_name="scan_results")
    op.drop_index("ix_scan_results_scan_job_id", table_name="scan_results")
