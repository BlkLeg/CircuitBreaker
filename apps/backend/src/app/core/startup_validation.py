"""Startup validation for security-critical dependencies and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings

_PLACEHOLDER_VALUES = frozenset(
    {
        "change_me",
        "changeme",
        "placeholder",
        "todo",
        "test",
        "secret",
        "password",
    }
)


@dataclass(frozen=True)
class StartupValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def allow_degraded_dependencies() -> bool:
    return os.environ.get("CB_ALLOW_DEGRADED_DEPENDENCIES", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_VALUES


def validate_secret_value(name: str, value: str | None, *, min_length: int = 1) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return f"{name} is missing or empty"
    if _is_placeholder(normalized):
        return f"{name} uses a placeholder value"
    if len(normalized) < min_length:
        return f"{name} is too short"
    return None


def validate_startup_secrets(*, jwt_secret: str | None, vault_key: str | None) -> tuple[str, ...]:
    errors = []
    jwt_error = validate_secret_value("JWT/session signing secret", jwt_secret, min_length=32)
    if jwt_error:
        errors.append(jwt_error)
    if vault_key:
        vault_error = validate_secret_value("Vault encryption key", vault_key, min_length=32)
        if vault_error:
            errors.append(vault_error)
    return tuple(errors)


async def validate_core_dependencies(redis_client: object | None, nats_connected: bool) -> None:
    if allow_degraded_dependencies():
        return

    errors: list[str] = []
    if effective_rate_limit_storage_uri().startswith("memory://"):
        errors.append("Rate-limit storage must use shared Redis storage in production")
    proxy_error = validate_egress_proxy()
    if proxy_error:
        errors.append(proxy_error)
    elif not settings.egress_proxy_url.strip():
        errors.append(
            "CB_EGRESS_PROXY_URL is required in production so public outbound HTTP clients "
            "cannot bypass controlled egress"
        )
    if redis_client is None:
        errors.append(
            "Redis is unavailable; shared rate limits, sessions, telemetry cache, and pub/sub "
            "cannot run safely"
        )
    if not nats_connected:
        errors.append(
            "NATS is unavailable; worker dispatch, notification delivery, and event fan-out "
            "cannot run safely"
        )
    if errors:
        raise RuntimeError("; ".join(errors))


def effective_rate_limit_storage_uri() -> str:
    return settings.rate_limit_storage_url.strip() or settings.redis_url.strip()


def validate_egress_proxy() -> str | None:
    from app.core.url_validation import configured_egress_proxy_url

    try:
        return configured_egress_proxy_url()
    except ValueError as exc:
        return f"CB_EGRESS_PROXY_URL is invalid: {exc}"
