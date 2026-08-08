"""The one path from a normalized check outcome to monitor state (Slice 3 §6).

Every assertion here is about the *shared* service, driven with server-shaped
and agent-shaped records, so a future remote caller cannot acquire semantics of
its own. The engine-level "both callers agree" proof lives in
tests/integration/test_monitor_engine_e2e.py.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.core.nats_client import nats_client
from app.db.models import MonitorEvent, MonitorItem, MonitorProbeRun, TelemetryTimeseries
from app.services.monitoring import result_service
from app.services.monitoring.collectors import Sample
from app.services.monitoring.result_service import MonitorResult, process_results


def _noop_close_factory(session):
    """Return a factory that yields the test session but suppresses close()
    so the SAVEPOINT-isolated session stays usable for post-batch assertions."""
    original_close = session.close

    def factory():
        session.close = lambda: None
        return session

    return factory, original_close


def _monitor(factories, **kwargs):
    defaults = {
        "check_type": "icmp",
        "target_type": None,
        "target_id": None,
        "max_retries": 0,
        "interval_secs": 60,
        "last_status": "up",
        "next_due_at": datetime.now(UTC) + timedelta(seconds=60),
    }
    defaults.update(kwargs)
    return factories.monitor_item(**defaults)


def _record(item, **kwargs):
    defaults = {
        "item_id": item.id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "check_type": item.check_type,
        "samples": [Sample("avail", 0.0)],
        "up": False,
        "msg": "100% packet loss (5 probes)",
        "checked_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return MonitorResult(**defaults)


async def test_completed_result_writes_samples_state_events_in_one_commit(db_session, factories):
    item = _monitor(factories)
    factory, orig_close = _noop_close_factory(db_session)

    commits = []
    orig_commit = db_session.commit
    db_session.commit = lambda: (commits.append(1), orig_commit())[1]

    record = _record(item, samples=[Sample("avail", 0.0), Sample("packet_loss_pct", 100.0)])
    try:
        with (
            patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
            patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
        ):
            written = await process_results([record], factory)
    finally:
        db_session.commit = orig_commit
        db_session.close = orig_close

    assert written == 2
    assert len(commits) == 1  # samples + state + events + run completion, atomically

    db_session.expire_all()
    assert db_session.get(MonitorItem, item.id).last_status == "down"
    assert {
        r.metric
        for r in db_session.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id == item.id)
        .all()
    } == {"avail", "packet_loss_pct"}
    event = db_session.query(MonitorEvent).filter(MonitorEvent.item_id == item.id).one()
    assert (event.event_type, event.status_from, event.status_to) == ("down", "up", "down")


async def test_proxmox_override_is_applied_to_remote_results_too(db_session, factories):
    """D-7: skipping the override would invert UP/DOWN for agent-executed
    ICMP/TCP on Proxmox targets relative to the byte-identical server check."""
    hw = factories.hardware(
        proxmox_node_name="pve1",
        telemetry_last_polled=datetime.now(UTC),
        telemetry_status="healthy",
    )
    item = _monitor(
        factories, target_type="hardware", target_id=hw.id, last_status="down", host="10.0.0.9"
    )
    agent = factories.agent(status="active")
    run = factories.monitor_probe_run(item, agent, status="dispatched")
    db_session.flush()

    factory, orig_close = _noop_close_factory(db_session)
    record = _record(
        item,
        source=result_service.SOURCE_AGENT,
        agent_id=agent.id,
        run_id=run.run_id,
    )
    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        await process_results([record], factory)
    db_session.close = orig_close

    db_session.expire_all()
    assert db_session.get(MonitorItem, item.id).last_status == "up"
    sample = (
        db_session.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id == item.id, TelemetryTimeseries.metric == "avail")
        .one()
    )
    assert sample.value == 1.0


async def test_source_is_always_monitor(db_session, factories):
    """`_uptime_pct_map` and `rollup_worker` never filter on `source`, so a
    second avail-writing source string would silently double-count uptime."""
    item = _monitor(factories)
    agent = factories.agent(status="active")
    run = factories.monitor_probe_run(item, agent, status="dispatched")
    db_session.flush()

    factory, orig_close = _noop_close_factory(db_session)
    record = _record(
        item,
        samples=[Sample("avail", 1.0)],
        up=True,
        msg="1.2ms avg, 0.0% loss",
        source=result_service.SOURCE_AGENT,
        agent_id=agent.id,
        run_id=run.run_id,
    )
    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        await process_results([record], factory)
    db_session.close = orig_close

    db_session.expire_all()
    rows = (
        db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == item.id).all()
    )
    assert rows and {r.source for r in rows} == {"monitor"}


async def test_details_are_never_written_to_telemetry_timeseries(db_session, factories):
    """D-8: `details` and per-sample `error_reason` live only in
    `monitor_probe_runs.result_metadata`. The hypertable keeps neither."""
    item = _monitor(factories, check_type="dns")
    agent = factories.agent(status="active")
    run = factories.monitor_probe_run(item, agent, status="dispatched")
    db_session.flush()

    factory, orig_close = _noop_close_factory(db_session)
    record = _record(
        item,
        samples=[Sample("avail", 0.0, error_reason="dns_error")],
        details={"records": ["10.0.0.5", "10.0.0.6"]},
        source=result_service.SOURCE_AGENT,
        agent_id=agent.id,
        run_id=run.run_id,
        msg="A lookup failed: NXDOMAIN",
    )
    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        await process_results([record], factory)
    db_session.close = orig_close

    db_session.expire_all()
    rows = (
        db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == item.id).all()
    )
    assert [r.metric for r in rows] == ["avail"]
    assert not hasattr(rows[0], "details")

    stored = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.run_id == run.run_id).one()
    assert stored.status == "completed"
    assert stored.result_metadata["details"] == {"records": ["10.0.0.5", "10.0.0.6"]}
    assert stored.result_metadata["error_reasons"] == [
        {"metric": "avail", "error_reason": "dns_error"}
    ]


async def test_transitions_and_live_status_are_published_after_the_commit_not_inside_it(
    db_session, factories
):
    item = _monitor(factories)
    factory, orig_close = _noop_close_factory(db_session)

    seq: list[str] = []
    orig_commit = db_session.commit
    db_session.commit = lambda: (seq.append("commit"), orig_commit())[1]

    async def fake_js_publish(subject, payload):
        seq.append(f"alert:{subject}")
        return True

    fake_redis = AsyncMock()

    async def fake_redis_publish(channel, payload):
        seq.append("live")

    fake_redis.publish.side_effect = fake_redis_publish

    try:
        with (
            patch.object(nats_client, "js_publish", side_effect=fake_js_publish),
            patch.object(result_service, "get_redis", AsyncMock(return_value=fake_redis)),
        ):
            await process_results([_record(item)], factory)
    finally:
        db_session.commit = orig_commit
        db_session.close = orig_close

    assert seq[0] == "commit"
    assert seq.count("commit") == 1
    assert seq[1] == f"alert:alert.monitor.down.{item.id}"
    assert seq[2] == "live"


def _execution_record(item, **kwargs):
    """An execution error: the vantage failed, which says nothing about the target.

    It deliberately carries an `avail` sample so the assertions below prove the
    branch drops it rather than merely never receiving one (§6).
    """
    defaults = {
        "outcome": result_service.OUTCOME_EXECUTION_ERROR,
        "execution_reason": "capacity_exhausted",
        "samples": [Sample("avail", 0.0)],
        "up": False,
        "msg": "agent queue is full",
    }
    defaults.update(kwargs)
    return _record(item, **defaults)


async def test_execution_error_writes_no_avail_sample(db_session, factories):
    item = _monitor(factories)
    agent = factories.agent(status="active")
    run = factories.monitor_probe_run(item, agent, status="dispatched")
    db_session.flush()

    factory, orig_close = _noop_close_factory(db_session)
    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        written = await process_results([_execution_record(item, run_id=run.run_id)], factory)
    db_session.close = orig_close

    assert written == 0
    db_session.expire_all()
    assert (
        db_session.query(TelemetryTimeseries).filter(TelemetryTimeseries.item_id == item.id).count()
        == 0
    )
    stored = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.run_id == run.run_id).one()
    assert stored.status == "execution_error"
    assert stored.error_code == "capacity_exhausted"
    monitor = db_session.get(MonitorItem, item.id)
    assert monitor.probe_execution_status == "unavailable"
    assert monitor.probe_execution_reason == "capacity_exhausted"
    # The run answers "what happened", not "when did the target last reply".
    assert monitor.probe_last_result_at is None


async def test_execution_error_does_not_touch_consecutive_failures_or_last_status(
    db_session, factories
):
    """It must not reach `state.apply_result`, which unconditionally rewrites
    `last_polled_at` and `consecutive_failures`."""
    item = _monitor(factories, last_status="up", max_retries=2)
    item.consecutive_failures = 1
    db_session.flush()
    due_before = item.next_due_at

    factory, orig_close = _noop_close_factory(db_session)
    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        await process_results([_execution_record(item, execution_reason="agent_offline")], factory)
    db_session.close = orig_close

    db_session.expire_all()
    monitor = db_session.get(MonitorItem, item.id)
    assert monitor.last_status == "up"
    assert monitor.consecutive_failures == 1
    assert monitor.last_polled_at is None
    assert monitor.next_due_at == due_before
    assert monitor.probe_execution_reason == "agent_offline"


async def test_execution_error_publishes_a_live_refresh_without_a_status_key(db_session, factories):
    """D-13: any `status` key would be splatted into the card by
    `ws_monitors._redis_listener` and clobber the UP/DOWN pill."""
    item = _monitor(factories)
    factory, orig_close = _noop_close_factory(db_session)

    published: list[tuple[str, str]] = []
    fake_redis = AsyncMock()

    async def fake_publish(channel, payload):
        published.append((channel, payload))

    fake_redis.publish.side_effect = fake_publish

    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=fake_redis)),
    ):
        await process_results([_execution_record(item, execution_reason="out_of_scope")], factory)
    db_session.close = orig_close

    assert len(published) == 1
    channel, raw = published[0]
    assert channel == f"monitor:{item.id}"
    payload = json.loads(raw)
    assert "status" not in payload
    assert payload["monitor_id"] == item.id
    assert payload["probe_execution_status"] == "unavailable"
    assert payload["probe_execution_reason"] == "out_of_scope"
    assert payload["ts"]


async def test_repeated_identical_execution_reason_records_only_one_event(db_session, factories):
    """§6: an execution event only when the reason changes.

    The scheduler clears `probe_execution_reason` every time it queues the
    monitor, so the column alone cannot be the memory — otherwise a silent agent
    writes one event per interval, forever.
    """
    item = _monitor(factories)
    factory, orig_close = _noop_close_factory(db_session)

    with (
        patch.object(nats_client, "js_publish", AsyncMock(return_value=True)),
        patch.object(result_service, "get_redis", AsyncMock(return_value=None)),
    ):
        for _ in range(2):
            await process_results(
                [_execution_record(item, execution_reason="agent_offline")], factory
            )
        db_session.expire_all()
        # What `services/monitoring/scheduler.py::_MARK_QUEUED_SQL` does on the
        # next interval, before the same condition reasserts itself.
        refreshed = db_session.get(MonitorItem, item.id)
        refreshed.probe_execution_status = "queued"
        refreshed.probe_execution_reason = None
        db_session.flush()
        await process_results([_execution_record(item, execution_reason="agent_offline")], factory)
        await process_results([_execution_record(item, execution_reason="out_of_scope")], factory)
    db_session.close = orig_close

    db_session.expire_all()
    events = (
        db_session.query(MonitorEvent)
        .filter(MonitorEvent.item_id == item.id)
        .order_by(MonitorEvent.id)
        .all()
    )
    assert [e.event_type for e in events] == [
        result_service.EVENT_EXECUTION,
        result_service.EVENT_EXECUTION,
    ]
    assert events[0].msg == "agent_offline"
    assert events[1].msg == "out_of_scope"
    assert [e.status_to for e in events] == ["up", "up"]
