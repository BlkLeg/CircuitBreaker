import asyncio
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.agent_crypto import ServerKeyRotationState, get_server_static_keypair
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


def _send_hello(initiator, ws, *, ts=None, payload=None) -> None:
    frame = {
        "v": 1,
        "type": "hello",
        "seq": 0,
        "ts": (ts or datetime.now(UTC)).isoformat(),
        "payload": payload or {},
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


def test_link_sends_hello_ack_then_capabilities_set_on_connect(db_session, ws_client):
    """The real Go agent (`internal/link/link.go`) only fires `OnConnected` —
    which resets reconnect backoff and gates link success (Task 4) — on an
    accepted `hello.ack` frame; it never applies capabilities from anything
    else at connect time. So `/link` must send a genuine `hello.ack` first
    (accepted, this agent's id, and — per the durable-delivery guarantee
    documented on `HelloAckPayload` — the complete current grant set),
    immediately followed by the existing `capabilities.set` push that
    actually drives the Go agent's `OnCapabilitiesSet` callback today."""
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)

        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert ack["type"] == "hello.ack"
        assert ack["seq"] == 0
        assert ack["payload"]["accepted"] is True
        assert ack["payload"]["agent_id"] == agent.id
        assert ack["payload"]["capabilities"]["host_telemetry"] is True
        assert "server_time" in ack["payload"]

        second = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert second["type"] == "capabilities.set"
        assert second["seq"] == 1
        assert second["payload"]["host_telemetry"] is True


def test_link_persists_hello_metadata_onto_agent_row(db_session, ws_client):
    """A hello carrying OS/version/arch/MAC metadata results in the Agent row
    reflecting those values once the server has accepted it and sent
    hello.ack/capabilities.set — real DB row, not a mock."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    assert agent.os is None
    assert agent.agent_version is None
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(
            initiator,
            ws,
            payload={
                "os": "linux",
                "os_version": "6.8.0-ubuntu",
                "arch": "amd64",
                "agent_version": "0.3.1",
                "primary_macs": ["aa:bb:cc:dd:ee:ff"],
            },
        )
        ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert ack["type"] == "hello.ack"
        second = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert second["type"] == "capabilities.set"

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.os == "linux"
    assert refreshed.os_version == "6.8.0-ubuntu"
    assert refreshed.arch == "amd64"
    assert refreshed.agent_version == "0.3.1"
    assert refreshed.primary_macs == ["aa:bb:cc:dd:ee:ff"]


def test_link_explicit_empty_primary_macs_blanks_stored_value(db_session, ws_client):
    """A hello that explicitly sends `"primary_macs": []` (field genuinely
    present in the payload, e.g. the device now has zero up network
    interfaces) must overwrite a previously-stored non-empty MAC list —
    presence, not truthiness, gates the update."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as setup_db:
        row = setup_db.get(Agent, agent.id)
        row.primary_macs = ["aa:bb:cc:dd:ee:ff"]
        setup_db.commit()

    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"primary_macs": []})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).primary_macs == []


def test_link_omitted_primary_macs_leaves_stored_value_untouched(db_session, ws_client):
    """A hello that omits `primary_macs` entirely (an old-shaped agent, or
    today's real hellos that don't report it) must leave the previously
    stored MAC list alone — distinct from explicitly sending `[]`."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as setup_db:
        row = setup_db.get(Agent, agent.id)
        row.primary_macs = ["aa:bb:cc:dd:ee:ff"]
        setup_db.commit()

    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.2"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).primary_macs == ["aa:bb:cc:dd:ee:ff"]


def test_link_hello_metadata_updates_across_reconnects(db_session, ws_client):
    """The row tracks the *latest* reported version across separate link
    sessions — an agent that self-updates between connects must not leave
    its row pinned to the version it enrolled with."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.0"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).agent_version == "0.3.0"

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.1"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).agent_version == "0.3.1"


