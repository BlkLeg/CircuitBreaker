"""Deduplicate scan_results and add unique constraint on (scan_job_id, ip_address).

Revision ID: 0048_scan_result_dedup_unique
Revises: 0047_user_auth_audit_columns
Create Date: 2026-03-14

Network + Docker scans could produce duplicate ScanResult rows for the same IP
within a single job. This migration:
  1. Deletes duplicate rows, keeping the one with the most data (longest raw_nmap_xml).
  2. Creates a unique index on (scan_job_id, ip_address) as a safety net.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_scan_result_dedup_unique"
down_revision = "0047_user_auth_audit_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Remove duplicates — keep the row with the longest raw_nmap_xml (most data)
    bind.execute(
        sa.text("""
            DELETE FROM scan_results
            WHERE id NOT IN (
                SELECT MIN(id) FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY scan_job_id, ip_address
                               ORDER BY COALESCE(LENGTH(raw_nmap_xml), 0) DESC, id ASC
                           ) AS rn
                    FROM scan_results
                    WHERE ip_address IS NOT NULL
                ) sub
                WHERE rn = 1
            )
            AND ip_address IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM scan_results sr2
                WHERE sr2.scan_job_id = scan_results.scan_job_id
                  AND sr2.ip_address = scan_results.ip_address
                  AND sr2.id != scan_results.id
            )
        """)
    )

    # 2. Create unique index (partial — ip_address IS NOT NULL)
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("scan_results")}
    if "uq_scan_result_job_ip" not in existing_indexes:
        op.create_index(
            "uq_scan_result_job_ip",
            "scan_results",
            ["scan_job_id", "ip_address"],
            unique=True,
            postgresql_where=sa.text("ip_address IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_scan_result_job_ip", table_name="scan_results")
