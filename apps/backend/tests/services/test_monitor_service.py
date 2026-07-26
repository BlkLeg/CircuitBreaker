from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.db.models import MonitorDailyStats, TelemetryTimeseries
from app.schemas.monitor import HttpConfig, MonitorCreate
from app.services import monitor_service
from app.workers import rollup_worker


def test_create_validates_config_per_type():
    payload = MonitorCreate(
        name="site",
        check_type="http",
        host="192.0.2.4",
        config={"url": "https://example.com", "accepted_statuses": ["200-299"]},
    )
    assert payload.config["url"] == "https://example.com"

    with pytest.raises(ValidationError):
        MonitorCreate(
            name="bad",
            check_type="http",
            host="h",
            config={"accepted_statuses": "not-a-list"},
        )


def test_http_config_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        HttpConfig(url="http://x/", bogus_field=1)


def test_create_and_get_roundtrip(db_session):
    payload = MonitorCreate(
        name="dns watch",
        check_type="dns",
        host="example.com",
        config={"record_type": "A"},
        interval_secs=120,
        max_retries=2,
    )
    created = monitor_service.create_monitor(db_session, payload)
    assert created["id"] > 0
    fetched = monitor_service.get_monitor(db_session, created["id"])
    assert fetched["name"] == "dns watch"
    assert fetched["check_type"] == "dns"
    assert fetched["config"] == {"record_type": "A"}
    assert fetched["status"] == "pending"


def test_pause_records_event_and_disables(db_session):
    payload = MonitorCreate(name="p", check_type="icmp", host="192.0.2.9", config={})
    created = monitor_service.create_monitor(db_session, payload)
    paused = monitor_service.set_paused(db_session, created["id"], True)
    assert paused["enabled"] is False
    events = monitor_service.get_events(db_session, created["id"])
    assert events[0]["event_type"] == "paused"


def test_list_filters_by_target(db_session):
    monitor_service.create_monitor(
        db_session,
        MonitorCreate(
            name="a",
            check_type="icmp",
            host="192.0.2.1",
            config={},
            target_type="hardware",
            target_id=42,
        ),
    )
    monitor_service.create_monitor(
        db_session,
        MonitorCreate(
            name="b",
            check_type="icmp",
            host="192.0.2.2",
            config={},
        ),
    )
    linked = monitor_service.list_monitors(db_session, target_type="hardware", target_id=42)
    assert [m["name"] for m in linked] == ["a"]
    everything = monitor_service.list_monitors(db_session)
    assert len(everything) >= 2


def test_get_uptime_short_windows_from_telemetry(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="w", check_type="icmp", host="192.0.2.20", config={})
    )
    now = datetime.now(UTC)
    db_session.add_all(
        [
            TelemetryTimeseries(
                entity_type="monitor",
                entity_id=0,
                item_id=created["id"],
                metric="avail",
                value=1.0,
                ts=now - timedelta(hours=1),
            ),
            TelemetryTimeseries(
                entity_type="monitor",
                entity_id=0,
                item_id=created["id"],
                metric="avail",
                value=0.0,
                ts=now - timedelta(hours=2),
            ),
        ]
    )
    db_session.commit()

    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime["pct_24h"] == 50.0
    assert uptime["pct_7d"] == 50.0
    assert uptime["pct_30d"] == 50.0


def test_get_uptime_long_windows_from_rollups(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="r", check_type="icmp", host="192.0.2.21", config={})
    )
    today = datetime.now(UTC).date()
    db_session.add_all(
        [
            MonitorDailyStats(
                item_id=created["id"],
                date=(today - timedelta(days=1)).isoformat(),
                total_minutes=1440,
                uptime_minutes=1440,
            ),
            MonitorDailyStats(
                item_id=created["id"],
                date=(today - timedelta(days=2)).isoformat(),
                total_minutes=1440,
                uptime_minutes=720,
            ),
        ]
    )
    db_session.commit()

    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime["pct_365d"] == 75.0
    assert uptime["pct_total"] == 75.0


def _seed_full_day_of_uptime(db_session, item_id, day, *, every_mins=5):
    """Write avail=1.0 telemetry across a full UTC day at a realistic poll interval."""
    db_session.add_all(
        [
            TelemetryTimeseries(
                entity_type="monitor",
                entity_id=0,
                item_id=item_id,
                metric="avail",
                value=1.0,
                ts=day + timedelta(minutes=m),
            )
            for m in range(0, 24 * 60, every_mins)
        ]
    )
    db_session.commit()


def test_get_uptime_total_is_100_for_fully_up_day_end_to_end(db_session):
    """Worker + service together: a monitor up all day reads 100%, not interval/1440."""
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="e2e", check_type="icmp", host="192.0.2.23", config={})
    )
    day = (datetime.now(UTC) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    _seed_full_day_of_uptime(db_session, created["id"], day)

    rollup_worker.calculate_daily_rollups(db_session, day.date().isoformat())

    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime["pct_total"] == 100.0
    assert uptime["pct_365d"] == 100.0


def test_get_uptime_365d_excludes_rows_older_than_the_window(db_session):
    """Rows past 365 days drop out of pct_365d but still count toward pct_total."""
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="win", check_type="icmp", host="192.0.2.24", config={})
    )
    day = (datetime.now(UTC) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    _seed_full_day_of_uptime(db_session, created["id"], day)
    rollup_worker.calculate_daily_rollups(db_session, day.date().isoformat())

    today = datetime.now(UTC).date()
    db_session.add(
        MonitorDailyStats(
            item_id=created["id"],
            date=(today - timedelta(days=400)).isoformat(),
            total_minutes=100,
            uptime_minutes=0,
        )
    )
    db_session.commit()

    uptime = monitor_service.get_uptime(db_session, created["id"])
    # 288 observed minutes yesterday, all up; the 400-day-old 0/100 row is out of window.
    assert uptime["pct_365d"] == 100.0
    # ...but all-time still sees it: 288 / (288 + 100).
    assert uptime["pct_total"] == 74.2


def test_get_uptime_no_data_is_none(db_session):
    created = monitor_service.create_monitor(
        db_session, MonitorCreate(name="n", check_type="icmp", host="192.0.2.22", config={})
    )
    uptime = monitor_service.get_uptime(db_session, created["id"])
    assert uptime == {
        "pct_24h": None,
        "pct_7d": None,
        "pct_30d": None,
        "pct_365d": None,
        "pct_total": None,
        "last_polled_at": None,
    }
