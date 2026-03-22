"""Per-tenant Redis sliding-window rate limiter.

Key:    rl:tenant:{tenant_id}   (Redis sorted set, member scored by timestamp ms)
Window: 60 seconds (rolling)
Limit:  CB_RATE_LIMIT_RPM env var (default 600 req/min)

Uses an atomic Lua script (registered via register_script / EVALSHA) to avoid
TOCTOU races. Returns HTTP 429 with a Retry-After header when limit is exceeded.

Skip conditions:
- Path is in _SKIP_PATHS (health/metrics endpoints)
- current_tenant_id ContextVar is None (unauthenticated request)
- Redis unavailable — fails open to preserve availability
"""

from __future__ import annotations

import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_logger = logging.getLogger(__name__)

_RATE_LIMIT_RPM: int = int(os.environ.get("CB_RATE_LIMIT_RPM", "600"))
_WINDOW_SECONDS: int = 60

_SKIP_PATHS: frozenset[str] = frozenset(
    [
        "/api/v1/health",
        "/api/v1/health/ready",
        "/metrics",
    ]
)

# Atomic sliding-window Lua script (executed server-side via EVALSHA).
# KEYS[1] = Redis key
# ARGV[1] = now_ms, ARGV[2] = window_ms, ARGV[3] = limit
# Returns: [0, new_count]            — request allowed
#          [1, retry_after_seconds]  — limit exceeded
_SLIDING_WINDOW_LUA = """
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)

if count < limit then
    local member = tostring(now) .. '-' .. tostring(math.random(1, 999999))
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    return {0, count + 1}
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
    return {1, retry_after}
end
"""


class TenantRateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a per-tenant rolling request limit backed by Redis."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        from app.middleware.tenant_middleware import current_tenant_id  # noqa: PLC0415

        tenant_id = current_tenant_id.get(None)
        if tenant_id is None:
            return await call_next(request)

        from app.core.redis import get_redis  # noqa: PLC0415

        redis = await get_redis()
        if redis is None:
            _logger.debug("Rate limit skipped — Redis unavailable")
            return await call_next(request)

        key = f"rl:tenant:{tenant_id}"
        now_ms = int(time.time() * 1000)
        window_ms = _WINDOW_SECONDS * 1000

        try:
            # register_script uses EVALSHA (cached) — Lua runs atomically on Redis server.
            script = redis.register_script(_SLIDING_WINDOW_LUA)
            result = await script(keys=[key], args=[now_ms, window_ms, _RATE_LIMIT_RPM])
            exceeded, value = int(result[0]), int(result[1])
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Rate limit check failed (%s) — allowing request", exc)
            return await call_next(request)

        if exceeded:
            retry_after = max(value, 1)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
