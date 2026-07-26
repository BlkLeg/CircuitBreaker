from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import MonitorDailyStats, MonitorItem, TelemetryTimeseries
from app.workers.rollup_worker import calculate_daily_rollups


def _make_item(db_session, **overrides):
    item = MonitorItem(
        name="w",
        host="192.0.2.30",
        check_type="icmp",
        interval_secs=60,
        last_status="up",
        next_due_at=datetime.now(UTC),
        **overrides,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_rollup_covers_non_hardware_target_types(db_session):
    item = _make_item(db_session, target_type="service", target_id=5)
    day = datetime(2026, 7, 20, tzinfo=UTC)
    db_session.add_all(
        [
            TelemetryTimeseries(
                entity_type="service",
                entity_id=5,
                item_id=item.id,
                metric="avail",
                value=1.0,
                ts=day + timedelta(minutes=m),
            )
            for m in range(0, 60, 10)
        ]
    )
    db_session.commit()

    calculate_daily_rollups(db_session, "2026-07-20")

    stat = db_session.scalar(
        select(MonitorDailyStats).where(
            MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20"
        )
    )
    assert stat is not None
    assert stat.total_minutes == 1440
    assert stat.uptime_minutes >= 1


def test_rollup_covers_standalone_monitor(db_session):
    item = _make_item(db_session, target_type=None, target_id=None)
    day = datetime(2026, 7, 20, tzinfo=UTC)
    db_session.add(
        TelemetryTimeseries(
            entity_type="monitor",
            entity_id=0,
            item_id=item.id,
            metric="avail",
            value=0.0,
            ts=day,
        )
    )
    db_session.commit()

    calculate_daily_rollups(db_session, "2026-07-20")

    stat = db_session.scalar(
        select(MonitorDailyStats).where(
            MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20"
        )
    )
    assert stat is not None
    assert stat.uptime_minutes == 0


def test_rollup_upserts_on_rerun(db_session):
    item = _make_item(db_session)
    calculate_daily_rollups(db_session, "2026-07-20")
    calculate_daily_rollups(db_session, "2026-07-20")
    count = db_session.scalar(
        select(func.count())
        .select_from(MonitorDailyStats)
        .where(MonitorDailyStats.item_id == item.id, MonitorDailyStats.date == "2026-07-20")
    )
    assert count == 1
