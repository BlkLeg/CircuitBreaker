"""The health-state contract: what a caller may safely do right now (SRV-03, RC-05).

`app.core.server_state` answers a different question — where this *process* is
in its own startup/shutdown cycle. That is not the same as what an operation
may safely do: a process whose lifecycle says READY is still unable to serve a
write when PostgreSQL is unreachable, and a process that is draining can still
serve reads it has already admitted. RC-05's health-state table names five
user-visible states, so this module derives them from two facts the process
already has — the lifecycle state and a bounded dependency probe — rather than
adding states to the lifecycle enum, which describes something else.

Two consumers, deliberately with different freshness rules:

* the health endpoints probe fresh on every call (`max_age_s=0`) — an
  orchestrator polling once every few seconds must never be answered from a
  cache it cannot see;
* the write-admission guard (`app.core.write_admission`) reads the cached
  snapshot, so a burst of writes cannot turn a dependency check into the load
  cascade that SRV-3's build sequence warns about.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

_logger = logging.getLogger(__name__)


class HealthState(StrEnum):
    """The five states RC-05's health-state table defines."""

    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"
    STOPPING = "stopping"


#: PostgreSQL is the source of truth (04-server-product-contract.md): without it
#: no write can be served safely, so its loss is NOT_READY, not DEGRADED.
REQUIRED_DEPENDENCIES: frozenset[str] = frozenset({"db"})

#: Redis is a disposable coordination layer. Losing it costs shared rate limits,
#: the telemetry cache and pub/sub — optional capability, not the inventory. Its
#: loss is DEGRADED: reads and inventory edits stay safe, so writes stay open.
OPTIONAL_DEPENDENCIES: frozenset[str] = frozenset({"redis"})

#: How long the guard may reuse a dependency verdict. Deliberately short: it
#: bounds how long a write can be admitted against a database that has just
#: gone away, and how many probes a burst of writes can trigger.
CACHE_TTL_S: float = float(os.environ.get("CB_HEALTH_CACHE_TTL_S", "2.0") or 2.0)


@dataclass(frozen=True)
class HealthSnapshot:
    """One evaluation of the health contract."""

    state: HealthState
    lifecycle: str
    checks: Mapping[str, str]
    degraded: tuple[str, ...]
    writes_permitted: bool
    reason: str | None
    observed_at: float

    def as_dict(self) -> dict[str, object]:
        return {
            "health": self.state.value,
            "degraded": list(self.degraded),
            "writes_permitted": self.writes_permitted,
        }


# ── Dependency probes ──────────────────────────────────────────────────────


def _probe_db() -> str:
    """Is the database reachable *and* is its schema the one this build needs?

    The second query is not decoration: a half-applied migration leaves a
    connectable database that cannot serve the discovery endpoints, and
    answering "ok" to that is how migration drift reaches users as a 500.
    """
    from sqlalchemy import text

    from app.db.session import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # Readiness contract check: discovery endpoints serialize ScanJob.error_reason.
            # If this column is missing (migration drift), report db as error.
            conn.execute(text("SELECT error_reason FROM scan_jobs LIMIT 1"))
    except Exception:
        return "error"
    return "ok"


async def probe_dependencies() -> dict[str, str]:
    """Bounded liveness of every dependency, keyed exactly as `/readyz` reports.

    `redis_health` is resolved from the module on every call rather than bound
    at import, so a test (and the emergency degraded-dependency switch) can
    substitute it without reaching into this module.
    """
    import app.core.redis as redis_module

    db_status = _probe_db()
    try:
        redis_ok = bool(await redis_module.redis_health())
    except Exception:
        redis_ok = False
    return {"db": db_status, "redis": "ok" if redis_ok else "error"}


# ── Classification ─────────────────────────────────────────────────────────


