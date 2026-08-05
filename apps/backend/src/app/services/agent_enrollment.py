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
# Distinct, higher ceiling for the *global* pairing-miss counter: it aggregates
# misses across every IP, so a distributed guesser rotating source addresses
# to dodge the per-IP lockout above still trips this one. Higher than
# _MISS_LIMIT on purpose — legitimate operator traffic (multiple admins
# fat-fingering codes) contributes to it too, so it needs headroom the
# single-IP counter doesn't.
_GLOBAL_MISS_LIMIT = 50
_GLOBAL_MISS_WINDOW_SECONDS = 15 * 60

# Per-IP and global caps on *connection attempts* to the anonymous /enroll and
# /link WS endpoints, checked before any Noise handshake byte is read (see
# check_and_record_ws_attempt). Separate key namespace per endpoint so a flood
# aimed at /enroll can't lock out legitimate already-provisioned agents
# reconnecting via /link, or vice versa.
_WS_ATTEMPT_IP_LIMIT = 20
_WS_ATTEMPT_IP_WINDOW_SECONDS = 60
_WS_ATTEMPT_GLOBAL_LIMIT = 200
_WS_ATTEMPT_GLOBAL_WINDOW_SECONDS = 60


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
    """Atomically get-and-delete — makes the code single-use.

    Uses Redis's native ``GETDEL`` (server-side atomic since Redis 6.2; this
    project targets ``redis:7-alpine``, see docker-compose.deps.yml) instead
    of a separate GET followed by DELETE. A get-then-delete pair is not
    atomic: two concurrent callers could both complete the GET and observe
    the same agent_id before either DELETE fires, letting the same
    single-use code be consumed twice. GETDEL closes that race by resolving
    and deleting in one round trip the server executes atomically.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return None
    val = await r.getdel(f"agent_pairing:{_hash_code(code)}")
    return int(val) if val is not None else None


async def record_pairing_miss(ip: str) -> None:
    """Record one incorrect-pairing-code attempt against both the per-IP
    counter and the global counter (Task 21) — the latter catches a
    distributed guesser that rotates source IPs specifically to stay under
    the per-IP threshold."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return
    key = f"agent_pairing_miss:{ip}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _MISS_WINDOW_SECONDS)

    global_key = "agent_pairing_miss:global"
    global_count = await r.incr(global_key)
    if global_count == 1:
        await r.expire(global_key, _GLOBAL_MISS_WINDOW_SECONDS)


async def is_pairing_locked_out(ip: str) -> bool:
    """True if this IP is locked out by its own miss count, OR the global
    miss count (aggregated across all IPs) has tripped — see
    record_pairing_miss's docstring for why both are tracked."""
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False
    count = await r.get(f"agent_pairing_miss:{ip}")
    if count is not None and int(count) >= _MISS_LIMIT:
        return True
    global_count = await r.get("agent_pairing_miss:global")
    return global_count is not None and int(global_count) >= _GLOBAL_MISS_LIMIT


async def check_and_record_ws_attempt(endpoint: str, ip: str) -> bool:
    """Redis-backed per-IP + global gate on connection attempts to an
    anonymous agent WS endpoint (``enroll`` or ``link``), meant to be called
    as the very first thing the handler does after ``websocket.accept()`` —
    before a single Noise handshake byte is read.

    Mirrors is_pairing_locked_out's expiring-counter pattern (fixed window,
    INCR + EXPIRE-on-first-increment), but as a proactive attempt cap rather
    than a miss-triggered lockout: every attempt counts against the window,
    not just failed ones, since a flood of well-formed handshakes is exactly
    as costly to the server (Noise DH + AEAD setup, a DB round trip) as a
    flood of malformed ones.

    Fails CLOSED: if Redis is unreachable, returns False (reject) instead of
    silently admitting unlimited attempts. /enroll and /link are the
    anonymous, adversarial-by-default surface — unlike the pairing-lookup
    REST endpoint (already gated behind an authenticated admin session),
    degrading this rate limit when Redis is down would silently weaken the
    one guarantee protecting them, which is exactly what the "fail clearly"
    requirement for these two endpoints rules out.
    """
    from app.core.redis import get_redis

    r = await get_redis()
    if r is None:
        return False

    ip_key = f"agent_ws_attempt:{endpoint}:{ip}"
    ip_count = await r.incr(ip_key)
    if ip_count == 1:
        await r.expire(ip_key, _WS_ATTEMPT_IP_WINDOW_SECONDS)

    global_key = f"agent_ws_attempt:{endpoint}:global"
    global_count = await r.incr(global_key)
    if global_count == 1:
        await r.expire(global_key, _WS_ATTEMPT_GLOBAL_WINDOW_SECONDS)

    return ip_count <= _WS_ATTEMPT_IP_LIMIT and global_count <= _WS_ATTEMPT_GLOBAL_LIMIT
