import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services import agent_enrollment as svc


def test_generate_pairing_code_format():
    code = svc.generate_pairing_code()
    parts = code.split("-")
    assert len(parts) == 3
    assert all(len(p) == 4 for p in parts)
    assert all(c in svc.CROCKFORD_ALPHABET for p in parts for c in p)


def test_generate_pairing_code_is_random():
    codes = {svc.generate_pairing_code() for _ in range(50)}
    assert len(codes) == 50  # 60 bits of entropy — collisions astronomically unlikely


@pytest.mark.asyncio
async def test_mint_then_resolve_pairing_code(monkeypatch):
    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v) or True
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: store.pop(k, None) is not None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    code = await svc.mint_pairing_code(agent_id=42)
    resolved = await svc.resolve_pairing_code(code)

    assert resolved == 42
    redis_client.setex.assert_called_once()
    ttl_arg = redis_client.setex.call_args[0][1]
    assert ttl_arg == svc.PAIRING_CODE_TTL_SECONDS


@pytest.mark.asyncio
async def test_resolve_unknown_code_returns_none(monkeypatch):
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    assert await svc.resolve_pairing_code("ZZZZ-ZZZZ-ZZZZ") is None


@pytest.mark.asyncio
async def test_consume_pairing_code_is_single_use(monkeypatch):
    store: dict[str, str] = {}
    redis_client = AsyncMock()
    redis_client.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v) or True
    redis_client.getdel.side_effect = lambda k: store.pop(k, None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    code = await svc.mint_pairing_code(agent_id=7)
    first = await svc.consume_pairing_code(code)
    second = await svc.consume_pairing_code(code)

    assert first == 7
    assert second is None


@pytest.mark.asyncio
async def test_consume_pairing_code_uses_atomic_getdel(monkeypatch):
    """consume_pairing_code must use a single atomic GETDEL, not a GET
    followed by a separate DELETE — a get-then-delete pair leaves a window
    where two concurrent consumers can both observe the same agent_id
    before either delete fires, breaking single-use under concurrency.
    """
    store: dict[str, str] = {"agent_pairing:" + svc._hash_code("AAAA-AAAA-AAAA"): "7"}
    redis_client = AsyncMock()
    redis_client.getdel.side_effect = lambda k: store.pop(k, None)
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    result = await svc.consume_pairing_code("AAAA-AAAA-AAAA")

    assert result == 7
    redis_client.getdel.assert_called_once()
    redis_client.get.assert_not_called()
    redis_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_consume_pairing_code_concurrent_calls_only_one_winner(monkeypatch):
    """Simulates two concurrent consumers racing on the same code.

    The mock's GETDEL models real Redis semantics: an awaited round trip
    (representing network/scheduling latency, so both calls can be
    "in flight" at once) followed by an atomic check-and-pop with no
    intervening await — exactly what the Redis server guarantees for
    GETDEL. Under the old get-then-delete implementation, an equivalent
    race (await on GET, then a separate await on DELETE) could let both
    calls read the value before either deleted it. With the atomic
    primitive, only one of the two concurrent calls may ever observe the
    agent_id — the other must see the code already consumed.
    """
    key = "agent_pairing:" + svc._hash_code("BBBB-BBBB-BBBB")
    store: dict[str, str] = {key: "7"}
    redis_client = AsyncMock()

    async def _atomic_getdel(k):
        await asyncio.sleep(0)  # simulate round-trip latency before the atomic op runs
        return store.pop(k, None)  # atomic check-and-remove, no await inside

    redis_client.getdel.side_effect = _atomic_getdel
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    results = await asyncio.gather(
        svc.consume_pairing_code("BBBB-BBBB-BBBB"),
        svc.consume_pairing_code("BBBB-BBBB-BBBB"),
    )

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert winners == [7]
    assert losers == [None]
    assert key not in store


@pytest.mark.asyncio
async def test_pairing_lockout_after_repeated_misses(monkeypatch):
    counts: dict[str, int] = {}

    async def _incr(key):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    redis_client = AsyncMock()
    redis_client.incr.side_effect = _incr
    redis_client.get.side_effect = lambda k: str(counts.get(k, 0)) if k in counts else None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    for _ in range(svc._MISS_LIMIT - 1):
        await svc.record_pairing_miss("10.0.0.5")
    assert await svc.is_pairing_locked_out("10.0.0.5") is False

    await svc.record_pairing_miss("10.0.0.5")
    assert await svc.is_pairing_locked_out("10.0.0.5") is True


@pytest.mark.asyncio
async def test_global_pairing_lockout_trips_across_different_ips(monkeypatch):
    """Task 21: a distributed guesser rotating source IPs specifically to
    dodge the per-IP miss lockout still gets locked out once the aggregate
    global miss count crosses its own threshold — even though no single IP
    involved ever comes close to _MISS_LIMIT on its own."""
    counts: dict[str, int] = {}

    async def _incr(key):
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    redis_client = AsyncMock()
    redis_client.incr.side_effect = _incr
    redis_client.get.side_effect = lambda k: str(counts.get(k, 0)) if k in counts else None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    for i in range(svc._GLOBAL_MISS_LIMIT - 1):
        await svc.record_pairing_miss(f"10.9.0.{i}")
    # A brand-new IP that has never missed itself is still clear.
    assert await svc.is_pairing_locked_out("10.9.99.1") is False

    # One more miss, from yet another fresh IP, tips the global counter over.
    await svc.record_pairing_miss("10.9.99.2")
    # A third, entirely uninvolved IP is now locked out purely by the global count.
    assert await svc.is_pairing_locked_out("10.9.99.3") is True


class _FakeWindowRedis:
    """Minimal fake Redis backing INCR/EXPIRE(NX)/GET/DECR against a fixed
    key -> (value, expires_at) store, with expiry evaluated against a
    test-controlled clock (`advance()`) rather than wall time — lets tests
    prove a counter actually resets once its window elapses, which a plain
    incrementing dict (as used by the other tests in this file) can't."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[int, float | None]] = {}
        self.now = 0.0

    def _evict_if_expired(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is None:
            return
        _, expires_at = entry
        if expires_at is not None and self.now >= expires_at:
            del self._store[key]

    async def incr(self, key: str) -> int:
        self._evict_if_expired(key)
        value, expires_at = self._store.get(key, (0, None))
        value += 1
        self._store[key] = (value, expires_at)
        return value

    async def get(self, key: str) -> str | None:
        self._evict_if_expired(key)
        entry = self._store.get(key)
        return str(entry[0]) if entry is not None else None

    async def expire(self, key: str, ttl: int, nx: bool = False) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return False
        value, expires_at = entry
        if nx and expires_at is not None:
            return False
        self._store[key] = (value, self.now + ttl)
        return True

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_ws_attempt_within_per_ip_limit_allowed(monkeypatch):
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    for _ in range(svc._WS_ATTEMPT_IP_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", "10.5.0.1") is True


@pytest.mark.asyncio
async def test_ws_attempt_exceeding_per_ip_limit_rejects_further_attempts_from_that_ip(
    monkeypatch,
):
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    ip = "10.5.0.2"
    for _ in range(svc._WS_ATTEMPT_IP_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", ip) is True

    assert await svc.check_and_record_ws_attempt("enroll", ip) is False
    # Still rejected on a subsequent attempt from the same IP, not just the one that tipped it.
    assert await svc.check_and_record_ws_attempt("enroll", ip) is False


@pytest.mark.asyncio
async def test_ws_attempt_per_ip_limit_does_not_affect_other_ips(monkeypatch):
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    exhausted_ip = "10.5.0.3"
    for _ in range(svc._WS_ATTEMPT_IP_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", exhausted_ip) is True
    assert await svc.check_and_record_ws_attempt("enroll", exhausted_ip) is False

    # A different IP is unaffected by the first IP's exhausted counter.
    assert await svc.check_and_record_ws_attempt("enroll", "10.5.0.4") is True


@pytest.mark.asyncio
async def test_ws_attempt_exceeding_global_limit_rejects_regardless_of_ip(monkeypatch):
    """Task 21: many distinct IPs, each individually far under the per-IP
    cap, still trip the shared global counter — and once tripped, a
    brand-new IP that has never attempted before is rejected too."""
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    for i in range(svc._WS_ATTEMPT_GLOBAL_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", f"10.6.0.{i}") is True

    assert await svc.check_and_record_ws_attempt("enroll", "10.6.99.99") is False


@pytest.mark.asyncio
async def test_ws_attempt_endpoints_have_independent_counters(monkeypatch):
    """Exhausting /enroll's per-IP counter must not block /link from the
    same IP — a flood aimed at one anonymous endpoint shouldn't be able to
    lock a legitimate, already-provisioned agent out of the other."""
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    ip = "10.5.0.5"
    for _ in range(svc._WS_ATTEMPT_IP_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", ip) is True
    assert await svc.check_and_record_ws_attempt("enroll", ip) is False

    assert await svc.check_and_record_ws_attempt("link", ip) is True


@pytest.mark.asyncio
async def test_ws_attempt_fails_closed_when_redis_unavailable(monkeypatch):
    """Task 21 / global constraint: Redis being degraded must refuse new
    /enroll and /link attempts, not silently disable the limit."""
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=None))

    assert await svc.check_and_record_ws_attempt("enroll", "10.7.0.1") is False
    assert await svc.check_and_record_ws_attempt("link", "10.7.0.1") is False


@pytest.mark.asyncio
async def test_ws_attempt_counter_expires_and_allows_retry_after_window(monkeypatch):
    fake = _FakeWindowRedis()
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=fake))

    ip = "10.8.0.1"
    for _ in range(svc._WS_ATTEMPT_IP_LIMIT):
        assert await svc.check_and_record_ws_attempt("enroll", ip) is True
    assert await svc.check_and_record_ws_attempt("enroll", ip) is False

    fake.advance(svc._WS_ATTEMPT_IP_WINDOW_SECONDS + 1)

    assert await svc.check_and_record_ws_attempt("enroll", ip) is True
