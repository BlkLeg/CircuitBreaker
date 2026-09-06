import json
import secrets
from datetime import UTC, datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import get_server_static_keypair
from app.db.models import Agent
from tests.helpers.agent_noise_client import TestNoiseInitiator

# Task 21 fix round (Important #2): every test in this file drives a real
# /enroll WS connection, which now runs through check_and_record_ws_attempt
# (and, for a new pending agent, acquire_pending_enrollment_lock) before any
# Noise handshake byte is processed — both fail closed if Redis is
# unreachable. Without this, every pre-existing test here (most of which
# predate rate limiting and have nothing to do with it) would need a live,
# reachable Redis just to get past websocket.accept(). See
# conftest.py::agent_redis_default's docstring. Tests below that need
# specific Redis behavior (rate-limit thresholds, Redis-down, a custom
# fake) still monkeypatch `get_redis` themselves, which simply overrides
# this default for their own duration.
pytestmark = pytest.mark.usefixtures("agent_redis_default")


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


def test_enrollment_records_the_endpoint_the_agent_dialed(db_session, ws_client):
    """An endpoint nothing can reach is invisible unless the agent names it: the
    server never connects to an agent, so it cannot observe which address the
    agent actually dialed on its own. The hello payload's `server_url` field
    (optional, so an older agent that omits it still enrolls) is stored on the
    new agent row as `enrolled_via_endpoint`."""
    import secrets

    from app.db.models import Agent

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())

        ws.send_bytes(
            initiator.encrypt(_make_hello_frame_bytes(server_url="https://cb.example.com"))
        )

        initiator.decrypt(ws.receive_bytes())

    agent = db_session.query(Agent).filter_by(status="pending").one()
    assert agent.enrolled_via_endpoint == "https://cb.example.com"


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


def test_enroll_broadcasts_enrolled_event_to_stream_viewers(db_session, ws_client, app_cfg):
    """Task 10 end-to-end proof: a brand-new pending enrollment pushes an
    `enrolled` event to every live /api/agents/stream viewer immediately,
    not only on the add-agent panel's 30s poll. The module-level
    `agent_redis_default` fixture's pub/sub never actually relays anything
    (see conftest.py's `_FakeNullPubSub`), so broadcast_presence falls back
    to ws_manager.broadcast — proven genuinely end-to-end here by actually
    running the /enroll handshake and reading the event back off a real
    /stream connection, mirroring
    test_ws_agents_stream.py::test_stream_authenticates_via_session_cookie_and_forwards_broadcast."""
    import secrets

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
    db_session, ws_client, app_cfg
):
    """A device that reconnects to /enroll while its prior enrollment is
    still pending reuses that same row (see
    test_enroll_rejects_reconnect_from_previously_rejected_device's sibling
    branches) — the UI already learned about it on the first handshake, so a
    second `enrolled` broadcast for the same agent_id would be a spurious
    duplicate "new agent" notification. No second event should reach a live
    /stream viewer within the test's observation window."""
    import secrets

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


