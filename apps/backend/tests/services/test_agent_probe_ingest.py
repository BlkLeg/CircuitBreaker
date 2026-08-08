"""Slice 3 §4: what the backend will and will not accept as a `probe.result`.

This is the only path on which a remote agent can move monitor state, so every
rule here is a security invariant rather than a preference: the size cap runs
before anything parses, the run/monitor/agent triple is matched before anything
is written, a result that missed its deadline updates audit rows only, and a
duplicate is inert.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.time import utcnow
from app.db.models import (
    AgentEvent,
    MonitorEvent,
    MonitorItem,
    MonitorProbeRun,
    TelemetryTimeseries,
)
from app.schemas.agent_frame import TYPE_PROBE_RESULT, AgentFrame
from app.services import agent_link, agent_probe


def _agent(factories, **kwargs):
    agent = factories.agent(status="active", **kwargs)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    return agent


def _monitor(factories, agent, **kwargs):
    defaults = {
        "check_type": "icmp",
        "host": "10.0.0.9",
        "probe_agent_id": agent.id,
        "interval_secs": 60,
        "max_retries": 0,
        "last_status": "up",
        "next_due_at": utcnow() + timedelta(seconds=60),
    }
    defaults.update(kwargs)
    return factories.monitor_item(**defaults)


def _run(db_session, factories, monitor, agent, *, deadline_in: float = 20.0, **kwargs):
    now = utcnow()
    defaults = {
        "status": "dispatched",
        "scheduled_at": now,
        "dispatched_at": now,
        "deadline_at": now + timedelta(seconds=deadline_in),
    }
    defaults.update(kwargs)
    run = factories.monitor_probe_run(monitor, agent, **defaults)
    db_session.flush()
    return run


def _payload(run, monitor, **kwargs):
    now = utcnow()
    payload = {
        "run_id": run.run_id,
        "monitor_id": monitor.id,
        "outcome": "completed",
        "up": False,
        "started_at": (now - timedelta(seconds=1)).isoformat(),
        "finished_at": now.isoformat(),
        "samples": [
            {"metric": "avail", "value": 0},
            {"metric": "packet_loss_pct", "value": 100},
        ],
        "msg": "100% packet loss (5 probes)",
    }
    payload.update(kwargs)
    return payload


def _samples(db_session, monitor):
    return db_session.query(TelemetryTimeseries).filter_by(item_id=monitor.id).all()


async def test_probe_result_oversized_details_is_rejected_without_touching_monitor_state(
    db_session, factories
):
    """64 KiB, enforced *first*. Nothing upstream bounds an inbound frame:
    ws_agents reads the socket without a size limit and `receive_frame` only
    parses JSON, so this handler is the cap. The payload below is also
    unauthenticated garbage (a run_id belonging to nobody) — the size refusal
    still has to be the one that fires, which is what proves the ordering."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent)

    payload = _payload(
        run, monitor, run_id="f" * 32, details={"blob": "x" * agent_probe.MAX_DETAILS_BYTES}
    )

    with pytest.raises(agent_probe.InvalidProbeResult) as excinfo:
        await agent_probe.ingest_probe_result(db_session, agent, payload)

    assert "details" in str(excinfo.value)

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "dispatched"
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"
    assert _samples(db_session, monitor) == []


async def test_message_is_truncated_to_two_thousand_characters(db_session, factories):
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent)

    validated = agent_probe.validate_probe_payload(_payload(run, monitor, msg="z" * 5000))
    assert len(validated.msg) == agent_probe.MAX_MSG_CHARS

    await agent_probe.ingest_probe_result(db_session, agent, _payload(run, monitor, msg="z" * 5000))

    db_session.expire_all()
    assert len(db_session.get(MonitorProbeRun, run.id).msg) == agent_probe.MAX_MSG_CHARS


async def test_probe_result_with_foreign_run_id_records_capability_violation(db_session, factories):
    """A run_id that matches no run this agent owns is an authorization
    failure, not a schema one — it is the shape a stolen or guessed token
    takes — so it lands in the same `capability_violation` audit trail
    `dispatch_frame` uses for an ungranted frame type."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    _run(db_session, factories, monitor, agent)

    frame = AgentFrame(
        type=TYPE_PROBE_RESULT,
        ts=utcnow(),
        payload=_payload(_Fake(run_id="a" * 32), monitor),
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .one()
    )
    assert violation.detail["reason"].startswith("unknown run")

    db_session.expire_all()
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"
    assert _samples(db_session, monitor) == []


class _Fake:
    """Stand-in for a run row, so a payload can name a run that does not exist."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


