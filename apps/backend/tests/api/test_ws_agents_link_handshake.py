"""The /link handshake: hello.ack then capabilities.set on connect, hello metadata
(OS/version/arch/MAC) persisted onto the Agent row across reconnects, the
version_changed event's exact firing point, connected/disconnected events,
cross-worker connection-owner registration, and a stale handshake timestamp.

Split out of the former tests/api/test_ws_agents_link.py.
"""

import json
import time
from datetime import UTC, datetime, timedelta

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
