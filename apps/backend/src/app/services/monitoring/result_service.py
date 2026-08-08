"""The single path from a normalized check outcome to monitor state (§6).

Whoever ran the check — this server's poll worker or a remote agent — hands the
identical record shape to `process_results`, and everything downstream of that
point is the same code: the Proxmox priority override, the availability samples,
the retry/PENDING/DOWN/UP state machine, the transition events, the down and
recovered alerts, and the live status push. §6's requirement that "server and
agent checks must produce the same status, event, history, and alert semantics"
is therefore a property of there being one implementation, not of two
implementations agreeing.

Provenance is carried, not branched on:

* `source` records *who* ran the check and is deliberately **not** the value
  written to `telemetry_timeseries.source`. That column stays `"monitor"` for
  every vantage, because `monitor_service._uptime_pct_map` and
  `workers/rollup_worker.py` both aggregate availability without filtering on
  it — a second source string would silently split, and then double-count, one
  monitor's uptime.
* `details` and per-sample `error_reason` are persisted **only** in
  `monitor_probe_runs.result_metadata` (D-8). Server-executed checks discard
  both today; `telemetry_timeseries` is a compressed Timescale hypertable with a
  90-day retention policy, and widening it for audit metadata that monitor state
  does not depend on would mean the disable/restore-compression dance from
  migration 0095 for no product benefit. The asymmetry is a decision.

Execution errors are the one branch that does not describe the target (§6). A
vantage that could not run the check says nothing about whether the host is up,
so that branch writes no availability sample, never reaches `state.apply_result`
— which unconditionally rewrites `last_polled_at` and `consecutive_failures` —
and never moves `last_status` or `next_due_at`. It updates the execution
condition, records an event only when the reason actually changes, and pushes a
live refresh that deliberately carries no `status` key (D-13).

Transaction ownership: `writer.write_samples` and `state.apply_result` both
document that the caller owns the transaction, so this module is that caller. It
commits **exactly once**, covering samples + state + events + run completion,
and it publishes alerts and live status only *after* that commit returns — a
listener must never be able to observe a transition that a rollback then erases.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.redis import get_redis
from app.core.subjects import (
    MONITOR_ALERT_DOWN,
    MONITOR_ALERT_RECOVERED,
    monitor_alert_payload,
)
from app.db.models import MonitorEvent, MonitorItem, MonitorProbeRun
from app.services.monitoring.collectors import Sample
from app.services.monitoring.proxmox_override import Outcome, apply_proxmox_overrides
from app.services.monitoring.state import PENDING, AppliedTransition, apply_result
from app.services.monitoring.writer import SampleRow, write_samples

logger = logging.getLogger(__name__)

# Who ran the check. Recorded on the run and used for logging; never written to
# `telemetry_timeseries.source` (see the module docstring).
SOURCE_SERVER = "server"
SOURCE_AGENT = "agent"

# What the executor reported, mirroring `monitor_probe_runs.outcome`. Only
# `completed` means "the target answered, or definitively did not"; every other
# outcome is an execution condition and takes the inert branch below.
OUTCOME_COMPLETED = "completed"
OUTCOME_EXECUTION_ERROR = "execution_error"

# `monitor_items.probe_execution_status`. `ready` is the vantage working;
# `unavailable` is a named failure; `stale` is D-4's "looks healthy, results are
# not arriving" and is written by the reconciliation pass, not from a result.
EXECUTION_READY = "ready"
EXECUTION_UNAVAILABLE = "unavailable"
EXECUTION_STALE = "stale"

# `monitor_events.event_type` for an execution condition. One type covers the
# whole vocabulary because the reason is in `msg` and is what the dedupe below
# compares; `status_to` carries the *target's* state through untouched, exactly
# as `monitor_service.set_paused` does for paused/resumed.
EVENT_EXECUTION = "execution"


@dataclass(frozen=True)
class MonitorResult:
    """One check, normalized, whoever ran it.

    `check_type`/`target_type`/`target_id` are required rather than convenient:
    `apply_proxmox_overrides` needs the item dicts to decide whether a
    hypervisor's fresher opinion outranks a raw ICMP/TCP answer, and a remote
    result that skipped that step would invert UP/DOWN relative to the
    byte-identical server-executed check (D-7).
    """

    item_id: int
    target_type: str | None
    target_id: int | None
    check_type: str | None
    samples: list[Sample]
    up: bool
    msg: str
    checked_at: datetime
    outcome: str = OUTCOME_COMPLETED
    details: dict | None = None
    source: str = SOURCE_SERVER
    agent_id: int | None = None
    run_id: str | None = None
    # Only read when `outcome` is not `completed`: the machine-readable reason
    # the vantage could not run the check, in `probe_eligibility`'s vocabulary.
    # It lands on `monitor_items.probe_execution_reason` and
    # `monitor_probe_runs.error_code`; `outcome` is the fallback so a caller
    # that forgets one still produces something switchable.
    execution_reason: str | None = None


@dataclass(frozen=True)
class PersistedResults:
    """What the committed batch owes the outside world."""

    written: int = 0
    transitions: list[AppliedTransition] = field(default_factory=list)
    # Ready-to-serialize live-status payloads, in batch order.
    live_status: list[dict] = field(default_factory=list)


async def process_results(results: list[MonitorResult], db_factory: Callable[[], Any]) -> int:
    """Persist a batch of normalized results, then publish what it produced.

    The top-level entrypoint for every caller: `monitor_poll_worker` for
    server-executed checks and the `probe.result` ingest path for agent-executed
    ones. Returns the number of sample rows written.
    """
    db = db_factory()
    try:
        persisted = persist_results(db, results)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    await publish_results(persisted)
    return persisted.written


def persist_results(db: Session, results: list[MonitorResult]) -> PersistedResults:
    """Samples + state + events + run completion, in one transaction.

    Owns the commit. Publishing is deliberately not done here: a NATS alert or a
    Redis push emitted inside the transaction would be observable before the
    rows that justify it, and unretractable if the commit then failed.
    """
    if not results:
        return PersistedResults()

    results = list(results)
    # Only completed results describe the target, so only they are overridden by
    # a hypervisor's fresher opinion and only they become samples. Positions are
    # preserved so the live-status pushes keep the caller's batch order.
    completed = [i for i, r in enumerate(results) if r.outcome == OUTCOME_COMPLETED]
    if completed:
        adjusted = _apply_proxmox_overrides(db, [results[i] for i in completed])
        for index, result in zip(completed, adjusted, strict=True):
            results[index] = result

    written = write_samples(db, [_sample_row(results[i]) for i in completed])
    transitions: list[AppliedTransition] = []
    live_status: list[dict] = []
    for result in results:
        if result.outcome != OUTCOME_COMPLETED:
            entry = _apply_execution_error(db, result)
            if entry is not None:
                live_status.append(entry)
            continue
        transition = apply_result(
            db, result.item_id, up=result.up, msg=result.msg, checked_at=result.checked_at
        )
        if transition:
            transitions.append(transition)
        live_status.append(
            {
                "monitor_id": result.item_id,
                "status": "up" if result.up else "down",
                "msg": result.msg,
                "ts": result.checked_at.isoformat(),
            }
        )
        _complete_run(db, result)
    db.commit()
    return PersistedResults(written=written, transitions=transitions, live_status=live_status)


async def publish_results(persisted: PersistedResults) -> None:
    await _publish_transitions(persisted.transitions)
    await _publish_live_status(persisted.live_status)


def _sample_row(result: MonitorResult) -> SampleRow:
    return (
        result.item_id,
        result.target_type,
        result.target_id,
        result.samples,
        result.checked_at,
    )


def _apply_proxmox_overrides(db: Session, results: list[MonitorResult]) -> list[MonitorResult]:
    """Run the batch through the existing override, in its own tuple vocabulary.

    `proxmox_override` predates this module and speaks `(SampleRow, up, msg)`;
    translating here keeps the override a single implementation shared by both
    vantages instead of growing a remote-aware copy.
    """
    items = [
        {
            "item_id": r.item_id,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "check_type": r.check_type,
        }
        for r in results
    ]
    outcomes: list[Outcome] = [(_sample_row(r), r.up, r.msg) for r in results]
    overridden = apply_proxmox_overrides(db, items, outcomes)
    if len(overridden) != len(results):  # pragma: no cover - the override is length-preserving
        logger.warning("Proxmox override changed the batch length; using raw results")
        return results
    return [
        _with_outcome(result, row, up, msg)
        for result, (row, up, msg) in zip(results, overridden, strict=True)
    ]


def _with_outcome(result: MonitorResult, row: SampleRow, up: bool, msg: str) -> MonitorResult:
    _, _, _, samples, _ = row
    if up is result.up and msg == result.msg and samples is result.samples:
        return result
    return MonitorResult(
        item_id=result.item_id,
        target_type=result.target_type,
        target_id=result.target_id,
        check_type=result.check_type,
        samples=samples,
        up=up,
        msg=msg,
        checked_at=result.checked_at,
        outcome=result.outcome,
        details=result.details,
        source=result.source,
        agent_id=result.agent_id,
        run_id=result.run_id,
    )


def record_execution_condition(
    db: Session,
    item_id: int,
    *,
    status: str,
    reason: str | None,
    occurred_at: datetime,
) -> dict | None:
    """Move the *vantage's* condition, leaving the target's state alone.

    The single writer for `monitor_items.probe_execution_*` outside the happy
    path, shared by the execution-error branch below and by the reconciliation
    pass (`probe_reconcile`). It writes no sample, touches no retry counter and
    does not pull `next_due_at` back: the monitor simply tries again on its
    normal interval, which is §2's rule and what keeps a broken agent from
    reading as a broken target.

    Returns the live-refresh payload for the caller to publish after the commit,
    or `None` when the monitor is gone. Caller owns the transaction.
    """
    monitor = db.get(MonitorItem, item_id)
    if monitor is None:  # pragma: no cover - the caller resolved the monitor first
        logger.debug("Execution condition for unknown monitor %s ignored", item_id)
        return None

    trimmed = reason[:128] if reason else None
    _record_execution_event(db, monitor, trimmed)
    monitor.probe_execution_status = status
    monitor.probe_execution_reason = trimmed
    return {
        "monitor_id": monitor.id,
        "probe_execution_status": status,
        "probe_execution_reason": trimmed,
        "ts": occurred_at.isoformat(),
    }


def _record_execution_event(db: Session, monitor: MonitorItem, reason: str | None) -> None:
    """§6: one event per *change* of reason, not one per occurrence.

    The monitor's own column cannot be the memory: `scheduler._MARK_QUEUED_SQL`
    clears `probe_execution_reason` every time the monitor is queued, so a
    silent agent would write one event per interval forever. The monitor's
    latest event is the memory instead — which also means a real UP/DOWN
    transition in between re-arms the condition, since the operator has seen
    monitor activity since the last time it was reported.
    """
    if reason is None:
        return
    latest = db.execute(
        select(MonitorEvent)
        .where(MonitorEvent.item_id == monitor.id)
        .order_by(MonitorEvent.created_at.desc(), MonitorEvent.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is not None and latest.event_type == EVENT_EXECUTION and latest.msg == reason:
        return
    db.add(
        MonitorEvent(
            item_id=monitor.id,
            event_type=EVENT_EXECUTION,
            # The target's state is carried through, never rewritten — the same
            # shape `monitor_service.set_paused` uses, and what keeps the status
            # pill and the check-history bar honest (§7).
            status_from=monitor.last_status,
            status_to=monitor.last_status or PENDING,
            msg=reason,
        )
    )


def _apply_execution_error(db: Session, result: MonitorResult) -> dict | None:
    """The inert branch: close the run, record the condition, publish a refresh."""
    reason = result.execution_reason or result.outcome
    _close_failed_run(db, result, reason)
    return record_execution_condition(
        db,
        result.item_id,
        status=EXECUTION_UNAVAILABLE,
        reason=reason,
        occurred_at=result.checked_at,
    )


def _close_failed_run(db: Session, result: MonitorResult, reason: str) -> None:
    """Retire the lease an execution error answers.

    `probe_last_result_at` is deliberately left alone: an execution error is not
    a result, and D-4's staleness rule has to keep seeing a monitor that is
    producing none.
    """
    if result.run_id is None:
        return
    run = db.execute(
        select(MonitorProbeRun).where(MonitorProbeRun.run_id == result.run_id)
    ).scalar_one_or_none()
    if run is None:  # pragma: no cover - the caller matched the run before calling
        logger.warning("Execution error for unknown probe run %s", result.run_id)
        return
    run.status = OUTCOME_EXECUTION_ERROR
    run.outcome = result.outcome
    run.error_code = reason[:64]
    run.completed_at = result.checked_at
    run.msg = result.msg[:2000] or None
    run.result_metadata = _result_metadata(result)


def _complete_run(db: Session, result: MonitorResult) -> None:
    """Close the lease this result answers, inside the same transaction.

    A no-op for server-executed checks, which have no run. The run row is where
    `details` and per-sample `error_reason` come to rest (D-8).
    """
    if result.run_id is None:
        return
    run = db.execute(
        select(MonitorProbeRun).where(MonitorProbeRun.run_id == result.run_id)
    ).scalar_one_or_none()
    if run is None:  # pragma: no cover - the caller matched the run before calling
        logger.warning("Result for unknown probe run %s, monitor state kept", result.run_id)
        return

    run.status = "completed"
    run.outcome = result.outcome
    run.completed_at = result.checked_at
    run.msg = result.msg[:2000]
    run.result_metadata = _result_metadata(result)

    monitor = db.get(MonitorItem, result.item_id)
    if monitor is not None:
        monitor.probe_last_result_at = result.checked_at
        monitor.probe_execution_status = EXECUTION_READY
        monitor.probe_execution_reason = None


def _result_metadata(result: MonitorResult) -> dict | None:
    metadata: dict = {}
    if result.details:
        metadata["details"] = result.details
    error_reasons = [
        {"metric": s.metric, "error_reason": s.error_reason}
        for s in result.samples
        if s.error_reason
    ]
    if error_reasons:
        metadata["error_reasons"] = error_reasons
    return metadata or None


async def _publish_transitions(transitions: list[AppliedTransition]) -> None:
    for t in transitions:
        if t.notify == "down":
            subject = MONITOR_ALERT_DOWN.format(item_id=t.item_id)
        elif t.notify == "recovered":
            subject = MONITOR_ALERT_RECOVERED.format(item_id=t.item_id)
        else:
            continue
        payload = monitor_alert_payload(
            t.item_id, t.name, t.status_to, t.msg, t.occurred_at.isoformat()
        )
        try:
            await nats_client.js_publish(subject, payload)
        except Exception as exc:  # noqa: BLE001 — alerting is best-effort here
            logger.warning("Failed to publish monitor alert %s: %s", subject, exc)


async def _publish_live_status(live_status: list[dict]) -> None:
    redis = await get_redis()
    if redis is None:
        return
    for entry in live_status:
        item_id = entry["monitor_id"]
        try:
            await redis.publish(f"monitor:{item_id}", json.dumps(entry))
        except Exception:  # noqa: BLE001 — live push degrades silently
            return


__all__ = [
    "EVENT_EXECUTION",
    "EXECUTION_READY",
    "EXECUTION_STALE",
    "EXECUTION_UNAVAILABLE",
    "OUTCOME_COMPLETED",
    "OUTCOME_EXECUTION_ERROR",
    "SOURCE_AGENT",
    "SOURCE_SERVER",
    "MonitorResult",
    "PersistedResults",
    "persist_results",
    "process_results",
    "publish_results",
    "record_execution_condition",
]
