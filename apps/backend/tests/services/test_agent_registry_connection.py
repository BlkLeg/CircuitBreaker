"""Task 8: cross-worker agent connection/control registry.

Covers `agent_registry.register_agent_connection` / `deregister_agent_connection`
/ `refresh_agent_connection` / `get_agent_connection_owner` (the Redis-backed
`agent_id -> worker_id` registry) and `publish_agent_control_frame` /
`claim_agent_control_frames` (the generic pub/sub delivery primitive), in
isolation from ws_agents.py's /link wiring — see test_ws_agents_link.py for
the end-to-end connect/disconnect coverage over the real WebSocket.
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.services import agent_registry as svc


class _FakeRedisBus:
    """Shared in-memory Redis double: a TTL-key store plus pub/sub, backing
    multiple independent client handles the way several OS processes would
    all connect to the one real Redis instance.

    Not the same double as conftest's `redis_mock` (no pub/sub, no real TTL
    eviction) or test_ws_agents_link.py's `_FakeTTLRedis` (no pub/sub) — this
    task specifically needs both a real-TTL key store *and* pub/sub in the
    same backing store, which neither existing double provides.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}
        self._channels: dict[str, list[asyncio.Queue]] = {}

    def client(self) -> "_FakeRedisClient":
        return _FakeRedisClient(self)


class _FakeRedisClient:
    def __init__(self, bus: _FakeRedisBus) -> None:
        self._bus = bus

    async def setex(self, key: str, ttl: float, value: str) -> bool:
        self._bus._store[key] = (time.monotonic() + ttl, value)
        return True

    async def set(self, key: str, value: str, nx: bool = False, ex: float | None = None) -> bool:
        """Backs acquire_pending_enrollment_lock's SET NX EX. Checks
        expiry-aware existence for `nx` the same way `get`/`exists` do below,
        so a key past its TTL is correctly treated as absent."""
        if nx and await self.exists(key):
            return False
        expires_at = time.monotonic() + ex if ex is not None else float("inf")
        self._bus._store[key] = (expires_at, value)
        return True

    async def get(self, key: str) -> str | None:
        entry = self._bus._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._bus._store[key]
            return None
        return value

    async def delete(self, key: str) -> int:
        return 1 if self._bus._store.pop(key, None) is not None else 0

    async def exists(self, key: str) -> int:
        return 1 if await self.get(key) is not None else 0

    async def publish(self, channel: str, message: str) -> int:
        subs = self._bus._channels.get(channel, [])
        for q in subs:
            q.put_nowait(message)
        return len(subs)

    def pubsub(self) -> "_FakePubSub":
        return _FakePubSub(self._bus)

    def register_script(self, script: str) -> "_FakeCompareAndDeleteScript":
        """Stand-in for redis-py's `register_script`/EVALSHA.

        Not a general Lua interpreter — this fake only understands the one
        script `agent_registry.deregister_agent_connection` actually
        registers (`_COMPARE_AND_DELETE_LUA`), and reimplements its exact
        semantics (get, compare, conditionally del — including honoring TTL
        expiry) directly in Python against the shared `_bus._store`. Good
        enough to prove the caller wires `register_script`/EVALSHA the same
        way `rate_limit_middleware.py` does and that the compare-and-delete
        behavior is correct; it cannot prove server-side atomicity, since
        that guarantee comes from real Redis executing the script in one
        step, not from anything a Python fake can model. See
        `test_deregister_leaves_entry_untouched_when_owned_by_a_different_worker`
        for why true concurrent interleaving isn't (and can't be) exercised
        here.
        """
        return _FakeCompareAndDeleteScript(self._bus)


class _FakeCompareAndDeleteScript:
    def __init__(self, bus: _FakeRedisBus) -> None:
        self._bus = bus

    async def __call__(self, keys: list[str], args: list[str]) -> int:
        key = keys[0]
        expected = args[0]
        entry = self._bus._store.get(key)
        if entry is None:
            return 0
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            del self._bus._store[key]
            return 0
        if value != expected:
            return 0
        del self._bus._store[key]
        return 1


class _FakePubSub:
    def __init__(self, bus: _FakeRedisBus) -> None:
        self._bus = bus
        self._queue: asyncio.Queue = asyncio.Queue()
        self._channels: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self._channels.append(channel)
        self._bus._channels.setdefault(channel, []).append(self._queue)

    # Mirrors redis-py's pubsub.get_message(timeout=...) signature.
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
        for channel in self._channels:
            subs = self._bus._channels.get(channel, [])
            if self._queue in subs:
                subs.remove(self._queue)
        self._channels = []

    async def aclose(self) -> None:
        pass


# ── registry: register / refresh / deregister / lookup ─────────────────────


