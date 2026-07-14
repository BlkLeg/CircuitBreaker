# apps/backend/tests/integration/test_monitor_engine_e2e.py
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.db.models import MonitorItem, TelemetryTimeseries
from app.services.monitoring.collectors import Sample
from app.services.monitoring.scheduler import claim_due_items
from app.workers.monitor_poll_worker import process_batch


def _due_item(db, host, offset_s=-1):
    it = MonitorItem(
        target_type="ip",
        target_id=None,
        host=host,
        check_type="icmp",
        params={"packet_count": 3},
        interval_secs=60,
        enabled=True,
        next_due_at=datetime.now(UTC) + timedelta(seconds=offset_s),
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def _noop_close_factory(session):
    """Return a factory that yields the test session but suppresses close()
    so the SAVEPOINT-isolated session stays usable for post-batch assertions."""
    original_close = session.close

    def factory():
        session.close = lambda: None
        return session

    return factory, original_close


def test_claim_then_poll_writes_samples(db_session):
    item = _due_item(db_session, "10.0.0.5")
    claimed = claim_due_items(db_session, batch=50)
    assert [c["item_id"] for c in claimed] == [item.id]

    factory, orig_close = _noop_close_factory(db_session)
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {
            "icmp": lambda host, params: [
                Sample("avail", 1.0),
                Sample("packet_loss_pct", 0.0),
            ]
        },
    ):
        written = asyncio.run(process_batch(claimed, factory))
    db_session.close = orig_close
    assert written == 2

    stored = (
        db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == item.id).all()
    )
    assert {r.metric for r in stored} == {"avail", "packet_loss_pct"}


def test_restart_self_heals_no_wedged_items(db_session):
    """After a claim, a 'crash' before poll leaves the item simply due again later —
    never stuck. Claiming again immediately returns nothing (next_due advanced)."""
    item = _due_item(db_session, "10.0.0.6")
    claim_due_items(db_session, batch=50)  # simulate scheduler enqueue, then 'crash'
    # No poll happened. Item is not wedged in a 'running' state — it's just scheduled ahead.
    assert claim_due_items(db_session, batch=50) == []
    refreshed = db_session.get(MonitorItem, item.id)
    assert refreshed.next_due_at > datetime.now(UTC)


def test_duplicate_delivery_is_tolerated(db_session):
    item = _due_item(db_session, "10.0.0.7")
    claimed = claim_due_items(db_session, batch=50)
    factory, orig_close = _noop_close_factory(db_session)
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {"icmp": lambda host, params: [Sample("avail", 1.0)]},
    ):
        asyncio.run(process_batch(claimed, factory))
        asyncio.run(process_batch(claimed, factory))  # redelivery
    db_session.close = orig_close
    # Two near-duplicate samples — harmless, no crash, both present.
    n = (
        db_session.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id == item.id, TelemetryTimeseries.metric == "avail")
        .count()
    )
    assert n == 2
