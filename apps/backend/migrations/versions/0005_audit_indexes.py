"""Phase 6 — audit log and discovery table indexes for common query patterns

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-07 00:00:00.000000

Adds indexes that accelerate the most common filter/sort patterns on the audit
log viewer and the discovery results panel:

  logs (audit):     category, action, actor_id, severity, created_at_utc,
                    (entity_type, entity_id) composite
  scan_results:     source_type, ip_address
"""

from __future__ import annotations

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Audit log indexes ──────────────────────────────────────────────────
    op.create_index("ix_logs_category", "logs", ["category"], unique=False)
    op.create_index("ix_logs_action", "logs", ["action"], unique=False)
    op.create_index("ix_logs_actor_id", "logs", ["actor_id"], unique=False)
    op.create_index("ix_logs_severity", "logs", ["severity"], unique=False)
    op.create_index("ix_logs_created_at_utc", "logs", ["created_at_utc"], unique=False)
    op.create_index(
        "ix_logs_entity_type_entity_id",
        "logs",
        ["entity_type", "entity_id"],
        unique=False,
    )

    # ── Discovery result indexes ───────────────────────────────────────────
    op.create_index("ix_scan_results_source_type", "scan_results", ["source_type"], unique=False)
    op.create_index("ix_scan_results_ip_address", "scan_results", ["ip_address"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scan_results_ip_address", table_name="scan_results")
    op.drop_index("ix_scan_results_source_type", table_name="scan_results")
    op.drop_index("ix_logs_entity_type_entity_id", table_name="logs")
    op.drop_index("ix_logs_created_at_utc", table_name="logs")
    op.drop_index("ix_logs_severity", table_name="logs")
    op.drop_index("ix_logs_actor_id", table_name="logs")
    op.drop_index("ix_logs_action", table_name="logs")
    op.drop_index("ix_logs_category", table_name="logs")
