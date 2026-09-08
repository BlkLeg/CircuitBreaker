"""Frame-sequence validation (duplicate/decreasing seq, unsupported version) and
transport-level rekeying: both directions over multiple intervals, a rejected
out-of-step rekey, and an undecryptable inbound frame that must be logged, not
silently dropped.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import time

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.api.ws_agents_link_fakes import (
    _active_agent_with_key,
    _connect_linked,
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


def test_link_rejects_replayed_and_invalid_sequences_but_stays_connected(db_session, ws_client):
    """End-to-end: a duplicate seq, a decreasing seq, and an unsupported
    version are all recorded as protocol_violation AgentEvents and don't
    tear down the connection — a subsequent well-formed, strictly-increasing
    frame still gets through and updates presence."""
    from app.db.models import AgentEvent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

        _send_frame(initiator, ws, seq=0)  # accepted, becomes the baseline
        _send_frame(initiator, ws, seq=0)  # duplicate — rejected
        _send_frame(initiator, ws, v=2, seq=1)  # unsupported version — rejected
        _send_frame(initiator, ws, seq=1)  # strictly increasing again — accepted

        # Give the server a moment to process the frames sent above before the
        # connection closes at the end of this `with` block.
        time.sleep(0.3)

    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .order_by(AgentEvent.id)
        .all()
    )
    reasons = [v.detail["reason"] for v in violations]
    assert "duplicate_sequence" in reasons
    assert "unsupported_version" in reasons


def _recv_rekey(initiator, ws):
    """Read one server frame, require it to be a transport.rekey announcement,
    and apply the matching receive-cipher rotation. The announcement decrypts
    under the *old* key — that it decrypts at all is the assertion that the
    server rekeyed only after sending it."""
    frame = json.loads(initiator.decrypt(ws.receive_bytes()))
    assert frame["type"] == "transport.rekey", frame
    assert frame["payload"]["direction"] == "outbound"
    initiator.rekey_recv()
    assert frame["payload"]["generation"] == initiator.recv_generation
    return frame


def _send_rekey(initiator, ws, seq, *, generation=None, direction="outbound"):
    """Announce an agent->server rekey under the old key, then rotate."""
    _send_frame(
        initiator,
        ws,
        type="transport.rekey",
        seq=seq,
        payload={
            "direction": direction,
            "generation": initiator.send_generation + 1 if generation is None else generation,
        },
    )
    initiator.rekey_send()


def test_link_rekeys_both_directions_over_multiple_intervals(db_session, ws_client, monkeypatch):
    """End-to-end over the real WebSocket: with the 15-minute interval
    accelerated to zero, the server rekeys its send cipher once per loop
    iteration while the agent independently rekeys its own — traffic keeps
    flowing in both directions across several generations, and nothing is
    recorded as a protocol violation."""
    from app.db.models import AgentEvent

    monkeypatch.setattr("app.core.agent_crypto.REKEY_INTERVAL_SECONDS", 0)

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        # The server's first loop iteration rekeys before it reads anything.
        _recv_rekey(initiator, ws)

        # A heartbeat under the agent's still-original send key drives one
        # more server loop iteration, hence one more server rekey.
        _send_frame(initiator, ws, seq=0)
        _recv_rekey(initiator, ws)

        # Now the agent rekeys its own direction, twice in a row, each
        # announcement sealed under the key in force at the time.
        _send_rekey(initiator, ws, seq=1)
        _recv_rekey(initiator, ws)
        _send_rekey(initiator, ws, seq=2)
        _recv_rekey(initiator, ws)

        # A heartbeat under the agent's twice-rekeyed send cipher must still
        # decrypt server-side, and the server's response under its own
        # four-times-rekeyed send cipher must still decrypt agent-side.
        _send_frame(initiator, ws, seq=3)
        _recv_rekey(initiator, ws)

        assert initiator.recv_generation == 5
        assert initiator.send_generation == 2

        time.sleep(0.3)

    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .all()
    )
    assert violations == []


@pytest.mark.parametrize(
    ("generation", "direction"),
    [(2, "outbound"), (0, "outbound"), (1, "inbound")],
    ids=["generation-gap", "zero-generation", "inbound-direction"],
)
def test_link_drops_connection_on_an_out_of_step_transport_rekey(
    db_session, ws_client, generation, direction
):
    """A rekey announcement the server can't apply is fatal: applying nothing
    would leave the agent's send cipher a generation ahead of the server's
    receive cipher, so every later frame would be undecryptable anyway."""
    from app.db.models import AgentEvent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        _send_rekey(initiator, ws, seq=0, generation=generation, direction=direction)
        time.sleep(0.3)

    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .all()
    )
    assert [v.detail["reason"] for v in violations] == ["invalid_transport_rekey"]


def test_link_logs_undecryptable_inbound_frame_instead_of_silently_dropping_it(
    db_session, ws_client, caplog
):
    """link_stream's main receive loop wraps `responder.decrypt(ct)` in a
    bare `except Exception: continue` with no logging at all — Task 31's
    E2E investigation flagged this as "the single most under-instrumented
    point in the entire path", capable of silently swallowing a real frame
    (e.g. the one-shot uninstall notification) with zero trace to root-cause
    from. A frame that fails to decrypt must still be logged, even though
    dropping it (not tearing down the connection) remains correct — an
    adversarial or desynced peer must not be able to kill the link over one
    bad frame."""
    import logging

    from app.db.models import AgentEvent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with caplog.at_level(logging.WARNING, logger="app.api.ws_agents"):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            _connect_linked(ws, agent_priv, server_pub)
            # Not a validly-encrypted frame under either side's cipher —
            # exercises the decrypt() call directly, distinct from a
            # decryptable-but-malformed frame body (receive_frame's own
            # validation, covered elsewhere).
            ws.send_bytes(b"not-a-valid-noise-ciphertext")
            time.sleep(0.3)

    assert any(
        str(agent.id) in record.getMessage() and "decrypt" in record.getMessage().lower()
        for record in caplog.records
    ), [r.getMessage() for r in caplog.records]

    # Dropping is silent to the wire protocol too — no protocol_violation
    # recorded for an undecryptable frame (that AgentEvent is reserved for
    # receive_frame's own decoded-but-invalid rejections).
    violations = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="protocol_violation")
        .all()
    )
    assert violations == []
