"""Telemetry retention: downsample warm-window rows, purge cold rows."""

from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.time import utcnow
from app.db.models import AppSettings, HardwareLiveMetric

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_DEFAULT_HOT_DAYS = 7
_DEFAULT_WARM_DAYS = 30


def _avg(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    return mean(clean) if clean else None


def run_retention_executor(
    db: Session,
    hot_days: int | None = None,
    warm_days: int | None = None,
) -> dict[str, int]:
    """Run retention/downsampling for HardwareLiveMetric rows.

    Hot window  (0 → hot_days ago):     keep all rows as-is.
    Warm window (hot_days → warm_days): replace raw rows with hourly averages
                                        (source="hourly_agg").
    Cold        (beyond warm_days):     delete entirely.

    Reads hot_days/warm_days from AppSettings when not supplied (defaults: 7/30).
    Returns {"downsampled": N, "deleted": N}.
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

    return {"downsampled": downsampled, "deleted": deleted}
