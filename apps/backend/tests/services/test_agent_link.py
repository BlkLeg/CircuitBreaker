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
