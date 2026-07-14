# apps/backend/tests/services/test_monitor_poll_worker.py
import asyncio
from unittest.mock import patch

from app.db.models import TelemetryTimeseries
from app.services.monitoring.collectors import Sample
from app.workers.monitor_poll_worker import poll_one, process_batch


def test_poll_one_runs_collector():
    item = {
        "item_id": 5,
        "target_type": "ip",
        "target_id": None,
        "host": "10.0.0.5",
        "check_type": "icmp",
        "params": {"packet_count": 1},
        "interval_secs": 60,
    }
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {"icmp": lambda host, params: [Sample("avail", 1.0)]},
    ):
        row = asyncio.run(poll_one(item))
    item_id, entity_type, entity_id, samples, ts = row
    assert item_id == 5
    assert samples[0].metric == "avail"


def test_poll_one_unknown_check_type_is_down():
    item = {
        "item_id": 6,
        "target_type": "ip",
        "target_id": None,
        "host": "x",
        "check_type": "bogus",
        "params": {},
        "interval_secs": 60,
    }
    row = asyncio.run(poll_one(item))
    _, _, _, samples, _ = row
    assert samples[0].metric == "avail" and samples[0].value == 0.0
    assert samples[0].error_reason == "unknown_check_type"


def _noop_close_factory(session):
    """Return a factory that yields the test session but suppresses close()
    so the SAVEPOINT-isolated session stays usable for post-batch assertions."""
    original_close = session.close

    def factory():
        session.close = lambda: None  # suppress close inside process_batch
        return session

    return factory, original_close


def test_process_batch_writes_all(db_session):
    factory, orig_close = _noop_close_factory(db_session)

    items = [
        {
            "item_id": 10,
            "target_type": "ip",
            "target_id": None,
            "host": "a",
            "check_type": "icmp",
            "params": {},
            "interval_secs": 60,
        },
        {
            "item_id": 11,
            "target_type": "ip",
            "target_id": None,
            "host": "b",
            "check_type": "icmp",
            "params": {},
            "interval_secs": 60,
        },
    ]
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {"icmp": lambda host, params: [Sample("avail", 1.0)]},
    ):
        written = asyncio.run(process_batch(items, factory))
    db_session.close = orig_close  # restore
    assert written == 2
    assert (
        db_session.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_([10, 11]))
        .count()
        == 2
    )
