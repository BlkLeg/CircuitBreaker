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
