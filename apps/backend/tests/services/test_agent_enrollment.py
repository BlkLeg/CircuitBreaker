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
    redis_client.get.side_effect = lambda k: store.get(k)
    redis_client.delete.side_effect = lambda k: store.pop(k, None) is not None
    monkeypatch.setattr("app.core.redis.get_redis", AsyncMock(return_value=redis_client))

    code = await svc.mint_pairing_code(agent_id=7)
    first = await svc.consume_pairing_code(code)
    second = await svc.consume_pairing_code(code)

    assert first == 7
    assert second is None


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
