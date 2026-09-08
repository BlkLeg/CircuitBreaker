"""Task 27: device-key rotation end-to-end over the real /link socket -- starting
a rotation, the old key working throughout the transition window, promotion on
the new key's first successful link, expiry, and survival of a malformed or
duplicate successor_pk (Fix round 1, findings C1/C2).

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
    _FakeTTLRedis,
    _receive_bytes_with_timeout,
    _send_frame,
    _send_hello,
)
from tests.helpers.agent_noise_client import TestNoiseInitiator

# Task 21 fix round (Important #2): every test in this file drives a real
# /link WS connection, which now runs through check_and_record_ws_attempt
# before any Noise handshake byte is processed — it fails closed if Redis
# is unreachable. Without this, every pre-existing test here that doesn't
# already install its own `_FakeTTLRedis` (most do, for the cross-worker
# pub/sub behavior they're actually testing) would need a live, reachable
# Redis just to get past websocket.accept(). See
# conftest.py::agent_redis_default's docstring. Tests that install their
# own fake via `monkeypatch.setattr("app.core.redis.get_redis", ...)`
# simply override this default for their own duration, same as before.
pytestmark = pytest.mark.usefixtures("agent_redis_default")


# ── Task 27: device-key rotation, end-to-end over the real /link socket ────


def _new_device_keypair() -> tuple[bytes, str]:
    """(private_bytes, public_hex) for a fresh X25519 device identity."""
    from cryptography.hazmat.primitives.asymmetric import x25519

    priv = secrets.token_bytes(32)
    pub = x25519.X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes_raw()
    return priv, pub.hex()


def test_link_key_rotate_start_persists_pending_key_and_acks(db_session, ws_client, monkeypatch):
    """Starting a rotation over the live, already-authenticated link persists
    the pending key + expiry server-side and acknowledges it back to the
    agent over the same key.rotate frame type — the ack the agent's own
    atomic device.key swap is gated on."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent, AgentEvent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Let link_stream's background control-frame listener actually
        # subscribe before the rotation request publishes its ack — same
        # precaution as the cross-worker-delivery proofs above.
        time.sleep(0.1)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        ack = json.loads(initiator.decrypt(raw))
        assert ack["type"] == "key.rotate"
        assert ack["payload"]["kind"] == "device"
        assert ack["payload"]["successor_pk"] == successor_hex
        assert "expiry" in ack["payload"]

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk == successor_hex
    assert refreshed.pending_device_pk_expiry is not None

    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_started")
        .one()
    )
    assert event.detail["expires_at"]


def test_link_accepts_current_key_throughout_the_transition_window(
    db_session, ws_client, monkeypatch
):
    """Once a rotation has started, the still-current (old) key must keep
    working for the whole transition window — an agent that hasn't switched
    over to its successor yet is not locked out."""
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)
        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _receive_bytes_with_timeout(ws, timeout=2.0)  # drain the ack

    # A fresh connection with the *old* key still succeeds — no promotion has
    # happened yet, so the current identity is unchanged.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

    from app.db.models import Agent

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == agent.device_pk
    assert refreshed.pending_device_pk == successor_hex