def test_link_version_changed_fires_only_on_reconnect_at_target_version(db_session, ws_client):
    """Task 24: `version_changed` must never fire at update-request time (that
    transition is `update_queued`, recorded by api/agents.py:post_update) —
    only once a later `/link` reconnect's hello reports the agent actually
    running `pending_update_version`. A reconnect that reports some *other*
    version (the agent hasn't updated yet) must not record it."""
    from app.db.models import Agent, AgentEvent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as setup_db:
        row = setup_db.get(Agent, agent.id)
        row.agent_version = "0.3.0"
        row.pending_update_version = "0.3.1"  # set by POST /update, simulated directly here
        setup_db.commit()

    _, server_pub = get_server_static_keypair()

    def _event_types():
        db_session.expire_all()
        return [
            e.event_type
            for e in db_session.query(AgentEvent)
            .filter_by(agent_id=agent.id)
            .order_by(AgentEvent.id)
        ]

    # First reconnect: still the old version (update queued but not yet
    # applied) — must not record version_changed.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.0"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    assert "version_changed" not in _event_types()
    db_session.expire_all()
    assert db_session.get(Agent, agent.id).pending_update_version == "0.3.1"

    # Second reconnect: the new binary, reporting the target version — this
    # is the one and only point version_changed may fire.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.1"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    types = _event_types()
    assert types.count("version_changed") == 1
    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="version_changed")
        .one()
    )
    assert event.detail == {"version": "0.3.1"}

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.agent_version == "0.3.1"
    assert refreshed.pending_update_version is None


def test_link_reconnect_without_pending_update_never_records_version_changed(db_session, ws_client):
    """An agent with no update queued (`pending_update_version` is None, the
    common case) must never record version_changed no matter what version its
    hello reports — there's nothing to compare against."""
    from app.db.models import AgentEvent

    agent, agent_priv = _active_agent_with_key(db_session)
    assert agent.pending_update_version is None
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.4.0"})
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "version_changed" not in types


def test_link_empty_hello_payload_does_not_blank_existing_metadata(db_session, ws_client):
    """An old-shaped/empty hello (every HelloPayload field defaults to None
    or []) must not erase metadata a prior hello or enrollment already
    recorded — only fields the hello actually reports get overwritten."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as setup_db:
        fresh = setup_db.get(Agent, agent.id)
        fresh.os = "linux"
        fresh.agent_version = "0.2.0"
        setup_db.commit()

    _, server_pub = get_server_static_keypair()
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)  # empty payload, like today's real hellos
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.os == "linux"
    assert refreshed.agent_version == "0.2.0"


def test_link_records_connected_then_disconnected_events(db_session, ws_client):
    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        ws.receive_bytes()  # hello.ack
        ws.receive_bytes()  # capabilities.set

    from app.db.models import AgentEvent

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "connected" in types
    assert "disconnected" in types


def test_link_registers_connection_owner_on_connect_and_deregisters_on_disconnect(
    db_session, ws_client, monkeypatch
):
    """Task 8: /link's connect path claims cross-worker control-routing
    ownership of the agent for the life of the socket and releases it once
    the socket closes — exercised end-to-end over the real WebSocket, not
    just by calling the registry functions directly.

    The registered value is scoped to *this connection*, not just this
    worker process — see test_link_second_connections_teardown_does_not_
    evict_still_live_first_connection below for why a bare process-wide
    `agent_registry.WORKER_ID` value isn't enough — but it's still prefixed
    with WORKER_ID for operational traceability (which worker owns a given
    live connection)."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

        owner = ws_client.portal.call(agent_registry.get_agent_connection_owner, agent.id)
        assert owner is not None
        assert owner.startswith(agent_registry.WORKER_ID)

    owner_after_disconnect = ws_client.portal.call(
        agent_registry.get_agent_connection_owner, agent.id
    )
    assert owner_after_disconnect is None


