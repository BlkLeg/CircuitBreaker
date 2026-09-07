"""Job lifecycle: dispatch a scan, close it out, and the jobs that follow one.

`discovery_service` is the scan *engine* — it runs a sweep and imports what it
found. This module is everything around that: deciding whether a job runs here
or on an agent, giving an agent's result a terminal status, scheduling a job
onto the event loop, and enqueueing the LLDP and OPNsense follow-up jobs a
completed scan can spawn.

The split is one-way by construction: dispatch calls into the engine, the
engine never calls back out here. That is what makes it a separate module
rather than a section — a job's lifecycle is read and changed by the API, the
scheduler and the agent link plane, none of which have any business reading the
nmap pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.core.time import utcnow_iso
from app.db.models import ScanJob, ScanResult
from app.db.session import SessionLocal, get_session_context

# The module, not its names: `discovery_service._emit_ws_event` and
# `run_scan_job` are what tests substitute to observe routing and WS traffic,
# and a name bound here at import time would hold the original past the patch.
from app.services import discovery_service
from app.services.discovery_scheduler import (
    _max_concurrent_scans,
    _running_scan_count,
    _schedule_queued_scan_jobs,
    main_loop,
)
from app.services.log_service import write_log
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger(__name__)

# D-4. The terminal vocabulary an agent-executed job may close with. There is
# deliberately no `partial`: `status` is a bare string read by the history
# filter, the history query and the review badge, and an interrupted scan is
# `failed` with its accepted findings kept and reviewable.
TERMINAL_JOB_STATUSES = ("completed", "failed", "cancelled")

# The `dispatch_status` and `progress_phase` that go with each of them. Kept as
# maps rather than as branches so a new terminal status cannot be added on one
# axis and forgotten on the other.
_DISPATCH_STATUS_FOR_JOB_STATUS = {
    "completed": "completed",
    "failed": "execution_error",
    "cancelled": "cancelled",
}
_PROGRESS_PHASE_FOR_JOB_STATUS = {
    "completed": "done",
    "failed": "failed",
    "cancelled": "cancelled",
}


async def finalize_agent_job(
    db: Session,
    job: ScanJob,
    status: str,
    *,
    error_reason: str | None = None,
    error_text: str | None = None,
) -> bool:
    """Close one agent-executed job. Returns whether *this* call closed it.

    `_scan_finalize`'s counterpart, and deliberately not `_scan_finalize`
    itself. That one writes `hosts_found`/`hosts_new`/`hosts_updated`/
    `hosts_conflict` *absolutely*, from the stats dict a finished batch
    produces; the agent path has no batch, it increments those counters per
    accepted finding as they arrive (D-10), and sharing the absolute write would
    clobber every one of them with a dict this path never assembles.

    Three properties make this safe to call from the `/link` read loop:

    * **It is a compare-and-set.** Two terminal summaries racing on separate
      connections — the exact shape of a spool replayed after a reconnect —
      both pass any pre-check; only the `WHERE status IN ('queued','running')`
      admits one of them, so there is exactly one finalization, one audit row
      and one `job_update`.
    * **It closes the dispatch with the job.** `dispatch_status` moves to a
      closed value in the same statement, which is what makes a finding arriving
      after the summary refusable by `agent_discovery` regardless of whether any
      `discovery.cancel` was ever delivered.
    * **It never merges.** `_auto_merge_known_devices` is not called here at any
      setting, because `discovery_merge._auto_merge_result` *creates* a
      `Hardware` row with no review and plan §5 says an agent-authored row
      reaches `discovery_import_service` only when a user accepts it. The
      `discovery_auto_merge` setting describes the server's own scan; an
      untrusted remote executor is not that.

      Note what that forbids, which is **creation** — and with it any write that
      changes an answer the inventory already holds. It is not a rule about the
      agent path as such. `discovery_enrich`, which `agent_discovery` *does*
      call per finding, backfills empty fields on a device the classifier had
      already matched: it has no create branch, guards every write on the
      current value being empty, and will not name a device from an agent's
      hostname. Nothing it writes is a thing this paragraph protects.
    """
    if status not in TERMINAL_JOB_STATUSES:
        raise ValueError(f"{status!r} is not a terminal scan job status")

    admitted = cast(
        "CursorResult[Any]",
        db.execute(
            update(ScanJob)
            .where(ScanJob.id == job.id, ScanJob.status.in_(("queued", "running")))
            .values(
                status=status,
                completed_at=utcnow_iso(),
                dispatch_status=_DISPATCH_STATUS_FOR_JOB_STATUS[status],
                error_reason=error_reason,
                error_text=error_text,
                progress_phase=_PROGRESS_PHASE_FOR_JOB_STATUS[status],
                progress_message=error_text or "",
            )
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if not admitted:
        logger.debug("Agent job %s was already finalized; this summary is inert", job.id)
        return False

    db.commit()
    db.refresh(job)

    # The ordinary discovery audit rows, with the ordinary actor: an operator
    # reading the trail should not have to know which executor ran the scan to
    # find the entry. `write_log` owns its own commit and never raises.
    if status == "completed":
        write_log(
            db,
            action="scan_completed",
            entity_type="scan_job",
            entity_id=job.id,
            category="discovery",
            actor=job.triggered_by,
            details=json.dumps(
                {
                    "hosts_found": job.hosts_found or 0,
                    "hosts_new": job.hosts_new or 0,
                    "hosts_conflict": job.hosts_conflict or 0,
                    "cidr": job.target_cidr,
                    "scan_agent_id": job.scan_agent_id,
                }
            ),
        )
    elif status == "failed":
        write_log(
            db,
            action="scan_failed",
            entity_type="scan_job",
            entity_id=job.id,
            category="discovery",
            severity="error",
            actor=job.triggered_by,
            details=json.dumps(
                {
                    "error": error_text or error_reason or "",
                    "cidr": job.target_cidr,
                    "scan_agent_id": job.scan_agent_id,
                }
            ),
        )

    pending_count = db.query(ScanResult).filter(ScanResult.merge_status == "pending").count()

    # The job just gave its concurrency slot back, so the backlog is drained the
    # same way a server scan drains it.
    #
    # The guard stays, but it no longer stands in for the loop-affinity defect
    # it was written for: `schedule_discovery_scan_job` now resolves a loop from
    # any thread, and this call site is on the /link read loop and always had
    # one. What it still protects is the drain's own two database reads — the
    # settings row and the queued-job query — on a session this coroutine shares
    # with the read loop. The terminal status is already committed and the
    # pending count already taken by the time we get here, so a failure at this
    # point must not cost the client its `job_update` event or hand the agent a
    # protocol violation for a summary the backend accepted. Logged loudly
    # enough to be found: a drain that keeps failing means the backlog is only
    # moving on `agent_discovery_reconcile`'s interval.
    try:
        _schedule_queued_scan_jobs(db)
    except Exception:
        logger.exception("Agent job %s: draining the queued backlog failed", job.id)

    # After the commit, never before: a client that refetches the job on this
    # event must find it already terminal, and the badge count already true.
    await discovery_service._emit_ws_event(
        "job_update",
        {
            "job": {
                "id": job.id,
                "status": status,
                "error_reason": error_reason,
                "progress_percent": 100,
            },
            "pending_count": pending_count,
        },
    )
    await discovery_service._emit_ws_event(
        "job_progress",
        {
            "job_id": job.id,
            "phase": _PROGRESS_PHASE_FOR_JOB_STATUS[status],
            "message": error_text or "",
            "percent": 100,
        },
    )
    return True


def job_scan_agent_id(db: Session, job_id: int) -> int | None:
    """The agent this job runs on, or `None` for the server scanner.

    One predicate, read by both routing call sites — `execute_scan_job` and
    `discovery_scheduler._run_profile_job_async`. Two copies of "is this an
    agent job" is exactly how one path comes to send an agent-targeted job to
    the server scanner, which plan §3 forbids because it changes the vantage
    point the operator asked for without telling anyone.
    """
    return db.execute(
        select(ScanJob.scan_agent_id).where(ScanJob.id == job_id)
    ).scalar_one_or_none()


async def execute_scan_job(db: Session, job_id: int) -> None:
    """The one branch between the server scanner and an agent (plan §3).

    There is deliberately no fallback in either direction: an agent-targeted job
    that cannot be dispatched closes with a reason, and is never quietly re-run
    from the server's vantage point.

    The one thing that does *not* close the job is the concurrency ceiling: a
    scan the operator asked for that has to wait its turn is not a scan that
    failed, so it is left in the backlog for a drain to pick up, exactly as a
    server job with no free slot is (`_scan_setup`).

    `agent_discovery` is imported here rather than at module scope because that
    module imports this one.
    """
    if job_scan_agent_id(db, job_id) is None:
        await discovery_service.run_scan_job(job_id)
        return

    if not _agent_dispatch_slot_available(db):
        # Left exactly as it is — `queued`, no lease, no deadline — which is what
        # `_scan_setup` does to a server job that cannot get a slot, and is why
        # both drains (`discovery_scheduler._schedule_queued_scan_jobs` and
        # `agent_discovery_reconcile._drain_queued_jobs`) will pick it up again.
        logger.info("Scan job %d: no slot available for agent dispatch, leaving it queued", job_id)
        return

    from app.services import agent_discovery

    await agent_discovery.dispatch_discovery_job(db, job_id)


def _agent_dispatch_slot_available(db: Session) -> bool:
    """Whether `max_concurrent_scans` has room for one more running scan.

    `agent_discovery._claim` moves the job to `status='running'`, which is what
    `_running_scan_count` counts — a dispatched agent job spends a slot from
    every other scan's point of view, so it has to ask for one first. Without
    this, a job created by cron or by the API reached the dispatcher directly
    and was exempt from a ceiling it then consumed; only the two drains asked.

    The ceiling is read through the scheduler's own helpers, never re-derived:
    a second opinion about how many scans may run at once is how one execution
    location comes to ignore a limit the operator set for all of them.

    Not a claim, so it races with the drains by construction; that is the same
    advisory check `_scan_setup` makes for a server job, and the authoritative
    mutual exclusion stays where it is — `_claim`'s conditional UPDATE.
    """
    return _running_scan_count(db) < _max_concurrent_scans(get_or_create_settings(db))


async def _execute_scan_job_in_session(job_id: int) -> None:
    """`execute_scan_job` for the background-task entry point, which owns no session."""
    with get_session_context() as db:
        await execute_scan_job(db, job_id)


def schedule_discovery_scan_job(job_id: int) -> None:
    """Start the job's executor on the event loop — from any thread — and log
    any uncaught outcome.

    Callable from a thread on purpose. Its main caller,
    `discovery_scheduler._schedule_queued_scan_jobs`, is reached from
    `_scan_finalize`, which is synchronous and runs *only* inside
    `loop.run_in_executor`. `asyncio.create_task` needs a running loop **in the
    calling thread** and an executor worker has none, so this used to raise
    `RuntimeError: no running event loop` precisely when a job had just freed a
    slot and a queued job was waiting for it — after the terminal status
    committed and before the pending count returned, so the job went terminal
    with no `job_update` event reaching the UI and the backlog never drained.
    `monitor_service._publish_soon` is the model for resolving the loop; unlike
    that one this must not degrade to "published nothing", because the backlog
    has no other owner on this path.

    asyncio tasks that raise without a done-callback only emit a generic
    "exception was never retrieved" message, which is easy to miss when
    diagnosing mid-scan UI drop-offs.
    """
    coro = _execute_scan_job_in_session(job_id)

    def _log_outcome(finished: Any) -> None:
        # Accepts both an `asyncio.Task` and the `concurrent.futures.Future`
        # `run_coroutine_threadsafe` hands back; the three methods used here
        # mean the same thing on both.
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.exception(
                "Discovery job %s background task failed — UI may show offline if the "
                "worker process exited; check stderr and /data logs",
                job_id,
                exc_info=exc,
            )

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        running.create_task(coro).add_done_callback(_log_outcome)
        return

    # A worker thread. The loop `main.py`'s lifespan registered is the one the
    # ws_manager broadcasts and the agent link both live on, which is why
    # `discovery_scheduler` already captures it for the APScheduler jobs.
    target = main_loop()
    if target is None or not target.is_running():
        # Nothing can be scheduled anywhere. Say so loudly rather than raising
        # into a finalizer that has already committed a terminal status, and
        # close the coroutine so it is not reported as never awaited.
        coro.close()
        logger.error(
            "Discovery job %s could not be scheduled: no running event loop in this thread "
            "and no main loop registered (set_main_loop). The queued backlog will not drain "
            "until the next reconciliation pass.",
            job_id,
        )
        return

    asyncio.run_coroutine_threadsafe(coro, target).add_done_callback(_log_outcome)


def enqueue_lldp_job(
    db: Session,
    ips: list[str],
    community: str = "public",
    port: int = 161,
) -> int:
    """Create a scan job of type lldp targeting the given IPs. Returns job_id."""
    import json

    from app.core.time import utcnow_iso as _utcnow_iso
    from app.db.models import DiscoveryProfile, ScanJob
    from app.services.credential_vault import get_vault

    now = _utcnow_iso()
    encrypted_community = get_vault().encrypt(community)

    profile = DiscoveryProfile(
        name="_lldp_enrich_transient",
        cidr=",".join(ips),
        scan_types=json.dumps(["lldp"]),
        snmp_community_encrypted=encrypted_community,
        snmp_port=port,
        enabled=1,
        created_at=now,
        updated_at=now,
    )
    db.add(profile)
    db.flush()

    job = ScanJob(
        profile_id=profile.id,
        target_cidr=",".join(ips),
        scan_types_json=json.dumps(["lldp"]),
        status="queued",
        source_type="api",
        triggered_by="api",
        created_at=now,
    )
    db.add(job)
    db.flush()
    db.commit()
    return job.id


async def run_opnsense_enrich(original_job_id: int, private_ips: list[str]) -> None:
    """Run nmap against OPNsense-discovered IPs and UPDATE existing ScanResult rows.

    Does NOT create new ScanResult rows or a new ScanJob.
    Sets the original job to "running" for the duration so the frontend timer ticks,
    then restores "completed" when done.
    """
    from app.services.discovery_probes import _run_nmap_scan

    db = SessionLocal()
    try:
        app_cfg = get_or_create_settings(db)
        if not getattr(app_cfg, "nmap_enabled", False):
            logger.info(
                "OPNsense enrich job %d skipped: nmap-based scanning is disabled", original_job_id
            )
            return
    finally:
        db.close()

    ip_list = " ".join(private_ips)
    logger.info("OPNsense enrich job %d: nmap against %d IPs", original_job_id, len(private_ips))

    # ── Mark job as running so the frontend timer activates ──────────────────
    enrich_started = utcnow_iso()
    db = SessionLocal()
    try:
        job = db.get(ScanJob, original_job_id)
        if job:
            job.status = "running"
            job.progress_phase = "enrich"
            job.progress_message = f"Enriching {len(private_ips)} hosts with nmap\u2026"
            db.commit()
    except Exception as exc:
        logger.warning("OPNsense enrich job %d: could not mark running — %s", original_job_id, exc)
        db.rollback()
    finally:
        db.close()

    await discovery_service._emit_ws_event(
        "job_update",
        {
            "job": {
                "id": original_job_id,
                "status": "running",
                "started_at": enrich_started,
                "progress_percent": 5,
            }
        },
    )
    await discovery_service._emit_ws_event(
        "job_progress",
        {
            "job_id": original_job_id,
            "phase": "enrich",
            "message": f"Enriching {len(private_ips)} hosts with nmap\u2026",
            "percent": 10,
        },
    )

    # ── Run nmap ──────────────────────────────────────────────────────────────
    try:
        nmap_results = await _run_nmap_scan(ip_list, "-Pn -T4 -F -sV")
    except Exception as exc:
        logger.warning("OPNsense enrich job %d: nmap failed \u2014 %s", original_job_id, exc)
        completed = utcnow_iso()
        db = SessionLocal()
        try:
            job = db.get(ScanJob, original_job_id)
            if job:
                job.status = "completed"
                job.completed_at = completed
                job.progress_phase = "enrich_failed"
                job.progress_message = str(exc)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        await discovery_service._emit_ws_event(
            "job_update",
            {
                "job": {
                    "id": original_job_id,
                    "status": "completed",
                    "completed_at": completed,
                    "progress_percent": 100,
                }
            },
        )
        return

    await discovery_service._emit_ws_event(
        "job_progress",
        {
            "job_id": original_job_id,
            "phase": "enrich",
            "message": "Saving nmap results\u2026",
            "percent": 80,
        },
    )

    # ── Update existing ScanResult rows ───────────────────────────────────────
    updated = 0
    db = SessionLocal()
    try:
        for ip, host_data in nmap_results.items():
            row = (
                db.query(ScanResult)
                .filter(
                    ScanResult.scan_job_id == original_job_id,
                    ScanResult.ip_address == ip,
                )
                .first()
            )
            if not row:
                continue

            open_ports = host_data.get("open_ports") or []
            if open_ports:
                row.open_ports_json = open_ports

            os_family = host_data.get("os_family")
            if os_family:
                row.os_family = os_family
                row.os_vendor = host_data.get("os_vendor")
                row.os_accuracy = host_data.get("os_accuracy")

            # Only overwrite hostname if nmap resolved one and OPNsense didn't provide one
            nmap_hostname = host_data.get("hostname")
            if nmap_hostname and not row.hostname:
                row.hostname = nmap_hostname

            raw_xml = host_data.get("raw")
            if raw_xml:
                row.raw_nmap_xml = raw_xml

            updated += 1

        db.commit()
        logger.info(
            "OPNsense enrich job %d: updated %d/%d records",
            original_job_id,
            updated,
            len(private_ips),
        )
    except Exception as exc:
        logger.warning("OPNsense enrich job %d: DB update failed \u2014 %s", original_job_id, exc)
        db.rollback()
    finally:
        db.close()

    # ── Restore job to completed ──────────────────────────────────────────────
    completed = utcnow_iso()
    db = SessionLocal()
    try:
        job = db.get(ScanJob, original_job_id)
        if job:
            job.status = "completed"
            job.completed_at = completed
            job.progress_phase = "enrich_done"
            job.progress_message = f"Enriched {updated} hosts"
            db.commit()
    except Exception as exc:
        logger.warning(
            "OPNsense enrich job %d: could not restore completed — %s", original_job_id, exc
        )
        db.rollback()
    finally:
        db.close()

    await discovery_service._emit_ws_event(
        "job_update",
        {
            "job": {
                "id": original_job_id,
                "status": "completed",
                "completed_at": completed,
                "progress_percent": 100,
            }
        },
    )
