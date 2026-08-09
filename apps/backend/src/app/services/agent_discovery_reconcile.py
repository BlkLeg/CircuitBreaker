"""The owner of an agent discovery job nobody else will ever look at (D-5).

Three jobs have no owner in the product without this pass, and each of them is
a job an operator was told would run:

1. **A lease whose agent went silent.** `dispatch_deadline_at` passed and no
   terminal summary arrived. Nothing on the `/link` read loop fires for an agent
   that is not there, so the job stays `running` forever while holding a
   `discovery_scheduler._running_scan_count` slot and doing no work — the
   wedged-item failure `probe_reconcile` exists to prevent on the remote probe
   path, in this table.
2. **A job parked in `waiting_for_agent`.** D-5 deliberately gives the claim
   back and leaves the job `queued` so it consumes no slot, which is correct and
   is also exactly why nothing looks at it again.
3. **The `queued` backlog itself.** `discovery_scheduler._schedule_queued_scan_jobs`
   has one caller — `discovery_service._scan_finalize` — so a job that failed to
   claim a slot waits for some *other* job to finish, and on an idle server that
   is forever.

`monitoring/probe_reconcile` is the model, and the one thing this borrows from
it above all is that **the grace is derived, never chosen**: a lease is written
off at the exact moment `agent_discovery.ingest_discovery_finding` stops
accepting findings against it, so a finding can never be simultaneously still
acceptable over there and attached to a dispatch already given up on here.
The two modules differ in one respect and it is stated at
`run_agent_discovery_reconciliation`: `probe_reconcile` rides
`monitor_scheduler.tick`, which is already the single active clock under the
`monitor_scheduler` advisory lock, so it deliberately holds no lock of its own.
This pass runs standalone from `main.py`'s lifespan and every replica would
otherwise run it at once, so it holds one.

Three passes, in this order and for these reasons:

* **Expire the dead leases** first, so the concurrency slot a silent agent was
  holding is free before anything counts slots.
* **Expire the parked jobs** whose deadline passed, before the retry — a pass
  that retried first would hand the job to `dispatch_discovery_job`, which
  parks it again with `dispatch_deadline_at = now + DISPATCH_DEADLINE_S`, and a
  deadline rewritten once a minute is one that never arrives.
* **Drain the backlog**, gating the parked jobs on the agent actually being
  back for the same reason.

Nothing here writes, moves or deletes a `ScanResult`. D-4 is explicit that an
interrupted agent scan is `failed` with its findings **retained** and
reviewable: there is no `partial` status, and the hosts the agent did report
before it went quiet were really observed.

**`services/discovery_reconciler.py` is not imported here and must not be.**
D-5 says so outright: that module heals discovery *readiness* — whether `nmap`
is present and capable on the server — and touches no `ScanJob` row. The two
share a word and nothing else, and `tests/services/test_agent_discovery_reconcile.py`
asserts the boundary against this file's own source.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.job_lock import run_with_advisory_lock
from app.core.time import utcnow
from app.db.models import ScanJob
from app.db.session import SessionLocal
from app.services import agent_discovery, agent_registry, discovery_scheduler, discovery_service
from app.services.settings_service import get_or_create_settings

_logger = logging.getLogger(__name__)

# The advisory lock this pass holds, and the APScheduler job id it registers
# under. One name for both so an operator reading `pg_locks` and an operator
# reading the scheduler's job list are looking at the same thing.
LOCK_NAME = "agent_discovery_reconcile"

# How often the pass runs. A dispatch deadline is measured in minutes, so the
# only thing a shorter interval buys is a faster retry after a reconnect —
# which is the case that matters most, because it is the one an operator is
# watching a spinner for.
RECONCILE_INTERVAL_S = int(os.getenv("CB_DISCOVERY_RECONCILE_INTERVAL_S", "60"))

# The window `agent_discovery` still accepts a late finding in, taken from that
# module's own constant rather than restated. `probe_reconcile` derives
# `RESULT_TIMEOUT_GRACE_S` from `agent_probe.LATE_RESULT_GRACE` for precisely
# this reason: two independently-chosen numbers would let a finding be refused
# as `late_finding` while its dispatch was still open here, or accepted here
# against a dispatch already expired.
LEASE_GRACE_S = int(agent_discovery.LATE_FINDING_GRACE.total_seconds())

# D-5's parking horizon, from the module that stamps it onto the row. Used for
# the rows that carry no `dispatch_deadline_at` of their own — see `_horizon`.
WAITING_HORIZON_S = agent_discovery.DISPATCH_DEADLINE_S

# `scan_jobs.dispatch_status` for a lease the server gave up on.
# `db/models.py` names `expired` in the column's vocabulary and
# `agent_discovery` declines to define it ("`expired` is Task 23's"), because
# this is the only module that can write it: `finalize_agent_job` maps every
# `failed` job onto `execution_error`, which is the agent's own word for a scan
# that ran and went wrong. These scans never ran, or stopped reporting.
DISPATCH_STATUS_EXPIRED = "expired"

# One pass must stay bounded — it holds the advisory lock while it runs. Both
# limits are self-clearing in the steady state (a lease expires once, a job is
# dispatched once) and only bite while a backlog is being worked off.
_EXPIRE_LIMIT = 200
_DRAIN_LIMIT = 200


@dataclass(frozen=True)
class ReconcileSummary:
    """What one pass did, for the caller's logs and for the tests."""

    # Leases whose agent stopped reporting mid-scan (D-4 `agent_disconnected`).
    disconnected: int = 0
    # Parked jobs whose agent never came back (D-4 `agent_unavailable`).
    unavailable: int = 0
    # Jobs handed to `agent_discovery.dispatch_discovery_job` and accepted by it.
    dispatched: int = 0
    # Queued *server* jobs handed to the ordinary fire-and-forget scan executor.
    scheduled: int = 0

    def __bool__(self) -> bool:
        return bool(self.disconnected or self.unavailable or self.dispatched or self.scheduled)