def test_link_stale_second_connections_teardown_does_not_evict_a_refreshed_first_connection(
    db_session, ws_client, monkeypatch
):
    """cb-agent uninstall's one-shot notifier (internal/link/link.go's
    `Uninstall`) deliberately opens a *second* /link connection for an
    agent whose persistent daemon connection is often still live —
    `runUninstall` notifies before it stops the service (cmd/cb-agent/
    main.go's `notifyUninstallBestEffort` runs before `performUninstall`).
    Registering is last-write-wins by design (whichever connection most
    recently registered is control-routing's current target — see
    `register_agent_connection`'s docstring), so connection B's connect
    legitimately overwrites connection A's entry; that part isn't the bug.

    The bug is in what happens next: if connection A sends a heartbeat
    (refreshing its own entry back on top of B's) *before* B disconnects,
    B's teardown must not blindly delete whatever is currently registered —
    only an entry that is still actually B's own. Scoped only to this
    worker process's bare `agent_registry.WORKER_ID` (identical for both
    connections), `deregister_agent_connection`'s compare-and-delete
    couldn't tell A's freshly-refreshed entry from B's stale one and would
    delete it anyway — evicting a connection that never disconnected and
    breaking control-frame routing to it until its next heartbeat happens
    to re-register."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws_a:
        initiator_a = _connect_linked(ws_a, agent_priv, server_pub)

        # Second, short-lived connection for the SAME agent — mirrors the
        # uninstall notifier connecting while the daemon's own persistent
        # connection (ws_a) is still open. Overwrites the registry entry;
        # expected, not yet the bug.
        with ws_client.websocket_connect("/api/v1/agents/link") as ws_b:
            _connect_linked(ws_b, agent_priv, server_pub)

            # Connection A retakes ownership — e.g. a heartbeat lands —
            # *while B is still connected*, racing B's still-pending teardown.
            _send_frame(initiator_a, ws_a, seq=1)
            time.sleep(0.3)
            owner_after_a_refreshes = ws_client.portal.call(
                agent_registry.get_agent_connection_owner, agent.id
            )
            assert owner_after_a_refreshes is not None

        # Connection B's teardown just ran, racing after A's refresh above.
        # Connection A is still open (never disconnected) and must still own
        # the registry entry, unchanged.
        owner_after_b_closes = ws_client.portal.call(
            agent_registry.get_agent_connection_owner, agent.id
        )
        assert owner_after_b_closes == owner_after_a_refreshes


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


def _connect_linked(ws, agent_priv, server_pub):
    """Handshake + hello + drain the initial hello.ack and capabilities.set.

    Real hello.ack (accepted, agent_id, capabilities, server_time) is sent
    first — it's what the real Go agent's `case frame.TypeHelloAck` gates
    `OnConnected`/backoff-reset on (see `link.go`) — followed immediately by
    a `capabilities.set` carrying the same grants, which is what actually
    drives the Go agent's `OnCapabilitiesSet` application today.
    """
    initiator = TestNoiseInitiator(agent_priv, server_pub)
    ws.send_bytes(initiator.write_message())
    initiator.read_message(ws.receive_bytes())
    _send_hello(initiator, ws)
    ack = json.loads(initiator.decrypt(ws.receive_bytes()))
    assert ack["type"] == "hello.ack"
    assert ack["payload"]["accepted"] is True
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


class _FakeTTLRedis:
    """Minimal async-Redis stand-in with *real* TTL expiry (via monotonic
    clock). conftest's `redis_mock` fixture is deliberately not reused here:
    its backing dict never evicts on TTL, which is exactly the behavior
    these tests need to exercise (presence keys genuinely expiring absent a
    heartbeat refresh).

    Also carries pub/sub (`publish`/`pubsub`, Task 9), matching
    test_agent_registry_connection.py's `_FakeRedisBus`/`_FakeRedisClient`
    split but as one class: every test in this file monkeypatches
    `app.core.redis.get_redis` to return a single instance of this double,
    so link_stream's own `subscribe` and a test's direct
    `publish_agent_control_frame` call naturally share the same in-memory
    channel registry below — standing in for the one real Redis instance a
    socket-holding worker and a REST-handling worker would both talk to.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._channels: dict[str, list[asyncio.Queue]] = {}

    async def setex(self, key: str, ttl: float, value: str) -> bool:
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    async def exists(self, key: str) -> int:
        entry = self._store.get(key)
        if entry is None:
            return 0
        expires_at, _ = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return 0
        return 1

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    async def incr(self, key: str) -> int:
        """Task 21: backs check_and_record_ws_attempt's per-IP/global
        counters. Stores the running count alongside a far-future
        placeholder expiry until `expire()` sets the real one, mirroring
        real Redis's INCR-creates-a-persistent-key-until-EXPIRE semantics."""
        entry = self._store.get(key)
        if entry is not None and time.monotonic() >= entry[0]:
            entry = None
        current = int(entry[1]) if entry is not None else 0
        current += 1
        expires_at = entry[0] if entry is not None else float("inf")
        self._store[key] = (expires_at, str(current))
        return current

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Backs `agent_registry.bulk_presence` (Task 28's
        `broadcast_server_key_rotate` calls it to find which agents are
        online before pushing) — a plain per-key `get` loop, since this
        fake's dict-backed store has no real MGET to speed up."""
        return [await self.get(key) for key in keys]

    async def expire(self, key: str, ttl: float, nx: bool = False) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return False
        expires_at, value = entry
        if nx and expires_at != float("inf"):
            return False
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    def register_script(self, script: str) -> "_FakeCompareAndDeleteScript":
        """Stand-in for redis-py's `register_script`/EVALSHA, needed because
        `/link`'s disconnect teardown now runs
        `agent_registry.deregister_agent_connection`'s atomic compare-and-
        delete Lua script (not a plain GET/DELETE) — see
        test_agent_registry_connection.py's `_FakeCompareAndDeleteScript` for
        the twin of this double and why it doesn't attempt to model true
        Redis-side atomicity."""
        return _FakeCompareAndDeleteScript(self._store)

    async def publish(self, channel: str, message: str) -> int:
        subs = self._channels.get(channel, [])
        for q in subs:
            q.put_nowait(message)
        return len(subs)

    def pubsub(self) -> "_FakePubSubSession":
        return _FakePubSubSession(self)


