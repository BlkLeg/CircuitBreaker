"""Presence freshness over a live /link socket: it tracks heartbeat frames
specifically (not any traffic), the dead-connection deadline does the same, and
an unknown device_pk is refused outright.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import secrets
import time

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
    _FakeTTLRedis,
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


def test_link_presence_goes_stale_when_only_non_heartbeat_frames_arrive(
    db_session, ws_client, monkeypatch
):
    """Presence freshness tracks `heartbeat` frames specifically. A steady
    stream of non-heartbeat traffic (here: `log` frames) arriving faster
    than the presence TTL must NOT keep presence looking fresh — it must go
    stale once the TTL set by the last real heartbeat (here: none, since
    connect-time presence isn't a heartbeat either) elapses, exactly as if
    the socket had gone silent."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(agent_registry, "_PRESENCE_TTL_SECONDS", 0.4)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        assert ws_client.portal.call(agent_registry.is_agent_online, agent.id) is True

        # Non-heartbeat traffic, faster than the shortened TTL, for longer
        # than the TTL — this is the exact scenario a last-any-traffic check
        # would get wrong.
        deadline = time.monotonic() + 0.9
        seq = 0
        while time.monotonic() < deadline:
            _send_frame(initiator, ws, type="log", seq=seq, payload={"msg": "still here"})
            seq += 1
            time.sleep(0.1)

        # Give the server a moment to process the last frame sent above.
        time.sleep(0.2)

        assert ws_client.portal.call(agent_registry.is_agent_online, agent.id) is False


def test_link_presence_stays_fresh_when_heartbeats_arrive_on_schedule(
    db_session, ws_client, monkeypatch
):
    """Companion to the staleness test above: real `heartbeat` frames
    arriving faster than the (shortened) presence TTL keep presence fresh
    throughout, confirming the fix doesn't just make presence go stale
    unconditionally."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(agent_registry, "_PRESENCE_TTL_SECONDS", 0.4)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        deadline = time.monotonic() + 0.9
        seq = 0
        while time.monotonic() < deadline:
            _send_frame(initiator, ws, type="heartbeat", seq=seq)
            seq += 1
            assert ws_client.portal.call(agent_registry.is_agent_online, agent.id) is True
            time.sleep(0.1)


def test_link_dead_connection_deadline_tracks_heartbeat_not_any_traffic(
    db_session, ws_client, monkeypatch
):
    """The WS-level dead-connection deadline (`_LINK_DEAD_SECONDS`) must be
    measured from the last real `heartbeat` frame, not from "any frame
    arrived recently". A `log` frame every 0.2s — individually spaced wider
    than the shrunk poll interval (so the TimeoutError branch that runs the
    deadline check actually fires between them) but narrower than the
    shrunk dead-seconds threshold — would keep a last-any-traffic check
    perpetually fooled into thinking the connection is alive, even though no
    heartbeat has arrived since connect. The fixed check must still tear the
    connection down once the shrunk dead-seconds threshold elapses since the
    last (never-arriving) heartbeat."""
    import app.api.ws_agents as ws_agents_module
    from app.db.models import AgentEvent

    monkeypatch.setattr(ws_agents_module, "_LINK_POLL_SECONDS", 0.1)
    monkeypatch.setattr(ws_agents_module, "_LINK_DEAD_SECONDS", 0.5)
    monkeypatch.setattr(ws_agents_module, "_LINK_PING_INTERVAL_SECONDS", 999)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        seq = 0
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            _send_frame(initiator, ws, type="log", seq=seq, payload={"msg": "still here"})
            seq += 1
            time.sleep(0.2)

        # Give the server's own loop a moment to notice the elapsed deadline
        # and run its disconnect cleanup.
        time.sleep(0.3)

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "disconnected" in types


def test_link_stays_connected_when_heartbeats_arrive_on_schedule(
    db_session, ws_client, monkeypatch
):
    """Companion to the test above: with the same shrunk poll/dead-seconds
    thresholds, real `heartbeat` frames arriving faster than the dead
    deadline keep the connection up — the fix doesn't tear down a
    genuinely-alive link."""
    import app.api.ws_agents as ws_agents_module
    from app.db.models import AgentEvent

    monkeypatch.setattr(ws_agents_module, "_LINK_POLL_SECONDS", 0.1)
    monkeypatch.setattr(ws_agents_module, "_LINK_DEAD_SECONDS", 0.5)
    monkeypatch.setattr(ws_agents_module, "_LINK_PING_INTERVAL_SECONDS", 999)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        seq = 0
        # 1.5s, three times the shrunk 0.5s dead-seconds threshold — long
        # enough that a false-positive teardown would already have happened
        # by the time this checks, while the `with` block (and thus the
        # connection) is still open.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            _send_frame(initiator, ws, type="heartbeat", seq=seq)
            seq += 1
            time.sleep(0.2)

        # Checked *before* the `with` block's own client-initiated close, so
        # this can only see a "disconnected" event if the server's own
        # deadline logic tore the connection down early — never one from the
        # ordinary close-on-exit below.
        types = [
            e.event_type
            for e in db_session.query(AgentEvent)
            .filter_by(agent_id=agent.id)
            .order_by(AgentEvent.id)
        ]
        assert "disconnected" not in types


def test_link_refuses_unknown_device_pk(ws_client):
    from starlette.websockets import WebSocketDisconnect

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            _send_hello(initiator, ws)
            ws.receive_bytes()  # should never arrive — connection closes 1008 first
