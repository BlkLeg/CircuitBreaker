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


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def allow_degraded_dependencies() -> bool:
    """Break-glass: waives every dependency gate below. Tests and emergencies only."""
    return _env_flag("CB_ALLOW_DEGRADED_DEPENDENCIES")


def allow_direct_egress() -> bool:
    """Waives the egress-proxy requirement alone, and nothing else.

    A single-node homelab host generally has no forward proxy to point
    CB_EGRESS_PROXY_URL at, and an empty value is indistinguishable from an
    operator who meant to configure one and did not. This flag records that
    running without a proxy is a decision. It does not disable the outbound URL
    policy in url_validation.py — SSRF checks, scheme and redirect validation
    still apply to every public request — and it deliberately does not reach
    the Redis, NATS, rate-limit-storage or secret gates, which is the whole
    reason it is separate from CB_ALLOW_DEGRADED_DEPENDENCIES.
    """
    return _env_flag("CB_ALLOW_DIRECT_EGRESS")


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
    elif not settings.egress_proxy_url.strip() and not allow_direct_egress():
        errors.append(
            "CB_EGRESS_PROXY_URL is required in production so public outbound HTTP clients "
            "cannot bypass controlled egress; set CB_ALLOW_DIRECT_EGRESS=true to run without "
            "a proxy on hosts that have none"
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
    """Return an error message, or None when the configured proxy is usable.

    This returns the *problem*, not the proxy. Returning the validated URL here
    made a correctly configured proxy read as a truthy error at the call site,
    so a valid CB_EGRESS_PROXY_URL failed startup with the URL itself as the
    message — leaving degraded mode as the only way to boot at all.
    """
    from app.core.url_validation import configured_egress_proxy_url

    try:
        configured_egress_proxy_url()
    except ValueError as exc:
        return f"CB_EGRESS_PROXY_URL is invalid: {exc}"
    return None
