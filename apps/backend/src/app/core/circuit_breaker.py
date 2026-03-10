"""Circuit breaker for external API calls (e.g. Proxmox, iLO).

Per-key state: closed (normal), open (fail fast), half_open (one trial).
After failure_threshold failures within failure_window_sec, the circuit opens
for open_duration_sec, then moves to half_open. One success closes; one failure re-opens.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

_logger = logging.getLogger(__name__)

T = TypeVar("T")

# Defaults: 3 failures in 60s -> open for 90s
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_FAILURE_WINDOW_SEC = 60
DEFAULT_OPEN_DURATION_SEC = 90


class CircuitBreaker:
    """In-memory circuit breaker per key (e.g. 'proxmox:42'). Thread-safe."""

    __slots__ = (
        "key",
        "failure_threshold",
        "failure_window_sec",
        "open_duration_sec",
        "_lock",
        "_failures",
        "_first_failure_time",
        "_state",
        "_open_until",
    )

    def __init__(
        self,
        key: str,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        failure_window_sec: int = DEFAULT_FAILURE_WINDOW_SEC,
        open_duration_sec: int = DEFAULT_OPEN_DURATION_SEC,
    ):
        self.key = key
        self.failure_threshold = failure_threshold
        self.failure_window_sec = failure_window_sec
        self.open_duration_sec = open_duration_sec
        self._lock = threading.Lock()
        self._failures: int = 0
        self._first_failure_time: float = 0.0
        self._state: str = "closed"
        self._open_until: float = 0.0

    def _now(self) -> float:
        return time.monotonic()

    def is_open(self) -> bool:
        """Return True if the circuit is open (caller should fail fast)."""
        with self._lock:
            now = self._now()
            if self._state == "closed":
                return False
            if self._state == "open":
                if now >= self._open_until:
                    self._state = "half_open"
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            now = self._now()
            if self._state == "half_open":
                self._state = "open"
                self._open_until = now + self.open_duration_sec
                _logger.debug("Circuit %s re-opened after half-open failure", self.key)
                return
            if self._failures == 0:
                self._first_failure_time = now
            self._failures += 1
            if self._failures >= self.failure_threshold:
                if now - self._first_failure_time <= self.failure_window_sec:
                    self._state = "open"
                    self._open_until = now + self.open_duration_sec
                    _logger.warning(
                        "Circuit %s opened after %d failures (open for %ds)",
                        self.key,
                        self._failures,
                        self.open_duration_sec,
                    )
                else:
                    self._failures = 1
                    self._first_failure_time = now


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(key: str, **kwargs: Any) -> CircuitBreaker:
    with _breakers_lock:
        if key not in _breakers:
            _breakers[key] = CircuitBreaker(key, **kwargs)
        return _breakers[key]


class CircuitOpenError(Exception):
    """Raised when the circuit is open and the call is skipped."""

    pass


async def call_with_circuit_breaker(
    key: str,
    coro_factory: Callable[[], Any],
    *,
    fallback: Any = None,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    failure_window_sec: int = DEFAULT_FAILURE_WINDOW_SEC,
    open_duration_sec: int = DEFAULT_OPEN_DURATION_SEC,
) -> Any:
    """Run the async call through the circuit breaker. Returns fallback if circuit is open or call fails."""
    breaker = get_breaker(
        key,
        failure_threshold=failure_threshold,
        failure_window_sec=failure_window_sec,
        open_duration_sec=open_duration_sec,
    )
    if breaker.is_open():
        _logger.debug("Circuit %s open — skipping call", key)
        return fallback
    try:
        result = await coro_factory()
        breaker.record_success()
        return result
    except Exception as e:
        breaker.record_failure()
        _logger.debug("Circuit %s recorded failure: %s", key, e)
        return fallback
