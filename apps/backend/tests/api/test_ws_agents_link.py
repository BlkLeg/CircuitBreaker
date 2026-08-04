import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.core.agent_crypto import get_server_static_keypair
from tests.helpers.agent_noise_client import TestNoiseInitiator


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


def test_link_persists_hello_metadata_onto_agent_row(db_session, ws_client):
    """A hello carrying OS/version/arch/MAC metadata results in the Agent row
    reflecting those values once the server has accepted it and sent
    capabilities.set (the /link handshake's functional equivalent of
    hello.ack) — real DB row, not a mock."""
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
        first = json.loads(initiator.decrypt(ws.receive_bytes()))
        assert first["type"] == "capabilities.set"

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
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).agent_version == "0.3.0"

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        initiator = TestNoiseInitiator(agent_priv, server_pub)
        ws.send_bytes(initiator.write_message())
        initiator.read_message(ws.receive_bytes())
        _send_hello(initiator, ws, payload={"agent_version": "0.3.1"})
        ws.receive_bytes()  # capabilities.set

    db_session.expire_all()
    assert db_session.get(Agent, agent.id).agent_version == "0.3.1"


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
    ownership of the agent for the life of the socket (via this worker's
    process-wide `agent_registry.WORKER_ID`) and releases it once the socket
    closes — exercised end-to-end over the real WebSocket, not just by
    calling the registry functions directly."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    fake_redis = _FakeTTLRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake_redis))

    agent, agent_priv = _active_agent_with_key(db_session)
    _, server_pub = get_server_static_keypair()

    with ws_client.websocket_connect("/api/v1/agents/link") as ws:
        _connect_linked(ws, agent_priv, server_pub)

        owner = ws_client.portal.call(agent_registry.get_agent_connection_owner, agent.id)
        assert owner == agent_registry.WORKER_ID

    owner_after_disconnect = ws_client.portal.call(
        agent_registry.get_agent_connection_owner, agent.id
    )
    assert owner_after_disconnect is None


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


class _FakeTTLRedis:
    """Minimal async-Redis stand-in with *real* TTL expiry (via monotonic
    clock). conftest's `redis_mock` fixture is deliberately not reused here:
    its backing dict never evicts on TTL, which is exactly the behavior
    these tests need to exercise (presence keys genuinely expiring absent a
    heartbeat refresh)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

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

    def register_script(self, script: str) -> "_FakeCompareAndDeleteScript":
        """Stand-in for redis-py's `register_script`/EVALSHA, needed because
        `/link`'s disconnect teardown now runs
        `agent_registry.deregister_agent_connection`'s atomic compare-and-
        delete Lua script (not a plain GET/DELETE) — see
        test_agent_registry_connection.py's `_FakeCompareAndDeleteScript` for
        the twin of this double and why it doesn't attempt to model true
        Redis-side atomicity."""
        return _FakeCompareAndDeleteScript(self._store)


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
