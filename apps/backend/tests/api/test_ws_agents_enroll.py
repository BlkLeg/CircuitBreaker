import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from app.db.models import Agent
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


def _login_viewer(ws_client):
    """Seeds a viewer user via a real committed connection (SessionLocal(),
    matching what agent_presence_stream itself uses) — db_session's
    SAVEPOINT-based isolation would never become visible to the handler's own
    SessionLocal() connection. Same pattern as
    test_ws_agents_link.py::_active_agent_with_key and
    test_ws_agents_stream.py::_login_viewer (duplicated locally rather than
    cross-imported — this repo's test modules under tests/api/ have no
    __init__.py, so they aren't set up as an importable package)."""
    import secrets

    from app.core.security import hash_password
    from app.core.time import utcnow_iso
    from app.db.models import User
    from app.db.session import SessionLocal

    password = "TestPassword123!"
    email = f"enroll-test-{secrets.token_hex(4)}@example.com"
    with SessionLocal() as db:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role="viewer",
            is_admin=False,
            is_superuser=False,
            is_active=True,
            display_name="Enroll Test Viewer",
            provider="local",
            created_at=utcnow_iso(),
        )
        db.add(user)
        db.commit()

    resp = ws_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def test_enroll_broadcasts_enrolled_event_to_stream_viewers(
    db_session, ws_client, app_cfg, monkeypatch
):
    """Task 10 end-to-end proof: a brand-new pending enrollment pushes an
    `enrolled` event to every live /api/agents/stream viewer immediately,
    not only on the add-agent panel's 30s poll. Redis is unavailable in the
    unit-test environment, so broadcast_presence falls back to
    ws_manager.broadcast — proven genuinely end-to-end here by actually
    running the /enroll handshake and reading the event back off a real
    /stream connection, mirroring
    test_ws_agents_stream.py::test_stream_authenticates_via_session_cookie_and_forwards_broadcast."""
    import secrets

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    _login_viewer(ws_client)

    with ws_client.websocket_connect("/api/v1/agents/stream") as stream_ws:
        ack = json.loads(stream_ws.receive_text())
        assert ack["status"] == "connected"

        _, server_pub = get_server_static_keypair()
        agent_priv = secrets.token_bytes(32)
        with ws_client.websocket_connect("/api/v1/agents/enroll") as enroll_ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            enroll_ws.send_bytes(initiator.write_message())
            initiator.read_message(enroll_ws.receive_bytes())
            enroll_ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
            ack_pt = initiator.decrypt(enroll_ws.receive_bytes())

        ack_payload = json.loads(ack_pt)["payload"]

        msg = json.loads(stream_ws.receive_text())
        assert msg["agent_id"] == ack_payload["agent_id"]
        assert msg["event_type"] == "enrolled"

    agent = db_session.query(Agent).filter_by(id=ack_payload["agent_id"]).one()
    assert agent.status == "pending"


def test_enroll_reconnect_of_still_pending_device_does_not_rebroadcast(
    db_session, ws_client, app_cfg, monkeypatch
):
    """A device that reconnects to /enroll while its prior enrollment is
    still pending reuses that same row (see
    test_enroll_rejects_reconnect_from_previously_rejected_device's sibling
    branches) — the UI already learned about it on the first handshake, so a
    second `enrolled` broadcast for the same agent_id would be a spurious
    duplicate "new agent" notification. No second event should reach a live
    /stream viewer within the test's observation window."""
    import secrets

    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    _login_viewer(ws_client)

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/stream") as stream_ws:
        ack = json.loads(stream_ws.receive_text())
        assert ack["status"] == "connected"

        with ws_client.websocket_connect("/api/v1/agents/enroll") as enroll_ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            enroll_ws.send_bytes(initiator.write_message())
            initiator.read_message(enroll_ws.receive_bytes())
            enroll_ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
            initiator.decrypt(enroll_ws.receive_bytes())

        first_event = json.loads(stream_ws.receive_text())
        assert first_event["event_type"] == "enrolled"
        first_agent_id = first_event["agent_id"]

        # Same device_pk reconnects while its enrollment is still pending.
        with ws_client.websocket_connect("/api/v1/agents/enroll") as enroll_ws2:
            initiator2 = TestNoiseInitiator(agent_priv, server_pub)
            enroll_ws2.send_bytes(initiator2.write_message())
            initiator2.read_message(enroll_ws2.receive_bytes())
            enroll_ws2.send_bytes(initiator2.encrypt(_make_hello_frame_bytes()))
            ack_pt2 = initiator2.decrypt(enroll_ws2.receive_bytes())

        ack_payload2 = json.loads(ack_pt2)["payload"]
        assert ack_payload2["agent_id"] == first_agent_id

        # Nudge a distinguishable broadcast through the same fallback path so
        # a hang here (nothing at all arriving) can't masquerade as "no
        # duplicate was sent" — if the reconnect had wrongly rebroadcast,
        # this read would return that spurious `enrolled` event instead of
        # the sentinel below.
        from app.core.ws_manager import ws_manager

        ws_client.portal.call(
            ws_manager.broadcast,
            {"agent_id": first_agent_id, "event_type": "_sentinel", "detail": None},
        )
        next_event = json.loads(stream_ws.receive_text())
        assert next_event["event_type"] == "_sentinel"

    agents = db_session.query(Agent).filter_by(id=first_agent_id).all()
    assert len(agents) == 1
