import json

import pytest

from app.schemas.agent_frame import AgentFrame
from app.services import agent_link


@pytest.mark.asyncio
async def test_dispatch_heartbeat_refreshes_presence(db_session, factories, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    refresh = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", refresh)

    frame = AgentFrame(type="heartbeat", ts="2026-07-27T12:00:00Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    refresh.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_heartbeat_refreshes_connection_registry(db_session, factories, monkeypatch):
    """Task 8: the connection-ownership registry refreshes on the same
    heartbeat cadence as presence, so it doesn't expire out from under a
    long-lived connection purely from the 60s TTL elapsing."""
    from unittest.mock import AsyncMock

    agent = factories.agent(status="active")
    monkeypatch.setattr("app.services.agent_registry.refresh_presence_heartbeat", AsyncMock())
    refresh_connection = AsyncMock()
    monkeypatch.setattr("app.services.agent_registry.refresh_agent_connection", refresh_connection)

    frame = AgentFrame(type="heartbeat", ts="2026-07-27T12:00:00Z", payload={})
    await agent_link.dispatch_frame(db_session, agent, frame)

    refresh_connection.assert_called_once_with(agent.id)


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

    frame = AgentFrame(
        type="key.rotate", ts="2026-08-04T12:00:00Z", payload={"kind": "device"}
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
