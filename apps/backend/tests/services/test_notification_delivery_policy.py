"""Shared notification response classification and bounded retry behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.schemas.notifications import AlertEnvelope
from app.schemas.notifications import TestResult as DeliveryTestResult
from app.services.notification_delivery import (
    DeliveryPolicy,
    MissingConfigurationError,
    classify_delivery_error,
    classify_http_response,
    deliver_with_policy,
)


@pytest.mark.parametrize(
    ("status", "state", "reason"),
    [
        (200, "accepted", "provider_accepted"),
        (204, "accepted", "provider_accepted"),
        (302, "terminal", "redirect_rejected"),
        (401, "terminal", "authentication_rejected"),
        (403, "terminal", "authentication_rejected"),
        (400, "terminal", "provider_rejected"),
        (429, "retryable", "rate_limited"),
        (500, "retryable", "upstream_unavailable"),
        (503, "retryable", "upstream_unavailable"),
    ],
)
def test_http_status_truth_table(status: int, state: str, reason: str) -> None:
    decision = classify_http_response(status, {}, "slack")

    assert decision.state == state
    assert decision.reason_code == reason


def test_retry_after_is_bounded() -> None:
    decision = classify_http_response(
        429, {"Retry-After": "900"}, "slack", max_retry_after_seconds=17
    )

    assert decision.retry_after == 17


def test_exception_results_never_echo_exception_text() -> None:
    secret = "https://hooks.example.test/SECRET-TOKEN"

    decisions = [
        classify_delivery_error(MissingConfigurationError(secret)),
        classify_delivery_error(httpx.ConnectError(secret)),
        classify_delivery_error(RuntimeError(secret)),
    ]

    assert all(secret not in decision.safe_message for decision in decisions)


@pytest.mark.asyncio
async def test_transient_responses_retry_until_acceptance() -> None:
    send = AsyncMock(
        side_effect=[
            SimpleNamespace(status_code=500, headers={}),
            SimpleNamespace(status_code=429, headers={"Retry-After": "2"}),
            SimpleNamespace(status_code=200, headers={}),
        ]
    )
    sleeps: list[float] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    outcome = await deliver_with_policy(
        "slack",
        {},
        AlertEnvelope(title="Host down"),
        policy=DeliveryPolicy(max_attempts=3, base_delay_seconds=1),
        send_attempt=send,
        sleeper=sleeper,
    )

    assert outcome.state == "accepted"
    assert outcome.attempt_count == 3
    assert sleeps == [1, 2]


@pytest.mark.asyncio
async def test_terminal_rejection_is_not_retried() -> None:
    send = AsyncMock(return_value=SimpleNamespace(status_code=403, headers={}))

    outcome = await deliver_with_policy(
        "teams",
        {},
        AlertEnvelope(title="Host down"),
        policy=DeliveryPolicy(max_attempts=5),
        send_attempt=send,
    )

    assert outcome.state == "terminal"
    assert outcome.reason_code == "authentication_rejected"
    assert outcome.attempt_count == 1
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_exhausted_test_is_a_completed_visible_failure() -> None:
    send = AsyncMock(return_value=SimpleNamespace(status_code=500, headers={}))

    outcome = await deliver_with_policy(
        "discord",
        {},
        AlertEnvelope(title="Host down"),
        policy=DeliveryPolicy(max_attempts=2, base_delay_seconds=0),
        send_attempt=send,
    )
    result = DeliveryTestResult.from_outcome(outcome.model_copy(update={"sink_id": 7}))

    assert outcome.state == "retryable"
    assert outcome.reason_code == "retry_exhausted"
    assert result.state == "terminal"
    assert result.ok is False