async def reconcile(db: Session, *, now: datetime | None = None) -> ReconcileSummary:
    """Run one whole pass. Owns its commits; `now` is for tests to pin the clock."""
    moment = now or utcnow()

    disconnected = await _expire_dead_leases(db, moment)
    unavailable = await _expire_parked_jobs(db, moment)
    dispatched, scheduled = await _drain_queued_jobs(db)

    summary = ReconcileSummary(
        disconnected=disconnected,
        unavailable=unavailable,
        dispatched=dispatched,
        scheduled=scheduled,
    )
    if summary:
        _logger.info(
            "agent discovery reconcile: %d disconnected, %d unavailable, "
            "%d dispatched, %d scheduled",
            disconnected,
            unavailable,
            dispatched,
            scheduled,
        )
    return summary


# ── Pass 1: a lease whose agent went silent ───────────────────────────────────


async def _expire_dead_leases(db: Session, moment: datetime) -> int:
    """Fail every open dispatch whose deadline plus the ingest grace has passed.

    `agent_discovery`'s own definition of "still open" is reused rather than
    restated — the set of `dispatch_status`/`status` values reached for here is
    exactly the set `_assert_dispatch_open` still admits a finding under, so the
    two can never disagree about whether a lease is live.

    D-4: `failed`, not a sixth status, and the accepted findings stay exactly
    where they are.
    """
    cutoff = moment - timedelta(seconds=LEASE_GRACE_S)
    candidates = db.execute(
        select(ScanJob)
        .where(
            ScanJob.scan_agent_id.is_not(None),
            ScanJob.status.in_(sorted(agent_discovery._OPEN_JOB_STATUSES)),
            ScanJob.dispatch_status.in_(sorted(agent_discovery._OPEN_DISPATCH_STATUSES)),
        )
        .order_by(ScanJob.id)
        .limit(_EXPIRE_LIMIT)
    ).scalars()

    expired = 0
    for job in list(candidates):
        if _horizon(job, moment) >= cutoff:
            continue
        if await _expire(db, job, agent_discovery.ERROR_AGENT_DISCONNECTED):
            expired += 1
    return expired


# ── Pass 2: a parked job whose agent never came back ──────────────────────────


