"""Add indexes to telemetry_timeseries for query performance.

Revision ID: 0048_telemetry_timeseries_indexes
Revises: 0047_user_auth_audit_columns
Create Date: 2026-03-17

Without indexes, range queries on telemetry_timeseries (e.g. "last 24h for
entity 5, metric cpu_pct") perform full table scans.  At ~1.4M rows/day for
50 nodes × 10 metrics × 1 poll/30s, this becomes a query performance cliff
within days.

Two composite indexes are added:
  - (entity_type, entity_id, ts DESC) — for per-entity time-range queries
  - (metric, ts DESC)                 — for cross-entity metric queries

Both use IF NOT EXISTS so re-running is safe.
"""

from alembic import op

revision = "0048_telemetry_timeseries_indexes"
down_revision = "0047_user_auth_audit_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_telemetry_ts_entity
        ON telemetry_timeseries (entity_type, entity_id, ts DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_telemetry_ts_metric
        ON telemetry_timeseries (metric, ts DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_telemetry_ts_entity")
    op.execute("DROP INDEX IF EXISTS ix_telemetry_ts_metric")