@pytest.mark.asyncio
async def test_register_agent_connection_writes_ttl_key_with_worker_id(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    ok = await svc.register_agent_connection(5, worker_id="worker-A")

    assert ok is True
    redis_client.setex.assert_called_once()
    key, ttl, value = redis_client.setex.call_args[0]
    assert key == "agent:connection:5"
    assert ttl == 60
    assert value == "worker-A"


@pytest.mark.asyncio
async def test_register_agent_connection_returns_false_and_logs_when_redis_down(
    monkeypatch, caplog
):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    with caplog.at_level("WARNING"):
        ok = await svc.register_agent_connection(5, worker_id="worker-A")

    assert ok is False
    assert any("registry unavailable" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_refresh_agent_connection_resets_ttl(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    await svc.refresh_agent_connection(5, worker_id="worker-A")

    redis_client.setex.assert_called_once_with("agent:connection:5", 60, "worker-A")


@pytest.mark.asyncio
async def test_refresh_agent_connection_is_a_noop_when_redis_down(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    await svc.refresh_agent_connection(5, worker_id="worker-A")  # must not raise

    redis_client.setex.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent_connection_owner_returns_none_when_absent(monkeypatch):
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    assert await svc.get_agent_connection_owner(5) is None


@pytest.mark.asyncio
async def test_deregister_removes_entry_when_still_owned_by_this_worker(monkeypatch):
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    await svc.register_agent_connection(5, worker_id="worker-A")
    assert await svc.get_agent_connection_owner(5) == "worker-A"

    await svc.deregister_agent_connection(5, worker_id="worker-A")

    assert await svc.get_agent_connection_owner(5) is None


@pytest.mark.asyncio
async def test_deregister_leaves_entry_untouched_when_owned_by_a_different_worker(monkeypatch):
    """A stale worker's disconnect-path teardown must not clobber a newer
    connection's registry entry — the race this compare-and-delete guards
    against: the agent reconnects to worker B before worker A's own `finally`
    block gets to run its deregister call.

    This exercises the sequential (non-concurrent) case of the guard: by the
    time worker A's deregister runs, worker B's register has already fully
    landed, so `_FakeCompareAndDeleteScript` sees the "wrong" value and
    declines to delete — proving the compare-and-delete *logic* is correct.
    It does not, and cannot, prove the *atomicity* the Lua script buys over a
    GET-then-DELETE: this fake's coroutine bodies never actually suspend
    mid-method the way a real network round trip would, so there is no
    `await` point for `asyncio.gather`/interleaved tasks to land another
    write between a "GET" and a "DELETE" in the first place — the race the
    old two-round-trip implementation was vulnerable to simply cannot be
    reproduced against this in-memory double, atomic or not. Confidence that
    the fix is real comes from the implementation now issuing exactly one
    `register_script`/EVALSHA call (mirroring `rate_limit_middleware.py`'s
    already-relied-upon pattern for the same TOCTOU concern) rather than
    separate `get`/`delete` calls, not from a test that catches the race in
    the act.
    """
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    await svc.register_agent_connection(5, worker_id="worker-A")
    await svc.register_agent_connection(5, worker_id="worker-B")  # reconnect elsewhere

    await svc.deregister_agent_connection(5, worker_id="worker-A")  # worker A's stale teardown

    assert await svc.get_agent_connection_owner(5) == "worker-B"


@pytest.mark.asyncio
async def test_deregister_is_a_noop_when_redis_down(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    await svc.deregister_agent_connection(5, worker_id="worker-A")  # must not raise

    redis_client.get.assert_not_called()
    redis_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_connection_registry_ttl_expiry_removes_stale_entry(monkeypatch):
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))
    monkeypatch.setattr(svc, "_CONNECTION_TTL_SECONDS", 0.2)

    await svc.register_agent_connection(5, worker_id="worker-A")
    assert await svc.get_agent_connection_owner(5) == "worker-A"

    await asyncio.sleep(0.3)  # past the shrunk TTL, no refresh sent

    assert await svc.get_agent_connection_owner(5) is None


# ── delivery primitive: publish / claim ─────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_agent_control_frame_returns_false_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    delivered = await svc.publish_agent_control_frame(5, {"type": "ping"})

    assert delivered is False


@pytest.mark.asyncio
async def test_publish_agent_control_frame_publishes_json_to_agent_channel(monkeypatch):
    redis_client = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    delivered = await svc.publish_agent_control_frame(5, {"type": "ping", "seq": 3})

    assert delivered is True
    redis_client.publish.assert_called_once()
    channel, payload = redis_client.publish.call_args[0]
    assert channel == "cb:agents:control:5"
    import json

    assert json.loads(payload) == {"type": "ping", "seq": 3}


async def _first_frame(agen):
    async for frame in agen:
        return frame
    return None


@pytest.mark.asyncio
async def test_control_frame_published_for_agent_owned_by_worker_b_is_claimed_only_by_worker_b(
    monkeypatch,
):
    """The cross-worker routing proof: two simulated worker processes (A and
    B) both listen on the same agent's control channel via independent
    `claim_agent_control_frames` generators, backed by the same shared fake
    Redis (standing in for the one real Redis instance two OS processes would
    both talk to, per the task brief's confirmed test-double reading). Only
    worker B — the registered owner — ever observes the published frame."""
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    await svc.register_agent_connection(7, worker_id="worker-B")

    listen_a = svc.claim_agent_control_frames(7, worker_id="worker-A")
    listen_b = svc.claim_agent_control_frames(7, worker_id="worker-B")

    task_a = asyncio.create_task(asyncio.wait_for(_first_frame(listen_a), timeout=1.0))
    task_b = asyncio.create_task(asyncio.wait_for(_first_frame(listen_b), timeout=1.0))
    # Let both listener generators reach their subscribed, awaiting-a-message
    # state before publishing — otherwise the publish could race ahead of one
    # or both subscriptions and never get delivered at all (ordinary Redis
    # pub/sub fire-and-forget semantics, faithfully modeled by the fake).
    await asyncio.sleep(0.05)

    delivered = await svc.publish_agent_control_frame(7, {"type": "ping"})
    assert delivered is True

    frame_b = await task_b
    assert frame_b == {"type": "ping"}

    with pytest.raises(asyncio.TimeoutError):
        await task_a

    await listen_a.aclose()
    await listen_b.aclose()


@pytest.mark.asyncio
async def test_claim_agent_control_frames_drops_message_when_ownership_changes_mid_flight(
    monkeypatch,
):
    """A worker still subscribed after losing ownership (its own teardown
    hasn't cancelled the listener task yet) must not yield a frame meant for
    whichever worker owns the connection now — the explicit per-message
    ownership re-check, not just "am I subscribed", is what "claim" means
    here."""
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    await svc.register_agent_connection(9, worker_id="worker-A")

    listen_a = svc.claim_agent_control_frames(9, worker_id="worker-A")
    task_a = asyncio.create_task(asyncio.wait_for(_first_frame(listen_a), timeout=1.0))
    await asyncio.sleep(0.05)

    # Ownership moves to worker B before the frame is published — worker A's
    # listener is still subscribed (its task hasn't been cancelled) but no
    # longer owns the connection.
    await svc.register_agent_connection(9, worker_id="worker-B")

    await svc.publish_agent_control_frame(9, {"type": "ping"})

    with pytest.raises(asyncio.TimeoutError):
        await task_a

    await listen_a.aclose()


@pytest.mark.asyncio
async def test_claim_agent_control_frames_returns_immediately_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    frames = [frame async for frame in svc.claim_agent_control_frames(5, worker_id="worker-A")]

    assert frames == []


# ── Task 21 fix round (Important #1): concurrent-pending-enrollment lock ──────
#
# count_pending_agents(db) + create_pending_agent(db, ...) used to run as two
# independent statements with no lock — under concurrent /enroll connections
# on different workers, each opening its own SessionLocal(), several could
# all observe a count under MAX_CONCURRENT_PENDING_AGENTS before any of them
# committed, and all insert, overshooting the cap. acquire_pending_enrollment_
# lock/release_pending_enrollment_lock close that window with a short-lived,
# cross-worker Redis lock (SET NX EX + the same compare-and-delete Lua script
# deregister_agent_connection above already uses).


@pytest.mark.asyncio
async def test_acquire_pending_enrollment_lock_is_mutually_exclusive(monkeypatch):
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    first_token = await svc.acquire_pending_enrollment_lock()
    assert first_token is not None

    # A second acquire attempt, while the first still holds the lock, must
    # fail — proving the lock actually excludes concurrent holders rather
    # than just handing out a token unconditionally. Retries would otherwise
    # mask this by eventually succeeding once the (much longer) TTL lapses,
    # so the retry budget is dropped to make this fast and unambiguous.
    monkeypatch.setattr(svc, "_PENDING_ENROLLMENT_LOCK_RETRY_ATTEMPTS", 1)
    second_token = await svc.acquire_pending_enrollment_lock()
    assert second_token is None


@pytest.mark.asyncio
async def test_release_pending_enrollment_lock_frees_it_for_the_next_acquirer(monkeypatch):
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    token = await svc.acquire_pending_enrollment_lock()
    assert token is not None

    await svc.release_pending_enrollment_lock(token)

    next_token = await svc.acquire_pending_enrollment_lock()
    assert next_token is not None
    assert next_token != token


@pytest.mark.asyncio
async def test_release_pending_enrollment_lock_only_releases_own_token(monkeypatch):
    """Compare-and-delete, not a bare delete: releasing with the wrong token
    (e.g. a call racing in after this holder's lock already expired and a
    *different* holder acquired it) must not clear someone else's lock."""
    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    real_token = await svc.acquire_pending_enrollment_lock()
    assert real_token is not None

    await svc.release_pending_enrollment_lock("not-the-real-token")

    monkeypatch.setattr(svc, "_PENDING_ENROLLMENT_LOCK_RETRY_ATTEMPTS", 1)
    still_held = await svc.acquire_pending_enrollment_lock()
    assert still_held is None  # the real holder's lock is still in place


@pytest.mark.asyncio
async def test_acquire_pending_enrollment_lock_fails_closed_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    assert await svc.acquire_pending_enrollment_lock() is None


@pytest.mark.asyncio
async def test_concurrent_pending_enrollment_attempts_cannot_overshoot_cap_when_locked(
    monkeypatch, db_session
):
    """The actual race the fix closes: several concurrent attempts to
    create a new pending agent, each its own real DB session (mirroring
    several /enroll connections on different workers), racing on
    count_pending_agents + create_pending_agent + commit.

    Genuine OS-thread concurrency, not `asyncio.gather` over coroutines:
    `SessionLocal` is a *sync* SQLAlchemy session with no `await` between
    the count and the insert, so under asyncio's single-threaded
    cooperative scheduling that whole sequence always runs as one
    uninterruptible block regardless of any lock — `asyncio.gather` alone
    can never actually interleave it, which would make a test built that
    way pass even with the lock removed entirely (verified by hand: it
    does). Real `concurrent.futures` threads give real parallelism instead
    — psycopg releases the GIL during the actual DB round trip, so two
    threads' count-then-insert sequences can genuinely race — while the
    lock's own acquire/release (async, needs the event loop) is dispatched
    back onto this test's loop via `run_coroutine_threadsafe` from each
    worker thread.
    """
    import secrets
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.db.models import Agent
    from app.db.session import SessionLocal

    bus = _FakeRedisBus()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=bus.client()))

    # Other tests in this suite create pending agents via real committed
    # SessionLocal() connections that outlive `db_session`'s own per-test
    # rollback (same reason test_ws_agents_enroll.py's concurrent-pending-cap
    # tests measure a baseline instead of assuming an empty table) — count
    # what's already there and cap exactly one above it.
    baseline_pending = db_session.query(Agent).filter_by(status="pending").count()
    monkeypatch.setattr(svc, "MAX_CONCURRENT_PENDING_AGENTS", baseline_pending + 1)

    loop = asyncio.get_running_loop()

    def _attempt_new_pending_agent() -> bool:
        # Runs in a real worker thread — acquire/release are async, so
        # they're dispatched onto the test's event loop from here. The main
        # thread must stay free to actually *run* that loop while this
        # blocks on `.result()`, which is exactly why the outer call below
        # uses `loop.run_in_executor` (awaited, non-blocking for the main
        # thread) rather than `ThreadPoolExecutor.map()` directly (blocking
        # the main thread — and therefore the loop these coroutines need to
        # run on — would deadlock every worker thread against itself).
        token = asyncio.run_coroutine_threadsafe(
            svc.acquire_pending_enrollment_lock(), loop
        ).result()
        assert token is not None, "lock should always be acquirable in this test"
        try:
            time.sleep(0.05)  # real thread sleep — widen the TOCTOU window on purpose
            with SessionLocal() as db:
                if svc.count_pending_agents(db) >= svc.MAX_CONCURRENT_PENDING_AGENTS:
                    return False
                svc.create_pending_agent(
                    db,
                    device_pk=secrets.token_hex(32),
                    fingerprint=secrets.token_hex(16),
                    hostname="race-test-locked",
                )
                db.commit()
                return True
        finally:
            asyncio.run_coroutine_threadsafe(
                svc.release_pending_enrollment_lock(token), loop
            ).result()

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = await asyncio.gather(
            *(loop.run_in_executor(executor, _attempt_new_pending_agent) for _ in range(3))
        )

    assert sum(results) == 1  # exactly one new row — never overshoots the cap
    assert db_session.query(Agent).filter_by(hostname="race-test-locked").count() == 1
    # Sanity-checked by hand (not shipped as its own test — asserting a raw
    # race condition reliably reproduces is inherently timing-dependent and
    # flaky against a fast local test DB): removing the lock from
    # `_attempt_new_pending_agent` above and re-running this same
    # real-thread setup does let multiple concurrent attempts see a
    # pre-commit count and all insert, overshooting the cap — confirming
    # the lock (not some other accident of scheduling) is what keeps the
    # assertion above at exactly 1.
