"""Task 27: device-key rotation state machine — start/settle/resolve, at the
service layer (no live WebSocket involved; see
tests/api/test_ws_agents_link.py for the end-to-end Noise-handshake proofs)."""

import secrets
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.db.models import AgentEvent
from app.services import agent_registry as svc


def _hexkey() -> str:
    return secrets.token_hex(32)


# ── start_device_key_rotation ──────────────────────────────────────────────


def test_start_device_key_rotation_persists_pending_key_and_expiry(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()

    accepted = svc.start_device_key_rotation(db_session, agent, successor)

    assert accepted is True
    assert agent.pending_device_pk == successor
    assert agent.pending_device_pk_expiry is not None
    delta = (agent.pending_device_pk_expiry - utcnow()).total_seconds()
    window = svc.DEVICE_KEY_ROTATION_WINDOW_SECONDS
    assert window - 5 <= delta <= window + 5


def test_start_device_key_rotation_records_key_rotation_started_event(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()

    svc.start_device_key_rotation(db_session, agent, successor)

    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_started")
        .one()
    )
    assert "expires_at" in event.detail
    assert "successor_fingerprint" in event.detail


def test_start_device_key_rotation_honors_custom_window(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()

    svc.start_device_key_rotation(db_session, agent, successor, window_seconds=60)

    delta = (agent.pending_device_pk_expiry - utcnow()).total_seconds()
    assert 55 <= delta <= 65


def test_start_device_key_rotation_rejects_successor_matching_current_key(db_session, factories):
    agent = factories.agent(status="active")

    accepted = svc.start_device_key_rotation(db_session, agent, agent.device_pk)

    assert accepted is False
    assert agent.pending_device_pk is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_rejected")
        .one()
    )
    assert event.detail == {"reason": "successor_matches_current"}


def test_start_device_key_rotation_rejects_successor_key_already_in_use(db_session, factories):
    agent = factories.agent(status="active")
    other = factories.agent(status="active")

    accepted = svc.start_device_key_rotation(db_session, agent, other.device_pk)

    assert accepted is False
    assert agent.pending_device_pk is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_rejected")
        .one()
    )
    assert event.detail == {"reason": "successor_key_in_use"}


def test_start_device_key_rotation_second_call_supersedes_first(db_session, factories):
    agent = factories.agent(status="active")
    first_successor = _hexkey()
    second_successor = _hexkey()

    svc.start_device_key_rotation(db_session, agent, first_successor)
    accepted = svc.start_device_key_rotation(db_session, agent, second_successor)

    assert accepted is True
    assert agent.pending_device_pk == second_successor


# ── settle_device_key_rotation ─────────────────────────────────────────────


def test_settle_promotes_pending_key_on_first_successful_link(db_session, factories):
    agent = factories.agent(status="active")
    old_pk = agent.device_pk
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor)

    svc.settle_device_key_rotation(db_session, agent, successor)

    assert agent.device_pk == successor
    assert agent.pending_device_pk is None
    assert agent.pending_device_pk_expiry is None

    event = (
        db_session.query(AgentEvent).filter_by(agent_id=agent.id, event_type="key_rotated").one()
    )
    assert event.detail["new_fingerprint"]
    assert event.detail["old_fingerprint"]
    assert old_pk != successor  # sanity: factories generated distinct keys


def test_settle_is_noop_when_connecting_on_current_key_with_no_pending_rotation(
    db_session, factories
):
    agent = factories.agent(status="active")

    svc.settle_device_key_rotation(db_session, agent, agent.device_pk)

    assert agent.pending_device_pk is None
    assert (
        db_session.query(AgentEvent).filter_by(agent_id=agent.id, event_type="key_rotated").count()
        == 0
    )


def test_settle_is_noop_when_connecting_on_current_key_during_unexpired_pending_rotation(
    db_session, factories
):
    agent = factories.agent(status="active")
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor)

    svc.settle_device_key_rotation(db_session, agent, agent.device_pk)

    # Still pending — the agent hasn't switched over yet, and the window
    # hasn't lapsed either, so nothing about the pending state changes.
    assert agent.pending_device_pk == successor
    assert (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_expired")
        .count()
        == 0
    )


def test_settle_clears_expired_pending_rotation_when_current_key_reconnects(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor, window_seconds=60)
    # Force the pending rotation into the past without waiting a real minute.
    agent.pending_device_pk_expiry = utcnow() - timedelta(seconds=1)

    svc.settle_device_key_rotation(db_session, agent, agent.device_pk)

    assert agent.pending_device_pk is None
    assert agent.pending_device_pk_expiry is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_expired")
        .one()
    )
    assert event is not None


