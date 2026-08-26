"""Classified, rate-limited fault reporting for background listeners and streams.

REL-07. Long-lived listeners (Redis pub/sub fan-out behind every WebSocket,
the mDNS/SSDP discovery listeners, the NATS-backed SSE stream, the agent
control-frame listener) must not die on a transient fault, which is why they
are wrapped in broad handlers. The failure mode that requirement targets is the
*other* half of that bargain: a broad handler that logs at DEBUG and moves on
turns a dead stream into a silent one, and a broad handler that logs at WARNING
inside a `while True:` turns a Redis outage into a log storm.

This module is the shared middle ground:

* ``classify_fault`` maps an exception onto a small, stable set of fault
  classes, so an operator can tell "the peer hung up" (routine) apart from
  "the payload on this channel is malformed" (a producer bug) apart from
  "Redis is gone" (an outage) without reading tracebacks.
* ``record_stream_fault`` emits one *throttled* structured log line per
  (component, fault class) — a burst of ``_LOG_BURST`` then at most one per
  ``_LOG_INTERVAL_S``, with the suppressed count carried on the next line so
  nothing is lost quietly — and always increments a counter.
* ``stream_fault_counts`` exposes those counters as a plain snapshot; the same
  numbers are published as the Prometheus counter
  ``circuitbreaker_stream_faults_total`` on `app.core.slo_metrics.REGISTRY`,
  which `/api/v1/metrics` already exposes.

Callers still decide the control flow (retry, continue, break, close). This
module never swallows anything on their behalf and never re-raises.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from typing import Any

from prometheus_client import Counter

from app.core import slo_metrics
from app.core.log_sanitize import safe_log_fragment

# ── Fault classes ────────────────────────────────────────────────────────────
# Stable label values. They are metric label values and appear in operator
# runbooks, so treat them as API: add, never rename.
FAULT_PEER_GONE = "peer_gone"
"""The far end of the stream hung up (WebSocket close, broken pipe, reset)."""
FAULT_TIMEOUT = "timeout"
"""An awaited step exceeded its deadline."""
FAULT_TRANSPORT = "transport"
"""The message bus itself failed — Redis, NATS, or the underlying socket."""
FAULT_DECODE = "decode"
"""A frame arrived but could not be parsed/decrypted into a usable payload."""
FAULT_DATABASE = "database"
"""A database call inside the listener failed."""
FAULT_UNEXPECTED = "unexpected"
"""Nothing above matched — treat as a defect until classified."""

# Log throttle: allow a short burst so the first occurrence is never delayed,
# then at most one line per interval per (component, fault) pair.
_LOG_BURST = 3
_LOG_INTERVAL_S = 60.0

# Default severity per class. A peer hanging up is routine; an unclassified
# fault is a defect and is logged with a traceback.
_DEFAULT_LEVEL: dict[str, int] = {
    FAULT_PEER_GONE: logging.DEBUG,
    FAULT_TIMEOUT: logging.INFO,
    FAULT_TRANSPORT: logging.WARNING,
    FAULT_DECODE: logging.WARNING,
    FAULT_DATABASE: logging.ERROR,
    FAULT_UNEXPECTED: logging.ERROR,
}

_MAX_CONTEXT_VALUE_LEN = 120

_logger = logging.getLogger(__name__)

# Registered on the process-lifetime registry `app.core.slo_metrics` owns, not
# on a private one: `app.api.metrics` already appends that registry's exposition
# to every scrape, and a counter nothing exposes is not a metric. Cardinality is
# bounded by construction (SRV-09) — `component` is a literal chosen at the call
# site from a fixed set, `fault` is one of the six classes above — so this series
# cannot grow with traffic, connections, or inventory size.
_FAULT_COUNTER = Counter(
    "circuitbreaker_stream_faults_total",
    "Faults observed by background listeners and streams, by component and class (REL-07).",
    ["component", "fault"],
    registry=slo_metrics.REGISTRY,
)

_lock = threading.Lock()
_counts: dict[tuple[str, str], int] = {}
_throttles: dict[tuple[str, str], _Throttle] = {}


class _Throttle:
    """Token bucket guarding one (component, fault) log stream."""

    __slots__ = ("tokens", "updated_at", "suppressed")

    def __init__(self) -> None:
        self.tokens: float = float(_LOG_BURST)
        self.updated_at: float = time.monotonic()
        self.suppressed: int = 0

    def take(self, now: float) -> int | None:
        """Consume a token. Returns the suppressed count to report, or None."""
        elapsed = now - self.updated_at
        self.updated_at = now
        self.tokens = min(float(_LOG_BURST), self.tokens + elapsed / _LOG_INTERVAL_S)
        if self.tokens < 1.0:
            self.suppressed += 1
            return None
        self.tokens -= 1.0
        suppressed, self.suppressed = self.suppressed, 0
        return suppressed


def _is_transport_error(exc: BaseException) -> bool:
    """True for Redis/NATS/socket transport failures.

    Matched by module and class name rather than by import: ``redis`` and
    ``nats`` are runtime dependencies of the listeners, not of this module, and
    a listener must not fail to report a fault because an optional client
    library is absent.
    """
    if isinstance(exc, ConnectionError | socket.error | EOFError):
        return True
    module = type(exc).__module__.split(".", 1)[0]
    if module in ("redis", "nats", "aioredis", "websockets"):
        return True
    return type(exc).__name__ in ("ConnectionClosed", "NoServersError")


def _is_peer_gone(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in ("WebSocketDisconnect", "ClientDisconnect", "ConnectionClosedOK"):
        return True
    return isinstance(exc, BrokenPipeError | ConnectionResetError | ConnectionAbortedError)


def _is_decode_error(exc: BaseException) -> bool:
    """True for "the bytes arrived but were not a usable payload".

    ``AttributeError`` is deliberately absent: on a frame it almost always
    means ``None`` reached code expecting an object, which is a defect in our
    code, not a malformed peer message, and it must surface as
    ``FAULT_UNEXPECTED`` with a traceback.
    """
    return isinstance(
        exc, json.JSONDecodeError | UnicodeDecodeError | ValueError | TypeError | KeyError
    )


def classify_fault(exc: BaseException) -> str:
    """Map an exception onto one of the module's fault classes.

    Order matters: a peer that hung up is reported as such even though the
    underlying exception is also a connection error, and a decode failure is
    only considered after every transport check, because several transport
    libraries raise ``ValueError`` subclasses.
    """
    if _is_peer_gone(exc):
        return FAULT_PEER_GONE
    if isinstance(exc, TimeoutError | asyncio.IncompleteReadError):
        return FAULT_TIMEOUT
    if _is_transport_error(exc):
        return FAULT_TRANSPORT
    if type(exc).__module__.split(".", 1)[0] in ("sqlalchemy", "psycopg", "psycopg2", "asyncpg"):
        return FAULT_DATABASE
    if _is_decode_error(exc):
        return FAULT_DECODE
    return FAULT_UNEXPECTED


def _format_context(context: dict[str, Any] | None) -> str:
    if not context:
        return "-"
    return " ".join(
        f"{key}={safe_log_fragment(value, max_len=_MAX_CONTEXT_VALUE_LEN)}"
        for key, value in context.items()
    )


def record_stream_fault(
    component: str,
    exc: BaseException,
    *,
    logger: logging.Logger | None = None,
    context: dict[str, Any] | None = None,
    level: int | None = None,
    fault: str | None = None,
) -> str:
    """Classify, count, and log ``exc`` once per throttle window.

    ``component`` is the listener/stream identity ("ws_discovery.redis_listener").
    Returns the fault class so the caller can branch on it — the caller, not
    this function, decides whether to continue, reconnect, or close.
    """
    fault_class = fault or classify_fault(exc)
    key = (component, fault_class)
    with _lock:
        _counts[key] = _counts.get(key, 0) + 1
        throttle = _throttles.get(key)
        if throttle is None:
            throttle = _Throttle()
            _throttles[key] = throttle
        suppressed = throttle.take(time.monotonic())
    _FAULT_COUNTER.labels(component=component, fault=fault_class).inc()

    if suppressed is None:
        return fault_class

    emit_level = _DEFAULT_LEVEL.get(fault_class, logging.ERROR) if level is None else level
    target = logger if logger is not None else _logger
    target.log(
        emit_level,
        "stream fault component=%s fault=%s %s error=%s:%s%s",
        component,
        fault_class,
        _format_context(context),
        type(exc).__name__,
        safe_log_fragment(exc),
        f" (suppressed={suppressed} in the last {_LOG_INTERVAL_S:.0f}s)" if suppressed else "",
        exc_info=(fault_class == FAULT_UNEXPECTED),
    )
    return fault_class


async def close_stream_socket(websocket: Any, *, component: str, code: int) -> None:
    """Close a WebSocket a listener can no longer feed, without raising.

    REL-07's acceptance is that a stream "recovers or closes explicitly". A
    fan-out task that gives up while leaving its socket open is the failure this
    prevents: the client keeps receiving keep-alive pings and never learns that
    no events will follow, so it never reconnects. ``websocket`` is a Starlette
    ``WebSocket``; it is typed loosely so this module stays free of a web
    framework import.

    A close that itself fails means the peer is already gone, which is the
    outcome we wanted — it is counted, not raised.
    """
    try:
        if getattr(websocket, "client_state", None) is not None:
            from starlette.websockets import WebSocketState

            if websocket.client_state is WebSocketState.DISCONNECTED:
                return
        await websocket.close(code=code)
    except Exception as exc:  # noqa: BLE001 - counted below, never propagated
        record_stream_fault(f"{component}.close", exc, fault=FAULT_PEER_GONE)


def stream_fault_counts() -> dict[str, int]:
    """Snapshot of fault counts keyed ``"<component>/<fault>"``."""
    with _lock:
        return {f"{component}/{fault}": count for (component, fault), count in _counts.items()}


def reset_stream_faults() -> None:
    """Clear counters and throttle state. Test-support only."""
    with _lock:
        _counts.clear()
        _throttles.clear()
