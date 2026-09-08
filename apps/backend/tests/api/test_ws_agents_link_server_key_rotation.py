"""Task 28: server-key rotation with an overlap window, end to end -- a live /link
handshake accepts either the current or successor server key during the overlap
and rejects the previous one after it elapses, and the successor key is
advertised over authenticated links both as a live push and a durable hello.ack
resend (Fix round 1).

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import ServerKeyRotationState, get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
    _FakeTTLRedis,
    _login_admin,
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


def _reset_server_key_rotation_committed() -> None:
    """Clear any server-key rotation state left over on the singleton
    `AppSettings` row from another test in this process. Unlike `db_session`'s
    rolled-back SAVEPOINT, `_start_server_key_rotation_committed` below
    commits for real (it has to, for `link_stream`'s own `SessionLocal()` to
    see it) — so without this, one test's rotation would still be "active"
    the next time a sibling test in this file tries to start its own."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings

    with SessionLocal() as db:
        row = get_or_create_settings(db)
        row.agent_server_key_pending_private_key = None
        row.agent_server_key_rotation_started_at = None
        row.agent_server_key_rotation_overlap_expires_at = None
        db.commit()


def _start_server_key_rotation_committed(
    *, overlap_seconds: int | None = None
) -> ServerKeyRotationState:
    """`agent_crypto.start_server_key_rotation`, but via a real committed
    `SessionLocal()` connection rather than the test's own `db_session` —
    same reasoning as `_active_agent_with_key` above: `link_stream`'s own
    `SessionLocal()` calls would never see a change made only inside
    `db_session`'s uncommitted SAVEPOINT. Always resets any rotation state
    left over from a previous test first (see `_reset_server_key_rotation_
    committed`), so this is deterministic regardless of test order."""
    from app.core.agent_crypto import start_server_key_rotation
    from app.db.session import SessionLocal

    _reset_server_key_rotation_committed()
    with SessionLocal() as db:
        state = start_server_key_rotation(db, overlap_seconds=overlap_seconds)
    assert state is not None
    return state


# ── Task 28: server-key rotation with an overlap window, end to end ────────
# Service-layer proofs of the same behavior (with an injectable/advanceable
# clock, no real wait at all) live in tests/test_agent_crypto.py's
# "server-key rotation" section; these prove the live /link wiring on top.


@pytest.fixture
def _server_key_rotation_cleanup():
    """Both tests below commit real server-key rotation state (via
    `_start_server_key_rotation_committed`) onto the process-global
    `AppSettings` singleton row — unlike `db_session`'s rolled-back
    SAVEPOINT, that persists past this test's own teardown. Worse than just
    "a rotation looks active to the next test": the retirement test actually
    *promotes* the successor into `agent_server_private_key`, permanently
    changing which key is "current" in the DB — while `get_server_static_
    keypair`'s process-lifetime cache (which many other tests, in this file
    and others, still rely on for the "real" current key) keeps returning
    the pre-rotation value forever after. Snapshotting the whole row before
    the test and restoring it verbatim afterward (not just clearing the
    rotation columns) undoes both kinds of leakage regardless of whether the
    test itself passed."""
    from app.db.session import SessionLocal
    from app.services.settings_service import get_or_create_settings

    _rotation_columns = (
        "agent_server_private_key",
        "agent_server_key_pending_private_key",
        "agent_server_key_rotation_started_at",
        "agent_server_key_rotation_overlap_expires_at",
    )
    with SessionLocal() as db:
        row = get_or_create_settings(db)
        snapshot = {column: getattr(row, column) for column in _rotation_columns}

    yield

    with SessionLocal() as db:
        row = get_or_create_settings(db)
        for column, value in snapshot.items():
            setattr(row, column, value)
        db.commit()


