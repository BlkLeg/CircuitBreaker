"""§4's `probe.cancel` triggers and §8's lifecycle table.

Five events retire an in-flight run: a monitor is paused, deleted or reassigned,
the agent's `remote_probe` grant is turned off, or the agent is revoked. All
five share one implementation in `monitor_service`, and all five are
authoritative in the database *first* — the frame that tells the agent to stop
is best effort (§4), so every test here checks the run row, not just the wire.

The run row is the part that has to be right: `uq_monitor_probe_runs_active` is
a partial unique index over `(monitor_id) WHERE status IN ('queued',
'dispatched')`, so a run left in flight blocks every future run for that monitor
until the reconciliation pass expires it.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time import utcnow
from app.db.models import MonitorItem, MonitorProbeRun
from app.schemas.agent_frame import TYPE_PROBE_CANCEL, TYPE_PROBE_RESULT, AgentFrame
from app.schemas.monitor import MonitorUpdate
from app.services import agent_probe, monitor_service


@pytest.fixture
def published(monkeypatch):
    """Capture every control frame the triggers hand the generic delivery path.

    Patched on the module rather than on a call site: `monitor_service` and
    `api/agents.py` both reach `publish_agent_control_frame` through the
    `agent_registry` module object, so one patch covers both and the
    `capabilities.set` frame `PUT /capabilities` sends anyway shows up here too
    — which is why every assertion filters on the frame type.
    """
    frames: list[tuple[int, dict]] = []

    async def _publish(agent_id: int, frame: dict) -> bool:
        frames.append((agent_id, frame))
        return True

    monkeypatch.setattr("app.services.agent_registry.publish_agent_control_frame", _publish)
    return frames


async def _drain() -> None:
    """Let a `loop.create_task`'d publish actually run.

    The synchronous triggers (`set_paused`, `delete_monitor`, `update_monitor`)
    cannot await, so they schedule the frame on the running loop — the same
    idiom `run_immediate_check` has always used. Nothing here depends on the
    publish having landed for correctness; the tests assert it because a silent
    regression to "never sends the frame" would only show up as agents wasting
    a full check on work the server already threw away.
    """
    await asyncio.sleep(0.05)


def _cancel_frames(published: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
    return [(agent_id, f) for agent_id, f in published if f["type"] == TYPE_PROBE_CANCEL]


def _assigned_monitor_with_run(db_session, factories, agent, **monitor_kwargs):
    """An agent-assigned monitor with one dispatched run against it."""
    now = utcnow()
    defaults = {
        "host": "10.0.0.9",
        "check_type": "icmp",
        "last_status": "up",
        "probe_agent_id": agent.id,
        "probe_execution_status": "running",
    }
    defaults.update(monitor_kwargs)
    monitor = factories.monitor_item(**defaults)
    run = factories.monitor_probe_run(
        monitor,
        agent,
        status="dispatched",
        scheduled_at=now,
        dispatched_at=now,
        deadline_at=now + timedelta(seconds=20),
    )
    db_session.flush()
    return monitor, run


def _result_payload(monitor_id: int, run_id: str) -> dict:
    now = utcnow()
    return {
        "run_id": run_id,
        "monitor_id": monitor_id,
        "outcome": "completed",
        "up": False,
        "started_at": (now - timedelta(seconds=1)).isoformat(),
        "finished_at": now.isoformat(),
        "samples": [{"metric": "avail", "value": 0}],
        "msg": "100% packet loss (5 probes)",
    }


async def test_pausing_a_monitor_cancels_its_active_run_and_publishes_probe_cancel(
    db_session, factories, published
):
    agent = factories.agent(status="active")
    monitor, run = _assigned_monitor_with_run(db_session, factories, agent)

    monitor_service.set_paused(db_session, monitor.id, True)
    await _drain()

    db_session.expire_all()
    assert run.status == "cancelled"
    assert run.error_code == monitor_service.CANCEL_MONITOR_PAUSED
    assert run.completed_at is not None
    assert _cancel_frames(published) == [
        (
            agent.id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {
                    "run_id": run.run_id,
                    "reason": monitor_service.CANCEL_MONITOR_PAUSED,
                },
            },
        )
    ]


async def test_deleting_a_monitor_cancels_its_active_run(db_session, factories, published):
    agent = factories.agent(status="active")
    monitor, run = _assigned_monitor_with_run(db_session, factories, agent)
    run_id = run.run_id

    assert monitor_service.delete_monitor(db_session, monitor.id) is True
    await _drain()

    # The run row goes with the monitor (FK CASCADE), so the frame has to be
    # captured before the delete or it can never be sent at all.
    assert (
        db_session.execute(
            select(MonitorProbeRun).where(MonitorProbeRun.run_id == run_id)
        ).scalar_one_or_none()
        is None
    )
    assert _cancel_frames(published) == [
        (
            agent.id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {
                    "run_id": run_id,
                    "reason": monitor_service.CANCEL_MONITOR_DELETED,
                },
            },
        )
    ]


async def test_reassigning_a_monitor_cancels_the_old_agents_run_and_rejects_its_late_result(
    db_session, factories, published
):
    """§9 case 9. The old vantage keeps executing until its own cancel lands —
    and whatever it eventually posts must not move a monitor that now belongs to
    somebody else."""
    old_agent = factories.agent(status="active")
    new_agent = factories.agent(status="active")
    monitor, run = _assigned_monitor_with_run(db_session, factories, old_agent)

    updated = monitor_service.update_monitor(
        db_session, monitor.id, MonitorUpdate(probe_agent_id=new_agent.id)
    )
    await _drain()

    assert updated is not None
    db_session.expire_all()
    assert monitor.probe_agent_id == new_agent.id
    # The old vantage's condition is not the new one's; nothing carries over.
    assert monitor.probe_execution_status is None
    assert monitor.probe_execution_reason is None
    assert run.status == "cancelled"
    assert run.error_code == monitor_service.CANCEL_MONITOR_REASSIGNED
    assert _cancel_frames(published) == [
        (
            old_agent.id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {
                    "run_id": run.run_id,
                    "reason": monitor_service.CANCEL_MONITOR_REASSIGNED,
                },
            },
        )
    ]

    # The old agent's in-flight check comes back anyway: the run is closed, so
    # it is inert — no sample, no transition, no uptime.
    disposition = await agent_probe.ingest_probe_result(
        db_session, old_agent, _result_payload(monitor.id, run.run_id)
    )
    assert disposition == agent_probe.DISPOSITION_DUPLICATE
    db_session.expire_all()
    assert monitor.last_status == "up"
    assert run.outcome is None


async def test_disabling_remote_probe_cancels_runs_and_marks_assignments_unavailable_without_deleting_them(  # noqa: E501
    client, auth_headers, db_session, factories, published
):
    """Driven through `PUT /capabilities`, not through the service helper.

    `agent_link.dispatch_frame`'s gate is `grants_dict` — the enabled flag alone
    — so the instant the grant is off, a result for a still-open run is dropped
    as a `capability_violation` and never reaches `agent_probe` at all. The run
    would then sit in `dispatched` until the reconciliation pass expired it,
    holding the partial unique index the whole time. Cancelling inside the
    endpoint is what closes that window, so the endpoint is what the test
    exercises.
    """
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    monitor, run = _assigned_monitor_with_run(db_session, factories, agent)
    db_session.commit()

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": False}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is False

    db_session.expire_all()
    assert run.status == "cancelled"
    assert run.error_code == monitor_service.CANCEL_CAPABILITY_DISABLED
    # The assignment survives: §8 says such monitors become unavailable, not
    # silently server-executed.
    assert monitor.probe_agent_id == agent.id
    assert monitor.probe_execution_status == "unavailable"
    assert monitor.probe_execution_reason == monitor_service.CANCEL_CAPABILITY_DISABLED
    assert _cancel_frames(published) == [
        (
            agent.id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {
                    "run_id": run.run_id,
                    "reason": monitor_service.CANCEL_CAPABILITY_DISABLED,
                },
            },
        )
    ]

    # And the window the cancellation closes: a result arriving now is refused
    # by the capability gate, so nothing downstream could have retired the run.
    from app.services import agent_link

    frame = AgentFrame(
        v=1,
        type=TYPE_PROBE_RESULT,
        seq=1,
        ts=utcnow(),
        payload=_result_payload(monitor.id, run.run_id),
    )
    await agent_link.dispatch_frame(db_session, agent, frame)
    db_session.expire_all()
    assert run.status == "cancelled"
    assert monitor.last_status == "up"


async def test_revoking_an_agent_cancels_runs_and_preserves_assignments(
    client, auth_headers, db_session, factories, published
):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    monitor, run = _assigned_monitor_with_run(db_session, factories, agent)
    db_session.commit()

    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        json={"reason": "decommissioned"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    db_session.expire_all()
    assert run.status == "cancelled"
    assert run.error_code == monitor_service.CANCEL_AGENT_REVOKED
    # Assignments are preserved, so re-approving the agent restores the vantage
    # rather than requiring every monitor to be reassigned by hand.
    assert monitor.probe_agent_id == agent.id
    assert monitor.probe_execution_status == "unavailable"
    assert monitor.probe_execution_reason == monitor_service.CANCEL_AGENT_REVOKED
    assert _cancel_frames(published) == [
        (
            agent.id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {
                    "run_id": run.run_id,
                    "reason": monitor_service.CANCEL_AGENT_REVOKED,
                },
            },
        )
    ]


async def test_cancellation_is_best_effort_and_a_failed_publish_still_expires_the_run(
    db_session, factories, monkeypatch
):
    """§4: "Cancellation is best-effort; the backend remains authoritative."

    Redis being down means the agent never hears about it — and must not mean
    the monitor is wedged behind a run nobody will ever close.
    """
    from app.services import agent_registry

    async def _fail(agent_id: int, frame: dict) -> bool:
        return False

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", _fail)

    agent = factories.agent(status="active")
    monitor, run = _assigned_monitor_with_run(db_session, factories, agent)

    monitor_service.set_paused(db_session, monitor.id, True)
    await _drain()

    db_session.expire_all()
    assert run.status == "cancelled"
    assert run.completed_at is not None
    # Nothing holds `uq_monitor_probe_runs_active` any more, so the monitor can
    # be dispatched again the moment it is resumed.
    assert (
        db_session.execute(
            select(MonitorProbeRun.id).where(
                MonitorProbeRun.monitor_id == monitor.id,
                MonitorProbeRun.status.in_(("queued", "dispatched")),
            )
        ).first()
        is None
    )
    # A result for the closed run cannot revive it either.
    disposition = await agent_probe.ingest_probe_result(
        db_session, agent, _result_payload(monitor.id, run.run_id)
    )
    assert disposition == agent_probe.DISPOSITION_DUPLICATE
    db_session.expire_all()
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"


async def test_cancellation_leaves_server_executed_monitors_alone(db_session, factories, published):
    """A monitor with no vantage has no run to cancel and no frame to send."""
    monitor = factories.monitor_item(host="10.0.0.4", last_status="up")
    db_session.flush()

    monitor_service.set_paused(db_session, monitor.id, True)
    await _drain()

    assert _cancel_frames(published) == []
