"""Worker to aggregate daily uptime stats.

Runs periodically to aggregate UptimeEvents into DailyUptimeStats
for efficient 24h uptime reporting.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DailyUptimeStats, HardwareMonitor, UptimeEvent
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def calculate_daily_rollups(db: Session, target_date: str) -> None:
    """Calculate and upsert daily uptime stats for all monitored hardware."""
    monitors = db.scalars(select(HardwareMonitor)).all()

    for monitor in monitors:
        # Start and end of the target date
        dt_start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=UTC)
        dt_end = dt_start + timedelta(days=1)

        iso_start = dt_start.isoformat()
        iso_end = dt_end.isoformat()

        # Fetch exact events to compute real time differences
        events = db.scalars(
            select(UptimeEvent)
            .where(
                UptimeEvent.hardware_id == monitor.hardware_id,
                UptimeEvent.checked_at >= iso_start,
                UptimeEvent.checked_at < iso_end,
            )
            .order_by(UptimeEvent.checked_at.asc())
        ).all()

        total_minutes = 24 * 60
        uptime_minutes = 0.0

        if not events:
            # If no events today, use the last known status from the monitor
            if monitor.last_status == "up":
                uptime_minutes = float(total_minutes)
        else:
            # Fetch the latest event before dt_start to know initial state
            prev_event = db.scalars(
                select(UptimeEvent)
                .where(
                    UptimeEvent.hardware_id == monitor.hardware_id,
                    UptimeEvent.checked_at < iso_start,
                )
                .order_by(UptimeEvent.checked_at.desc())
                .limit(1)
            ).first()

            current_status = prev_event.status if prev_event else "down"
            current_time = dt_start

            for e in events:
                event_time = datetime.fromisoformat(e.checked_at.replace("Z", "+00:00"))
                duration_mins = (event_time - current_time).total_seconds() / 60.0

                if current_status == "up":
                    uptime_minutes += duration_mins

                current_time = event_time
                current_status = e.status

            # Add the rest of the day until dt_end or now (if target_date is today)
            end_of_period = min(dt_end, datetime.now(UTC))
            if current_time < end_of_period:
                duration_mins = (end_of_period - current_time).total_seconds() / 60.0
                if current_status == "up":
                    uptime_minutes += duration_mins

        uptime_minutes = int(uptime_minutes)

        stat = db.scalar(
            select(DailyUptimeStats).where(
                DailyUptimeStats.hardware_id == monitor.hardware_id,
                DailyUptimeStats.date == target_date,
            )
        )

        if not stat:
            stat = DailyUptimeStats(
                hardware_id=monitor.hardware_id,
                date=target_date,
                total_minutes=total_minutes,
                uptime_minutes=uptime_minutes,
            )
            db.add(stat)
        else:
            stat.total_minutes = total_minutes
            stat.uptime_minutes = uptime_minutes
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
            entity_type="daily_uptime_stats",
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
