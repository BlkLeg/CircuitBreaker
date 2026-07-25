from datetime import UTC, datetime, timedelta

from app.db.models import MonitorEvent, MonitorItem
from app.services.monitoring.state import DOWN, PENDING, UP, apply_result, decide

# ── decide(): pure transitions ─────────────────────────────────────────────────


def test_up_stays_up():
    d = decide(UP, 0, up=True, max_retries=3)
    assert d.new_status == UP and d.retries == 0
    assert d.event_type is None and d.notify is None


def test_first_check_up():
    d = decide(None, 0, up=True, max_retries=0)
    assert d.new_status == UP and d.event_type == "up" and d.notify is None


def test_failure_enters_pending_within_retries():
    d = decide(UP, 0, up=False, max_retries=3)
    assert d.new_status == PENDING and d.retries == 1
    assert d.event_type == "pending" and d.notify is None


def test_pending_stays_pending_silently():
    d = decide(PENDING, 1, up=False, max_retries=3)
    assert d.new_status == PENDING and d.retries == 2 and d.event_type is None


def test_retries_exhausted_goes_down():
    d = decide(PENDING, 3, up=False, max_retries=3)
    assert d.new_status == DOWN and d.event_type == "down" and d.notify == "down"


def test_no_retries_goes_straight_down():
    d = decide(UP, 0, up=False, max_retries=0)
    assert d.new_status == DOWN and d.notify == "down"


def test_down_stays_down_silently():
    d = decide(DOWN, 5, up=False, max_retries=3)
    assert d.new_status == DOWN and d.event_type is None and d.notify is None


def test_recovery_from_down_notifies():
    d = decide(DOWN, 4, up=True, max_retries=3)
    assert d.new_status == UP and d.retries == 0
    assert d.event_type == "up" and d.notify == "recovered"


def test_recovery_from_pending_no_notify():
    d = decide(PENDING, 2, up=True, max_retries=3)
    assert d.new_status == UP and d.event_type == "up" and d.notify is None


# ── apply_result(): row + event persistence ────────────────────────────────────


def _mk_item(db, **kw):
    defaults = dict(
        name="m",
        host="192.0.2.1",
        check_type="icmp",
        target_type=None,
        max_retries=1,
        retry_interval_secs=5,
        interval_secs=60,
        last_status=UP,
        consecutive_failures=0,
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
        last_status_change_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    defaults.update(kw)
    item = MonitorItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_apply_failure_sets_pending_and_reschedules(db_session):
    item = _mk_item(db_session)
    now = datetime.now(UTC)
    transition = apply_result(db_session, item.id, up=False, msg="timeout", checked_at=now)
    db_session.flush()
    db_session.refresh(item)
    assert item.last_status == PENDING
    assert item.consecutive_failures == 1
    # retry rescheduling: next check ~retry_interval_secs out, not interval_secs
    assert (item.next_due_at - now).total_seconds() <= 10
    assert transition.status_to == PENDING and transition.notify is None
    ev = db_session.query(MonitorEvent).filter_by(item_id=item.id).one()
    assert ev.event_type == "pending" and ev.msg == "timeout"


def test_apply_down_then_recover_notifies(db_session):
    item = _mk_item(db_session, last_status=PENDING, consecutive_failures=1)
    now = datetime.now(UTC)
    t1 = apply_result(db_session, item.id, up=False, msg="still down", checked_at=now)
    assert t1.status_to == DOWN and t1.notify == "down"
    t2 = apply_result(db_session, item.id, up=True, msg="200 in 12ms", checked_at=now)
    assert t2.status_to == UP and t2.notify == "recovered"
    db_session.flush()
    db_session.refresh(item)
    assert item.consecutive_failures == 0
    assert db_session.query(MonitorEvent).filter_by(item_id=item.id).count() == 2


def test_apply_no_transition_returns_none(db_session):
    item = _mk_item(db_session)
    result = apply_result(db_session, item.id, up=True, msg="ok", checked_at=datetime.now(UTC))
    assert result is None
    assert db_session.query(MonitorEvent).filter_by(item_id=item.id).count() == 0


def test_apply_missing_item_returns_none(db_session):
    assert apply_result(db_session, 999999, up=True, msg="", checked_at=datetime.now(UTC)) is None
