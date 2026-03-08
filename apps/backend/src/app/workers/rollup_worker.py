"""Worker to aggregate daily uptime stats.

Runs periodically to aggregate UptimeEvents into DailyUptimeStats
for efficient 24h uptime reporting.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
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

        # Count total events and up events for the day
        total_events = (
            db.scalar(
                select(func.count())
                .select_from(UptimeEvent)
                .where(
                    UptimeEvent.hardware_id == monitor.hardware_id,
                    UptimeEvent.checked_at >= iso_start,
                    UptimeEvent.checked_at < iso_end,
                )
            )
            or 0
        )

        up_events = (
            db.scalar(
                select(func.count())
                .select_from(UptimeEvent)
                .where(
                    UptimeEvent.hardware_id == monitor.hardware_id,
                    UptimeEvent.checked_at >= iso_start,
                    UptimeEvent.checked_at < iso_end,
                    UptimeEvent.status == "up",
                )
            )
            or 0
        )

        # Assuming events roughly correspond to intervals.
        # This is an approximation since we changed to state-event logging,
        # so for daily stats, we might calculate total minutes from exact transitions later.
        # For now, we seed the rollup with basic counts
        # (This logic can be refined to calculate exact durations between state transitions)
        # Assuming interval_secs determines the original frequency if events were continuous:
        mins_per_event = monitor.interval_secs / 60.0

        total_minutes = int(total_events * mins_per_event)
        uptime_minutes = int(up_events * mins_per_event)

        # For state transition logic, a better approach is to find time difference
        # between UP and DOWN events. If the current model is just beginning to use transition logic,
        # we will placeholder this as a direct summation and refine it as the events settle.

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


def run_rollup_job() -> None:
    """APScheduler-compatible wrapper — opens its own DB session."""
    db = SessionLocal()
    try:
        # Target yesterday to finalize rollups, or today for incremental
        target_date = datetime.now(UTC).strftime("%Y-%m-%d")
        calculate_daily_rollups(db, target_date)

        # Also run for yesterday to ensure completed day is accurate
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        calculate_daily_rollups(db, yesterday)
    except Exception as exc:
        logger.error("run_rollup_job failed: %s", exc)
    finally:
        db.close()


if __name__ == "__main__":
    run_rollup_job()
