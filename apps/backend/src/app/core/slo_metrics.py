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

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

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

#: Task 1c (observability phase 2): buckets small enough to distinguish a
#: healthy loop (sub-millisecond) from one that is starting to starve, since
#: this histogram exists specifically to answer "how blocked does it get",
#: not just "is it blocked".
_LOOP_LAG_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

#: How often the sampler in `run_event_loop_lag_sampler` sleeps between
#: samples, and therefore also the sleep duration the observed lag is measured
#: against. A 100ms cadence is cheap enough to run unconditionally in
#: production and fine-grained enough to catch a blocking call in the seconds
#: after it starts.
_LOOP_LAG_SAMPLE_INTERVAL_SECONDS = 0.1

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

event_loop_lag_seconds = Gauge(
    "circuitbreaker_event_loop_lag_seconds",
    "Most recently observed asyncio event loop scheduling lag, in seconds",
    registry=REGISTRY,
)

event_loop_lag_seconds_hist = Histogram(
    "circuitbreaker_event_loop_lag_seconds_hist",
    "Distribution of observed asyncio event loop scheduling lag, in seconds",
    buckets=_LOOP_LAG_BUCKETS,
    registry=REGISTRY,
)

# ── Connection-pool saturation (route §5: "DB pool utilization + pool_timeout
# events") ─────────────────────────────────────────────────────────────────
# These live here rather than in `app.api.metrics` because the timeout counter
# has to survive across scrapes, and splitting a pool's utilization gauges from
# its exhaustion counter across two registries would mean reading two different
# exposition blocks to answer one question. The gauges are refreshed from the
# live engine pool in `exposition()`, so they are point-in-time reads that
# happen to be published from the process-lifetime registry.

db_pool_size = Gauge(
    "circuitbreaker_db_pool_size",
    "Configured size of the synchronous SQLAlchemy connection pool",
    registry=REGISTRY,
)

db_pool_checked_out = Gauge(
    "circuitbreaker_db_pool_checked_out",
    "Connections currently checked out of the synchronous pool",
    registry=REGISTRY,
)

db_pool_checked_in = Gauge(
    "circuitbreaker_db_pool_checked_in",
    "Connections currently idle in the synchronous pool",
    registry=REGISTRY,
)

db_pool_overflow = Gauge(
    "circuitbreaker_db_pool_overflow",
    "Overflow connections beyond the configured pool size (negative until the pool is full)",
    registry=REGISTRY,
)

db_pool_timeouts_total = Counter(
    "circuitbreaker_db_pool_timeouts_total",
    "Requests that failed because the connection pool did not free a slot within pool_timeout",
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


def record_db_pool_timeout() -> None:
    """Count one connection-pool exhaustion (`pool_timeout` elapsed)."""
    db_pool_timeouts_total.inc()


def refresh_db_pool_gauges() -> None:
    """Read the live pool's occupancy onto the gauges, best-effort.

    Imported lazily because `app.db.session` builds the engine at import time
    and raises when `CB_DB_URL` is unset — a metrics scrape must not be what
    turns a configuration problem into an import error, and `core` must not
    take a load-time dependency on `db`.

    Only `QueuePool` keeps occupancy counters. A `NullPool` — which some test
    configurations substitute — has nothing to report, and the gauges are left
    at whatever they last held rather than being zeroed: an unmeasurable pool is
    not an empty one, and publishing zeros would be a false reading.
    """
    try:
        from sqlalchemy.pool import QueuePool

        from app.db.session import engine

        pool = engine.pool
        if not isinstance(pool, QueuePool):
            _logger.debug(
                "[slo_metrics] %s does not expose occupancy counters", type(pool).__name__
            )
            return
        db_pool_size.set(pool.size())
        db_pool_checked_out.set(pool.checkedout())
        db_pool_checked_in.set(pool.checkedin())
        db_pool_overflow.set(pool.overflow())
    except Exception as exc:  # noqa: BLE001 - a scrape must never fail on instrumentation
        _logger.warning("[slo_metrics] db pool gauge refresh failed: %s", exc)


def record_loop_lag(lag_seconds: float) -> None:
    """Record one event-loop-lag sample onto both the gauge and the histogram."""
    event_loop_lag_seconds.set(lag_seconds)
    event_loop_lag_seconds_hist.observe(lag_seconds)


async def run_event_loop_lag_sampler() -> None:
    """Sample asyncio event-loop scheduling lag until cancelled.

    Sleeps for `_LOOP_LAG_SAMPLE_INTERVAL_SECONDS` and measures how much
    longer the sleep actually took than requested with
    `time.perf_counter()` — the amount of time the loop spent doing something
    else instead of waking this task on schedule, which is a direct measure
    of whether the event loop is being blocked by synchronous work.

    Meant to run as a background `asyncio.Task` for the life of the process
    (started from the FastAPI lifespan in `main.py`). Cancellation is the
    normal way to stop it: `asyncio.CancelledError` is deliberately not
    caught here, so `task.cancel()` followed by `await task` behaves exactly
    like cancelling any other task and the caller decides how to swallow it.
    Any other exception is logged and the loop continues — a broken sampler
    must not take the rest of the process down with it, and must not stop
    producing samples over one bad measurement.
    """
    while True:
        started = time.perf_counter()
        await asyncio.sleep(_LOOP_LAG_SAMPLE_INTERVAL_SECONDS)
        try:
            elapsed = time.perf_counter() - started
            lag = max(0.0, elapsed - _LOOP_LAG_SAMPLE_INTERVAL_SECONDS)
            record_loop_lag(lag)
        except Exception as exc:  # noqa: BLE001 - a broken sampler must not crash the process
            _logger.warning("[slo_metrics] event loop lag sample failed: %s", exc)


def exposition() -> bytes:
    """Prometheus text exposition for the process-lifetime series."""
    from prometheus_client import generate_latest

    refresh_process_gauges()
    refresh_db_pool_gauges()
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

        async def _send(message: Message) -> None:
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
