import json

import pytest

from app.schemas.agent_frame import AgentFrame
from app.services import agent_link


@pytest.mark.asyncio
async def test_dispatch_uninstall_revokes_agent_and_preserves_row(db_session, factories):
    """Task 29 (`cb-agent uninstall`'s server-side counterpart): the
    best-effort `uninstall` frame `link.Uninstall` sends must flip the
    agent's server row to `status=revoked` for audit — not delete it, and
    not merely mark it inactive some other way. _handle_uninstall already
    calls agent_registry.revoke_agent for this; this test verifies that call
    actually lands and is durable (dispatch_frame commits), not just that
    the handler is wired up."""
    from app.db.models import Agent

    agent = factories.agent(status="active")
    agent_id = agent.id

    frame = AgentFrame(type="uninstall", ts="2026-07-27T12:00:00Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent_id)
    assert refreshed is not None, (
        "agent row must still be present after uninstall — revoked, not deleted"
    )
    assert refreshed.status == "revoked"
    assert refreshed.revoked_at is not None
    assert refreshed.revoke_reason == "uninstalled by agent"
    # actor_user_id=None (agent-initiated, not an operator action) must be
    # preserved as None, not coerced into some sentinel — the audit trail
    # should be able to tell "the agent uninstalled itself" apart from "an
    # operator revoked it" by this field alone.
    assert refreshed.revoked_by_user_id is None


@pytest.mark.asyncio
async def test_dispatch_heartbeat_refreshes_presence(db_session, factories, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", refresh)

    frame = AgentFrame(type="heartbeat", ts="2026-07-27T12:00:00Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    refresh.assert_called_once()


# test_dispatch_heartbeat_refreshes_connection_registry used to live here,
# asserting _handle_heartbeat called agent_registry.refresh_agent_connection.
# It no longer does: that refresh moved to ws_agents.py's link_stream itself
# (its TYPE_HEARTBEAT branch), because the registry entry must be scoped to
# *this connection*, not agent_link's process-wide default WORKER_ID — see
# link_stream's `connection_id` docstring for why (a second /link connection
# sharing one worker process, e.g. cb-agent uninstall's one-shot notifier
# alongside an agent's still-live daemon connection, would otherwise be
# indistinguishable from it and could evict it on disconnect).
# test_ws_agents_link.py::
# test_link_stale_second_connections_teardown_does_not_evict_a_refreshed_first_connection
# covers the refresh (and the bug it fixes) end-to-end over the real
# WebSocket, where connection_id is actually in scope.


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_type", ["log", "telemetry.host", "uninstall"])
async def test_dispatch_non_heartbeat_frame_does_not_refresh_presence(
    db_session, factories, monkeypatch, frame_type
):
    """Presence freshness must track `heartbeat` frames specifically, not
    "any traffic on the socket" — a log line, a telemetry report, or any
    other non-heartbeat frame type must never refresh presence, or a chatty
    agent whose heartbeat ticker has actually stalled could look perpetually
    online."""
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", refresh)

    frame = AgentFrame(
        type=frame_type,
        ts="2026-07-27T12:00:00Z",
        payload={"cpu": 0.1} if frame_type == "telemetry.host" else {},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    refresh.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_ungranted_frame_records_violation_and_does_not_dispatch(
    db_session,
    factories,
):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=False)

    frame = AgentFrame(type="telemetry.host", ts="2026-07-27T12:00:00Z", payload={"cpu": 0.5})
    await agent_link.dispatch_frame(db_session, agent, frame)

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .one()
    )
    assert violation.detail == {"frame_type": "telemetry.host"}


@pytest.mark.asyncio
async def test_dispatch_granted_telemetry_frame_does_not_record_violation(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    frame = AgentFrame(type="telemetry.host", ts="2026-07-27T12:00:00Z", payload={"cpu": 0.5})
    await agent_link.dispatch_frame(db_session, agent, frame)

    count = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .count()
    )
    assert count == 0


def _raw(*, v=1, type="heartbeat", seq=0, ts="2026-07-27T12:00:00Z", payload=None):
    return json.dumps(
        {"v": v, "type": type, "seq": seq, "ts": ts, "payload": payload or {}}
    ).encode()


def test_receive_frame_accepts_strictly_increasing_sequences(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    session = agent_link.LinkSessionState()

    for seq in (0, 1, 2, 10):
        frame = agent_link.receive_frame(db_session, agent, _raw(seq=seq), session)
        assert frame is not None
        assert frame.seq == seq

    count = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .count()
    )
    assert count == 0


def test_receive_frame_rejects_duplicate_sequence(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    session = agent_link.LinkSessionState()

    assert agent_link.receive_frame(db_session, agent, _raw(seq=3), session) is not None
    assert agent_link.receive_frame(db_session, agent, _raw(seq=3), session) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "duplicate_sequence"
    assert violation.detail["seq"] == 3
    assert violation.detail["last_seq"] == 3


def test_receive_frame_rejects_decreasing_sequence(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    session = agent_link.LinkSessionState()

    assert agent_link.receive_frame(db_session, agent, _raw(seq=5), session) is not None
    assert agent_link.receive_frame(db_session, agent, _raw(seq=2), session) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "decreasing_sequence"
    assert violation.detail["seq"] == 2
    assert violation.detail["last_seq"] == 5

    # The rejected frame must not move the session's baseline: the next
    # strictly-increasing sequence relative to the original 5 still passes.
    assert agent_link.receive_frame(db_session, agent, _raw(seq=6), session) is not None


def test_receive_frame_rejects_unsupported_version(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    assert agent_link.receive_frame(db_session, agent, _raw(v=2, seq=0)) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "unsupported_version"
    assert violation.detail["v"] == 2


def test_receive_frame_rejects_malformed_frame_bodies(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    assert agent_link.receive_frame(db_session, agent, b"not json at all") is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "malformed_frame"


def test_receive_frame_rejects_frame_missing_required_fields(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    # Valid JSON, but missing the required "ts" field.
    raw = json.dumps({"v": 1, "type": "heartbeat", "seq": 0}).encode()
    assert agent_link.receive_frame(db_session, agent, raw) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "malformed_frame"


def test_receive_frame_rejects_empty_type(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    assert agent_link.receive_frame(db_session, agent, _raw(type="", seq=0)) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "malformed_frame"
    assert violation.detail["seq"] == 0


def test_receive_frame_rejects_negative_sequence(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    assert agent_link.receive_frame(db_session, agent, _raw(seq=-1)) is None

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .one()
    )
    assert violation.detail["reason"] == "malformed_frame"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "expected_event"),
    [
        ("started", "update_started"),
        ("succeeded", "update_succeeded"),
        ("failed", "update_failed"),
        ("rolled_back", "update_rolled_back"),
    ],
)
async def test_dispatch_update_status_records_distinct_events(
    db_session, factories, phase, expected_event
):
    """Task 24: each `update.status` phase records its own distinct
    `agent_events` type — not a single generic event, and not the
    request-time `update_queued`/reconnect-time `version_changed` events,
    which are recorded elsewhere (api/agents.py, agent_registry.
    update_hello_metadata respectively)."""
    from app.db.models import AgentEvent

    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": phase},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    events = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert events == [expected_event]


@pytest.mark.asyncio
async def test_dispatch_update_status_failed_records_error_detail(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": "failed", "error": "update: sha256 mismatch"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    event = db_session.query(AgentEvent).filter_by(agent_id=agent.id).one()
    assert event.detail == {"version": "0.2.0", "error": "update: sha256 mismatch"}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["failed", "rolled_back"])
async def test_dispatch_update_status_terminal_phase_clears_pending_version(
    db_session, factories, phase
):
    """A failed download/verify/swap, or a confirmed rollback, means this
    attempt will never reconnect at the target version — pending_update_version
    must clear so a stale target doesn't linger (and so a later, unrelated
    update can be queued without the clash) and so version_changed never
    fires for an attempt that's already known to have not landed."""
    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": phase},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_update_version is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["started", "succeeded"])
async def test_dispatch_update_status_non_terminal_phase_leaves_pending_version(
    db_session, factories, phase
):
    """started/succeeded don't resolve the attempt yet — succeeded still
    awaits the reconnect that actually confirms the new version is running
    (version_changed), so pending_update_version must survive both."""
    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": phase},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_update_version == "0.2.0"


@pytest.mark.asyncio
async def test_dispatch_update_status_mismatched_version_leaves_pending_version(
    db_session, factories
):
    """A failed/rolled_back report for some *other* version than the one
    currently pending must not clear the real pending target — e.g. a stale
    report from an update attempt that's already been superseded."""
    agent = factories.agent(status="active", pending_update_version="0.3.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": "failed"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_update_version == "0.3.0"


@pytest.mark.asyncio
async def test_dispatch_update_status_malformed_payload_does_not_raise(db_session, factories):
    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="update.status", ts="2026-08-04T12:00:00Z", payload={"phase": "started"}
    )
    await agent_link.dispatch_frame(db_session, agent, frame)  # must not raise

    from app.db.models import AgentEvent

    assert db_session.query(AgentEvent).filter_by(agent_id=agent.id).count() == 0


@pytest.mark.asyncio
async def test_dispatch_update_status_unknown_phase_is_ignored(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": "somersaulting"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert db_session.query(AgentEvent).filter_by(agent_id=agent.id).count() == 0
    assert agent.pending_update_version == "0.2.0"


@pytest.mark.asyncio
async def test_dispatch_update_status_requires_no_capability_grant(db_session, factories):
    """update.status is transport-level like log/heartbeat — dispatched
    regardless of capability grants, and must never record a
    capability_violation."""
    from app.db.models import AgentEvent

    agent = factories.agent(status="active", pending_update_version="0.2.0")

    frame = AgentFrame(
        type="update.status",
        ts="2026-08-04T12:00:00Z",
        payload={"version": "0.2.0", "phase": "started"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .count()
    )
    assert violations == 0


@pytest.mark.asyncio
async def test_receive_frame_then_dispatch_frame_pipeline(db_session, factories, monkeypatch):
    """The intended two-stage pipeline: receive_frame validates and decodes,
    dispatch_frame only ever sees frames that already passed validation."""
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", refresh)

    frame = agent_link.receive_frame(db_session, agent, _raw(seq=0))
    assert frame is not None

    await agent_link.dispatch_frame(db_session, agent, frame)
    refresh.assert_called_once()


# ── key.rotate, kind="device" (Task 27) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_key_rotate_device_kind_starts_rotation(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")
    successor = "bb" * 32

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={
            "kind": "device",
            "successor_pk": successor,
            # Deliberately a much longer window than the server's own
            # default — start_device_key_rotation must ignore this, the
            # transition window is server-controlled, not client-negotiable.
            "expiry": "2026-09-01T12:00:00Z",
        },
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_device_pk == successor
    assert agent.pending_device_pk_expiry is not None
    from datetime import UTC, datetime

    delta = (agent.pending_device_pk_expiry - datetime.now(UTC)).total_seconds()
    from app.services import agent_registry

    assert delta < agent_registry.DEVICE_KEY_ROTATION_WINDOW_SECONDS + 5

    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_started")
        .one()
    )
    assert "expires_at" in event.detail


@pytest.mark.asyncio
async def test_dispatch_key_rotate_ignores_server_kind_from_an_agent(db_session, factories):
    """kind="server" is Task 28's direction (server -> agent); an inbound
    frame claiming it is not a request this handler understands and must be
    dropped, not misinterpreted as a device-key rotation request."""
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={"kind": "server", "successor_pk": "cc" * 32, "expiry": "2026-09-01T12:00:00Z"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_device_pk is None
    assert db_session.query(AgentEvent).filter_by(agent_id=agent.id).count() == 0


@pytest.mark.asyncio
async def test_dispatch_key_rotate_malformed_payload_does_not_raise(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    frame = AgentFrame(type="key.rotate", ts="2026-08-04T12:00:00Z", payload={"kind": "device"})
    await agent_link.dispatch_frame(db_session, agent, frame)  # must not raise

    assert agent.pending_device_pk is None
    assert db_session.query(AgentEvent).filter_by(agent_id=agent.id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_successor_pk",
    [
        "zz" * 32,  # not hex
        "ab" * 31,  # too short
        "ab" * 5000,  # unbounded-length input (review finding I1)
    ],
)
async def test_dispatch_key_rotate_malformed_successor_pk_does_not_raise(
    db_session, factories, bad_successor_pk
):
    """C1 regression: `KeyRotatePayload.successor_pk` must reject a non-hex
    or wrong-length value at frame-decode time (pydantic ValidationError,
    caught in `_handle_key_rotate`) rather than reaching
    `start_device_key_rotation`'s `bytes.fromhex(...)`, which would raise an
    unhandled ValueError that — over the real /link socket — tears down the
    agent's connection (see tests/api/test_ws_agents_link.py's live-socket
    proof of the same finding)."""
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={
            "kind": "device",
            "successor_pk": bad_successor_pk,
            "expiry": "2026-09-01T12:00:00Z",
        },
    )
    await agent_link.dispatch_frame(db_session, agent, frame)  # must not raise

    assert agent.pending_device_pk is None
    assert db_session.query(AgentEvent).filter_by(agent_id=agent.id).count() == 0


@pytest.mark.asyncio
async def test_dispatch_key_rotate_rejects_successor_matching_current_key(db_session, factories):
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={
            "kind": "device",
            "successor_pk": agent.device_pk,
            "expiry": "2026-09-01T12:00:00Z",
        },
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    assert agent.pending_device_pk is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_rejected")
        .one()
    )
    assert event.detail == {"reason": "successor_matches_current"}


@pytest.mark.asyncio
async def test_dispatch_key_rotate_requires_no_capability_grant(db_session, factories):
    """key.rotate is a transport/security control frame like heartbeat/
    update.status — dispatched regardless of capability grants, and must
    never record a capability_violation."""
    from app.db.models import AgentEvent

    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={
            "kind": "device",
            "successor_pk": "dd" * 32,
            "expiry": "2026-09-01T12:00:00Z",
        },
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .count()
    )
    assert violations == 0


@pytest.mark.asyncio
async def test_dispatch_key_rotate_publishes_ack_control_frame(db_session, factories, monkeypatch):
    """Once the pending key is durably committed, the server acknowledges it
    back to the agent over the same key.rotate frame type/kind — the ack the
    agent's own atomic device.key swap is gated on."""
    from unittest.mock import AsyncMock

    publish = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.agent_registry.publish_agent_control_frame", publish)

    agent = factories.agent(status="active")
    successor = "ee" * 32

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={"kind": "device", "successor_pk": successor, "expiry": "2026-09-01T12:00:00Z"},
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    publish.assert_called_once()
    call_agent_id, call_frame = publish.call_args[0]
    assert call_agent_id == agent.id
    assert call_frame["type"] == "key.rotate"
    assert call_frame["payload"]["kind"] == "device"
    assert call_frame["payload"]["successor_pk"] == successor
    assert "expiry" in call_frame["payload"]


@pytest.mark.asyncio
async def test_dispatch_key_rotate_does_not_publish_ack_when_rejected(
    db_session, factories, monkeypatch
):
    from unittest.mock import AsyncMock

    publish = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.agent_registry.publish_agent_control_frame", publish)

    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="key.rotate",
        ts="2026-08-04T12:00:00Z",
        payload={
            "kind": "device",
            "successor_pk": agent.device_pk,
            "expiry": "2026-09-01T12:00:00Z",
        },
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    publish.assert_not_called()


# ── probe.result dispatch (Slice 3 §4) ────────────────────────────────────────


def _probe_result_frame(db_session, factories, agent, monitor=None):
    """A monitor with a dispatched run, plus the frame that answers it."""
    from datetime import timedelta

    from app.core.time import utcnow

    if monitor is None:
        monitor = factories.monitor_item(
            check_type="icmp",
            host="10.0.0.9",
            probe_agent_id=agent.id,
            last_status="up",
            max_retries=0,
        )
    now = utcnow()
    run = factories.monitor_probe_run(
        monitor,
        agent,
        status="dispatched",
        scheduled_at=now,
        dispatched_at=now,
        deadline_at=now + timedelta(seconds=20),
    )
    db_session.flush()
    frame = AgentFrame(
        type="probe.result",
        ts=now,
        payload={
            "run_id": run.run_id,
            "monitor_id": monitor.id,
            "outcome": "completed",
            "up": False,
            "started_at": (now - timedelta(seconds=1)).isoformat(),
            "finished_at": now.isoformat(),
            "samples": [{"metric": "avail", "value": 0}],
            "msg": "100% packet loss (5 probes)",
        },
    )
    return monitor, run, frame


@pytest.mark.asyncio
async def test_probe_result_without_the_grant_records_a_capability_violation(db_session, factories):
    """Already true via `CAPABILITY_FOR_TYPE[TYPE_PROBE_RESULT]`; pinned here
    because it is the outermost of §4's authorization checks — an agent whose
    `remote_probe` grant is off must never reach the ingest handler at all, so
    nothing it claims can touch monitor state."""
    from app.db.models import AgentEvent, MonitorItem, MonitorProbeRun

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    monitor, run, frame = _probe_result_frame(db_session, factories, agent)

    await agent_link.dispatch_frame(db_session, agent, frame)

    violation = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="capability_violation")
        .one()
    )
    assert violation.detail == {"frame_type": "probe.result"}

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "dispatched"
    assert db_session.get(MonitorItem, monitor.id).last_status == "up"


@pytest.mark.asyncio
async def test_probe_result_dispatch_commits_exactly_once(db_session, factories):
    """Samples, state, the transition event and the run's completion have to
    become durable together (§6): a reader must never be able to observe a
    monitor that went DOWN while the run that says why is still open.

    Only commits that actually carry pending work are counted. `dispatch_frame`
    always ends with its own `db.commit()`, which by then has nothing left to
    flush — one *transaction*, not one call, is what the invariant is about.
    """
    from app.db.models import MonitorEvent, MonitorItem, MonitorProbeRun, TelemetryTimeseries

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    monitor, run, frame = _probe_result_frame(db_session, factories, agent)

    effective = []
    original_commit = db_session.commit

    def counting_commit():
        pending = bool(db_session.new or db_session.dirty or db_session.deleted)
        original_commit()
        if pending:
            effective.append(1)

    db_session.commit = counting_commit
    try:
        await agent_link.dispatch_frame(db_session, agent, frame)
    finally:
        db_session.commit = original_commit

    assert effective == [1]

    db_session.expire_all()
    assert db_session.get(MonitorProbeRun, run.id).status == "completed"
    assert db_session.get(MonitorItem, monitor.id).last_status == "down"
    assert db_session.query(MonitorEvent).filter_by(item_id=monitor.id).count() == 1
    assert db_session.query(TelemetryTimeseries).filter_by(item_id=monitor.id).count() == 1


# ── discovery.finding dispatch (Slice 4 §4, Task 17) ──────────────────────────


@pytest.fixture(autouse=True)
def reset_violation_window():
    """`agent_telemetry._violations` is process-global; leaking counts across
    tests would make every rate-limit assertion below order-dependent. Mirrors
    the identically-named fixture in test_agent_telemetry.py."""
    from app.services import agent_telemetry

    agent_telemetry._violations.clear()
    yield
    agent_telemetry._violations.clear()


def _events_of_type(db, agent, event_type: str) -> list:
    from app.db.models import AgentEvent

    return list(
        db.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type=event_type)
        .order_by(AgentEvent.id)
    )


def _frozen_monotonic(monkeypatch) -> dict:
    """Pin `recordable_violation`'s only clock, returning the dict that moves it.

    Only `agent_telemetry`'s own `time` reference is replaced: patching stdlib
    `time.monotonic` globally would also move asyncio's clock underneath these
    async tests.
    """
    from types import SimpleNamespace

    from app.services import agent_telemetry

    clock = {"now": 1000.0}
    monkeypatch.setattr(agent_telemetry, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    return clock


def _discovery_finding_payload(**overrides) -> dict:
    """A schema-valid `discovery.finding`. It names no real dispatch — every
    test here asserts routing and auditing, never acceptance, which is
    test_agent_discovery_ingest.py's subject."""
    payload = {
        "dispatch_id": "f" * 32,
        "scan_job_id": 4242,
        "finding_id": "ab12cd34",
        "kind": "host",
        "observed_at": "2026-08-08T12:00:00Z",
        "ip_address": "10.0.0.9",
        "open_ports": [{"port": 22, "protocol": "tcp", "banner": "SSH-2.0-OpenSSH_9.6"}],
        "evidence": ["tcp_connect"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_discovery_finding_with_the_grant_reaches_the_ingest_service(
    db_session, factories, monkeypatch
):
    """The one `_HANDLERS` line Task 17 adds. Without it a granted agent's
    findings are accepted by the capability gate and then silently dropped,
    which is indistinguishable from a scan that found nothing.

    Also pins that `frame.ts` is *not* forwarded: `discovery.finding` is a data
    frame and therefore spools, so its `TS` is the producer's clock and never
    arrival time — the lease rule is judged against the server's own clock
    inside the ingest service (see `_handle_probe_result` for the same rule).
    """
    from unittest.mock import AsyncMock

    from app.services import agent_discovery

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    ingest = AsyncMock(return_value=agent_discovery.DISPOSITION_ACCEPTED)
    monkeypatch.setattr(agent_discovery, "ingest_discovery_finding", ingest)

    payload = _discovery_finding_payload()
    frame = AgentFrame(type="discovery.finding", ts="2026-08-08T12:00:01Z", payload=payload)
    await agent_link.dispatch_frame(db_session, agent, frame)

    ingest.assert_awaited_once_with(db_session, agent, payload)
    assert "received_at" not in (ingest.await_args.kwargs or {}), (
        "the agent's own frame timestamp must never be handed to the lease check"
    )


@pytest.mark.asyncio
async def test_discovery_finding_without_the_grant_is_dropped_as_a_capability_violation(
    db_session, factories, monkeypatch
):
    """Already true via `CAPABILITY_FOR_TYPE[TYPE_DISCOVERY_FINDING]`; pinned
    here because it is the outermost of §4's authorization checks — an agent
    whose `local_discovery` grant is off must never reach the ingest service at
    all, so nothing it claims can become a reviewable row."""
    from unittest.mock import AsyncMock

    from app.services import agent_discovery

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=False)
    ingest = AsyncMock()
    monkeypatch.setattr(agent_discovery, "ingest_discovery_finding", ingest)

    frame = AgentFrame(
        type="discovery.finding", ts="2026-08-08T12:00:01Z", payload=_discovery_finding_payload()
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    ingest.assert_not_awaited()
    events = _events_of_type(db_session, agent, "capability_violation")
    assert len(events) == 1
    assert events[0].detail == {"frame_type": "discovery.finding"}


@pytest.mark.asyncio
async def test_malformed_discovery_finding_records_a_protocol_violation(db_session, factories):
    """A body that does not parse is a schema mistake, not an authorization
    failure, and must be audited as the ordinary `protocol_violation` the
    telemetry and probe paths already use. Runs against the real ingest service
    rather than a stub so the event type comes from the domain error it
    actually raises."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)

    frame = AgentFrame(type="discovery.finding", ts="2026-08-08T12:00:01Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    events = _events_of_type(db_session, agent, "protocol_violation")
    assert len(events) == 1
    assert events[0].detail["reason"] == "payload schema is invalid"
    assert events[0].detail["repeated"] == 1
    assert _events_of_type(db_session, agent, "capability_violation") == []


@pytest.mark.asyncio
async def test_repeated_malformed_discovery_findings_collapse_to_one_audit_event(
    db_session, factories, monkeypatch
):
    """`discovery.finding` is a spooled data frame, so the shape this has to
    survive is a whole outage's worth of rejected bodies replayed in one burst
    at reconnect. Every rejection must go through
    `agent_telemetry.recordable_violation`, which is the only bound on how many
    rows one agent can write into `agent_events`."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    clock = _frozen_monotonic(monkeypatch)

    for seq in range(100):
        await agent_link.dispatch_frame(
            db_session,
            agent,
            AgentFrame(type="discovery.finding", seq=seq, ts="2026-08-08T12:00:01Z", payload={}),
        )

    events = _events_of_type(db_session, agent, "protocol_violation")
    assert len(events) == 1, "100 rejections inside one minute must collapse to one audit event"

    clock["now"] += 61
    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(type="discovery.finding", seq=100, ts="2026-08-08T12:00:01Z", payload={}),
    )

    events = _events_of_type(db_session, agent, "protocol_violation")
    assert len(events) == 2
    assert events[1].detail["repeated"] == 100, "the suppressed count must survive the window"


@pytest.mark.asyncio
async def test_discovery_finding_rejection_keeps_the_event_type_the_domain_error_chose(
    db_session, factories, monkeypatch
):
    """A finding posted against a dispatch this agent does not own is what a
    stolen token looks like, so `ingest_discovery_finding` raises with
    `event_type="capability_violation"` and the handler must record *that*
    rather than its own default — and must rate-limit it identically, since an
    attacker replaying a guessed token is exactly the flood the limiter exists
    for. The stolen-token scenario itself belongs to
    test_agent_discovery_ingest.py; this pins only the routing.
    """
    from app.services import agent_discovery

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    _frozen_monotonic(monkeypatch)

    async def _refuse(db, refused_agent, payload, **kwargs):
        raise agent_discovery.InvalidDiscoveryFinding(
            agent_discovery.REASON_DISPATCH_OWNER_MISMATCH,
            event_type=agent_discovery.EVENT_CAPABILITY_VIOLATION,
        )

    monkeypatch.setattr(agent_discovery, "ingest_discovery_finding", _refuse)

    for seq in range(100):
        await agent_link.dispatch_frame(
            db_session,
            agent,
            AgentFrame(
                type="discovery.finding",
                seq=seq,
                ts="2026-08-08T12:00:01Z",
                payload=_discovery_finding_payload(),
            ),
        )

    events = _events_of_type(db_session, agent, "capability_violation")
    assert len(events) == 1
    assert events[0].detail["reason"] == agent_discovery.REASON_DISPATCH_OWNER_MISMATCH
    assert _events_of_type(db_session, agent, "protocol_violation") == []


@pytest.mark.asyncio
async def test_self_audited_discovery_rejection_is_not_recorded_twice(
    db_session, factories, monkeypatch
):
    """`InvalidDiscoveryFinding.audited` marks the one rejection that wrote and
    committed its own event atomically with closing the job (the finding-ceiling
    breach). The handler must skip its own `record_event` for it, and must not
    consume the rate-limit window either — otherwise the very next genuine
    rejection is suppressed by a breach that already recorded itself.
    """
    from app.services import agent_discovery

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True)
    _frozen_monotonic(monkeypatch)

    async def _refuse_already_audited(db, refused_agent, payload, **kwargs):
        raise agent_discovery.InvalidDiscoveryFinding(
            agent_discovery.REASON_FINDING_CEILING,
            event_type=agent_discovery.EVENT_CAPABILITY_VIOLATION,
            audited=True,
        )

    real_ingest = agent_discovery.ingest_discovery_finding
    monkeypatch.setattr(agent_discovery, "ingest_discovery_finding", _refuse_already_audited)
    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(
            type="discovery.finding",
            ts="2026-08-08T12:00:01Z",
            payload=_discovery_finding_payload(),
        ),
    )

    assert _events_of_type(db_session, agent, "capability_violation") == []
    assert _events_of_type(db_session, agent, "protocol_violation") == []

    # Same agent, same minute: the window was never consumed, so an ordinary
    # rejection still records.
    monkeypatch.setattr(agent_discovery, "ingest_discovery_finding", real_ingest)
    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(type="discovery.finding", seq=1, ts="2026-08-08T12:00:01Z", payload={}),
    )
    assert len(_events_of_type(db_session, agent, "protocol_violation")) == 1


# ── capability.violation: the agent's own scope-disagreement reports (§7) ─────


def _capability_violation_payload(**overrides) -> dict:
    """The shape `probe.Runtime.emitCapabilityViolation` sends: which of our
    frames it refused, plus the scope evaluator's own machine-readable reason."""
    payload = {
        "frame_type": "probe.assign",
        "reason": "out_of_scope",
        "address": "203.0.113.9",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_agent_reported_capability_violation_is_recorded_on_the_agents_timeline(
    db_session, factories
):
    """Plan §7 requires a `capability_violation` event for rejected agent
    behavior, and the agent's own refusal is the half the server cannot observe:
    the two ends disagreed about this agent's scope, so a backend bug that
    dispatches out-of-scope work is visible on the timeline instead of looking
    like a flaky monitor. The frame is declared but was silently dropped before
    Task 17, so this produced no row at all."""
    agent = factories.agent(status="active")

    frame = AgentFrame(
        type="capability.violation",
        ts="2026-08-08T12:00:01Z",
        payload=_capability_violation_payload(),
    )
    await agent_link.dispatch_frame(db_session, agent, frame)

    events = _events_of_type(db_session, agent, "capability_violation")
    assert len(events) == 1
    assert events[0].detail["reason"] == "out_of_scope"
    assert events[0].detail["frame_type"] == "probe.assign"
    assert events[0].detail["address"] == "203.0.113.9"
    # A server-side gate drop writes only {"frame_type": ...}; the two must be
    # tellable apart, because they mean opposite things about who refused.
    assert events[0].detail["reported_by"] == "agent"


@pytest.mark.asyncio
async def test_capability_violation_needs_no_grant_and_so_must_be_bounded(db_session, factories):
    """`capability.violation` is deliberately absent from `CAPABILITY_FOR_TYPE`,
    so `dispatch_frame`'s grant gate does not apply: an agent with every
    capability off can still write here. That is why the payload is validated
    against a closed vocabulary before anything is persisted — the destination
    is an unbounded JSONB column with no retention job."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=False)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(
            type="capability.violation",
            ts="2026-08-08T12:00:01Z",
            payload=_capability_violation_payload(),
        ),
    )

    assert len(_events_of_type(db_session, agent, "capability_violation")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"frame_type": "probe.assign", "reason": "in_scope"}, id="an-acceptance"),
        pytest.param(
            {"frame_type": "probe.assign", "reason": "unresolved_hostname"},
            id="a-resolution-failure-the-agent-reports-as-an-execution-error",
        ),
        pytest.param(
            {"frame_type": "probe.assign", "reason": "capability not granted"},
            id="free-prose",
        ),
        pytest.param(
            {"frame_type": "probe.assign", "reason": "x" * 400},
            id="an-unbounded-reason",
        ),
        pytest.param(
            {"frame_type": "probe.assign", "reason": "out_of_scope", "detail": "d" * 400},
            id="an-over-long-detail",
        ),
        pytest.param(
            {"frame_type": "probe.assign", "reason": "out_of_scope", "address": "a" * 400},
            id="an-address-wider-than-an-ipv6-literal",
        ),
        pytest.param({}, id="an-empty-body"),
    ],
)
async def test_unbounded_capability_violation_writes_no_row(db_session, factories, payload):
    """Anything outside the bounded payload is dropped, not stored. A frame the
    grant gate does not cover and no retention job prunes is the wrong place to
    be permissive, and the agent's own emitter sends exactly the closed
    vocabulary — a report outside it is not a scope disagreement this server can
    act on. Dropping mirrors `_handle_update_status`'s unknown-phase branch."""
    agent = factories.agent(status="active")

    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(type="capability.violation", ts="2026-08-08T12:00:01Z", payload=payload),
    )

    assert _events_of_type(db_session, agent, "capability_violation") == []
    assert _events_of_type(db_session, agent, "protocol_violation") == []


@pytest.mark.asyncio
async def test_capability_violation_free_text_is_sanitized_before_it_is_stored(
    db_session, factories
):
    """`detail` is the one free-text field, so it is the one log-injection
    vector: a CRLF plus a forged level prefix is exactly what plan §7's
    no-untrusted-contents rule exists for. It goes through
    `core.log_sanitize.safe_log_fragment`, the same way every reason on the
    finding-ingest path does."""
    agent = factories.agent(status="active")

    await agent_link.dispatch_frame(
        db_session,
        agent,
        AgentFrame(
            type="capability.violation",
            ts="2026-08-08T12:00:01Z",
            payload=_capability_violation_payload(
                detail="refused\r\nERROR forged record token=hunter2"
            ),
        ),
    )

    stored = _events_of_type(db_session, agent, "capability_violation")[0].detail["detail"]
    assert "\r" not in stored and "\n" not in stored
    assert "hunter2" not in stored, "a secret-shaped fragment must be redacted, not stored"


@pytest.mark.asyncio
async def test_hundred_capability_violations_in_one_minute_write_at_most_one_row(
    db_session, factories, monkeypatch
):
    """The required bound. `capability.violation` needs no grant, so an agent
    that has lost every capability can still emit it as fast as it likes into an
    unbounded JSONB column that nothing prunes; `recordable_violation` runs
    *before* any write, so the flood costs one row, not a hundred.

    The surviving row records the machine-readable reason and, at most, an
    address — never a banner or an evidence value. The payload below carries
    both, exactly as a hostile agent would.
    """
    agent = factories.agent(status="active")
    _frozen_monotonic(monkeypatch)

    payload = _capability_violation_payload(
        banner="SSH-2.0-OpenSSH_9.6 leaked-banner-bytes",
        evidence=["tcp_connect", "leaked-evidence-value"],
        open_ports=[{"port": 22, "banner": "leaked-banner-bytes"}],
    )
    for seq in range(100):
        await agent_link.dispatch_frame(
            db_session,
            agent,
            AgentFrame(
                type="capability.violation", seq=seq, ts="2026-08-08T12:00:01Z", payload=payload
            ),
        )

    events = _events_of_type(db_session, agent, "capability_violation")
    assert len(events) == 1, "100 reports inside one minute must collapse to one audit row"
    detail = events[0].detail
    assert detail["reason"] == "out_of_scope"
    assert detail["address"] == "203.0.113.9"
    assert detail["repeated"] == 1
    assert "banner" not in detail and "evidence" not in detail and "open_ports" not in detail
    serialized = json.dumps(detail)
    assert "leaked-banner-bytes" not in serialized
    assert "leaked-evidence-value" not in serialized
