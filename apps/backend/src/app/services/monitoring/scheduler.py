"""Atomically claim due monitor items and route them to their vantage.

The claim is one statement: it locks due rows with FOR UPDATE SKIP LOCKED,
ranks them per vantage, advances next_due_at (with small jitter so a
post-downtime burst spreads out), and returns the claimed rows. This makes
double-enqueue impossible and is safe across concurrent schedulers, though
normally only one runs (advisory lock).

Two vantages exist (Slice 3 §2): `probe_agent_id IS NULL` is server execution,
published to `MONITOR_POLL_ITEM` exactly as before; a non-NULL `probe_agent_id`
means one named agent runs the check, which needs a durable run row first and
is published to `MONITOR_PROBE_REMOTE` carrying nothing but that run's id.

Do not restructure the commit-before-publish ordering below. It is precisely
why a crashed worker never wedges an item — the property pinned by
tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.subjects import MONITOR_POLL_ITEM, MONITOR_PROBE_REMOTE

logger = logging.getLogger(__name__)

# ── The run deadline ─────────────────────────────────────────────────────────
# How long an agent has to return a result before the run is expired. §4's
# `probe.assign` example shows scheduled_at + 20s, but that is only what the
# *default* ICMP check costs; it is an example, not a constant.
#
# A fixed deadline is a silent-failure generator. `internal/collect/probe`'s
# runtime.go runs every check under `context.WithDeadline(ctx, DeadlineAt)`, so
# a deadline shorter than the configured budget aborts the check mid-flight and
# reports `outcome="execution_error"` — and by design an execution error never
# moves monitor state. An ICMP monitor with `packet_count=20` (allowed by
# `schemas/monitor.py`'s `le=20`, and offered by MonitorForm.jsx) needs
# 20 x 1.5 s = 30 s to observe 100% packet loss; at 20 s it would report
# `probe_execution_status='unavailable'` forever while the byte-identical
# server-executed monitor reports DOWN. §6's parity requirement is exactly what
# that breaks.
#
# So the deadline is derived from the monitor's own configuration, using the
# collector-side defaults from the parity contract. Stored configs are sparse —
# `_MonitorBase._validate_config` persists `model_dump(exclude_unset=True)` —
# so every value has to come through `params.get(key, default)` here too.
#
# The three knobs are the operator escape hatch:
#   * headroom covers the dispatch hop, the runtime's pre-dial scope resolve
#     (`resolveTimeout = 5s`) and clock skew, and is always added on top;
#   * the floor keeps a cheap check from getting an unreasonably tight window
#     and preserves the historical 20 s for every default-configured monitor;
#   * the ceiling bounds how long any single check may occupy a run — a
#     pathological config (the `ports` list has no length bound) must not leave
#     a monitor un-reconciled for hours.
_PROBE_DEADLINE_HEADROOM_S = float(os.getenv("CB_MONITOR_PROBE_DEADLINE_HEADROOM_S", "10"))
_PROBE_DEADLINE_MIN_S = float(os.getenv("CB_MONITOR_PROBE_DEADLINE_MIN_S", "20"))
_PROBE_BUDGET_MAX_S = float(os.getenv("CB_MONITOR_PROBE_BUDGET_MAX_S", "600"))

# A TCP host is dialled once per resolved address per port on both sides. The
# scheduler cannot know how many addresses a name will yield, so budget for the
# dual-stack case (one A + one AAAA), which is the common one.
_TCP_ADDRESS_FANOUT = 2


def _positive_float(params: dict, key: str, default: float) -> float:
    """`params` is free-form JSONB. A junk value falls back to the collector
    default rather than raising inside the scheduler tick."""
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _positive_int(params: dict, key: str, default: int) -> int:
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _check_budget_seconds(check_type: str, params: dict) -> float:
    """Wall-clock a check can legitimately spend, per the parity contract.

    Mirrors what the collectors — and their Go twins in
    `apps/agent/internal/collect/probe` — actually spend, not what pydantic
    declares.
    """
    if check_type == "icmp":
        # collect_icmp pings serially: packet_count x timeout.
        return _positive_int(params, "packet_count", 5) * _positive_float(params, "timeout", 1.5)
    if check_type == "tcp":
        # collect_tcp tries `ports` IN ORDER, one timeout each, first success
        # wins. Both socket.create_connection and tcp.go's dial loop then retry
        # every *address* the host resolved to, with the full timeout each, so a
        # dual-stack name costs twice a literal's — see _TCP_ADDRESS_FANOUT.
        ports = params.get("ports") or [params.get("port", 80)]
        attempts = len(ports) if isinstance(ports, list) and ports else 1
        return attempts * _TCP_ADDRESS_FANOUT * _positive_float(params, "timeout", 1.0)
    if check_type == "http":
        # collect_http spends the request timeout, then _tls_details opens a
        # second connection with the same timeout.
        return 2 * _positive_float(params, "timeout", 10.0)
    if check_type == "dns":
        # dnspython's `lifetime` (and dns.go's lookupCtx) bound the whole
        # resolution by one timeout, however many servers are tried.
        return _positive_float(params, "timeout", 5.0)
    return 0.0


def probe_deadline_seconds(check_type: str, params: dict | None) -> float:
    """Seconds an agent gets to return a result for this monitor's check."""
    budget = _check_budget_seconds(check_type, params or {})
    if budget > _PROBE_BUDGET_MAX_S:
        # Never truncate silently: this is the same failure mode the fixed
        # deadline had, just at a configuration nobody should be running.
        logger.warning(
            "A %s check's configured budget of %.0fs exceeds "
            "CB_MONITOR_PROBE_BUDGET_MAX_S (%.0fs); the run will expire before it finishes",
            check_type,
            budget,
            _PROBE_BUDGET_MAX_S,
        )
        budget = _PROBE_BUDGET_MAX_S
    return max(budget + _PROBE_DEADLINE_HEADROOM_S, _PROBE_DEADLINE_MIN_S)


