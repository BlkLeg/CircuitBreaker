from datetime import UTC, datetime

from app.db.models import MonitorItem


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
