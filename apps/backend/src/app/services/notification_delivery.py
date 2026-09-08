"""Shared notification provider payloads, classification, and bounded retries.

Provider response bodies and exception strings are deliberately absent from
every result produced here. They may contain credentials or internal service
content and are not needed to decide whether a delivery can be retried.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.url_validation import outbound_async_client, safe_async_request
from app.schemas.notifications import AlertEnvelope, DeliveryOutcome, TestResult


class MissingConfigurationError(RuntimeError):
    """A destination lacks configuration required for delivery."""


class EmailRecipientMissingError(MissingConfigurationError):
    """An email destination has no recipient."""


class SmtpNotConfiguredError(MissingConfigurationError):
    """The shared SMTP transport is incomplete."""


class UnsupportedProviderError(RuntimeError):
    """A destination names a provider for which no adapter exists."""


@dataclass(frozen=True, slots=True)
class DeliveryDecision:
    """Safe classification of one provider attempt."""

    state: str
    reason_code: str
    safe_message: str
    retry_after: int | None = None


@dataclass(frozen=True, slots=True)
class DeliveryPolicy:
    """Bounded in-process retry policy; JetStream owns longer retries."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 10.0
    total_timeout_seconds: float = 20.0
    max_retry_after_seconds: int = 30


def _bounded_retry_after(headers: Mapping[str, str] | None, *, maximum: int = 30) -> int | None:
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = math.ceil(float(raw))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = math.ceil((retry_at - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, min(seconds, maximum))


def classify_http_response(
    status: int,
    headers: Mapping[str, str] | None,
    provider: str,
    *,
    max_retry_after_seconds: int = 30,
) -> DeliveryDecision:
    """Classify an HTTP status without inspecting the response body."""
    provider_name = provider.title()
    if 200 <= status < 300:
        return DeliveryDecision(
            "accepted", "provider_accepted", f"{provider_name} accepted the request."
        )
    if 300 <= status < 400:
        return DeliveryDecision(
            "terminal",
            "redirect_rejected",
            "The destination returned a redirect, which is not accepted for webhooks.",
        )
    if status in {401, 403}:
        return DeliveryDecision(
            "terminal",
            "authentication_rejected",
            "The provider rejected the destination credentials.",
        )
    if status == 429:
        return DeliveryDecision(
            "retryable",
            "rate_limited",
            "The provider rate-limited the request.",
            _bounded_retry_after(headers, maximum=max_retry_after_seconds),
        )
    if status in {408, 425} or 500 <= status < 600:
        return DeliveryDecision(
            "retryable",
            "upstream_unavailable",
            "The provider is temporarily unavailable.",
            _bounded_retry_after(headers, maximum=max_retry_after_seconds),
        )
    if 400 <= status < 500:
        return DeliveryDecision(
            "terminal", "provider_rejected", "The provider rejected the request."
        )
    return DeliveryDecision(
        "terminal", "invalid_response", "The provider returned an invalid response."
    )


def classify_delivery_error(exc: BaseException) -> DeliveryDecision:
    """Map an exception to a safe operational category."""
    if isinstance(exc, EmailRecipientMissingError):
        return DeliveryDecision(
            "terminal", "missing_recipient", "The email destination has no recipient."
        )
    if isinstance(exc, SmtpNotConfiguredError):
        return DeliveryDecision(
            "terminal",
            "smtp_not_configured",
            "SMTP is not configured. Complete SMTP settings before testing email.",
        )
    if isinstance(exc, MissingConfigurationError):
        return DeliveryDecision(
            "terminal", "missing_configuration", "The destination is not fully configured."
        )
    if isinstance(exc, UnsupportedProviderError):
        return DeliveryDecision(
            "terminal", "unsupported_provider", "The destination provider is not supported."
        )
    if isinstance(exc, (ValueError, httpx.UnsupportedProtocol)):
        return DeliveryDecision(
            "terminal", "policy_rejected", "The destination was rejected by outbound policy."
        )
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return DeliveryDecision(
            "retryable", "timeout", "The provider did not respond before the timeout."
        )
    if isinstance(exc, (httpx.NetworkError, ConnectionError, OSError)):
        return DeliveryDecision("retryable", "network_error", "The provider could not be reached.")
    name = type(exc).__name__.lower()
    if "auth" in name or "credential" in name or "decrypt" in name:
        return DeliveryDecision(
            "terminal", "authentication_rejected", "Destination credentials are unavailable."
        )
    return DeliveryDecision(
        "retryable", "delivery_error", "Delivery failed before the provider accepted it."
    )


def build_provider_payload(provider: str, event: AlertEnvelope) -> dict[str, Any]:
    """Build the existing provider-specific body without I/O."""
    if provider == "slack":
        slack_color = (
            "#FF0000"
            if event.severity == "critical"
            else "#FFA500"
            if event.severity == "warning"
            else "#36a64f"
        )
        return {
            "text": f"*{event.title}*\n{event.message}",
            "attachments": [
                {
                    "color": slack_color,
                    "fields": [{"title": "Severity", "value": event.severity, "short": True}],
                }
            ],
        }
    if provider == "discord":
        discord_color = (
            0xFF0000
            if event.severity == "critical"
            else 0xFFA500
            if event.severity == "warning"
            else 0x36A64F
        )
        return {
            "embeds": [
                {
                    "title": event.title,
                    "description": event.message,
                    "color": discord_color,
                    "footer": {"text": f"Severity: {event.severity}"},
                }
            ]
        }
    if provider == "teams":
        colors = {"critical": "FF0000", "warning": "FFA500", "info": "36a64f"}
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": colors.get(event.severity, "0076D7"),
            "summary": event.title,
            "sections": [
                {
                    "activityTitle": event.title,
                    "activityText": event.message,
                    "facts": [{"name": "Severity", "value": event.severity}],
                }
            ],
        }
    if provider == "email":
        return {}
    raise UnsupportedProviderError(provider)