class _FakePubSubSession:
    """Stand-in for redis-py's `Redis.pubsub()` session — subscribe/
    get_message/unsubscribe/aclose only, matching what
    `agent_registry.claim_agent_control_frames` actually calls. Twin of
    test_agent_registry_connection.py's `_FakePubSub`, backed by
    `_FakeTTLRedis._channels` instead of a separate bus object."""

    def __init__(self, redis: "_FakeTTLRedis") -> None:
        self._redis = redis
        self._queue: asyncio.Queue = asyncio.Queue()
        self._subscribed: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self._subscribed.append(channel)
        self._redis._channels.setdefault(channel, []).append(self._queue)

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,  # noqa: ASYNC109
    ):
        try:
            data = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        return {"type": "message", "data": data}

    async def unsubscribe(self) -> None:
        for channel in self._subscribed:
            subs = self._redis._channels.get(channel, [])
            if self._queue in subs:
                subs.remove(self._queue)
        self._subscribed = []

    async def aclose(self) -> None:
        pass


class _FakeCompareAndDeleteScript:
    def __init__(self, store: dict[str, tuple[float, str]]) -> None:
        self._store = store

    async def __call__(self, keys: list[str], args: list[str]) -> int:
        key = keys[0]
        expected = args[0]
        entry = self._store.get(key)
        if entry is None:
            return 0
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return 0
        if value != expected:
            return 0
        del self._store[key]
        return 1


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


def _receive_bytes_with_timeout(ws, timeout: float = 2.0) -> bytes:
    """`WebSocketTestSession.receive` (what `ws.receive_bytes()` calls) has no
    built-in timeout — it blocks forever if nothing arrives. Run it on a
    worker thread so a genuine delivery bug in the code under test surfaces
    as a test failure within `timeout` rather than hanging the suite. Doesn't
    join the thread on timeout (`shutdown(wait=False)`) since a hung
    `receive_bytes()` call would never return to let it — an acceptable
    thread leak on the failure path only."""
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(ws.receive_bytes)
    try:
        return future.result(timeout=timeout)
    finally:
        pool.shutdown(wait=False)