# D-2. PostgreSQL rejects `FOR UPDATE is not allowed with window functions`, so
# the per-vantage ranking cannot sit at the same query level as the claim: the
# lock has to happen first and the ranking second. That inverts the two limits —
# the global cap would apply *before* the rank, letting a single agent with a
# 400-monitor backlog consume the whole locked set and starve every other
# vantage, which is the exact thing §2's fair-sharing rule exists to prevent.
# Oversampling the lock restores fairness; rows locked but not claimed are
# released at commit and cost nothing. `:oversample` is the fairness knob.
#
# The final ORDER BY is round-robin (rn first, then due time), so when the global
# cap does bite it takes the most-overdue check from every vantage before taking
# any vantage's second one.
#
# This relies on ix_monitor_items_probe_due; without it the oversampled ORDER BY
# degrades to a full sort over every due row.
_CLAIM_SQL = text(
    """
    WITH locked AS (
        SELECT id, next_due_at, probe_agent_id
        FROM monitor_items
        WHERE enabled AND next_due_at <= now()
        ORDER BY next_due_at
        FOR UPDATE SKIP LOCKED
        LIMIT :oversample
    ),
    ranked AS (
        SELECT
            id,
            next_due_at,
            row_number() OVER (
                PARTITION BY coalesce(probe_agent_id, 0)
                ORDER BY next_due_at
            ) AS rn
        FROM locked
    )
    UPDATE monitor_items
    SET next_due_at = now()
        + make_interval(secs => interval_secs)
        + make_interval(secs => random() * least(interval_secs, 5)),
        updated_at = now()
    WHERE id IN (
        SELECT id FROM ranked
        WHERE rn <= :per_vantage
        ORDER BY rn, next_due_at
        LIMIT :batch
    )
    RETURNING id, target_type, target_id, host, check_type, params, interval_secs,
              probe_agent_id
    """
)

# The partial unique index on (monitor_id) WHERE status IN ('queued','dispatched')
# is the real guard; this pre-check exists so the common case never has to
# provoke an IntegrityError.
_ACTIVE_RUN_SQL = text(
    """
    SELECT 1 FROM monitor_probe_runs
    WHERE monitor_id = :monitor_id AND status IN ('queued', 'dispatched')
    LIMIT 1
    """
)

_INSERT_RUN_SQL = text(
    """
    INSERT INTO monitor_probe_runs
        (run_id, monitor_id, agent_id, status, scheduled_at, deadline_at, created_at)
    VALUES
        (:run_id, :monitor_id, :agent_id, 'queued', now(),
         now() + make_interval(secs => :deadline_s), now())
    """
)

_MARK_QUEUED_SQL = text(
    """
    UPDATE monitor_items
    SET probe_execution_status = 'queued',
        probe_execution_reason = NULL,
        updated_at = now()
    WHERE id = :monitor_id
    """
)

