from datetime import UTC, datetime

from app.db.models import MonitorEvent, MonitorItem


def test_monitor_item_persists_with_defaults(db_session):
    item = MonitorItem(
        target_type="hardware",
        target_id=1,
        host="10.0.0.5",
        check_type="icmp",
        params={"packet_count": 5, "timeout": 1.5},
        interval_secs=60,
        next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert item.id is not None
    assert item.enabled is True
    assert item.consecutive_failures == 0
    assert item.params["packet_count"] == 5


def test_telemetry_row_accepts_item_id(db_session):
    from datetime import UTC, datetime

    from app.db.models import TelemetryTimeseries

    row = TelemetryTimeseries(
        entity_type="hardware",
        entity_id=1,
        item_id=42,
        metric="packet_loss_pct",
        value=0.0,
        ts=datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.item_id == 42


def test_monitor_item_native_fields(db_session):
    item = MonitorItem(
        name="edge router dns",
        target_type=None,
        target_id=None,
        host="192.0.2.10",
        check_type="dns",
        params={"record_type": "A"},
        interval_secs=60,
        max_retries=3,
        retry_interval_secs=15,
        next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.flush()
    assert item.id is not None
    assert item.max_retries == 3
    assert item.last_status_change_at is None


def test_monitor_event_row(db_session):
    item = MonitorItem(
        name="probe",
        host="192.0.2.11",
        check_type="icmp",
        target_type="ip",
        next_due_at=datetime.now(UTC),
    )
    db_session.add(item)
    db_session.flush()
    ev = MonitorEvent(
        item_id=item.id,
        event_type="down",
        status_from="up",
        status_to="down",
        msg="timed out",
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None
    assert ev.created_at is not None
