from datetime import UTC, datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from tests.helpers.agent_noise_client import TestNoiseInitiator


def _make_hello_frame_bytes(**overrides) -> bytes:
    import json

    payload = {
        "hostname": "test-box",
        "machine_id_hash": None,
        "os": "linux",
        "os_version": "6.1",
        "arch": "amd64",
        "agent_version": "0.1.0",
        "primary_macs": ["aa:bb:cc:dd:ee:ff"],
    }
    payload.update(overrides)
    frame = {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload,
    }
    return json.dumps(frame).encode()


def test_enroll_creates_pending_agent_and_returns_pairing_code(db_session, ws_client):
    import secrets

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))

        ack_ct = ws.receive_bytes()
        ack_pt = initiator.decrypt(ack_ct)

    import json

    ack = json.loads(ack_pt)
    assert ack["type"] == "hello.ack"
    assert "pairing_code" in ack["payload"]
    assert len(ack["payload"]["pairing_code"].split("-")) == 3

    from app.db.models import Agent

    agent = db_session.query(Agent).filter_by(status="pending").one()
    assert agent.hostname == "test-box"


def test_enroll_rejects_stale_handshake_timestamp(db_session, ws_client):
    import secrets
    from datetime import timedelta

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        stale_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        import json

        payload = {"hostname": "test-box", "os": "linux", "arch": "amd64", "agent_version": "0.1.0"}
        frame = {"v": 1, "type": "hello", "seq": 0, "ts": stale_ts, "payload": payload}
        ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))

        # Server sends a clock-skew error frame before closing 1008.
        err_ct = ws.receive_bytes()
        err = json.loads(initiator.decrypt(err_ct))
        assert err["payload"]["error"] == "clock_skew"


def test_enroll_closes_cleanly_on_non_binary_first_frame(ws_client):
    """Regression test: a TEXT frame as the very first message used to crash
    the handler with an unhandled KeyError (Starlette's receive_bytes()
    indexes message["bytes"], which a text-frame message dict doesn't have).
    It must now degrade to the same clean 1008 close as every other
    malformed-input path, not an unhandled exception."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
            ws.send_text("not a noise handshake message")
            ws.receive_bytes()

    assert exc_info.value.code == 1008


def test_enroll_closes_cleanly_on_hello_frame_missing_ts(ws_client):
    """Regression test: a hello frame missing "ts" used to crash the handler
    with an unhandled KeyError (only ClockSkewError was caught around the
    check_clock_skew() call). Any anonymous client that completes the Noise
    handshake — no prior registration required — can reach this path with
    one bad field, so it must close cleanly rather than crash."""
    import json
    import secrets

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())

            # No "ts" key at all.
            payload = {"hostname": "test-box", "os": "linux", "arch": "amd64"}
            frame = {"v": 1, "type": "hello", "seq": 0, "payload": payload}
            ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))

            ws.receive_bytes()

    assert exc_info.value.code == 1008


def test_enroll_rejects_reconnect_from_previously_rejected_device(db_session, ws_client):
    """Regression test: Agent.status has four values (pending|active|revoked|
    rejected), but the handler only branched on revoked/active/pending
    explicitly. A previously-rejected agent reconnecting with the same
    keypair used to fall through to create_pending_agent() against a
    device_pk column that's unique — the existing rejected row already holds
    that value, so db.flush() raised an uncaught IntegrityError. It must now
    close cleanly instead, and must not create a second row for the same
    device_pk."""
    import hashlib
    import secrets

    from app.core.agent_crypto import _public_from_private
    from app.db.models import Agent
    from app.db.session import SessionLocal

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)
    device_pk_hex = _public_from_private(agent_priv).hex()
    fingerprint = hashlib.sha256(bytes.fromhex(device_pk_hex)).hexdigest()[:32]

    # Pre-seed a rejected agent for this exact device, via a real committed
    # connection (SessionLocal(), matching what the handler itself uses) —
    # db_session's SAVEPOINT-based isolation would never become visible to
    # the handler's own SessionLocal() connection.
    with SessionLocal() as setup_db:
        setup_db.add(
            Agent(
                device_pk=device_pk_hex,
                fingerprint=fingerprint,
                status="rejected",
                hostname="previously-rejected-box",
            )
        )
        setup_db.commit()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())

            ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))

            ws.receive_bytes()

    assert exc_info.value.code == 1008

    agents = db_session.query(Agent).filter_by(device_pk=device_pk_hex).all()
    assert len(agents) == 1
    assert agents[0].status == "rejected"
