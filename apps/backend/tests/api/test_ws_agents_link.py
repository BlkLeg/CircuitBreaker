import hashlib
import json
import secrets
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
