"""The metrics RC-05's service objectives are measured from.

RC-05 publishes availability, latency and freshness targets, and its acceptance
clause requires that the SRV-03 tests "produce the named metrics". Targets with
no measurement source in the product are candidate targets, not promises, so
this module is where the process-lifetime series live:

* ``circuitbreaker_http_requests_total`` and
  ``circuitbreaker_http_request_duration_seconds`` — the API availability and
  latency indicators.
* ``circuitbreaker_health_state`` — the RC-05 health-state contract as a
  series, so "how long was it degraded" is answerable after the fact.
* ``circuitbreaker_write_admission_rejections_total`` — how often readiness
  actually refused a write (SRV-03), by the state that refused it.
* ``circuitbreaker_background_job_runs_total`` — background job outcomes,
  including the ``skipped_not_owner`` outcome that makes SRV-02's single-owner
  claim observable rather than merely asserted.

Cardinality is the reason these are defined here rather than at each call site.
SRV-09 requires that label sets cannot grow with traffic: the HTTP series are
labelled with the *route template* the request matched (never the raw path,
which carries ids), the status is bucketed into a class, and an unmatched
request collapses to a single ``unmatched`` label value.

The registry is private to this module. ``app.api.metrics`` appends its
exposition to the inventory metrics it builds per scrape, because those are
point-in-time gauges read from the database while these are counters that must
survive across scrapes.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp, Receive, Scope, Send

#: Process-lifetime registry. Separate from the per-scrape registry in
#: app.api.metrics so counters are not reset every time Prometheus scrapes.
REGISTRY = CollectorRegistry(auto_describe=False)

#: Every state RC-05 names, so a scrape always carries the full series and an
#: alert can fire on `circuitbreaker_health_state{state="degraded"} == 1`
#: rather than on the absence of a label.
_HEALTH_STATES = ("starting", "ready", "degraded", "not_ready", "stopping")

#: Tuned for the RC-05 latency objective ("p95 under 500 ms for common
#: inventory reads"): the boundary being measured must be a bucket edge.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_UNMATCHED_ROUTE = "unmatched"

http_requests_total = Counter(
    "circuitbreaker_http_requests_total",
    "HTTP requests served, by route template and response status class",
    ["method", "route", "status_class"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "circuitbreaker_http_request_duration_seconds",
    "HTTP request duration in seconds, by route template",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

health_state = Gauge(
    "circuitbreaker_health_state",
    "RC-05 health state of this process (1 for the current state, 0 otherwise)",
    ["state"],
    registry=REGISTRY,
)

write_admission_rejections_total = Counter(
    "circuitbreaker_write_admission_rejections_total",
    "Mutating API requests refused because readiness could not serve them safely",
    ["health"],
    registry=REGISTRY,
)

background_job_runs_total = Counter(
    "circuitbreaker_background_job_runs_total",
    "Background job executions by job id and outcome (ran, failed, skipped_not_owner)",
    ["job", "outcome"],
    registry=REGISTRY,
)

process_uptime_seconds = Gauge(
    "circuitbreaker_process_uptime_seconds",
    "Seconds since this process finished importing",
    registry=REGISTRY,
)

_PROCESS_START = time.monotonic()

for _state in _HEALTH_STATES:
    health_state.labels(state=_state).set(0)


# ── Recording helpers ──────────────────────────────────────────────────────


def record_health_state(state: str) -> None:
    """Publish the current RC-05 health state as a one-hot gauge."""
    for known in _HEALTH_STATES:
        health_state.labels(state=known).set(1 if known == state else 0)


def record_write_rejected(health: str) -> None:
    write_admission_rejections_total.labels(health=health).inc()


def record_job_run(job_id: str, outcome: str) -> None:
    """Record one background job execution. `job_id` is a fixed registry key."""
    background_job_runs_total.labels(job=job_id, outcome=outcome).inc()


def refresh_process_gauges() -> None:
    process_uptime_seconds.set(time.monotonic() - _PROCESS_START)


def exposition() -> bytes:
    """Prometheus text exposition for the process-lifetime series."""
    from prometheus_client import generate_latest

    refresh_process_gauges()
    return generate_latest(REGISTRY)


# ── HTTP instrumentation ───────────────────────────────────────────────────


def _route_label(path: str, scope: Scope) -> str:
    """The route *template* the request matched, or `unmatched`.

    Built from the path parameters the router bound rather than from a route
    table: this FastAPI version includes routers by reference (`app.routes`
    holds `_IncludedRouter` objects, not the endpoints), so there is no
    table to look the endpoint up in, and reading one would tie this to a
    private structure that has already changed once.

    Substituting the bound values back out of the path is what bounds the
    cardinality: `/api/v1/hardware/4711` and `/api/v1/hardware/4712` both
    become `/api/v1/hardware/{item_id}`, so a series cannot be created per
    inventory object. The path passed in is the one the request arrived with —
    a `Mount` rewrites `scope["path"]` for the sub-application it delegates to.
    """
    if scope.get("endpoint") is None:
        return _UNMATCHED_ROUTE
    params = scope.get("path_params") or {}
    if not params:
        return path
    template = path
    # Longest first: a shorter value that is a substring of a longer one would
    # otherwise corrupt the longer replacement.
    for name, value in sorted(params.items(), key=lambda kv: -len(str(kv[1]))):
        text = str(value)
        if text and text in template:
            template = template.replace(text, "{" + name + "}")
    return template


class HttpMetricsMiddleware:
    """Count and time every HTTP request (RC-05 availability and latency SLIs).

    Outermost in the stack on purpose: what a user experiences includes the
    time every other middleware spends, and a response produced by one of them
    (a rate-limit 429, a readiness 503) is still a served request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        # Captured before the call: a Mount rewrites scope["path"] in place.
        path = scope.get("path", "")
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def _send(message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            elapsed = time.perf_counter() - started
            route = _route_label(path, scope)
            status_class = f"{status_holder['status'] // 100}xx"
            http_requests_total.labels(method=method, route=route, status_class=status_class).inc()
            http_request_duration_seconds.labels(method=method, route=route).observe(elapsed)