async def _expire_parked_jobs(db: Session, moment: datetime) -> int:
    """Fail every `waiting_for_agent` job past its deadline (D-5, D-4).

    No grace is added here, unlike the lease pass. `_release_to_waiting` clears
    `dispatch_id` along with the claim, so no request was ever published under a
    token the agent could quote and there is no finding in flight to be fair to.
    """
    candidates = db.execute(
        select(ScanJob)
        .where(
            ScanJob.scan_agent_id.is_not(None),
            ScanJob.status == "queued",
            ScanJob.progress_phase == agent_discovery.PHASE_WAITING_FOR_AGENT,
        )
        .order_by(ScanJob.id)
        .limit(_EXPIRE_LIMIT)
    ).scalars()

    expired = 0
    for job in list(candidates):
        if _horizon(job, moment) >= moment:
            continue
        if await _expire(db, job, agent_discovery.ERROR_AGENT_UNAVAILABLE):
            expired += 1
    return expired


async def _expire(db: Session, job: ScanJob, error_reason: str) -> bool:
    """Close one given-up job. Returns whether *this* call closed it.

    `finalize_agent_job` is the one closer for an agent job and is reused whole:
    it is a compare-and-set, so two workers reaching the same row write one
    terminal status, one `scan_failed` audit row and one `job_update` between
    them — which is what makes this pass idempotent without a lock, and the lock
    a defence against wasted work rather than against corruption.
    """
    closed = await discovery_service.finalize_agent_job(
        db, job, "failed", error_reason=error_reason, error_text=error_reason
    )
    if not closed:
        return False
    # After the finalization, never inside it: the `failed -> execution_error`
    # mapping belongs to `discovery_service`, and a row that is momentarily
    # `execution_error` is already closed to ingest either way, so the narrower
    # word costs nothing and tells an operator which of the two happened.
    job.dispatch_status = DISPATCH_STATUS_EXPIRED
    db.commit()
    return True


def _horizon(job: ScanJob, moment: datetime) -> datetime:
    """When this job stops being worth waiting for.

    `dispatch_deadline_at` is the real clock and is what both the dispatcher and
    the ingest path judge against. A row without one is not thereby immortal —
    `probe_reconcile` coalesces onto `scheduled_at` for exactly this reason, and
    D-5's own `DISPATCH_DEADLINE_S` measured from the job's creation is this
    table's equivalent. An unparseable `created_at` is the one case that refuses
    to guess: the job is left for the drain rather than failed on a clock
    nobody can read.
    """
    if job.dispatch_deadline_at is not None:
        # `scan_jobs` admits naive datetimes; `agent_discovery` already owns the
        # one place that decides what a naive one means, and a second answer
        # here is how the two paths come to disagree by the length of a UTC
        # offset.
        return agent_discovery._aware(job.dispatch_deadline_at)
    created = _parsed(job.created_at)
    if created is None:
        return moment + timedelta(seconds=WAITING_HORIZON_S)
    return created + timedelta(seconds=WAITING_HORIZON_S)


