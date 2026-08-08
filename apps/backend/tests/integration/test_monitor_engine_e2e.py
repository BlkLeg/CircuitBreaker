# apps/backend/tests/integration/test_monitor_engine_e2e.py
import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.core.nats_client import nats_client
from app.db.models import MonitorEvent, MonitorItem, TelemetryTimeseries
from app.services.monitoring import result_service
from app.services.monitoring.collectors import CheckResult, Sample
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
            "icmp": lambda host, params: CheckResult(
                up=True,
                samples=[
                    Sample("avail", 1.0),
                    Sample("packet_loss_pct", 0.0),
                ],
            )
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
        {"icmp": lambda host, params: CheckResult(up=True, samples=[Sample("avail", 1.0)])},
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


def _parity_item(db, name):
    it = MonitorItem(
        name=name,
        target_type=None,
        target_id=None,
        host="10.0.0.20",
        check_type="icmp",
        params={},
        interval_secs=60,
        max_retries=0,
        enabled=True,
        last_status="up",
        next_due_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    db.add(it)
    db.flush()
    return it


def _normalize_alert(subject, payload, item_id):
    """Strip the two fields that legitimately differ between two monitors."""
    return (
        subject.replace(f".{item_id}", ".<id>"),
        {k: v for k, v in payload.items() if k not in ("monitor_id", "occurred_at")},
    )


async def test_server_and_agent_paths_produce_identical_status_events_and_alerts(
    db_session, factories
):
    """§6's acceptance bar: one normalized result, two callers, one semantics.

    The server caller is `monitor_poll_worker.process_batch`; the agent caller
    hands `result_service` the same normalized record with remote provenance.
    Status, events, history rows and the alert must be indistinguishable.
    """
    server_item = _parity_item(db_session, "parity")
    agent_item = _parity_item(db_session, "parity")
    agent = factories.agent(status="active")
    run = factories.monitor_probe_run(agent_item, agent, status="dispatched")
    db_session.flush()

    samples = [Sample("avail", 0.0), Sample("packet_loss_pct", 100.0)]
    msg = "100% packet loss (5 probes)"

    alerts: list[tuple[str, dict]] = []

    async def fake_js_publish(subject, payload):
        alerts.append((subject, payload))
        return True

    live: list[tuple[str, str]] = []
    fake_redis = AsyncMock()

    async def fake_redis_publish(channel, payload):
        live.append((channel, payload))

    fake_redis.publish.side_effect = fake_redis_publish

    factory, orig_close = _noop_close_factory(db_session)
    with (
        patch(
            "app.workers.monitor_poll_worker.COLLECTORS",
            {"icmp": lambda host, params: CheckResult(up=False, samples=list(samples), msg=msg)},
        ),
        patch.object(nats_client, "js_publish", side_effect=fake_js_publish),
        patch.object(result_service, "get_redis", AsyncMock(return_value=fake_redis)),
    ):
        await process_batch(
            [
                {
                    "item_id": server_item.id,
                    "target_type": None,
                    "target_id": None,
                    "host": server_item.host,
                    "check_type": "icmp",
                    "params": {},
                }
            ],
            factory,
        )
        await result_service.process_results(
            [
                result_service.MonitorResult(
                    item_id=agent_item.id,
                    target_type=None,
                    target_id=None,
                    check_type="icmp",
                    samples=list(samples),
                    up=False,
                    msg=msg,
                    checked_at=datetime.now(UTC),
                    source=result_service.SOURCE_AGENT,
                    agent_id=agent.id,
                    run_id=run.run_id,
                )
            ],
            factory,
        )
    db_session.close = orig_close
    db_session.expire_all()

    def _state(item_id):
        item = db_session.get(MonitorItem, item_id)
        events = [
            (e.event_type, e.status_from, e.status_to, e.msg)
            for e in db_session.query(MonitorEvent)
            .filter(MonitorEvent.item_id == item_id)
            .order_by(MonitorEvent.id)
            .all()
        ]
        series = sorted(
            (r.metric, r.value, r.source, r.entity_type, r.entity_id)
            for r in db_session.query(TelemetryTimeseries)
            .filter(TelemetryTimeseries.item_id == item_id)
            .all()
        )
        return (item.last_status, item.consecutive_failures, events, series)

    assert _state(server_item.id) == _state(agent_item.id)

    server_alert = next(a for a in alerts if a[0].endswith(f".{server_item.id}"))
    agent_alert = next(a for a in alerts if a[0].endswith(f".{agent_item.id}"))
    assert _normalize_alert(*server_alert, server_item.id) == _normalize_alert(
        *agent_alert, agent_item.id
    )

    assert {c for c, _ in live} == {
        f"monitor:{server_item.id}",
        f"monitor:{agent_item.id}",
    }
