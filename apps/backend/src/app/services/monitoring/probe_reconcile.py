"""Expiry, staleness, and retention for remote probe runs (§8, D-4, D-5).

The backend stays the authority even when the executor goes quiet. A run is a
lease, and §1's partial unique index means an unreturned lease is not merely
untidy — it holds `(monitor_id) WHERE status IN ('queued','dispatched')` and
blocks every future run for that monitor. One silent agent would therefore wedge
its assignments permanently, which is the exact failure
`tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items`
exists to prevent on the server path. Expiry is what buys the remote path the
same property, and it is also what makes best-effort `probe.cancel` safe (§4).

This runs at the top of `workers/monitor_scheduler.py::tick` (D-5) — no new
worker, no `supervisord` entry, and no second advisory lock. `monitor_scheduler`
is already the single active clock, already holds the `monitor_scheduler`
advisory lock, and already opens a session per tick; anything else would need
its own leader election to avoid two replicas reconciling the same runs.

Three passes, in this order and for this reason:

1. **Expire.** A `queued`/`dispatched` run whose deadline passed more than
   `RESULT_TIMEOUT_GRACE_S` ago is written off: the run becomes `expired` and
   its monitor becomes `unavailable`/`result_timeout`. The grace matches the
   window `services/agent_probe.py` gives a late result, so the two can never
   disagree about whether a result was still allowed to land.
2. **Stale (D-4).** A vantage that is active, online, granted and readiness-fresh
   but has produced no accepted result within `2 x interval_secs` is `stale`:
   nothing is visibly wrong, and results are still not arriving. It is
   deliberately the *lower*-priority signal — `unavailable` always names a
   specific cause, so a monitor already carrying one is left alone, and so is a
   monitor with a run still in flight. Without that precedence the two passes
   would alternate every interval and write an event each time.
3. **Purge.** §1's seven-day retention, scheduled separately from the tick
   because it is a daily job, not a per-second one.

Nothing here writes an availability sample, touches `consecutive_failures`, or
moves `last_status` or `next_due_at`. An unavailable vantage is not a down
target (§2, D-12); the monitor simply tries again on its normal interval.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import AgentCapabilityReadiness, MonitorProbeRun
from app.services import agent_probe, agent_registry
from app.services.monitoring import probe_eligibility, result_service

logger = logging.getLogger(__name__)

# §4 gives a late result `deadline_at + 30s`, and a run is written off at exactly
# that moment — derived from the ingest path's own constant rather than restated,
# so a result can never be simultaneously "still acceptable" over there and
# attached to a run already expired over here.
RESULT_TIMEOUT_GRACE_S = int(agent_probe.LATE_RESULT_GRACE.total_seconds())
# D-4's threshold: no accepted result within two whole intervals.
STALE_INTERVAL_MULTIPLIER = 2
# §1. Long-term availability lives in `telemetry_timeseries` and the monitor
# rollups; a run row is audit for a check the server did not perform itself.
PROBE_RUN_RETENTION_DAYS = int(os.getenv("CB_MONITOR_PROBE_RETENTION_DAYS", "7"))

# `monitor_probe_runs.error_code` / `monitor_items.probe_execution_reason`, in
# `probe_eligibility`'s machine-readable vocabulary.
REASON_RESULT_TIMEOUT = "result_timeout"
REASON_NO_RECENT_RESULT = "no_recent_result"

# A single tick must stay bounded. Both passes are self-limiting in the steady
# state — an expired run is expired once, a stale monitor is marked once — so
# these caps only bite while a backlog is being worked off.
_EXPIRE_LIMIT = 500
_STALE_LIMIT = 500

# `:now` rather than `now()` so a test can pin the clock; the tick passes none
# and gets the server's own.
_EXPIRE_SQL = text(
    """
    UPDATE monitor_probe_runs
    SET status = 'expired',
        error_code = :reason,
        completed_at = :now
    WHERE id IN (
        SELECT id FROM monitor_probe_runs
        WHERE status IN ('queued', 'dispatched')
          -- coalesce, not a bare deadline_at: a run written without one would
          -- otherwise never expire and would hold the index forever. The
          -- dispatcher refuses to send such a run, so this is the belt to that
          -- braces.
          AND coalesce(deadline_at, scheduled_at) < :now - make_interval(secs => :grace)
        ORDER BY scheduled_at
        LIMIT :limit
    )
    RETURNING monitor_id
    """
)

# Everything D-4 can ask of the database. Readiness freshness and agent presence
# are answered in Python afterwards, against `probe_eligibility`'s own
# definitions, so this module never grows a second copy of them.
_STALE_CANDIDATES_SQL = text(
    """
    SELECT m.id AS monitor_id, m.probe_agent_id AS agent_id, m.check_type AS check_type
    FROM monitor_items m
    JOIN agents a ON a.id = m.probe_agent_id
    -- The grant row's own `enabled` flag, never its `config`: merged registry
    -- defaults are what `structured_grants_dict` is for, and no migration ever
    -- backfills a config.
    JOIN agent_capability_grants g
      ON g.agent_id = a.id AND g.capability = :capability AND g.enabled
    WHERE m.enabled
      AND m.probe_agent_id IS NOT NULL
      AND a.status = 'active'
      -- NULL is not stale: a monitor that has never produced a result has not
      -- stopped producing them, and D-4 is written against a real last result.
      AND m.probe_last_result_at IS NOT NULL
      AND m.probe_last_result_at
          < :now - make_interval(secs => :multiplier * m.interval_secs)
      -- `unavailable` already names a cause and outranks `stale`; re-marking a
      -- monitor that is already stale would only churn.
      AND coalesce(m.probe_execution_status, '') NOT IN ('unavailable', 'stale')
      AND NOT EXISTS (
          SELECT 1 FROM monitor_probe_runs pr
          WHERE pr.monitor_id = m.id AND pr.status IN ('queued', 'dispatched')
      )
    ORDER BY m.probe_last_result_at
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class ReconcileSummary:
    """What one pass did, for the caller's logs and for the tests."""

    expired: int = 0
    stale: int = 0


