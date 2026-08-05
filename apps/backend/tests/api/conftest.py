"""Shared test doubles for tests/api/ — not autouse itself; test modules that
want the default opt in via `pytestmark = pytest.mark.usefixtures(...)` (see
test_ws_agents_enroll.py / test_ws_agents_link.py) rather than every file
under tests/api/ picking it up unconditionally. Kept out of the top-level
conftest.py for the same reason: files with nothing to do with WS agent
endpoints shouldn't be affected by it.
"""

from __future__ import annotations

import time

import pytest


class FakeAgentRedis:
    """General-purpose in-memory fake covering every Redis operation Task
    21's code (and the agent-enrollment/link machinery it sits next to)
    exercises: expiring INCR/EXPIRE counters (check_and_record_ws_attempt,
    is_pairing_locked_out/record_pairing_miss), SETEX/GET/GETDEL (pairing
    codes), SET NX EX + a Lua compare-and-delete (acquire/release_pending_
    enrollment_lock, deregister_agent_connection), and PUBLISH/pubsub
    (broadcast_presence / _redis_agent_listener — pubsub here never
    actually relays anything, matching test_ws_agents_enroll.py's
    `_redis_client_with_no_pubsub_relay`, which is the correct behavior for
    a single-process fake standing in for what would otherwise be a
    cross-worker channel).

    Real TTL expiry via a monotonic clock (mirrors test_ws_agents_link.py's
    `_FakeTTLRedis`, the same idea, generalized) — a key past its expiry is
    treated as absent on the next access, no manual eviction sweep needed.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float | None, str]] = {}

    def _evict_if_expired(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is None:
            return
        expires_at, _ = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._store[key]

    async def incr(self, key: str) -> int:
        self._evict_if_expired(key)
        expires_at, value = self._store.get(key, (None, "0"))
        new_value = int(value) + 1
        self._store[key] = (expires_at, str(new_value))
        return new_value

    async def expire(self, key: str, ttl: float, nx: bool = False) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return False
        expires_at, value = entry
        if nx and expires_at is not None:
            return False
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    async def get(self, key: str) -> str | None:
        self._evict_if_expired(key)
        entry = self._store.get(key)
        return entry[1] if entry is not None else None

    async def set(self, key: str, value: str, nx: bool = False, ex: float | None = None) -> bool:
        self._evict_if_expired(key)
        if nx and key in self._store:
            return False
        expires_at = (time.monotonic() + ex) if ex is not None else None
        self._store[key] = (expires_at, value)
        return True

    async def setex(self, key: str, ttl: float, value: str) -> bool:
        self._store[key] = (time.monotonic() + ttl, value)
        return True

    async def getdel(self, key: str) -> str | None:
        self._evict_if_expired(key)
        entry = self._store.pop(key, None)
        return entry[1] if entry is not None else None

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        self._evict_if_expired(key)
        return 1 if key in self._store else 0

    async def publish(self, channel: str, message: str) -> int:
        return 0  # No cross-connection relay in this single-process fake.

    def pubsub(self) -> _FakeNullPubSub:
        return _FakeNullPubSub()

    def register_script(self, script: str) -> _FakeCompareAndDeleteScript:
        return _FakeCompareAndDeleteScript(self)


class _FakeNullPubSub:
    """Never delivers anything — matches _redis_agent_listener's own
    tolerance for a pubsub session that yields nothing (its subscribe/
    get_message calls are already wrapped in a try/except that degrades
    silently, so this doesn't need to error, just sit idle).

    `get_message` actually awaits `timeout` (real redis-py blocks for up to
    `timeout` seconds waiting for a message before returning None) rather
    than returning immediately: callers like `_redis_agent_listener` run
    `while not stop_event.is_set(): msg = await pubsub.get_message(...)` —
    an implementation that never truly suspends turns that into a
    zero-yield busy loop that starves the entire event loop of any chance
    to run other tasks (found by hand: it silently hung every WS test in
    the same event loop, not just this one)."""

    async def subscribe(self, *channels: str) -> None:
        return None

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,  # noqa: ASYNC109
    ):
        import asyncio

        await asyncio.sleep(timeout)
        return None

    async def unsubscribe(self, *channels: str) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _FakeCompareAndDeleteScript:
    """Stand-in for redis-py's register_script/EVALSHA — reimplements the
    one Lua script this codebase actually registers (get, compare,
    conditionally del) directly against the fake's own store, matching
    test_agent_registry_connection.py's `_FakeCompareAndDeleteScript`."""

    def __init__(self, redis: FakeAgentRedis) -> None:
        self._redis = redis

    async def __call__(self, keys: list[str], args: list[str]) -> int:
        key = keys[0]
        expected = args[0]
        current = await self._redis.get(key)
        if current != expected:
            return 0
        await self._redis.delete(key)
        return 1


@pytest.fixture
def agent_redis_default(monkeypatch) -> FakeAgentRedis:
    """Patches `app.core.redis.get_redis` to return a fresh `FakeAgentRedis`
    by default.

    Task 21 added Redis-backed rate limiting (check_and_record_ws_attempt,
    acquire_pending_enrollment_lock) that fails CLOSED when Redis is down —
    correct in production, but it means every test that drives a real
    `/enroll` or `/link` WS connection without mocking Redis would
    otherwise need a live, reachable Redis just to get past
    `websocket.accept()`, even tests that predate rate limiting entirely
    and have nothing to do with it. This fixture removes that dependency.

    Not autouse here — test modules opt in with
    `pytestmark = pytest.mark.usefixtures("agent_redis_default")` (see
    test_ws_agents_enroll.py / test_ws_agents_link.py) so the effect is
    scoped to exactly the files that need it, not every test under
    tests/api/. A test that needs specific Redis behavior (Redis-down,
    a lowered threshold, a custom fake) still calls its own
    `monkeypatch.setattr("app.core.redis.get_redis", ...)` as before — same
    `monkeypatch` fixture, so the test's own call simply wins for the rest
    of that test, and everything is restored to the real function at
    teardown regardless of how many times it was patched.
    """
    fake = FakeAgentRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)
    return fake
