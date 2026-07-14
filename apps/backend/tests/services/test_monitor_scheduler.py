from datetime import UTC, datetime, timedelta

from app.db.models import MonitorItem
from app.services.monitoring.scheduler import claim_due_items


def _mk(db, *, due_offset_s, enabled=True, interval=60):
    item = MonitorItem(
        target_type="ip",
        target_id=None,
        host="10.0.0.9",
        check_type="icmp",
        params={},
        interval_secs=interval,
        enabled=enabled,
        next_due_at=datetime.now(UTC) + timedelta(seconds=due_offset_s),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_claim_returns_only_due_enabled_items(db_session):
    due = _mk(db_session, due_offset_s=-5)
    _mk(db_session, due_offset_s=120)  # not due
    _mk(db_session, due_offset_s=-5, enabled=False)  # disabled

    claimed = claim_due_items(db_session, batch=100)
    ids = [c["item_id"] for c in claimed]
    assert ids == [due.id]


def test_claim_advances_next_due_beyond_now(db_session):
    item = _mk(db_session, due_offset_s=-5, interval=60)
    claim_due_items(db_session, batch=100)
    db_session.expire_all()
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.next_due_at > datetime.now(UTC)
    # Immediately claiming again returns nothing — no double-enqueue.
    assert claim_due_items(db_session, batch=100) == []