async def reconcile(db: Session, *, now: datetime | None = None) -> ReconcileSummary:
    """Expire overdue runs, then mark silent-but-healthy vantages stale.

    Owns its commit and publishes the live refreshes only after it returns, for
    the same reason `result_service.persist_results` does: a listener must never
    observe a condition that a rollback then erases.
    """
    moment = now or utcnow()
    live: list[dict] = []

    expired = _expire_overdue_runs(db, moment, live)
    stale = await _mark_stale(db, moment, live)
    db.commit()

    if live:
        await result_service.publish_results(result_service.PersistedResults(live_status=live))
    if expired or stale:
        logger.info("probe reconcile: %d run(s) expired, %d monitor(s) stale", expired, stale)
    return ReconcileSummary(expired=expired, stale=stale)


def _expire_overdue_runs(db: Session, moment: datetime, live: list[dict]) -> int:
    monitor_ids = [
        row.monitor_id
        for row in db.execute(
            _EXPIRE_SQL,
            {
                "reason": REASON_RESULT_TIMEOUT,
                "now": moment,
                "grace": RESULT_TIMEOUT_GRACE_S,
                "limit": _EXPIRE_LIMIT,
            },
        )
    ]
    for monitor_id in monitor_ids:
        entry = result_service.record_execution_condition(
            db,
            monitor_id,
            status=result_service.EXECUTION_UNAVAILABLE,
            reason=REASON_RESULT_TIMEOUT,
            occurred_at=moment,
        )
        if entry is not None:
            live.append(entry)
    return len(monitor_ids)


async def _mark_stale(db: Session, moment: datetime, live: list[dict]) -> int:
    candidates = list(
        db.execute(
            _STALE_CANDIDATES_SQL,
            {
                "capability": probe_eligibility.CAPABILITY,
                "now": moment,
                "multiplier": STALE_INTERVAL_MULTIPLIER,
                "limit": _STALE_LIMIT,
            },
        ).mappings()
    )
    if not candidates:
        return 0

    fresh = _fresh_readiness(db, {c["agent_id"] for c in candidates}, moment)
    presence = await agent_registry.bulk_presence(sorted({c["agent_id"] for c in candidates}))

    marked = 0
    for candidate in candidates:
        agent_id = candidate["agent_id"]
        if not presence.get(agent_id, {}).get("online"):
            # Offline is a known cause, and the dispatcher records it as such.
            continue
        collector = probe_eligibility.READINESS_COLLECTORS.get(candidate["check_type"])
        if collector is None or (agent_id, collector) not in fresh:
            continue
        entry = result_service.record_execution_condition(
            db,
            candidate["monitor_id"],
            status=result_service.EXECUTION_STALE,
            reason=REASON_NO_RECENT_RESULT,
            occurred_at=moment,
        )
        if entry is not None:
            live.append(entry)
            marked += 1
    return marked


def _fresh_readiness(db: Session, agent_ids: set[int], moment: datetime) -> set[tuple[int, str]]:
    """`(agent_id, collector)` pairs whose readiness still describes a live agent.

    Freshness and the usable-state vocabulary both come from
    `probe_eligibility`, which is the one place they are defined: a readiness row
    carries no TTL, so a row saying `ready` may predate an outage of any length.
    """
    if not agent_ids:
        return set()
    cutoff = moment - timedelta(seconds=probe_eligibility.READINESS_MAX_AGE_S)
    rows = db.execute(
        select(
            AgentCapabilityReadiness.agent_id,
            AgentCapabilityReadiness.collector,
        ).where(
            AgentCapabilityReadiness.agent_id.in_(agent_ids),
            # Reached into deliberately: §2's readiness vocabulary is defined
            # once, in the eligibility evaluator, and a second copy here would
            # be free to drift from the one dispatch actually enforces.
            AgentCapabilityReadiness.state.in_(probe_eligibility._USABLE_READINESS_STATES),
            AgentCapabilityReadiness.updated_at.is_not(None),
            AgentCapabilityReadiness.updated_at >= cutoff,
        )
    ).all()
    return {(agent_id, collector) for agent_id, collector in rows}


def purge_probe_runs(db: Session, *, now: datetime | None = None) -> int:
    """Delete probe runs past §1's seven-day retention. Owns its commit."""
    cutoff = (now or utcnow()) - timedelta(days=PROBE_RUN_RETENTION_DAYS)
    result = db.execute(delete(MonitorProbeRun).where(MonitorProbeRun.created_at < cutoff))
    deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
    db.commit()
    if deleted:
        logger.info("Purged %d probe run(s) older than %d days", deleted, PROBE_RUN_RETENTION_DAYS)
    return deleted


def purge_old_probe_runs() -> int:
    """The zero-argument shape the APScheduler retention job in `main.py` takes."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return purge_probe_runs(db)


__all__ = [
    "PROBE_RUN_RETENTION_DAYS",
    "REASON_NO_RECENT_RESULT",
    "REASON_RESULT_TIMEOUT",
    "RESULT_TIMEOUT_GRACE_S",
    "STALE_INTERVAL_MULTIPLIER",
    "ReconcileSummary",
    "purge_old_probe_runs",
    "purge_probe_runs",
    "reconcile",
]