async def test_probe_result_for_another_agents_run_is_rejected(db_session, factories):
    owner = _agent(factories)
    intruder = _agent(factories)
    monitor = _monitor(factories, owner)
    run = _run(db_session, factories, monitor, owner)

    with pytest.raises(agent_probe.InvalidProbeResult) as excinfo:
        await agent_probe.ingest_probe_result(db_session, intruder, _payload(run, monitor))

    assert excinfo.value.event_type == "capability_violation"

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "dispatched"
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"
    assert _samples(db_session, monitor) == []


async def test_late_result_updates_run_audit_but_not_monitor_state(db_session, factories):
    """`deadline_at + 30s`. The run records what arrived; the monitor does not,
    because a result the scheduler has already given up on would otherwise
    rewrite history and uptime out of order."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent, deadline_in=-31)

    disposition = await agent_probe.ingest_probe_result(db_session, agent, _payload(run, monitor))

    assert disposition == agent_probe.DISPOSITION_LATE

    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    assert stored.status == "expired"
    assert stored.outcome == "completed"
    assert stored.error_code == agent_probe.ERROR_LATE_RESULT
    assert stored.completed_at is not None

    item = db_session.get(MonitorItem, monitor.id)
    assert item.last_status == "up"
    assert item.probe_last_result_at is None
    assert _samples(db_session, monitor) == []
    assert db_session.query(MonitorEvent).filter_by(item_id=monitor.id).count() == 0


async def test_deadline_is_evaluated_against_server_receipt_time_not_frame_ts(
    db_session, factories
):
    """A spooled result keeps its original producer `TS` — the Go agent only
    stamps `TS` when it is zero — so `frame.ts` is agent-clock provenance and
    never arrival time. Judging the deadline by it would let a result that sat
    in the spool for an hour walk straight past the lease it missed."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent, deadline_in=-3600)

    produced_at = run.deadline_at - timedelta(seconds=5)
    frame = AgentFrame(
        type=TYPE_PROBE_RESULT,
        ts=produced_at,
        payload=_payload(
            run,
            monitor,
            started_at=(produced_at - timedelta(seconds=1)).isoformat(),
            finished_at=produced_at.isoformat(),
        ),
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "expired"
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"
    assert _samples(db_session, monitor) == []


async def test_duplicate_probe_result_is_idempotent(db_session, factories):
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent)
    payload = _payload(run, monitor)

    first = await agent_probe.ingest_probe_result(db_session, agent, payload)
    assert first == agent_probe.DISPOSITION_ACCEPTED

    db_session.expire_all()
    completed_at = db_session.get(MonitorProbeRun, run.id).completed_at
    failures = db_session.get(MonitorItem, monitor.id).consecutive_failures
    sample_count = len(_samples(db_session, monitor))
    assert sample_count == 2

    second = await agent_probe.ingest_probe_result(db_session, agent, payload)
    assert second == agent_probe.DISPOSITION_DUPLICATE

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).completed_at == completed_at
    assert db_session.get(MonitorItem, monitor.id).consecutive_failures == failures
    assert len(_samples(db_session, monitor)) == sample_count
    assert db_session.query(MonitorEvent).filter_by(item_id=monitor.id).count() == 1


async def test_completed_result_feeds_the_shared_result_service(db_session, factories, monkeypatch):
    """One result path (Global Constraints): the ingest handler normalizes and
    hands off, it does not write samples or drive the state machine itself."""
    from app.services.monitoring import result_service

    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent)

    seen: list[list[result_service.MonitorResult]] = []
    original = result_service.persist_results

    def spy(db, results):
        seen.append(list(results))
        return original(db, results)

    monkeypatch.setattr(agent_probe.result_service, "persist_results", spy)

    await agent_probe.ingest_probe_result(
        db_session, agent, _payload(run, monitor, details={"probes": 5})
    )

    assert len(seen) == 1
    (record,) = seen[0]
    assert record.item_id == monitor.id
    assert record.source == result_service.SOURCE_AGENT
    assert record.agent_id == agent.id
    assert record.run_id == run.run_id
    assert record.check_type == "icmp"
    assert [(s.metric, s.value) for s in record.samples] == [
        ("avail", 0.0),
        ("packet_loss_pct", 100.0),
    ]

    db_session.expire_all()
    assert db_session.get(MonitorItem, monitor.id).last_status == "down"
    assert {s.metric for s in _samples(db_session, monitor)} == {"avail", "packet_loss_pct"}
    stored = db_session.get(MonitorProbeRun, run.id)
    assert (stored.status, stored.outcome) == ("completed", "completed")
    assert stored.result_metadata == {"details": {"probes": 5}}


