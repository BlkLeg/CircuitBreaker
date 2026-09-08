"""Shared test doubles for the test_ws_agents_link.py split family under
tests/api/.

Anything used by two or more of the split modules lives here and is
imported explicitly; a helper used by exactly one module lives in that
module instead. This file is not itself collected by pytest (its name
doesn't start with `test_`).
"""

import asyncio
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

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


def _send_frame(initiator, ws, *, v=1, type="heartbeat", seq, payload=None) -> None:
    frame = {
        "v": v,
        "type": type,
        "seq": seq,
        "ts": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    ws.send_bytes(initiator.encrypt(json.dumps(frame).encode()))


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
