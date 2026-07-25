import pytest
from pydantic import ValidationError

from app.schemas.monitor import HttpConfig, MonitorCreate
from app.services import monitor_service


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