# D-6: skipping costs one interval; queuing would build a backlog behind exactly
# the agent that is already slow. next_due_at is deliberately left where the
# claim put it.
_MARK_IN_FLIGHT_SQL = text(
    """
    UPDATE monitor_items
    SET probe_execution_status = 'running',
        probe_execution_reason = 'previous_run_in_flight',
        updated_at = now()
    WHERE id = :monitor_id
    """
)

# §8: a NATS publication failure is a dispatch failure, not a target failure —
# no avail sample, no retry counter, just "try again soon". Jittered so a broker
# blip does not re-converge every assigned monitor onto one tick.
_DISPATCH_FAILED_SQL = text(
    """
    UPDATE monitor_items
    SET next_due_at = now() + make_interval(secs => random() * least(interval_secs, 5)),
        probe_execution_status = 'unavailable',
        probe_execution_reason = 'dispatch_failed',
        updated_at = now()
    WHERE id = :monitor_id
    """
)

# The run has to leave the active statuses too, or it keeps the partial unique
# index and the pull-back above just buys a 'previous_run_in_flight' skip.
_FAIL_RUN_SQL = text(
    """
    UPDATE monitor_probe_runs
    SET status = 'execution_error',
        error_code = 'dispatch_failed',
        completed_at = now()
    WHERE run_id = :run_id
    """
)


def claim_due_items(
    db: Session,
    batch: int = 200,
    per_vantage: int = 50,
    oversample: int = 1000,
) -> list[dict]:
    rows = (
        db.execute(
            _CLAIM_SQL,
            {"batch": batch, "per_vantage": per_vantage, "oversample": oversample},
        )
        .mappings()
        .all()
    )
    db.commit()
    return [
        {
            "item_id": r["id"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "host": r["host"],
            "check_type": r["check_type"],
            "params": r["params"] or {},
            "interval_secs": r["interval_secs"],
            "probe_agent_id": r["probe_agent_id"],
        }
        for r in rows
    ]


def _create_probe_run(db: Session, item: dict) -> str | None:
    """Open a run for an agent-assigned monitor, or None if one is in flight.

    Committed before the caller publishes: the dispatcher resolves the run id on
    its own session and would otherwise race the scheduler's transaction.
    """
    monitor_id = item["item_id"]
    if db.execute(_ACTIVE_RUN_SQL, {"monitor_id": monitor_id}).first() is not None:
        db.execute(_MARK_IN_FLIGHT_SQL, {"monitor_id": monitor_id})
        db.commit()
        return None

    run_id = secrets.token_hex(16)
    try:
        db.execute(
            _INSERT_RUN_SQL,
            {
                "run_id": run_id,
                "monitor_id": monitor_id,
                "agent_id": item["probe_agent_id"],
                "deadline_s": probe_deadline_seconds(item["check_type"], item["params"]),
            },
        )
        db.execute(_MARK_QUEUED_SQL, {"monitor_id": monitor_id})
        db.commit()
    except IntegrityError:
        # Another scheduler (or a check-now) opened a run between the pre-check
        # and the insert. Same answer as the pre-check: skip the interval.
        db.rollback()
        db.execute(_MARK_IN_FLIGHT_SQL, {"monitor_id": monitor_id})
        db.commit()
        return None
    return run_id


def _record_dispatch_failure(db: Session, item: dict, run_id: str) -> None:
    db.execute(_FAIL_RUN_SQL, {"run_id": run_id})
    db.execute(_DISPATCH_FAILED_SQL, {"monitor_id": item["item_id"]})
    db.commit()


async def enqueue_due(
    db: Session,
    publish: Callable[[str, dict], Awaitable[bool]],
    batch: int = 200,
    per_vantage: int = 50,
    oversample: int = 1000,
) -> int:
    items = claim_due_items(db, batch=batch, per_vantage=per_vantage, oversample=oversample)
    enqueued = 0
    for item in items:
        if item["probe_agent_id"] is None:
            if await publish(MONITOR_POLL_ITEM, item):
                enqueued += 1
            else:
                logger.warning("Failed to enqueue poll for item %s", item["item_id"])
            continue

        run_id = _create_probe_run(db, item)
        if run_id is None:
            continue
        # Only the run id travels over NATS: the dispatcher loads the host,
        # config and any credentials from the database immediately before
        # encrypted delivery to the agent (§2).
        if await publish(MONITOR_PROBE_REMOTE, {"run_id": run_id}):
            enqueued += 1
        else:
            logger.warning(
                "Failed to dispatch probe run %s for item %s to agent %s",
                run_id,
                item["item_id"],
                item["probe_agent_id"],
            )
            _record_dispatch_failure(db, item, run_id)
    return enqueued