def test_link_delivers_capabilities_set_published_by_another_worker(
    db_session, ws_client, monkeypatch
):
    """Task 9 end-to-end proof. `agent_registry.publish_agent_control_frame`
    is exactly what `PUT /agents/{id}/capabilities` (agents.py's
    `put_capabilities`) calls after committing a grant change — calling it
    directly here stands in for that REST request landing on a *different*
    worker process than the one holding this agent's live /link socket (the
    two would share one real Redis instance; `_FakeTTLRedis` plays that role
    for both sides here). What's under test is link_stream's own claim-and-
    deliver wiring, not the registry primitives themselves — those already
    have dedicated coverage in test_agent_registry_connection.py without any
    real /link connection involved at all."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before publishing — otherwise the publish could
        # race ahead of the subscribe and never be delivered at all (ordinary
        # Redis pub/sub fire-and-forget semantics), mirroring
        # test_agent_registry_connection.py's identical precaution.
        time.sleep(0.1)

        published = ws_client.portal.call(
            agent_registry.publish_agent_control_frame,
            agent.id,
            {"type": "capabilities.set", "payload": {"remote_probe": True}},
        )
        assert published is True

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "capabilities.set"
        assert frame["payload"] == {"remote_probe": True}


def test_link_delivers_disconnect_published_by_another_worker(db_session, ws_client, monkeypatch):
    """Companion to the capabilities.set proof above, for `disconnect`. No
    REST/service-layer call site publishes this frame type yet — wiring
    revoke/reject to it is Task 10's job — but link_stream's claim-and-
    deliver path is generic over frame type (`_control_frame_bytes` doesn't
    special-case capabilities.set vs. anything else), so delivery already
    works correctly ahead of Task 10 adding the trigger."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)

        published = ws_client.portal.call(
            agent_registry.publish_agent_control_frame,
            agent.id,
            {"type": "disconnect", "payload": {"reason": "revoked"}},
        )
        assert published is True

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "disconnect"
        assert frame["payload"] == {"reason": "revoked"}


def _login_admin(ws_client, factories):
    """Creates and logs in an admin user through `ws_client` itself (not the
    separate async `client` fixture) so the session cookie lands in
    `ws_client`'s own cookie jar and every subsequent `ws_client.post(...)`
    in the same test carries it automatically — same reasoning as
    test_ws_agents_stream.py's `_login_viewer`. `factories` (backed by
    `db_session`) is safe to combine with `ws_client` here because
    `ws_client`'s own `get_db` override already points at that same
    `db_session` instance (see conftest.py's `ws_client` fixture) — unlike
    the WS /link and /enroll handlers below, which open their own
    `SessionLocal()` and therefore need a real committed row instead."""
    admin = factories.user(role="admin", password="TestPassword123!")
    resp = ws_client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": "TestPassword123!"}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    csrf = resp.cookies.get("cb_csrf", "test-csrf-token")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


