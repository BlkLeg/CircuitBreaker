# apps/backend/tests/services/test_monitor_poll_worker.py
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.db.models import MonitorItem, TelemetryTimeseries
from app.services.monitoring.collectors import CheckResult, Sample
from app.workers import monitor_poll_worker as mpw
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
    up_result = CheckResult(up=True, samples=[Sample("avail", 1.0)], msg="ok")
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {"icmp": lambda host, params: up_result},
    ):
        row, up, msg = asyncio.run(poll_one(item))
    item_id, entity_type, entity_id, samples, ts = row
    assert item_id == 5
    assert samples[0].metric == "avail"
    assert up is True and msg == "ok"


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
    row, up, msg = asyncio.run(poll_one(item))
    _, _, _, samples, _ = row
    assert samples[0].metric == "avail" and samples[0].value == 0.0
    assert samples[0].error_reason == "unknown_check_type"
    assert up is False


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
    with (
        patch(
            "app.workers.monitor_poll_worker.COLLECTORS",
            {"icmp": lambda host, params: CheckResult(up=True, samples=[Sample("avail", 1.0)])},
        ),
        patch.object(mpw, "get_redis", AsyncMock(return_value=None)),
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


async def test_poll_one_returns_up_and_msg():
    up_result = CheckResult(up=True, samples=[Sample("avail", 1.0)], msg="ok")
    with patch(
        "app.workers.monitor_poll_worker.COLLECTORS",
        {"fake_up": lambda host, params: up_result},
    ):
        row, up, msg = await poll_one(
            {
                "item_id": 1,
                "target_type": "ip",
                "target_id": None,
                "host": "192.0.2.1",
                "check_type": "fake_up",
                "params": {},
            }
        )
    assert up is True and msg == "ok"
    assert row[0] == 1


async def test_process_batch_applies_state_and_publishes(db_session):
    factory, orig_close = _noop_close_factory(db_session)
    item = MonitorItem(
        name="web",
        host="192.0.2.1",
        check_type="fake_down",
        target_type=None,
        max_retries=0,
        interval_secs=60,
        last_status="up",
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    db_session.add(item)
    db_session.flush()

    published = []

    async def fake_js_publish(subject, payload):
        published.append((subject, payload))
        return True

    fake_redis = AsyncMock()
    with (
        patch(
            "app.workers.monitor_poll_worker.COLLECTORS",
            {
                "fake_down": lambda host, params: CheckResult(
                    up=False, samples=[Sample("avail", 0.0)], msg="dead"
                )
            },
        ),
        patch.object(mpw.nats_client, "js_publish", side_effect=fake_js_publish),
        patch.object(mpw, "get_redis", AsyncMock(return_value=fake_redis)),
    ):
        await process_batch(
            [
                {
                    "item_id": item.id,
                    "target_type": None,
                    "target_id": None,
                    "host": item.host,
                    "check_type": "fake_down",
                    "params": {},
                }
            ],
            factory,
        )
    db_session.close = orig_close  # restore

    db_session.expire_all()
    fresh = db_session.get(MonitorItem, item.id)
    assert fresh.last_status == "down"
    assert any(s.startswith("alert.monitor.down.") for s, _ in published)
    fake_redis.publish.assert_awaited()