def test_settle_promotes_even_if_pending_key_expiry_has_just_passed(db_session, factories):
    """settle_device_key_rotation trusts the caller (resolve_agent_for_handshake)
    to have already rejected an expired pending key before this ever runs —
    it does not re-check expiry on the promotion branch itself. This pins
    that division of responsibility rather than silently relying on it."""
    agent = factories.agent(status="active")
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor)
    agent.pending_device_pk_expiry = utcnow() - timedelta(seconds=1)

    svc.settle_device_key_rotation(db_session, agent, successor)

    assert agent.device_pk == successor
    assert agent.pending_device_pk is None


# ── resolve_agent_for_handshake ─────────────────────────────────────────────


def test_resolve_agent_for_handshake_matches_current_key(db_session, factories):
    agent = factories.agent(status="active")

    resolved = svc.resolve_agent_for_handshake(db_session, agent.device_pk)

    assert resolved is not None
    assert resolved.id == agent.id


def test_resolve_agent_for_handshake_matches_unexpired_pending_key(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor)

    resolved = svc.resolve_agent_for_handshake(db_session, successor)

    assert resolved is not None
    assert resolved.id == agent.id


def test_resolve_agent_for_handshake_rejects_expired_pending_key(db_session, factories):
    agent = factories.agent(status="active")
    successor = _hexkey()
    svc.start_device_key_rotation(db_session, agent, successor, window_seconds=60)
    agent.pending_device_pk_expiry = utcnow() - timedelta(seconds=1)

    resolved = svc.resolve_agent_for_handshake(db_session, successor)

    assert resolved is None


def test_resolve_agent_for_handshake_returns_none_for_unknown_key(db_session, factories):
    factories.agent(status="active")

    resolved = svc.resolve_agent_for_handshake(db_session, _hexkey())

    assert resolved is None


# ── Fix round 1 (review findings C1/C2): malformed input and duplicate ─────
# pending-key rejection, at the service layer. See tests/services/
# test_agent_link.py and tests/api/test_ws_agents_link.py for the same two
# findings proven through the schema layer and the live /link socket.


@pytest.mark.parametrize(
    "malformed",
    [
        "zz" * 32,  # non-hex characters, right length
        "ab" * 31,  # valid hex, wrong (too short) length
        "ab" * 33,  # valid hex, wrong (too long) length
        "AB" * 32,  # uppercase hex — schema/registry both require lowercase
        "a" * 10_000,  # unbounded-length input (Important finding I1)
        "",
    ],
)
def test_start_device_key_rotation_rejects_malformed_successor_pk(db_session, factories, malformed):
    """C1 defense in depth: `start_device_key_rotation` must reject a
    malformed `successor_pk` by returning False and recording
    `key_rotation_rejected`, never by raising — `hashlib.sha256(bytes.fromhex(...))`
    a few lines below would otherwise raise an unhandled ValueError on any of
    these inputs."""
    agent = factories.agent(status="active")

    accepted = svc.start_device_key_rotation(db_session, agent, malformed)

    assert accepted is False
    assert agent.pending_device_pk is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_rejected")
        .one()
    )
    assert event.detail == {"reason": "successor_pk_malformed"}


def test_start_device_key_rotation_rejects_successor_already_pending_for_another_agent(
    db_session, factories
):
    """C2: a successor key already claimed as a *different* agent's
    `pending_device_pk` (not just its `device_pk`) must be rejected too —
    otherwise two agents can end up with the same `pending_device_pk`, and
    `resolve_agent_for_handshake`'s lookup on that column raises
    `MultipleResultsFound` the next time either device's successor key
    presents itself in a handshake."""
    agent_a = factories.agent(status="active")
    agent_b = factories.agent(status="active")
    shared_successor = _hexkey()

    first_accept = svc.start_device_key_rotation(db_session, agent_a, shared_successor)
    assert first_accept is True

    second_accept = svc.start_device_key_rotation(db_session, agent_b, shared_successor)

    assert second_accept is False
    assert agent_b.pending_device_pk is None
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent_b.id, event_type="key_rotation_rejected")
        .one()
    )
    assert event.detail == {"reason": "successor_key_in_use"}

    # The read path that used to raise MultipleResultsFound on this exact
    # scenario (before this fix prevented the collision at write time) also
    # must not raise, as a defensive backstop.
    resolved = svc.resolve_agent_for_handshake(db_session, shared_successor)
    assert resolved is not None
    assert resolved.id == agent_a.id