def test_revoke_delivers_immediate_disconnect_over_live_link(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Task 10 end-to-end proof, genuinely exercising the real `POST
    /agents/{id}/revoke` REST endpoint (not `publish_agent_control_frame`
    called directly, unlike the companion proof above which stands in for a
    cross-worker publish) — the trigger this task adds on top of Task 9's
    already-proven generic claim-and-deliver delivery mechanics. Asserts both
    halves of the required behavior: the DB status flip AND the immediate
    disconnect frame landing on the live socket, without waiting for the
    poll-based fallback."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    headers = _login_admin(ws_client, factories)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before the REST call publishes — mirrors the
        # same precaution in the companion cross-worker-publish proof above.
        time.sleep(0.1)

        resp = ws_client.post(
            f"/api/v1/agents/{agent.id}/revoke",
            json={"reason": "compromised"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "disconnect"
        assert frame["payload"] == {"reason": "compromised"}

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.status == "revoked"
    assert refreshed.revoke_reason == "compromised"


def test_reject_publishes_disconnect_control_frame(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Reject's counterpart to the revoke proof above. A rejected agent is
    never expected to hold a live /link socket in normal operation (only a
    still-pending device can be rejected, and pending devices never reach
    /link — see enroll_stream's active/pending/revoked/rejected branching),
    so this asserts the publish call itself lands on the agent's control
    channel — the same level of proof Task 9's own registry-only tests use
    in test_agent_registry_connection.py — rather than a live socket
    delivery, which would require contradicting that invariant."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent
    from app.db.session import SessionLocal

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, _agent_priv = _active_agent_with_key(db_session)
    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.status = "pending"
        db.commit()

    headers = _login_admin(ws_client, factories)

    # Subscribe to the agent's control channel first (mirrors
    # claim_agent_control_frames' own subscribe-then-publish ordering
    # requirement) so the reject endpoint's publish is observed directly,
    # without a live /link connection in the loop.
    pubsub = fake_redis.pubsub()
    ws_client.portal.call(pubsub.subscribe, f"cb:agents:control:{agent.id}")

    resp = ws_client.post(f"/api/v1/agents/{agent.id}/reject", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    msg = ws_client.portal.call(pubsub.get_message, True, 2.0)
    assert msg is not None and msg["type"] == "message"
    frame = json.loads(msg["data"])
    assert frame == {"type": "disconnect", "payload": {"reason": "rejected"}}

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.status == "rejected"


def test_capabilities_put_delivers_immediate_push_over_live_link(
    db_session, ws_client, monkeypatch, factories, app_cfg
):
    """Task 11's first half, end-to-end: the real `PUT
    /agents/{id}/capabilities` REST endpoint (not
    `publish_agent_control_frame` called directly, unlike the companion Task
    9 proof `test_link_delivers_capabilities_set_published_by_another_worker`
    above) delivers a `capabilities.set` push to a live /link socket
    immediately — without waiting for the poll-based fallback or a
    reconnect. Mirrors `test_revoke_delivers_immediate_disconnect_over_live_link`'s
    shape for the capabilities-grant trigger instead of revoke/reject."""
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    headers = _login_admin(ws_client, factories)

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Give link_stream's background control-frame listener a moment to
        # actually subscribe before the REST call publishes — mirrors the
        # same precaution in the companion cross-worker-publish proof above.
        time.sleep(0.1)

        resp = ws_client.put(
            f"/api/v1/agents/{agent.id}/capabilities",
            json={"capabilities": {"remote_probe": True}},
            headers=headers,
        )
        assert resp.status_code == 200

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        frame = json.loads(initiator.decrypt(raw))
        assert frame["type"] == "capabilities.set"
        # The full, authoritative grant set (host_telemetry from
        # _active_agent_with_key's seed data plus the newly-granted
        # remote_probe) — not just the one capability this request named.
        assert frame["payload"] == {"host_telemetry": True, "remote_probe": True}


def test_link_hello_ack_resends_complete_grants_regardless_of_prior_push_success(
    db_session, ws_client
):
    """Task 11's durable-delivery half: the DB stays authoritative, so a
    fresh `hello.ack` on reconnect always carries the *complete* current
    grant set — even when the grant change that produced it was never pushed
    to any live socket at all (the strongest form of "a missed push",
    stronger than a failed `publish_agent_control_frame` call, which Task 9
    already proves never fails the request — see
    test_agents_api.py::test_capabilities_put_succeeds_even_when_control_frame_publish_fails).
    No connection was live when the grant changed here, so there was no
    push to miss; the next hello.ack must still reflect it correctly."""
    from app.db.session import SessionLocal
    from app.services import agent_registry

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        first_ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert first_ack["payload"]["capabilities"] == {"host_telemetry": True}

    # Change the grant set with no /link socket connected at all — nothing
    # to push to, and nothing that could have "failed" to push either.
    with SessionLocal() as db:
        agent_registry.set_capability_grants(
            db, agent.id, {"host_telemetry": False, "remote_probe": True}, actor_user_id=None
        )
        db.commit()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws)
        second_ack = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert second_ack["type"] == "hello.ack"
        assert second_ack["payload"]["capabilities"] == {
            "host_telemetry": False,
            "remote_probe": True,
        }


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


# ── Task 27: device-key rotation, end-to-end over the real /link socket ────


def _new_device_keypair() -> tuple[bytes, str]:
    """(private_bytes, public_hex) for a fresh X25519 device identity."""
    from cryptography.hazmat.primitives.asymmetric import x25519

    priv = secrets.token_bytes(32)
    pub = x25519.X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes_raw()
    return priv, pub.hex()


def test_link_key_rotate_start_persists_pending_key_and_acks(db_session, ws_client, monkeypatch):
    """Starting a rotation over the live, already-authenticated link persists
    the pending key + expiry server-side and acknowledges it back to the
    agent over the same key.rotate frame type — the ack the agent's own
    atomic device.key swap is gated on."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent, AgentEvent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        # Let link_stream's background control-frame listener actually
        # subscribe before the rotation request publishes its ack — same
        # precaution as the cross-worker-delivery proofs above.
        time.sleep(0.1)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )

        raw = _receive_bytes_with_timeout(ws, timeout=2.0)
        ack = json.loads(initiator.decrypt(raw))
        assert ack["type"] == "key.rotate"
        assert ack["payload"]["kind"] == "device"
        assert ack["payload"]["successor_pk"] == successor_hex
        assert "expiry" in ack["payload"]

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk == successor_hex
    assert refreshed.pending_device_pk_expiry is not None

    event = (
        db_session.query(AgentEvent)
        .filter_by(agent_id=agent.id, event_type="key_rotation_started")
        .one()
    )
    assert event.detail["expires_at"]


def test_link_accepts_current_key_throughout_the_transition_window(
    db_session, ws_client, monkeypatch
):
    """Once a rotation has started, the still-current (old) key must keep
    working for the whole transition window — an agent that hasn't switched
    over to its successor yet is not locked out."""
    from unittest.mock import AsyncMock

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)
        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _receive_bytes_with_timeout(ws, timeout=2.0)  # drain the ack

    # A fresh connection with the *old* key still succeeds — no promotion has
    # happened yet, so the current identity is unchanged.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

    from app.db.models import Agent

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == agent.device_pk
    assert refreshed.pending_device_pk == successor_hex


def test_link_promotes_pending_key_on_first_successful_link_and_retires_old_key(
    db_session, ws_client, monkeypatch
):
    """The full rotation lifecycle end-to-end: starting a rotation, the old
    key still working, the new (still-pending) key's first successful link
    promoting it (clearing the pending state and recording `key_rotated`),
    and the old key being refused afterward."""
    from unittest.mock import AsyncMock

    from app.db.models import Agent, AgentEvent

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)
        time.sleep(0.1)
        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": successor_hex,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _receive_bytes_with_timeout(ws, timeout=2.0)  # drain the ack

    # First successful link under the new (pending) key promotes it.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, successor_priv, server_pub)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == successor_hex
    assert refreshed.pending_device_pk is None
    assert refreshed.pending_device_pk_expiry is None

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "key_rotated" in types

    # The old key is retired — no longer a recognized identity for this agent.
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(agent_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            _send_hello(initiator, ws)
            ws.receive_bytes()  # never arrives — closes 1008 first


def test_link_refuses_pending_key_past_its_expiry(db_session, ws_client):
    """A pending key presented after its transition window has lapsed is
    rejected exactly like an unrecognized key — the rotation is never
    silently promoted late."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.pending_device_pk = successor_hex
        row.pending_device_pk_expiry = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/api/v1/agents/link") as ws:
            initiator = TestNoiseInitiator(successor_priv, server_pub)
            ws.send_bytes(initiator.write_message())
            initiator.read_message(ws.receive_bytes())
            _send_hello(initiator, ws)
            ws.receive_bytes()  # never arrives — closes 1008 first


def test_link_clears_expired_pending_rotation_when_current_key_reconnects(db_session, ws_client):
    """No scheduled sweep clears a stale pending rotation (unlike e.g.
    expire_stale_pending_agents for pending *enrollments*) — the agent's own
    next reconnect on its unchanged current key is what notices and clears
    it, recording `key_rotation_expired`."""
    from app.db.models import Agent, AgentEvent
    from app.db.session import SessionLocal

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    _successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row = db.get(Agent, agent.id)
        row.pending_device_pk = successor_hex
        row.pending_device_pk_expiry = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.device_pk == agent.device_pk
    assert refreshed.pending_device_pk is None
    assert refreshed.pending_device_pk_expiry is None

    types = [
        e.event_type
        for e in db_session.query(AgentEvent).filter_by(agent_id=agent.id).order_by(AgentEvent.id)
    ]
    assert "key_rotation_expired" in types


# ── Fix round 1 (review finding C1): malformed successor_pk over the live,
# already-authenticated /link socket must not tear down the connection ─────


def test_link_survives_malformed_key_rotate_successor_pk(db_session, ws_client):
    """Reviewer repro for C1: `{"kind":"device","successor_pk":"zz"*32,...}`
    sent over an authenticated /link socket used to raise an unhandled
    ValueError out of `bytes.fromhex(successor_pk)` deep in
    `start_device_key_rotation`, which propagated out of `dispatch_frame`
    and killed the connection from a single malformed frame. It must instead
    be rejected at frame-decode time and leave the session alive — proven
    here by sending a well-formed frame afterward on the same connection and
    getting a normal response."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": "zz" * 32,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        # The connection must still be alive: a subsequent well-formed frame
        # is accepted and processed normally, and — critically — no
        # exception propagates out of this `with` block from the frame sent
        # above.
        _send_frame(initiator, ws, type="heartbeat", seq=1)
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk is None


def test_link_survives_key_rotate_successor_pk_wrong_length(db_session, ws_client):
    """Same finding, a different malformed shape: valid hex but the wrong
    length (not a 32-byte X25519 key) must also be rejected rather than
    reaching `bytes.fromhex`/the `pending_device_pk` column unchecked."""
    from app.db.models import Agent

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = _connect_linked(ws, agent_priv, server_pub)

        _send_frame(
            initiator,
            ws,
            type="key.rotate",
            seq=0,
            payload={
                "kind": "device",
                "successor_pk": "ab" * 31,
                "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        _send_frame(initiator, ws, type="heartbeat", seq=1)
        time.sleep(0.3)

    db_session.expire_all()
    refreshed = db_session.get(Agent, agent.id)
    assert refreshed.pending_device_pk is None


# ── Fix round 1 (review finding C2): duplicate pending-key collision must
# not be able to reach a live handshake and raise MultipleResultsFound ─────


def test_link_handshake_survives_duplicate_pending_device_pk(db_session, ws_client):
    """Reviewer repro for C2: two different agents ending up with the same
    `pending_device_pk` used to make `resolve_agent_for_handshake`'s
    `.scalar_one_or_none()` raise `MultipleResultsFound` the next time either
    device's successor key presented itself in a handshake. The primary fix
    is that `start_device_key_rotation` now refuses to create that duplicate
    in the first place (see tests/services/test_agent_registry_key_rotation.py);
    this test proves the read-path backstop by writing the duplicate
    directly and then performing a real handshake against it, which must
    succeed (rather than raise) and resolve deterministically to one agent."""
    from app.db.models import Agent
    from app.db.session import SessionLocal

    agent_a, _ = _active_agent_with_key(db_session)
    agent_b, _ = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()
    successor_priv, successor_hex = _new_device_keypair()

    with SessionLocal() as db:
        row_a = db.get(Agent, agent_a.id)
        row_a.pending_device_pk = successor_hex
        row_a.pending_device_pk_expiry = datetime.now(UTC) + timedelta(minutes=15)
        row_b = db.get(Agent, agent_b.id)
        row_b.pending_device_pk = successor_hex
        row_b.pending_device_pk_expiry = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()

    # Must not raise MultipleResultsFound — the handshake completes normally.
    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, successor_priv, server_pub)


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
