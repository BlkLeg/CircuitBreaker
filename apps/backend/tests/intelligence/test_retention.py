from datetime import UTC, datetime, timedelta

from app.db.models import HardwareLiveMetric
from app.services.intelligence.retention import run_retention_executor


def _seed_dense(db, hw_id, days_ago_start, days_ago_end, interval_minutes=1):
    start = datetime.now(tz=UTC) - timedelta(days=days_ago_start)
    start = start.replace(minute=0, second=0, microsecond=0)  # align to hour boundary
    end = datetime.now(tz=UTC) - timedelta(days=days_ago_end)
    end = end.replace(minute=0, second=0, microsecond=0)  # align to hour boundary
    rows, ts = [], start
    while ts < end:
        rows.append(
            HardwareLiveMetric(
                hardware_id=hw_id,
                collected_at=ts,
                cpu_pct=30.0,
                mem_pct=40.0,
                disk_pct=50.0,
                source="test",
                status="up",
            )
        )
        ts += timedelta(minutes=interval_minutes)
    db.bulk_save_objects(rows)
    db.flush()
    return len(rows)


def test_recent_data_preserved(db_session, factories):
    """Data within hot_retention_days is not touched."""
    hw = factories.hardware(name="ret-hw-1", ip_address="10.9.9.1")
    seeded = _seed_dense(db_session, hw.id, days_ago_start=3, days_ago_end=1)

    run_retention_executor(db_session, hot_days=7, warm_days=30)

    remaining = db_session.query(HardwareLiveMetric).filter_by(hardware_id=hw.id).count()
    assert remaining == seeded


def test_old_data_downsampled_not_deleted(db_session, factories):
    """Data older than hot_days gets downsampled to hourly; raw rows removed."""
    hw = factories.hardware(name="ret-hw-2", ip_address="10.9.9.2")
    # 2 days of per-minute data from 10-12 days ago (outside hot=7 window)
    _seed_dense(db_session, hw.id, days_ago_start=12, days_ago_end=10)

    run_retention_executor(db_session, hot_days=7, warm_days=30)

    raw_count = (
        db_session.query(HardwareLiveMetric).filter_by(hardware_id=hw.id, source="test").count()
    )
    assert raw_count == 0  # raw rows removed

    agg_count = (
        db_session.query(HardwareLiveMetric)
        .filter_by(hardware_id=hw.id, source="hourly_agg")
        .count()
    )
    assert agg_count == 48  # 2 days × 24 hours