def test_link_promotes_pending_key_on_first_successful_link_and_retires_old_key(
    db_session, ws_client, monkeypatch
):
    """The full rotation lifecycle end-to-end: starting a rotation, the old
    key still working, the new (still-pending) key's first successful link
    promoting it (clearing the pending state and recording `key_rotated`),
    and the old key being refused afterward."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent, AgentEvent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)
        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _receive_bytes_with_timeout(ws, timeout=2.0)  # drain the ack

    # First successful link under the new (pending) key promotes it.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, successor_priv, server_pub)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == successor_hex
    assert refreshed.pending_device_pk is None
    assert refreshed.pending_device_pk_expiry is None

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "key_rotated" in types

    # The old key is retired — no longer a recognized identity for this agent.
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            _send_hello(initiator, ws)
            ws.receive_bytes()  # never arrives — closes 1008 first


def test_link_refuses_pending_key_past_its_expiry(db_session, ws_client):
    """A pending key presented after its transition window has lapsed is
    rejected exactly like an unrecognized key — the rotation is never
    silently promoted late."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.pending_device_pk = successor_hex
        row.pending_device_pk_expiry = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(successor_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            _send_hello(initiator, ws)
            ws.receive_bytes()  # never arrives — closes 1008 first


def test_link_clears_expired_pending_rotation_when_current_key_reconnects(db_session, ws_client):
    """No scheduled sweep clears a stale pending rotation (unlike e.g.
    expire_stale_pending_agents for pending *enrollments*) — the agent's own
    next reconnect on its unchanged current key is what notices and clears
    it, recording `key_rotation_expired`."""
    from app.db.models import Agent, AgentEvent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.pending_device_pk = successor_hex
        row.pending_device_pk_expiry = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == agent.device_pk
    assert refreshed.pending_device_pk is None
    assert refreshed.pending_device_pk_expiry is None

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "key_rotation_expired" in types


# ── Fix round 1 (review finding C1): malformed successor_pk over the live,
# already-authenticated /link socket must not tear down the connection ─────


def test_link_survives_malformed_key_rotate_successor_pk(db_session, ws_client):
    """Reviewer repro for C1: `{"kind":"device","successor_pk":"zz"*32,...}`
    sent over an authenticated /link socket used to raise an unhandled
    ValueError out of `bytes.fromhex(successor_pk)` deep in
    `start_device_key_rotation`, which propagated out of `dispatch_frame`
    and killed the connection from a single malformed frame. It must instead
    be rejected at frame-decode time and leave the session alive — proven
    here by sending a well-formed frame afterward on the same connection and
    getting a normal response."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": "zz" * 32,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        # The connection must still be alive: a subsequent well-formed frame
        # is accepted and processed normally, and — critically — no
        # exception propagates out of this `with` block from the frame sent
        # above.
        _send_frame(initiator, ws, type="heartbeat", seq=1)
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk is None


def test_link_survives_key_rotate_successor_pk_wrong_length(db_session, ws_client):
    """Same finding, a different malformed shape: valid hex but the wrong
    length (not a 32-byte X25519 key) must also be rejected rather than
    reaching `bytes.fromhex`/the `pending_device_pk` column unchecked."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": "ab" * 31,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _send_frame(initiator, ws, type="heartbeat", seq=1)
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk is None


# ── Fix round 1 (review finding C2): duplicate pending-key collision must
# not be able to reach a live handshake and raise MultipleResultsFound ─────


def test_link_handshake_survives_duplicate_pending_device_pk(db_session, ws_client):
    """Reviewer repro for C2: two different agents ending up with the same
    `pending_device_pk` used to make `resolve_agent_for_handshake`'s
    `.scalar_one_or_none()` raise `MultipleResultsFound` the next time either
    device's successor key presented itself in a handshake. The primary fix
    is that `start_device_key_rotation` now refuses to create that duplicate
    in the first place (see tests/services/test_agent_registry_key_rotation.py);
    this test proves the read-path backstop by writing the duplicate
    directly and then performing a real handshake against it, which must
    succeed (rather than raise) and resolve deterministically to one agent."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent_a, _ = _active_agent_with_key(db_session)
    agent_b, _ = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row_a = db.get(Agent, agent_a.id)
        row_a.pending_device_pk = successor_hex
        row_a.pending_device_pk_expiry = datetime.now(UTC) + timedelta(minutes=15)
        row_b = db.get(Agent, agent_b.id)
        row_b.pending_device_pk = successor_hex
        row_b.pending_device_pk_expiry = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()

    # Must not raise MultipleResultsFound — the handshake completes normally.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, successor_priv, server_pub)
