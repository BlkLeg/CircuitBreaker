"""Redis-backed password reset token lifecycle.

Tokens are stored as ``password_reset:{token}`` keys with a 15-minute TTL.
Each token maps to a ``user_id``.  Tokens are single-use: consumed (deleted)
after a successful password change.
"""

from __future__ import annotations

import logging
import secrets

from app.core.redis import get_redis

_logger = logging.getLogger(__name__)

RESET_TOKEN_TTL = 900  # 15 minutes
REDIS_KEY_PREFIX = "password_reset"


async def create_reset_token(user_id: int) -> str:
    """Generate a reset token, write it to Redis, and return the token string."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot create password reset token")

    token = secrets.token_urlsafe(32)
    redis_key = f"{REDIS_KEY_PREFIX}:{token}"

    await redis.setex(redis_key, RESET_TOKEN_TTL, str(user_id))

    stored = await redis.get(redis_key)
    if not stored:
        raise RuntimeError(f"Redis write verification failed for key={redis_key}")

    _logger.info(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
        # Logs only token[:8] prefix — first 8 chars of token, not the full token value
        "[password_reset] token created user_id=%s token_prefix=%s... ttl=%ss",
        user_id,
        token[:8],
        RESET_TOKEN_TTL,
    )
    return token


async def resolve_reset_token(token: str) -> int | None:
    """Return user_id if the token is valid and not expired, else None."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot resolve password reset token")

    redis_key = f"{REDIS_KEY_PREFIX}:{token}"
    stored = await redis.get(redis_key)

    if not stored:
        _logger.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
            # Safe: logs only first 8 chars of the token (opaque prefix) —
            # insufficient to reconstruct or reuse the token.
            "[password_reset] token not found or expired prefix=%s...",
            token[:8],
        )
        return None

    return int(stored)


async def consume_reset_token(token: str) -> None:
    """Delete the token after successful use (one-time use enforced)."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis is unavailable — cannot consume password reset token")

    await redis.delete(f"{REDIS_KEY_PREFIX}:{token}")
    _logger.info(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
        # Safe: logs only first 8 chars of the token (opaque prefix) —
        # insufficient to reconstruct or reuse the token.
        "[password_reset] token consumed prefix=%s...",
        token[:8],
    )