def classify(lifecycle_state: str, checks: Mapping[str, str]) -> HealthSnapshot:
    """Turn (lifecycle state, dependency verdicts) into the RC-05 health state.

    Ordering is the contract. Draining outranks dependency health — a process
    that is going away must stop admitting writes even while every dependency
    is green — and a required-dependency failure outranks an optional one,
    because "no database" is never merely degraded.
    """
    failed_required = tuple(
        sorted(name for name in REQUIRED_DEPENDENCIES if checks.get(name, "error") != "ok")
    )
    failed_optional = tuple(
        sorted(name for name in OPTIONAL_DEPENDENCIES if checks.get(name, "error") != "ok")
    )
    observed_at = time.monotonic()

    if lifecycle_state == "stopping":
        return HealthSnapshot(
            state=HealthState.STOPPING,
            lifecycle=lifecycle_state,
            checks=dict(checks),
            degraded=failed_optional,
            writes_permitted=False,
            reason="server is draining",
            observed_at=observed_at,
        )
    if lifecycle_state == "starting":
        return HealthSnapshot(
            state=HealthState.STARTING,
            lifecycle=lifecycle_state,
            checks=dict(checks),
            degraded=failed_optional,
            writes_permitted=False,
            reason="server is still starting up",
            observed_at=observed_at,
        )
    if failed_required:
        return HealthSnapshot(
            state=HealthState.NOT_READY,
            lifecycle=lifecycle_state,
            checks=dict(checks),
            degraded=failed_optional,
            writes_permitted=False,
            reason=f"required dependency unavailable: {', '.join(failed_required)}",
            observed_at=observed_at,
        )
    if failed_optional:
        return HealthSnapshot(
            state=HealthState.DEGRADED,
            lifecycle=lifecycle_state,
            checks=dict(checks),
            degraded=failed_optional,
            # RC-05: degraded means "read inventory, edit inventory when the
            # database is healthy". The database is healthy here by definition,
            # so a write is still safe — only work that would be dispatched
            # *through* the degraded capability is not.
            writes_permitted=True,
            reason=f"optional dependency unavailable: {', '.join(failed_optional)}",
            observed_at=observed_at,
        )
    return HealthSnapshot(
        state=HealthState.READY,
        lifecycle=lifecycle_state,
        checks=dict(checks),
        degraded=(),
        writes_permitted=True,
        reason=None,
        observed_at=observed_at,
    )


# ── Cached evaluation ──────────────────────────────────────────────────────

_cached: HealthSnapshot | None = None
_probe_started_at: float | None = None


def _cache_is_fresh(
    snapshot: HealthSnapshot | None, max_age_s: float, now: float, lifecycle: str
) -> bool:
    """A cached verdict is usable only while the lifecycle it was taken under still holds.

    Comparing the lifecycle rather than trusting the TTL is what makes SIGTERM
    immediate: the moment the lifespan marks the process STOPPING, every cached
    "writes are fine" answer is stale by construction, so a drain cannot admit
    one last write out of a cache the shutdown path forgot to invalidate.
    """
    return (
        snapshot is not None
        and snapshot.lifecycle == lifecycle
        and (now - snapshot.observed_at) < max_age_s
    )


async def current_health(*, max_age_s: float | None = None) -> HealthSnapshot:
    """The current health snapshot, probing at most once per `max_age_s`.

    Concurrency is handled without a lock on purpose: an `asyncio.Lock` binds
    to the first event loop that awaits it, and this module is imported once
    per process but used from every loop a test session creates. Instead a
    probe in flight is recorded, and callers arriving during it are served the
    previous verdict — at most one probe per window, no loop affinity, and no
    request ever blocked behind another request's database round trip.
    """
    global _cached, _probe_started_at

    from app.core import slo_metrics
    from app.core.server_state import get_state

    lifecycle = str(get_state())
    ttl = CACHE_TTL_S if max_age_s is None else max_age_s
    now = time.monotonic()
    if _cache_is_fresh(_cached, ttl, now, lifecycle):
        return _cached  # type: ignore[return-value]
    if (
        ttl > 0
        and _probe_started_at is not None
        and (now - _probe_started_at) < ttl
        and _cache_is_fresh(_cached, float("inf"), now, lifecycle)
    ):
        # A probe is already in flight for this same lifecycle; serve the last
        # verdict rather than piling a second round trip onto a dependency that
        # may be exactly the thing in trouble.
        return _cached  # type: ignore[return-value]

    _probe_started_at = now
    try:
        checks = await probe_dependencies()
    finally:
        _probe_started_at = None

    snapshot = classify(lifecycle, checks)
    _cached = snapshot
    slo_metrics.record_health_state(snapshot.state.value)
    return snapshot


def cached_health() -> HealthSnapshot | None:
    """The last evaluated snapshot, without probing. None before the first probe."""
    return _cached


def reset_cache() -> None:
    """Drop the cached verdict. For lifecycle transitions and for tests."""
    global _cached, _probe_started_at
    _cached = None
    _probe_started_at = None
