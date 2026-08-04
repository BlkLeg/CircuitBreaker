import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.helpers.agent_noise_client import TestNoiseInitiator


def _send_hello(initiator, ws, *, ts=None) -> None:
    frame = {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "ts": (ts or datetime.now(UTC)).isoformat(),
        "payload": {},
    }
    ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))


def _active_agent_with_key(db_session):
    # Seeded via a real committed connection (SessionLocal(), matching what
    # link_stream itself uses) — db_session's SAVEPOINT-based isolation would
    # never become visible to the handler's own SessionLocal() connection.
    # See test_ws_agents_enroll.py::test_enroll_rejects_reconnect_from_previously_rejected_device
    # for the same pattern.
    from app.db.models import Agent, AgentCapabilityGrant
    from app.db.session import SessionLocal

    agent_priv = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric import x25519

    pub = x25519.X25519PrivateKey.from_private_bytes(agent_priv).public_key().public_bytes_raw()
    device_pk = pub.hex()
    fingerprint = hashlib.sha256(pub).hexdigest()[:32]

    with SessionLocal() as setup_db:
        agent = Agent(
            device_pk=device_pk,
            fingerprint=fingerprint,
            status="active",
            hostname="link-test-box",
        )
        setup_db.add(agent)
        setup_db.flush()
        setup_db.add(
            AgentCapabilityGrant(agent_id=agent.id, capability="host_telemetry", enabled=True)
        )
        setup_db.commit()
        agent_id = agent.id

    agent = db_session.get(Agent, agent_id)
    return agent, agent_priv


def test_link_sends_capabilities_set_on_connect(db_session, ws_client):
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)

        first = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert first["type"] == "capabilities.set"
        assert first["payload"]["host_telemetry"] is True


def test_link_records_connected_then_disconnected_events(db_session, ws_client):
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        ws.receive_bytes()  # capabilities.set

    from app.db.models import AgentEvent

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "connected" in types
    assert "disconnected" in types


def test_link_rejects_stale_handshake_timestamp(db_session, ws_client):
    _agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        stale_ts = datetime.now(UTC) - timedelta(minutes=5)
        _send_hello(initiator, ws, ts=stale_ts)

        err = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert err["payload"]["error"] == "clock_skew"


def _send_frame(initiator, ws, *, v=1, type="heartbeat", seq, payload=None) -> None:
    frame = {
        "v": v,
        "type": type,
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))


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


def _connect_linked(ws, agent_priv, server_pub):
    """Handshake + hello + drain the initial capabilities.set."""
    initiator = TestNoiseInitiator(agent_priv, server_pub)
    ws.send_bytes(initiator.write_message())
    initiator.read_message(ws.receive_bytes())
    _send_hello(initiator, ws)
    assert json.loads(initiator.decrypt(ws.receive_bytes()))["type"] == "capabilities.set"
    return initiator


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