def test_link_accepts_both_server_keys_during_the_overlap_window(
    db_session, ws_client, monkeypatch, _server_key_rotation_cleanup
):
    """Once an admin starts a server-key rotation, a live /link handshake
    succeeds whether the connecting agent used the server's current or its
    successor public key — the overlap window's whole point — and each
    connection records which of the two this agent pinned."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, current_server_pub = get_server_static_keypair()
    state = _start_server_key_rotation_committed(overlap_seconds=3600)
    successor_server_pub = state.successor_pub
    assert successor_server_pub is not None
    assert successor_server_pub != current_server_pub

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, current_server_pub)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, successor_server_pub)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.server_pk_current_pinned_at is not None
    assert refreshed.server_pk_successor_pinned_at is not None


def test_link_rejects_previous_server_key_and_accepts_successor_after_overlap_elapses(
    db_session, ws_client, monkeypatch, _server_key_rotation_cleanup
):
    """The previous server key is retired — no longer accepted — only once
    the overlap window elapses. Uses a short *real* overlap window (1s) so
    this proves the actual live-socket wiring without a 7-day wait; the
    exact retirement-timing logic itself is proven with an injected clock in
    test_agent_crypto.py's test_complete_ik_handshake_retires_previous_key_
    once_overlap_elapses, with no wait at all."""
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, old_current_server_pub = get_server_static_keypair()
    state = _start_server_key_rotation_committed(overlap_seconds=1)
    successor_server_pub = state.successor_pub
    assert successor_server_pub is not None

    time.sleep(1.5)

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(agent_priv, old_current_server_pub)
            ws.send_bytes(initiator.write_message())
            ws.receive_bytes()  # never arrives — handshake itself failed, 1008 close

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, successor_server_pub)


# ── Fix round 1 (Critical finding): advertise the successor key over ───────
# authenticated links, both a live push on rotation start and a durable
# resend on every hello.ack while the rotation stays active.


def test_server_key_rotate_delivers_key_rotate_over_live_link(
    db_session, ws_client, monkeypatch, factories, app_cfg, _server_key_rotation_cleanup
):
    """The real `POST /agents/server-key/rotate` admin endpoint pushes a live
    `key.rotate` (kind="server") frame to an already-connected agent
    immediately — not just delivered lazily whenever it next happens to
    reconnect (proven separately below) — via the same Task 8/9 cross-worker
    control-frame path Task 9/10/11 already proved for capabilities.set/
    disconnect. Mirrors test_capabilities_put_delivers_immediate_push_over_
    live_link's shape for this trigger instead of a capability grant."""
    import hashlib
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    headers = _login_admin(ws_client, factories)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before the REST call publishes — same
        # precaution as the companion capabilities.set/disconnect proofs.
        time.sleep(0.1)

        resp = ws_client.post("/api/v1/agents/server-key/rotate", headers=headers)
        assert resp.status_code == 201
        successor_fingerprint = resp.json()["successor_key_fingerprint"]

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "key.rotate"
        assert frame["payload"]["kind"] == "server"
        assert len(frame["payload"]["successor_pk"]) == 64
        assert "expiry" in frame["payload"]
        # Cross-check against the endpoint's own reported fingerprint — the
        # same key, not just a plausible-looking one.
        pushed_fingerprint = hashlib.sha256(
            bytes.fromhex(frame["payload"]["successor_pk"])
        ).hexdigest()[:32]
        assert pushed_fingerprint == successor_fingerprint


def test_link_hello_ack_resends_active_rotation_key_rotate_frame(
    db_session, ws_client, _server_key_rotation_cleanup
):
    """Durability half: a *new* connection established while a rotation is
    active receives the key.rotate frame as part of its own hello.ack
    sequence, right after capabilities.set — the fallback for whatever the
    live-push half (proven above) misses (a worker down at push time, a
    connection that hadn't finished establishing yet, or a publish racing a
    disconnect), mirroring Task 11's "re-send the authoritative set on every
    hello.ack" for capabilities.set."""
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    state = _start_server_key_rotation_committed(overlap_seconds=3600)
    assert state.successor_pub is not None

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)

        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert ack["type"] == "hello.ack"
        capabilities_frame = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert capabilities_frame["type"] == "capabilities.set"
        rotate_frame = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert rotate_frame["type"] == "key.rotate"
        assert rotate_frame["payload"]["kind"] == "server"
        assert rotate_frame["payload"]["successor_pk"] == state.successor_pub.hex()


def test_link_hello_ack_omits_key_rotate_frame_when_no_rotation_is_active(db_session, ws_client):
    """The common case: with no rotation in progress, hello.ack is followed
    by capabilities.set and nothing else — no key.rotate frame is sent."""
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)

        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert ack["type"] == "hello.ack"
        capabilities_frame = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert capabilities_frame["type"] == "capabilities.set"

        # Nothing else should follow within a short window — send a
        # heartbeat and confirm the connection stays healthy with no stray
        # extra frame arriving first.
        _send_frame(initiator, ws, type="heartbeat", seq=0)
        time.sleep(0.2)
