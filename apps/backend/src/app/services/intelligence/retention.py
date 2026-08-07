"""Telemetry retention: downsample warm-window rows, purge cold rows."""

from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import extract, func, select
from sqlalchemy.dialects import postgresql

from app.core.time import utcnow
from app.db.models import AgentHostSample, AgentHostSampleHourly, AppSettings, HardwareLiveMetric

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.orm import Session

_DEFAULT_HOT_DAYS = 7
_DEFAULT_WARM_DAYS = 30
_BUCKET_SECONDS = 3600

# The eight series `GET /agents/{id}/history` emits, in the order it emits them.
# Any field added here must also be added to the history projection, and vice
# versa, or a 7 d/30 d point will carry a `None` series.
_AGENT_SUMMARY_FIELDS = (
    "cpu_pct",
    "mem_pct",
    "root_disk_pct",
    "net_rx_bps",
    "net_tx_bps",
    "max_temp_c",
    "load_1",
    "uptime_s",
)


def _avg(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    return mean(clean) if clean else None


def run_retention_executor(
    db: Session,
    hot_days: int | None = None,
    warm_days: int | None = None,
) -> dict[str, int]:
    """Run retention/downsampling for hardware **and** agent telemetry.

    Hot window  (0 → hot_days ago):     keep all rows as-is.
    Warm window (hot_days → warm_days): replace raw rows with hourly averages.
    Cold        (beyond warm_days):     delete entirely.

    Two independent branches share the same window arithmetic:

    * ``hardware_live_metrics`` — warm rows are collapsed in place into
      ``source="hourly_agg"`` rows.
    * ``agent_host_samples`` — warm rows are collapsed into the portable
      ``agent_host_sample_hourly`` table by a single set-based upsert, so the
      7-30 day window behaves identically with and without TimescaleDB jobs.
      The bucket expression is deliberately ``to_timestamp(floor(...))`` rather
      than ``time_bucket()``/``date_bin()``: the backend is PostgreSQL-only but
      TimescaleDB-optional.

    Neither branch commits — the caller (``workers/analytics_worker.py``) owns
    the transaction.

    Reads hot_days/warm_days from AppSettings when not supplied (defaults: 7/30).
    Returns grand totals plus a per-branch breakdown::

        {"downsampled": N, "deleted": N,
         "hardware_downsampled": N, "hardware_deleted": N,
         "agent_downsampled": N, "agent_deleted": N, "agent_hourly_deleted": N}
    """
    # Resolve settings
    if hot_days is None or warm_days is None:
        settings = db.execute(select(AppSettings)).scalar_one_or_none()
        if hot_days is None:
            hot_days = (
                getattr(settings, "telemetry_hot_days", None) or _DEFAULT_HOT_DAYS
                if settings
                else _DEFAULT_HOT_DAYS
            )
        if warm_days is None:
            warm_days = (
                getattr(settings, "telemetry_warm_days", None) or _DEFAULT_WARM_DAYS
                if settings
                else _DEFAULT_WARM_DAYS
            )

    now = utcnow()
    hot_cutoff = now - timedelta(days=hot_days)
    warm_cutoff = now - timedelta(days=warm_days)

    downsampled = 0

    # --- Warm window: downsample raw rows to hourly averages ---
    # Find distinct hardware_ids that have non-aggregated rows in the warm window
    hw_ids_result = (
        db.execute(
            select(HardwareLiveMetric.hardware_id)
            .where(
                HardwareLiveMetric.collected_at >= warm_cutoff,
                HardwareLiveMetric.collected_at < hot_cutoff,
                HardwareLiveMetric.source != "hourly_agg",
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    for hw_id in hw_ids_result:
        raw_rows = (
            db.execute(
                select(HardwareLiveMetric)
                .where(
                    HardwareLiveMetric.hardware_id == hw_id,
                    HardwareLiveMetric.collected_at >= warm_cutoff,
                    HardwareLiveMetric.collected_at < hot_cutoff,
                    HardwareLiveMetric.source != "hourly_agg",
                )
                .order_by(HardwareLiveMetric.collected_at)
            )
            .scalars()
            .all()
        )

        if not raw_rows:
            continue

        # Group by hour bucket
        buckets: dict[object, list[HardwareLiveMetric]] = {}
        for row in raw_rows:
            bucket = row.collected_at.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(row)

        # Delete raw rows
        raw_ids = [r.id for r in raw_rows]
        db.query(HardwareLiveMetric).filter(HardwareLiveMetric.id.in_(raw_ids)).delete(
            synchronize_session=False
        )

        # Insert averaged rows
        for bucket_ts, bucket_rows in buckets.items():
            agg = HardwareLiveMetric(
                hardware_id=hw_id,
                collected_at=bucket_ts,
                cpu_pct=_avg([r.cpu_pct for r in bucket_rows]),
                mem_pct=_avg([r.mem_pct for r in bucket_rows]),
                disk_pct=_avg([r.disk_pct for r in bucket_rows]),
                mem_used_mb=_avg([r.mem_used_mb for r in bucket_rows]),
                temp_c=_avg([r.temp_c for r in bucket_rows]),
                power_w=_avg([r.power_w for r in bucket_rows]),
                status=bucket_rows[-1].status,
                source="hourly_agg",
            )
            db.add(agg)
            downsampled += 1

    db.flush()

    # --- Cold window: delete all rows older than warm_cutoff ---
    deleted = (
        db.query(HardwareLiveMetric)
        .filter(HardwareLiveMetric.collected_at < warm_cutoff)
        .delete(synchronize_session=False)
    )

    # --- Agent host samples ---------------------------------------------------
    # Fleet-wide maintenance pass: this is the named exemption to the "filter on
    # both agent_id and collected_at" rule — the aggregate groups *by* agent_id
    # across every agent and both DELETEs are fleet-wide by design. All three
    # statements still carry a collected_at/bucket_at predicate, so hypertable
    # chunk exclusion applies.
    bucket_at = func.to_timestamp(
        func.floor(extract("epoch", AgentHostSample.collected_at) / _BUCKET_SECONDS)
        * _BUCKET_SECONDS
    )
    agg_select = (
        select(
            AgentHostSample.agent_id,
            bucket_at,
            func.count(),
            func.jsonb_build_object(
                *[
                    part
                    for name in _AGENT_SUMMARY_FIELDS
                    for part in (name, func.avg(getattr(AgentHostSample, name)))
                ]
            ),
        )
        .where(
            AgentHostSample.collected_at >= warm_cutoff,
            AgentHostSample.collected_at < hot_cutoff,
        )
        .group_by(AgentHostSample.agent_id, bucket_at)
    )
    upsert = postgresql.insert(AgentHostSampleHourly).from_select(
        ["agent_id", "bucket_at", "sample_count", "summary"], agg_select
    )
    upsert = upsert.on_conflict_do_update(
        index_elements=["agent_id", "bucket_at"],
        set_={
            "sample_count": upsert.excluded.sample_count,
            "summary": upsert.excluded.summary,
        },
    )
    agent_downsampled = cast("CursorResult[Any]", db.execute(upsert)).rowcount

    # Aggregate first, then purge: everything below hot_cutoff goes, which
    # includes rows older than warm_cutoff that the aggregate deliberately
    # skipped — they are already cold and have no hourly bucket to feed.
    # Kept as a portable bulk DELETE; drop_chunks() is Timescale-only.
    agent_deleted = (
        db.query(AgentHostSample)
        .filter(AgentHostSample.collected_at < hot_cutoff)
        .delete(synchronize_session=False)
    )
    agent_hourly_deleted = (
        db.query(AgentHostSampleHourly)
        .filter(AgentHostSampleHourly.bucket_at < warm_cutoff)
        .delete(synchronize_session=False)
    )

    return {
        "downsampled": downsampled + agent_downsampled,
        "deleted": deleted + agent_deleted + agent_hourly_deleted,
        "hardware_downsampled": downsampled,
        "hardware_deleted": deleted,
        "agent_downsampled": agent_downsampled,
        "agent_deleted": agent_deleted,
        "agent_hourly_deleted": agent_hourly_deleted,
    }