async def test_execution_error_result_does_not_write_avail_or_touch_retries(db_session, factories):
    """§6: an agent that could not run the check says nothing about the target.
    The `avail` sample below is deliberately present in the payload — a result
    that is not `completed` must not reach the state machine no matter what it
    claims to have measured."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent, last_status="up")
    run = _run(db_session, factories, monitor, agent)

    disposition = await agent_probe.ingest_probe_result(
        db_session,
        agent,
        _payload(run, monitor, outcome="execution_error", msg="no icmp socket"),
    )

    assert disposition == agent_probe.DISPOSITION_AUDIT_ONLY

    db_session.expire_all()
    item = db_session.get(MonitorItem, monitor.id)
    assert item.last_status == "up"
    assert item.consecutive_failures == 0
    assert item.probe_last_result_at is None
    assert item.probe_execution_status == "unavailable"
    assert item.probe_execution_reason == agent_probe.REASON_AGENT_EXECUTION_ERROR
    assert _samples(db_session, monitor) == []
    assert db_session.query(MonitorEvent).filter_by(item_id=monitor.id).count() == 0

    stored = db_session.get(MonitorProbeRun, run.id)
    assert (stored.status, stored.outcome) == ("execution_error", "execution_error")
    assert stored.msg == "no icmp socket"


async def test_result_metadata_never_contains_config_secrets(db_session, factories):
    """D-10 ships HTTP credentials to the agent in memory only; §4 forbids them
    coming back. The agent is expected not to echo them, and the backend is not
    expected to take its word for it — the monitor's own secret values are
    redacted out of `details` and `msg` before either is persisted."""
    agent = _agent(factories)
    monitor = _monitor(
        factories,
        agent,
        check_type="http",
        host="app.internal",
        params={
            "url": "https://app.internal/health",
            "password": "hunter2-correct-horse",
            "token": "t0ps3cret-bearer-value",
            "headers": {"Authorization": "Bearer t0ps3cret-bearer-value"},
        },
    )
    run = _run(db_session, factories, monitor, agent)

    await agent_probe.ingest_probe_result(
        db_session,
        agent,
        _payload(
            run,
            monitor,
            up=True,
            samples=[{"metric": "avail", "value": 1}, {"metric": "http_status", "value": 200}],
            msg="200 for hunter2-correct-horse in 12ms",
            details={
                "password": "hunter2-correct-horse",
                "request": {"Authorization": "Bearer t0ps3cret-bearer-value"},
                "note": "logged in as hunter2-correct-horse",
                "http_status": 200,
            },
        ),
    )

    db_session.expire_all()
    stored = db_session.get(MonitorProbeRun, run.id)
    blob = json.dumps(stored.result_metadata or {})
    assert "hunter2-correct-horse" not in blob
    assert "t0ps3cret-bearer-value" not in blob
    assert "password" not in blob.lower()
    assert "authorization" not in blob.lower()
    # The non-secret part of the audit record survives the redaction.
    assert stored.result_metadata["details"]["http_status"] == 200
    assert "hunter2-correct-horse" not in (stored.msg or "")


async def test_utc_naive_timestamps_are_accepted_as_utc(db_session, factories):
    """`AgentFrame`/`ProbeResultPayload` accept a naive ISO timestamp; comparing
    one against a tz-aware deadline would raise TypeError inside the /link read
    loop and take the connection down."""
    agent = _agent(factories)
    monitor = _monitor(factories, agent)
    run = _run(db_session, factories, monitor, agent)

    naive = datetime.now(UTC).replace(tzinfo=None)
    disposition = await agent_probe.ingest_probe_result(
        db_session,
        agent,
        _payload(run, monitor, started_at=naive.isoformat(), finished_at=naive.isoformat()),
    )

    assert disposition == agent_probe.DISPOSITION_ACCEPTED
