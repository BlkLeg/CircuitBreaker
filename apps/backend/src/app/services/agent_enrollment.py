"""Pairing-code lifecycle for agent enrollment — Redis-backed, single-use.

The pairing code is a selector, not a credential: both approval routes require
an authenticated session with a role permitted to approve agents (§2.4 of
specs/2026-07-26-cb-agent-design.md), so a leaked code alone buys an attacker
nothing.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

_logger = logging.getLogger(__name__)

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_CODE_BITS = 60
PAIRING_CODE_TTL_SECONDS = 15 * 60

_MISS_LIMIT = 10
_MISS_WINDOW_SECONDS = 15 * 60


def generate_pairing_code() -> str:
    n = secrets.randbits(PAIRING_CODE_BITS)
    chars = []
    for _ in range(12):
        chars.append(CROCKFORD_ALPHABET[n & 0x1F])
        n >>= 5
    chars.reverse()
    raw = "".join(chars)
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def _hash_code(code: str) -> str:
    normalized = code.strip().upper().replace("-", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


async def mint_pairing_code(agent_id: int) -> str:
    from app.core.redis import get_redis

    code = generate_pairing_code()
    r = await get_redis()
    if r is not None:
        await r.setex(f"agent_pairing:{_hash_code(code)}", PAIRING_CODE_TTL_SECONDS, str(agent_id))
    else:
        _logger.warning("Redis unavailable — minted pairing code will not resolve")
    return code


async def resolve_pairing_code(code: str) -> int | None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    val = await r.get(f"agent_pairing:{_hash_code(code)}")
    return int(val) if val is not None else None


async def consume_pairing_code(code: str) -> int | None:
    """Resolve then delete — makes the code single-use."""
    from app.core.redis import get_redis

    agent_id = await resolve_pairing_code(code)
    if agent_id is not None:
        r = await get_redis()
        if r is not None:
            await r.delete(f"agent_pairing:{_hash_code(code)}")
    return agent_id


async def record_pairing_miss(ip: str) -> None:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    key = f"agent_pairing_miss:{ip}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _MISS_WINDOW_SECONDS)


async def is_pairing_locked_out(ip: str) -> bool:
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False
    count = await r.get(f"agent_pairing_miss:{ip}")
    return count is not None and int(count) >= _MISS_LIMIT
