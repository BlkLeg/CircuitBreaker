"""Async Redis client singleton.

Provides a lazy-connecting ``redis.asyncio.Redis`` via :func:`get_redis`.
If the connection cannot be established the helper returns ``None`` so callers
can degrade gracefully (fall back to DB reads, skip publish, etc.).

:func:`get_redis` performs lazy reconnection with a cooldown so that a
startup race (Redis not yet ready when the backend worker boots) is
self-healing without hammering the server on every call.

Configuration is driven by the ``CB_REDIS_URL`` environment variable which
defaults to ``redis://localhost:6379/0`` for the embedded single-container
deployment.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import redis.asyncio as aioredis

_logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_url: str = os.environ.get("CB_REDIS_URL", "redis://localhost:6379/0")
_password_file: str = os.environ.get("CB_REDIS_PASSWORD_FILE", "/data/.redis_pass")

_RECONNECT_COOLDOWN_S = 10.0
_last_reconnect_attempt: float = 0.0


def _resolve_redis_password(url: str) -> str | None:
    """Resolve Redis password for URLs without embedded auth.

    Priority:
    1) Explicit ``CB_REDIS_PASSWORD`` environment variable
    2) Embedded single-container password file (``/data/.redis_pass`` by default)
       when connecting to localhost/loopback.
    """
    parsed = urlparse(url)
    if parsed.password:
        return None

    explicit = os.environ.get("CB_REDIS_PASSWORD")
    if explicit:
        return explicit

    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return None

    try:
        pass_file = Path(_password_file)
        if pass_file.exists():
            secret = pass_file.read_text(encoding="utf-8").strip()
            if secret:
                return secret
    except Exception as exc:
        _logger.debug("Failed reading Redis password file %s: %s", _password_file, exc)

    return None


async def _try_connect(connect_timeout: int = 5, socket_timeout: int = 5) -> aioredis.Redis | None:
    """Attempt a Redis connection.  Returns the client or ``None``."""
    try:
        password = _resolve_redis_password(_url)
        client = aioredis.from_url(
            _url,
            password=password,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=True,
        )
        await client.ping()
        return client
    except Exception:
        return None


async def init_redis(url: str | None = None) -> aioredis.Redis | None:
    """Create (or re-create) the module-level Redis connection.

    Returns the client on success, ``None`` on failure.
    """
    global _redis, _url
    if url:
        _url = url

    client = await _try_connect()
    if client is not None:
        _redis = client
        _logger.info("Redis connected (%s)", _url)
        return _redis

    _logger.warning("Redis unavailable (%s) — will lazy-reconnect on next get_redis() call", _url)
    _redis = None
    return None


async def get_redis() -> aioredis.Redis | None:
    """Return the active Redis client, or ``None`` if Redis is down.

    If the cached client is ``None`` or a stale connection is detected,
    attempts a lightweight reconnect.  Reconnect probes are rate-limited
    to at most once per ``_RECONNECT_COOLDOWN_S`` seconds so hot-path
    callers are never blocked by repeated connection attempts.
    """
    global _redis, _last_reconnect_attempt

    if _redis is not None:
        try:
            await _redis.ping()
            return _redis
        except Exception:
            _logger.warning("Redis connection lost — will attempt reconnect")
            try:
                await _redis.aclose()
            except Exception:
                pass
            _redis = None

    now = time.monotonic()
    if now - _last_reconnect_attempt < _RECONNECT_COOLDOWN_S:
        return None

    _last_reconnect_attempt = now
    client = await _try_connect(connect_timeout=2, socket_timeout=2)
    if client is not None:
        _redis = client
        _logger.info("Redis reconnected (%s)", _url)
        return _redis

    return None


async def close_redis() -> None:
    """Gracefully close the Redis connection."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception as exc:
            _logger.debug("Redis close error: %s", exc)
        finally:
            _redis = None
        _logger.info("Redis disconnected.")


async def redis_health() -> bool:
    """Quick health-check — returns True if Redis responds to PING."""
    if _redis is None:
        return False
    try:
        return await _redis.ping()
    except Exception:
        return False
