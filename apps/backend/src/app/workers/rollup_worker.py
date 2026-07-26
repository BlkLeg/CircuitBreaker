"""Worker to aggregate daily uptime stats.

Runs periodically to aggregate raw telemetry into MonitorDailyStats
for efficient long-range uptime reporting (365d, all-time).
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import MonitorDailyStats, MonitorItem
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def calculate_daily_rollups(db: Session, target_date: str) -> None:
    """Calculate and upsert daily uptime stats for every monitor using telemetry."""
    item_ids = db.scalars(select(MonitorItem.id)).all()

    dt_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=UTC)
    dt_end = dt_start + timedelta(days=1)

    for item_id in item_ids:
        query = text("""
            SELECT count(*) as up_minutes
            FROM (
                SELECT time_bucket('1 minute', ts) as minute_bucket, max(value) as max_avail
                FROM telemetry_timeseries
                WHERE item_id = :item_id
                  AND metric = 'avail'
                  AND ts >= :start_ts AND ts < :end_ts
                GROUP BY minute_bucket
            ) sub
            WHERE max_avail > 0
        """)

        up_minutes = (
            db.scalar(query, {"item_id": item_id, "start_ts": dt_start, "end_ts": dt_end}) or 0
        )

        total_minutes = 24 * 60

        stat = db.scalar(
            select(MonitorDailyStats).where(
                MonitorDailyStats.item_id == item_id,
                MonitorDailyStats.date == target_date,
            )
        )

        if not stat:
            stat = MonitorDailyStats(
                item_id=item_id,
                date=target_date,
                total_minutes=total_minutes,
                uptime_minutes=int(up_minutes),
            )
            db.add(stat)
        else:
            stat.total_minutes = total_minutes
            stat.uptime_minutes = int(up_minutes)
            stat.updated_at = datetime.now(UTC)

    db.commit()


def _run_rollup_job_impl() -> None:
    """Inner rollup logic (called under advisory lock)."""
    db = SessionLocal()
    try:
        target_date = datetime.now(UTC).strftime("%Y-%m-%d")
        calculate_daily_rollups(db, target_date)
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        calculate_daily_rollups(db, yesterday)
    except Exception as exc:
        logger.error("run_rollup_job failed: %s", exc)
        from app.core.worker_audit import log_worker_audit

        log_worker_audit(
            action="rollup_failed",
            entity_type="monitor_daily_stats",
            details=str(exc)[:200],
            severity="error",
            worker_name="rollup_worker",
        )
    finally:
        db.close()


def run_rollup_job() -> None:
    """APScheduler-compatible wrapper. Single-run via advisory lock."""
    from app.core.job_lock import run_with_advisory_lock

    run_with_advisory_lock("daily_uptime_rollup", job_fn=_run_rollup_job_impl)


if __name__ == "__main__":
    run_rollup_job()
