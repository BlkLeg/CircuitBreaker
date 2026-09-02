"""Slice 4.1: the TLS trust rotation state machine."""

from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.services import agent_tls_pin


def test_no_rotation_reads_as_inactive(db_session):
    state = agent_tls_pin.load_tls_pin_rotation_state(db_session)
    assert state.rotation_active is False
    assert state.successor_mode is None
    assert state.successor_pin is None


def test_start_records_a_self_signed_successor(db_session, self_signed_certificate):
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None
    assert state.rotation_active is True
    assert state.successor_mode == "self_signed"
    assert state.successor_pin  # a real SPKI digest, not empty
    assert state.overlap_expires_at is not None


def test_start_records_a_public_cutover_with_no_pin(db_session, letsencrypt_certificate):
    """A Let's Encrypt successor drops the pin. The rotation is still active —
    an empty pin is a policy, not an absence."""
    state = agent_tls_pin.start_tls_pin_rotation(db_session, letsencrypt_certificate)
    assert state is not None
    assert state.rotation_active is True
    assert state.successor_mode == "public"
    assert state.successor_pin == ""


def test_second_start_while_active_is_refused(db_session, self_signed_certificate):
    assert agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate) is not None
    assert agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate) is None


def test_complete_clears_every_column(db_session, self_signed_certificate):
    agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    agent_tls_pin.complete_tls_pin_rotation(db_session)

    state = agent_tls_pin.load_tls_pin_rotation_state(db_session)
    assert state.rotation_active is False
    assert state.successor_pin is None
    assert state.started_at is None
    assert state.overlap_expires_at is None


def test_overlap_defaults_to_seven_days(db_session, self_signed_certificate):
    now = utcnow()
    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate, now=now)
    assert state is not None
    expected = now + timedelta(seconds=agent_tls_pin.TLS_PIN_OVERLAP_SECONDS)
    assert state.overlap_expires_at == expected


def test_record_tls_pin_marks_the_successor_bucket(db_session, factories):
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "successor")

    assert agent.tls_pin_successor_pinned_at is not None
    assert agent.tls_pin_current_pinned_at is None


def test_record_tls_pin_marks_the_current_bucket(db_session, factories):
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "current")

    assert agent.tls_pin_current_pinned_at is not None
    assert agent.tls_pin_successor_pinned_at is None


def test_record_tls_pin_ignores_an_unreported_kind(db_session, factories):
    """An agent predating this mechanism sends no tls_pin_kind at all. That
    must leave both columns untouched rather than being counted as
    convergence on the current policy — an agent that cannot report is
    exactly the one an operator must not be told has converged."""
    from app.services import agent_registry

    agent = factories.agent(status="active")
    agent_registry.record_tls_pin(db_session, agent, "")

    assert agent.tls_pin_current_pinned_at is None
    assert agent.tls_pin_successor_pinned_at is None


@pytest.mark.asyncio
async def test_broadcast_pushes_only_to_online_active_agents(
    db_session, factories, monkeypatch, self_signed_certificate
):
    from app.services import agent_registry

    online = factories.agent(status="active")
    offline = factories.agent(status="active")
    pushed: list[int] = []

    async def fake_presence(ids):
        return {online.id: {"online": True}, offline.id: {"online": False}}

    async def fake_publish(agent_id, frame):
        assert frame["type"] == "tls.pin.rotate"
        assert frame["payload"]["mode"] == "self_signed"
        pushed.append(agent_id)

    monkeypatch.setattr(agent_registry, "bulk_presence", fake_presence)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", fake_publish)

    state = agent_tls_pin.start_tls_pin_rotation(db_session, self_signed_certificate)
    assert state is not None
    count = await agent_registry.broadcast_tls_pin_rotate(db_session, state)

    assert pushed == [online.id]
    assert count == 1
