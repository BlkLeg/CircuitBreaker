"""Readiness that rejects writes, rather than merely reporting on them (SRV-03).

SRV-03's second normative clause is "readiness rejects writes when they cannot
be served safely". A 503 on `/readyz` only *advertises* that; it takes an
orchestrator to act on it, and nothing at all stops the write that arrives
before the load balancer notices. This middleware is the enforcement half:
every mutating request to the versioned API is admitted only while
`app.core.health` says a write is safe.

Two rejection sources, with deliberately different scope:

* **Dependency facts.** A required dependency that cannot answer (PostgreSQL,
  or a schema that does not match this build) rejects writes unconditionally.
  Nothing has to arm it, because nothing about it is a matter of policy — the
  write cannot be persisted.
* **Lifecycle transitions.** STARTING and STOPPING reject writes only in a
  process whose ASGI lifespan is actually driving the lifecycle state, which
  `arm()` records at startup and `disarm()` clears once shutdown has finished
  and the server has stopped accepting. Under uvicorn/hypercorn no request can
  even reach the app before lifespan startup completes, so this costs nothing
  in production; it keeps the guard from firing in an embedded or test host
  that mounts the ASGI app with no lifespan at all and therefore leaves the
  lifecycle state at its import-time default.

Deliberately *not* guarded: reads, WebSocket sessions (an established agent
link is drained by the lifespan, not refused mid-frame), and the health
endpoints themselves — RC-05's contract keeps health and diagnostics safe in
every state, which is exactly when an operator needs them most.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.health import HealthState, current_health

_logger = logging.getLogger(__name__)

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_GUARDED_PREFIX = "/api/"

#: Health and diagnostics stay reachable in every state. They are GET/HEAD
#: today; naming them keeps that true if one ever grows a POST form.
_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/livez",
        "/api/v1/readyz",
        "/api/v1/startupz",
        "/api/v1/health",
    }
)

#: Machine-readable error codes for the two refusals, so a client can tell
#: "come back later, nothing happened" from "your request was wrong".
ERROR_CODE_NOT_READY = "SERVICE_NOT_READY"
ERROR_CODE_DRAINING = "SERVER_DRAINING"

#: What a client should wait before retrying. Short: both conditions clear on
#: their own — a dependency comes back, or a replacement process finishes
#: starting — and a long value would strand a caller past the recovery.
_RETRY_AFTER_S = "5"

_gate_armed: bool = False


def arm() -> None:
    """Record that this process's ASGI lifespan owns the lifecycle state."""
    global _gate_armed
    _gate_armed = True


def disarm() -> None:
    """Release the lifecycle gate once shutdown has finished.

    Called at the very end of lifespan shutdown, after the drain: the server
    has stopped accepting by then, so in production this changes nothing. It
    exists so that an in-process host which runs the lifespan and then keeps
    using the app object does not inherit a permanently closed gate from a
    lifecycle that already ended.
    """
    global _gate_armed
    _gate_armed = False


def is_armed() -> bool:
    return _gate_armed


def _rejection(state: HealthState, reason: str | None) -> JSONResponse:
    draining = state is HealthState.STOPPING
    detail = (
        "Server is shutting down and is no longer accepting writes."
        if draining
        else f"Server cannot serve writes safely: {reason or state.value}."
    )
    return JSONResponse(
        status_code=503,
        content={
            "error_code": ERROR_CODE_DRAINING if draining else ERROR_CODE_NOT_READY,
            "detail": detail,
            "health": state.value,
        },
        headers={"Retry-After": _RETRY_AFTER_S},
    )


class WriteAdmissionMiddleware:
    """Refuse mutating API requests the server cannot serve safely."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if (
            method not in _MUTATING_METHODS
            or not path.startswith(_GUARDED_PREFIX)
            or path in _EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        snapshot = await current_health()
        if snapshot.writes_permitted:
            await self.app(scope, receive, send)
            return
        if snapshot.state in (HealthState.STARTING, HealthState.STOPPING) and not _gate_armed:
            await self.app(scope, receive, send)
            return

        from app.core import slo_metrics

        slo_metrics.record_write_rejected(snapshot.state.value)
        _logger.warning(
            "write rejected: %s %s refused while health=%s (%s)",
            method,
            path,
            snapshot.state.value,
            snapshot.reason,
        )
        await _rejection(snapshot.state, snapshot.reason)(scope, receive, send)
