"""Tests for circuit breaker (open after N failures, fail-fast)."""

from unittest.mock import AsyncMock

from app.core.circuit_breaker import (
    CircuitBreaker,
    call_with_circuit_breaker,
    get_breaker,
)


def test_breaker_opens_after_threshold_failures():
    """After failure_threshold failures in the window, circuit opens."""
    b = CircuitBreaker("test", failure_threshold=3, failure_window_sec=60, open_duration_sec=90)
    assert b.is_open() is False
    b.record_failure()
    b.record_failure()
    assert b.is_open() is False
    b.record_failure()
    assert b.is_open() is True


def test_breaker_success_resets_failures():
    """A success resets failure count."""
    b = CircuitBreaker("test2", failure_threshold=3, failure_window_sec=60, open_duration_sec=90)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.is_open() is False


def test_get_breaker_singleton_per_key():
    """Same key returns the same breaker instance."""
    b1 = get_breaker("proxmox:1")
    b2 = get_breaker("proxmox:1")
    assert b1 is b2
    assert get_breaker("proxmox:2") is not b1


async def test_call_with_circuit_breaker_returns_fallback_when_open():
    """When circuit is open, call_with_circuit_breaker returns fallback without calling."""
    key = "test_open_fallback"
    breaker = get_breaker(key, failure_threshold=1, failure_window_sec=10, open_duration_sec=3600)
    for _ in range(3):
        breaker.record_failure()
    coro_factory = AsyncMock(return_value="ok")
    result = await call_with_circuit_breaker(key, coro_factory, fallback="fallback")
    assert result == "fallback"
    coro_factory.assert_not_called()


async def test_call_with_circuit_breaker_returns_fallback_on_exception():
    """When the coro raises, fallback is returned."""
    key = "test_fail_key_returns_fallback"
    coro_factory = AsyncMock(side_effect=ConnectionError("down"))
    result = await call_with_circuit_breaker(
        key,
        coro_factory,
        fallback="err",
        failure_threshold=5,
        failure_window_sec=60,
        open_duration_sec=90,
    )
    assert result == "err"
