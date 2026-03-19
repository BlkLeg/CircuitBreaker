"""Redis-backed magic link token lifecycle.

Tokens are stored as ``magic_link:{token}`` keys with a 10-minute TTL.
Each token maps to a ``user_id``.  Tokens are single-use: consumed (deleted)
after a successful authentication.
"""

from __future__ import annotations

import logging
import secrets

from app.core.redis import get_redis

_logger = logging.getLogger(__name__)

MAGIC_LINK_TTL = 600  # 10 minutes
REDIS_KEY_PREFIX = "magic_link"


async def create_magic_link_token(user_id: int) -> str:
    """Generate a magic link token, store in Redis, return the token string."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot create magic link token")

    token = secrets.token_urlsafe(32)
    redis_key = f"{REDIS_KEY_PREFIX}:{token}"

    await redis.setex(redis_key, MAGIC_LINK_TTL, str(user_id))

    stored = await redis.get(redis_key)
    if not stored:
        raise RuntimeError(f"Redis write verification failed for key={redis_key}")

    _logger.info(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
        # Logs only token[:8] prefix — first 8 chars of token, not the full token value
        "[magic_link] token created user_id=%s token_prefix=%s... ttl=%ss",
        user_id,
        token[:8],
        MAGIC_LINK_TTL,
    )
    return token


async def resolve_magic_link_token(token: str) -> int | None:
    """Return user_id if the token is valid and not expired, else None."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot resolve magic link token")

    redis_key = f"{REDIS_KEY_PREFIX}:{token}"
    stored = await redis.get(redis_key)

    if not stored:
        _logger.warning(
            "[magic_link] token not found or expired prefix=%s...", token[:8]
        )  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
        return None

    return int(stored)


async def consume_magic_link_token(token: str) -> None:
    """Delete the token after successful use (one-time use enforced)."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot consume magic link token")

    await redis.delete(f"{REDIS_KEY_PREFIX}:{token}")
    _logger.info(
        "[magic_link] token consumed prefix=%s...", token[:8]
    )  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