def test_enroll_rejects_further_attempts_from_ip_past_per_ip_limit(ws_client, monkeypatch):
    """Task 21: once this IP's per-attempt counter trips, the connection is
    refused before a single Noise handshake byte is processed — the server
    never even replies to the client's handshake message."""
    from app.services import agent_enrollment

    monkeypatch.setattr(agent_enrollment, "_WS_ATTEMPT_IP_LIMIT", 1)

    # First attempt: under the (lowered) limit, completes the full handshake normally.
    _, server_pub = get_server_static_keypair()
    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(secrets.token_bytes(32), server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
        initiator.decrypt(ws.receive_bytes())

    # Second attempt from the same (TestClient-fixed) source IP: over the
    # limit, rejected immediately with no handshake response at all.
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws2:
            initiator2 = TestNoiseInitiator(secrets.token_bytes(32), server_pub)
            ws2.send_bytes(initiator2.write_message())
            ws2.receive_bytes()  # nothing coming — server already closed

    assert exc_info.value.code == 1013


def test_enroll_rejects_regardless_of_ip_once_global_limit_exceeded(ws_client, monkeypatch):
    """Task 21: the global counter trips independently of the per-IP one —
    lowering only the global limit (leaving the per-IP ceiling at its
    default) still rejects a subsequent attempt. (Per-IP independence of
    the global counter — i.e. that a *different* IP is what actually stays
    unblocked — is covered at the unit level in
    test_agent_enrollment.py::test_ws_attempt_exceeding_global_limit_rejects_regardless_of_ip,
    since Starlette's TestClient can't be made to present a different
    source IP per connection here.)"""
    from app.services import agent_enrollment

    monkeypatch.setattr(agent_enrollment, "_WS_ATTEMPT_GLOBAL_LIMIT", 1)

    _, server_pub = get_server_static_keypair()
    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(secrets.token_bytes(32), server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
        initiator.decrypt(ws.receive_bytes())

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws2:
            initiator2 = TestNoiseInitiator(secrets.token_bytes(32), server_pub)
            ws2.send_bytes(initiator2.write_message())
            ws2.receive_bytes()

    assert exc_info.value.code == 1013


def test_enroll_rejects_new_pending_agent_past_concurrent_cap(db_session, ws_client, monkeypatch):
    """Task 21: once MAX_CONCURRENT_PENDING_AGENTS agents already await
    approval, a brand-new device's /enroll handshake is refused before a new
    pending row (and its long-held approval-poll connection) is created for
    it. A device that already has a pending row of its own is unaffected —
    only the *new-row* path is capped (see enroll_stream's `else` branch)."""
    from app.core.agent_crypto import _public_from_private
    from app.db.session import SessionLocal
    from app.services import agent_registry

    # Other tests in this module create pending agents via real committed
    # SessionLocal() connections (same reason test_enroll_rejects_reconnect
    # _from_previously_rejected_device does) that outlive `db_session`'s own
    # per-test rollback, so the DB isn't guaranteed empty of pending agents
    # here — count what's already there and cap exactly one above it.
    baseline_pending = db_session.query(Agent).filter_by(status="pending").count()
    monkeypatch.setattr(agent_registry, "MAX_CONCURRENT_PENDING_AGENTS", baseline_pending + 1)

    # Seed exactly the (lowered) cap's worth of pending agents directly —
    # cheaper than driving that many real handshakes end to end.
    with SessionLocal() as db:
        agent_registry.create_pending_agent(
            db,
            device_pk=secrets.token_hex(32),
            fingerprint=secrets.token_hex(16),
            hostname="filler-box",
        )
        db.commit()

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
            ws.receive_bytes()

    assert exc_info.value.code == 1013

    device_pk_hex = _public_from_private(agent_priv).hex()
    agents_for_device = db_session.query(Agent).filter_by(device_pk=device_pk_hex).all()
    assert agents_for_device == []
    assert db_session.query(Agent).filter_by(status="pending").count() == baseline_pending + 1


def test_enroll_reconnect_of_pending_device_unaffected_by_concurrent_cap(
    db_session, ws_client, monkeypatch
):
    """The concurrent-pending cap only guards the create-a-new-row path — a
    device reconnecting to /enroll while its own enrollment is still pending
    reuses that same row (see the reconnect-of-still-pending tests above),
    so it must succeed even when the cap is already saturated by *other*
    agents' pending rows."""
    from app.services import agent_registry

    # See test_enroll_rejects_new_pending_agent_past_concurrent_cap for why
    # the cap is set relative to a measured baseline rather than assumed 0.
    baseline_pending = db_session.query(Agent).filter_by(status="pending").count()
    monkeypatch.setattr(agent_registry, "MAX_CONCURRENT_PENDING_AGENTS", baseline_pending + 1)

    _, server_pub = get_server_static_keypair()
    agent_priv = secrets.token_bytes(32)

    # First connection creates the one new pending row the (lowered) cap allows.
    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
        ack_pt = initiator.decrypt(ws.receive_bytes())
    first_agent_id = json.loads(ack_pt)["payload"]["agent_id"]

    # Same device reconnects while its own enrollment is still pending —
    # reuses its row rather than needing a fresh slot under the cap.
    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws2:
        initiator2 = TestNoiseInitiator(agent_priv, server_pub)
        ws2.send_bytes(initiator2.write_message())
        initiator2.read_message(ws2.receive_bytes())
        ws2.send_bytes(initiator2.encrypt(_make_hello_frame_bytes()))
        ack_pt2 = initiator2.decrypt(ws2.receive_bytes())

    ack_payload2 = json.loads(ack_pt2)["payload"]
    assert ack_payload2["agent_id"] == first_agent_id
    assert db_session.query(Agent).filter_by(status="pending").count() == baseline_pending + 1


def test_enroll_releases_pending_lock_on_exception(db_session, ws_client, monkeypatch):
    """Regression test for fix round 2: the pending-enrollment Redis lock
    acquired in the new-agent path must be released even if an exception
    (e.g., a race-condition IntegrityError from duplicate device_pk) occurs
    between acquire_pending_enrollment_lock() and db.commit().

    Without the try/finally wrapper around that region, the lock sits held
    for its full 5s TTL on every such failure, wrongly blocking unrelated new
    enrollments for that duration. This test verifies the lock is actually
    released by successfully enrolling a *different* device immediately after
    an enroll attempt that raises an exception."""
    from sqlalchemy.exc import IntegrityError

    _, server_pub = get_server_static_keypair()
    agent_priv_1 = secrets.token_bytes(32)
    agent_priv_2 = secrets.token_bytes(32)

    from app.services import agent_registry

    original_create_pending = agent_registry.create_pending_agent

    exception_raised = False

    def mock_create_pending_raises(*args, **kwargs):
        nonlocal exception_raised
        exception_raised = True
        # Simulate a same-device_pk race that slips past the `existing is
        # None` check (that read happens before lock acquisition) — the
        # db.flush() in the real create_pending_agent will raise IntegrityError
        # on device_pk unique constraint violation.
        raise IntegrityError("Duplicate device_pk", orig="Duplicate", params={})

    # First connection: monkeypatch create_pending_agent to raise, simulating
    # a race. The lock must be released even though the exception is raised
    # before db.commit().
    monkeypatch.setattr(agent_registry, "create_pending_agent", mock_create_pending_raises)

    # The exception will propagate and close the WebSocket connection. We
    # can't directly catch it, but we just need the connection attempt to
    # happen and fail — the important thing is that the finally block in
    # enroll_stream still runs and releases the lock.
    try:
        with ws_client.websocket_connect("/api/v1/agents/enroll") as ws:
            initiator = TestNoiseInitiator(agent_priv_1, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            ws.send_bytes(initiator.encrypt(_make_hello_frame_bytes()))
            # The handler will close the connection due to IntegrityError,
            # causing receive_bytes to raise. We ignore it.
            try:
                ws.receive_bytes()
            except Exception:
                pass
    except Exception:
        # Connection closed due to exception in handler.
        pass

    assert exception_raised, "Mock should have been called"

    # Restore the real create_pending_agent for the second connection.
    monkeypatch.setattr(agent_registry, "create_pending_agent", original_create_pending)

    # Second connection: a *different* device enrolling immediately after.
    # If the lock was leaked (held for its full 5s TTL), this would be
    # rejected with code=1013 (rate limited / pending cap). Instead, it must
    # succeed because the lock was released via the finally block.
    with ws_client.websocket_connect("/api/v1/agents/enroll") as ws2:
        initiator2 = TestNoiseInitiator(agent_priv_2, server_pub)
        ws2.send_bytes(initiator2.write_message())
        initiator2.read_message(ws2.receive_bytes())
        ws2.send_bytes(initiator2.encrypt(_make_hello_frame_bytes()))

        ack_ct = ws2.receive_bytes()
        ack_pt = initiator2.decrypt(ack_ct)

    ack = json.loads(ack_pt)
    assert ack["type"] == "hello.ack"
    assert "pairing_code" in ack["payload"]
    assert "agent_id" in ack["payload"]

    # Verify the second device actually created a pending agent.
    from app.core.agent_crypto import _public_from_private

    device_pk_hex_2 = _public_from_private(agent_priv_2).hex()
    agent = db_session.query(Agent).filter_by(device_pk=device_pk_hex_2).one()
    assert agent.status == "pending"
