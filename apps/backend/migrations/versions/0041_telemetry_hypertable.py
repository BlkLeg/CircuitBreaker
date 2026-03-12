"""TimescaleDB hypertable for telemetry_timeseries + retention policy.

Revision ID: 0041_telemetry_hypertable
Revises: 0040_rls_policies
Create Date: 2026-03-11

If TimescaleDB is available, converts telemetry_timeseries to a hypertable
with automatic chunking on the ``ts`` column and sets a 90-day retention
policy.  Falls back gracefully if TimescaleDB is not installed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_telemetry_hypertable"
down_revision = "0040_rls_policies"
branch_labels = None
depends_on = None


def _has_timescaledb(bind) -> bool:
    """Check if the timescaledb extension is available (not necessarily created)."""
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb' LIMIT 1")
    )
    return result.scalar() is not None


def _is_hypertable(bind, table: str) -> bool:
    """Check if a table is already a TimescaleDB hypertable."""
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = :tbl LIMIT 1"
        ),
        {"tbl": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("telemetry_timeseries"):
        return

    if not _has_timescaledb(bind):
        # Fallback: just ensure the compound index exists
        existing_idx = {i["name"] for i in insp.get_indexes("telemetry_timeseries")}
        if "ix_tts_entity_ts_hyper" not in existing_idx:
            op.create_index(
                "ix_tts_entity_ts_hyper",
                "telemetry_timeseries",
                ["entity_type", "entity_id", "ts"],
            )
        return

    # Enable extension
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))

    # Convert to hypertable (migrate_data moves existing rows into chunks)
    if not _is_hypertable(bind, "telemetry_timeseries"):
        op.execute(
            sa.text(
                "SELECT create_hypertable("
                "  'telemetry_timeseries', 'ts', migrate_data => true, if_not_exists => true"
                ")"
            )
        )

    # Compound index for entity+time range queries
    existing_idx = {i["name"] for i in insp.get_indexes("telemetry_timeseries")}
    if "ix_tts_entity_ts_hyper" not in existing_idx:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_tts_entity_ts_hyper "
                "ON telemetry_timeseries (entity_type, entity_id, ts DESC)"
            )
        )

    # 90-day retention policy
    try:
        op.execute(
            sa.text(
                "SELECT add_retention_policy('telemetry_timeseries', INTERVAL '90 days', "
                "if_not_exists => true)"
            )
        )
    except Exception:  # noqa: BLE001
        pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("telemetry_timeseries"):
        return

    # Remove retention policy if TimescaleDB is present
    if _has_timescaledb(bind):
        try:
            op.execute(
                sa.text("SELECT remove_retention_policy('telemetry_timeseries', if_exists => true)")
            )
        except Exception:  # noqa: BLE001
            pass

    # Drop the index we created
    existing_idx = {i["name"] for i in insp.get_indexes("telemetry_timeseries")}
    if "ix_tts_entity_ts_hyper" in existing_idx:
        op.drop_index("ix_tts_entity_ts_hyper", table_name="telemetry_timeseries")