async def send_once(
    provider: str,
    config: Mapping[str, Any],
    event: AlertEnvelope,
    *,
    request_fn: Callable[..., Awaitable[Any]] = safe_async_request,
    email_sender: Callable[[str, str, str, str], Awaitable[None]] | None = None,
) -> Any:
    """Perform one bounded provider attempt and return its response, if any."""
    if provider == "email":
        recipient = str(config.get("to") or config.get("to_address") or "").strip()
        if not recipient:
            raise EmailRecipientMissingError("Email sink has no recipient")
        if email_sender is None:
            raise SmtpNotConfiguredError("SMTP is not configured")
        await email_sender(recipient, event.title, event.message, event.severity)
        return None

    payload = build_provider_payload(provider, event)
    webhook_url = str(config.get("webhook_url") or "").strip()
    if not webhook_url:
        raise MissingConfigurationError("webhook URL missing")
    async with outbound_async_client() as client:
        return await request_fn(client, "POST", webhook_url, json=payload, timeout=10.0)


async def deliver_with_policy(
    provider: str,
    config: Mapping[str, Any],
    event: AlertEnvelope,
    *,
    sink_id: int | None = None,
    event_id: str | None = None,
    policy: DeliveryPolicy | None = None,
    send_attempt: Callable[[], Awaitable[Any]] | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> DeliveryOutcome:
    """Attempt delivery within a strict local budget and return safe state."""
    selected = policy or DeliveryPolicy()
    attempts = 0
    started = monotonic()
    last_decision = DeliveryDecision(
        "retryable", "delivery_error", "Delivery failed before provider acceptance."
    )
    last_status: int | None = None

    async def default_attempt() -> Any:
        return await send_once(provider, config, event)

    attempt_fn = send_attempt or default_attempt
    for attempt_index in range(max(1, selected.max_attempts)):
        attempts += 1
        try:
            remaining = selected.total_timeout_seconds - (monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            response = await asyncio.wait_for(attempt_fn(), timeout=remaining)
            status = getattr(response, "status_code", None)
            if isinstance(status, int):
                last_status = status
                last_decision = classify_http_response(
                    status,
                    getattr(response, "headers", None),
                    provider,
                    max_retry_after_seconds=selected.max_retry_after_seconds,
                )
            else:
                last_decision = DeliveryDecision(
                    "accepted", "provider_accepted", f"{provider.title()} accepted the request."
                )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            last_decision = classify_delivery_error(exc)

        if last_decision.state != "retryable":
            break
        if attempt_index + 1 >= selected.max_attempts:
            break
        elapsed = monotonic() - started
        delay = (
            float(last_decision.retry_after)
            if last_decision.retry_after is not None
            else min(
                selected.base_delay_seconds * (2**attempt_index),
                selected.max_delay_seconds,
            )
        )
        if elapsed + delay >= selected.total_timeout_seconds:
            last_decision = DeliveryDecision(
                "retryable",
                "retry_exhausted",
                "Delivery retries were exhausted; the event remains eligible for redelivery.",
                last_decision.retry_after,
            )
            break
        await sleeper(delay)

    if last_decision.state == "retryable" and attempts >= selected.max_attempts:
        last_decision = DeliveryDecision(
            "retryable",
            "retry_exhausted",
            "Delivery retries were exhausted; the event remains eligible for redelivery.",
            last_decision.retry_after,
        )
    return DeliveryOutcome(
        state=last_decision.state,  # type: ignore[arg-type]
        reason_code=last_decision.reason_code,
        safe_message=last_decision.safe_message,
        provider=provider,
        sink_id=sink_id,
        event_id=event_id,
        attempt_count=attempts,
        http_status=last_status,
        retry_after=last_decision.retry_after,
        accepted_at=datetime.now(UTC) if last_decision.state == "accepted" else None,
    )


async def test_sink_delivery(
    provider: str,
    config: Mapping[str, Any],
    event: AlertEnvelope,
    *,
    sink_id: int,
    request_fn: Callable[..., Awaitable[Any]] = safe_async_request,
    email_sender: Callable[[str, str, str, str], Awaitable[None]] | None = None,
    policy: DeliveryPolicy | None = None,
) -> TestResult:
    """Run the Test button through the same adapter and decision policy."""

    async def attempt() -> Any:
        return await send_once(
            provider,
            config,
            event,
            request_fn=request_fn,
            email_sender=email_sender,
        )

    outcome = await deliver_with_policy(
        provider,
        config,
        event,
        sink_id=sink_id,
        policy=policy,
        send_attempt=attempt,
    )
    return TestResult.from_outcome(outcome)
