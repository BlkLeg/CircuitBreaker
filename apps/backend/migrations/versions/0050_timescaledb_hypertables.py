"""Convert hardware_live_metrics and telemetry_timeseries to TimescaleDB hypertables.

Revision ID: 0050_timescaledb_hypertables
Revises: 715595fafdec
Create Date: 2026-03-21

Requires TimescaleDB extension installed in PostgreSQL (timescaledb-2-postgresql-15).
Both the native installer and Dockerfile.mono install the extension automatically.

Changes:
  hardware_live_metrics:
    - Drop single-column PK on id; replace with composite PK (id, collected_at)
      (TimescaleDB requires the partitioning column in the PK)
    - Convert to hypertable on collected_at
    - Compression: segment by hardware_id, order by collected_at DESC
    - Compression policy: compress chunks older than 7 days
    - Retention policy: drop chunks older than 30 days (replaces daily DELETE job)

  telemetry_timeseries:
    - Migration 0041 already ran but TimescaleDB was unavailable at the time.
      This migration retroactively applies the hypertable + policies.
    - Compression: segment by entity_type/entity_id, order by ts DESC
    - Compression policy: compress chunks older than 14 days
    - Retention policy: drop chunks older than 90 days

Graceful fallback: if TimescaleDB is not installed, migration skips silently.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_timescaledb_hypertables"
down_revision = "715595fafdec"
branch_labels = None
depends_on = None


def _has_timescaledb(bind: sa.engine.Connection) -> bool:
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb' LIMIT 1")
    )
    return result.scalar() is not None


def _is_hypertable(bind: sa.engine.Connection, table: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = :tbl LIMIT 1"
        ),
        {"tbl": table},
    )
    return result.scalar() is not None


def _apply_hypertable(
    bind: sa.engine.Connection,
    table: str,
    time_col: str,
    retention_interval: str,
    compress_after: str,
    compress_segmentby: str,
    compress_orderby: str,
) -> None:
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return

    if _is_hypertable(bind, table):
        return  # Already converted; policies may already exist — skip.

    op.execute(
        sa.text(
            f"SELECT create_hypertable('{table}', '{time_col}', "
            f"migrate_data => true, if_not_exists => true)"
        )
    )

    op.execute(
        sa.text(
            f"ALTER TABLE {table} SET ("
            f"timescaledb.compress, "
            f"timescaledb.compress_segmentby = '{compress_segmentby}', "
            f"timescaledb.compress_orderby = '{compress_orderby}'"
            f")"
        )
    )

    op.execute(
        sa.text(
            f"SELECT add_compression_policy('{table}', "
            f"INTERVAL '{compress_after}', if_not_exists => true)"
        )
    )

    op.execute(
        sa.text(
            f"SELECT add_retention_policy('{table}', "
            f"INTERVAL '{retention_interval}', if_not_exists => true)"
        )
    )


def _fix_hardware_live_metrics_pk(bind: sa.engine.Connection) -> None:
    """Ensure the PK on hardware_live_metrics is (id, collected_at) composite.

    TimescaleDB requires the partitioning column (collected_at) to be part of
    the primary key. The original table had only id as the PK.
    """
    insp = sa.inspect(bind)
    pk = insp.get_pk_constraint("hardware_live_metrics")
    if set(pk.get("constrained_columns", [])) == {"id", "collected_at"}:
        return  # Already composite — nothing to do.

    # Drop the old single-column PK constraint.
    op.execute(
        sa.text(
            "ALTER TABLE hardware_live_metrics DROP CONSTRAINT IF EXISTS pk_hardware_live_metrics"
        )
    )

    # Create composite PK satisfying TimescaleDB's requirement.
    op.execute(sa.text("ALTER TABLE hardware_live_metrics ADD PRIMARY KEY (id, collected_at)"))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_timescaledb(bind):
        # TimescaleDB not installed — skip gracefully.
        # Re-run `make migrate` after installing timescaledb-2-postgresql-15.
        return

    # Enable the extension (idempotent).
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))

    # ── telemetry_timeseries ────────────────────────────────────────────────
    # Migration 0041 ran but skipped hypertable conversion because TimescaleDB
    # was not available at the time. Apply it now.
    _apply_hypertable(
        bind,
        table="telemetry_timeseries",
        time_col="ts",
        retention_interval="90 days",
        compress_after="14 days",
        compress_segmentby="entity_type, entity_id",
        compress_orderby="ts DESC",
    )

    # ── hardware_live_metrics ───────────────────────────────────────────────
    # Fix PK first (TimescaleDB requires time column in PK), then convert.
    _fix_hardware_live_metrics_pk(bind)
    _apply_hypertable(
        bind,
        table="hardware_live_metrics",
        time_col="collected_at",
        retention_interval="30 days",
        compress_after="7 days",
        compress_segmentby="hardware_id",
        compress_orderby="collected_at DESC",
    )


def downgrade() -> None:
    bind = op.get_bind()

    if not _has_timescaledb(bind):
        return

    for table in ("hardware_live_metrics", "telemetry_timeseries"):
        try:
            op.execute(sa.text(f"SELECT remove_retention_policy('{table}', if_exists => true)"))
            op.execute(sa.text(f"SELECT remove_compression_policy('{table}', if_exists => true)"))
        except Exception:  # noqa: BLE001
            pass
    # Note: converting a hypertable back to a plain table requires pg_dump/restore.
    # This downgrade only removes policies; the hypertable structure remains.