def _parsed(value: str | None) -> datetime | None:
    """`scan_jobs.created_at` is an ISO string column, not a timestamp."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# ── Pass 3: the queued backlog ────────────────────────────────────────────────


async def _drain_queued_jobs(db: Session) -> tuple[int, int]:
    """Start what the ceiling allows. Returns `(dispatched, scheduled)`.

    `_schedule_queued_scan_jobs`'s job, done here because nothing else does it
    outside `_scan_finalize`, and deliberately not by calling it. That function
    now carries a parked-job guard of its own (`discovery_scheduler.py`: it
    filters `progress_phase IS DISTINCT FROM 'waiting_for_agent'` in SQL), but
    the two guards are not the same guard and neither is redundant. Its one is
    unconditional — it fires on *every* job completion anywhere and has no
    presence information, so a parked job is simply not its business, and
    handing one back to `dispatch_discovery_job` while the agent is still away
    has `agent_discovery._release_to_waiting` stamp a fresh
    `dispatch_deadline_at` over the deadline that was about to expire it.
    This one is conditional on `bulk_presence`, because un-parking a job whose
    agent has *come back* is precisely what this pass exists to do, and presence
    is the only thing that can tell those two cases apart. Deleting either would
    lose a behaviour: the scheduler's, and the backlog would never drain for an
    agent that returned.

    An agent job is awaited rather than fired and forgotten, because
    `dispatch_discovery_job` is a handful of indexed reads and one published
    frame; a server job is fired and forgotten through the ordinary entry
    point, because awaiting an nmap sweep would hold the advisory lock for its
    whole duration.
    """
    settings = get_or_create_settings(db)
    # Both borrowed from the scheduler that defines the ceiling. A second
    # opinion here about how many scans may run at once is how an agent job
    # comes to be exempt from a limit the operator set for all of them.
    slots = discovery_scheduler._max_concurrent_scans(
        settings
    ) - discovery_scheduler._running_scan_count(db)
    if slots <= 0:
        return 0, 0

    candidates = list(
        db.execute(
            select(ScanJob)
            .where(ScanJob.status == "queued")
            .order_by(ScanJob.created_at.asc(), ScanJob.id.asc())
            .limit(_DRAIN_LIMIT)
        ).scalars()
    )
    if not candidates:
        return 0, 0

    # One Redis round trip for the whole batch, as `probe_reconcile` does. Only
    # the parked jobs consult it: a job that has never been claimed still goes
    # to the dispatcher when its agent is away, because being parked with a
    # deadline is precisely what should happen to it next.
    presence = await agent_registry.bulk_presence(
        sorted({job.scan_agent_id for job in candidates if job.scan_agent_id is not None})
    )

    dispatched = 0
    scheduled = 0
    for job in candidates:
        if slots <= 0:
            break
        if job.scan_agent_id is None:
            discovery_service.schedule_discovery_scan_job(job.id)
            scheduled += 1
        else:
            if job.progress_phase == agent_discovery.PHASE_WAITING_FOR_AGENT and not presence.get(
                job.scan_agent_id, {}
            ).get("online"):
                continue
            if not await agent_discovery.dispatch_discovery_job(db, job.id):
                # Parked again, claimed by another worker, or closed with a
                # reason — the dispatcher already wrote whichever it was, and
                # none of them took a slot.
                continue
            dispatched += 1
        slots -= 1
    return dispatched, scheduled


# ── The scheduled entry point ─────────────────────────────────────────────────


async def _reconcile_once() -> None:
    """One pass on its own session, with its own failure swallowed.

    A reconciliation defect must not be able to stop the scheduler or leave the
    advisory lock held — `monitor_scheduler.tick` guards its call into
    `probe_reconcile` for the same reason.
    """
    with SessionLocal() as db:
        try:
            await reconcile(db)
        except Exception:
            _logger.exception("agent discovery reconciliation pass failed")
            db.rollback()


async def run_agent_discovery_reconciliation() -> None:
    """APScheduler entry point, registered on an `IntervalTrigger` in `main.py`'s
    lifespan (D-5) — **not** in `core.scheduler.reload_discovery_jobs`, which is
    re-invoked on every profile write and first removes every job it registered.

    A coroutine on purpose. `AsyncIOScheduler` runs a coroutine job on the event
    loop and a plain function in its thread pool, and this pass belongs on the
    loop: `discovery_service.schedule_discovery_scan_job` starts the server-scan
    executor, and its first choice is `asyncio.create_task` on the calling
    thread's loop. Off the loop it no longer raises — it falls back to
    `run_coroutine_threadsafe` on `discovery_scheduler.main_loop()`, which is
    what made `_scan_finalize` safe to call the same drain from a
    `run_in_executor` worker thread — but that fallback is a recovery, and this
    pass does not need it: awaiting the dispatcher directly and calling
    `create_task` from the loop it belongs to keeps every WebSocket event this
    pass produces on the loop that owns the connections.

    The lock is taken in a worker thread and the pass handed straight back to
    the loop from inside it, because `run_with_advisory_lock` holds a
    session-level Postgres lock for the whole of `job_fn` and `job_fn` is
    synchronous. That keeps the lock held across the entire pass while never
    blocking the loop on the lock's own round trip.
    """
    loop = asyncio.get_running_loop()

    def _under_lock() -> None:
        # `_reconcile_once` never raises, so this future always resolves and the
        # lock is always released.
        asyncio.run_coroutine_threadsafe(_reconcile_once(), loop).result()

    await asyncio.to_thread(run_with_advisory_lock, LOCK_NAME, job_fn=_under_lock)


__all__ = [
    "DISPATCH_STATUS_EXPIRED",
    "LEASE_GRACE_S",
    "LOCK_NAME",
    "RECONCILE_INTERVAL_S",
    "WAITING_HORIZON_S",
    "ReconcileSummary",
    "reconcile",
    "run_agent_discovery_reconciliation",
]
