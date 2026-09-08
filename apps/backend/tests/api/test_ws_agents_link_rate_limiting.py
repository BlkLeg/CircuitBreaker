"""Task 21's per-IP attempt-rate gate as wired into /link: attempts over the limit
are refused before a single Noise handshake byte is processed, and /link's
counter is independent from /enroll's.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import secrets

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import _active_agent_with_key, _send_hello
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


def test_link_rejects_further_attempts_from_ip_past_per_ip_limit(
    db_session, ws_client, monkeypatch
):
    """Task 21: same attempt-rate gate as /enroll, wired into /link — once
    this IP's per-attempt counter trips, the connection is refused before a
    single Noise handshake byte is processed."""
    from app.services import agent_enrollment

    monkeypatch.setattr(agent_enrollment, "_WS_ATTEMPT_IP_LIMIT", 1)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    # First attempt: under the (lowered) limit, completes normally.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert ack["payload"]["accepted"] is True

    # Second attempt from the same (TestClient-fixed) source IP: over the
    # limit, rejected immediately with no handshake response at all.
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/link") as ws2:
            initiator2 = TestNoiseInitiator(agent_priv, server_pub)
            ws2.send_bytes(initiator2.write_message())
            ws2.receive_bytes()  # nothing coming — server already closed

    assert exc_info.value.code == 1013


def test_link_attempt_counter_is_independent_from_enroll(db_session, ws_client, monkeypatch):
    """Exhausting /link's per-IP counter must not block /enroll from the
    same IP, and vice versa — separate key namespaces per endpoint (see
    check_and_record_ws_attempt)."""
    from app.services import agent_enrollment

    monkeypatch.setattr(agent_enrollment, "_WS_ATTEMPT_IP_LIMIT", 1)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        json.loads(initiator.decrypt(ws.receive_bytes()))

    # /link is now over its own (lowered) per-IP limit, but /enroll — a
    # different endpoint namespace — must still accept a fresh attempt from
    # the very same source IP.
    with ws_client.websocket_connect("/api/v1/agents/enroll") as enroll_ws:
        enroll_initiator = TestNoiseInitiator(secrets.token_bytes(32), server_pub)
        enroll_ws.send_bytes(enroll_initiator.write_message())
        # No exception — the handshake response arrives normally.
        enroll_initiator.read_message(enroll_ws.receive_bytes())
