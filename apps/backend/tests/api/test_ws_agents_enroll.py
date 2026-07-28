from datetime import UTC, datetime

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
