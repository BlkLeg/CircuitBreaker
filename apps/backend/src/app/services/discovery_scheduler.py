"""Job scheduling, profile scan dispatch, and purge lifecycle for discovery."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import ScanJob, ScanResult
from app.db.session import SessionLocal
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger(__name__)


# B4: The main event loop captured at import time (set by main.py lifespan).
# APScheduler jobs run in a thread pool; they must dispatch coroutines onto
# this loop with run_coroutine_threadsafe — NOT asyncio.run() — so that
# ws_manager.broadcast() reaches the live WebSocket connections.
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from main.py lifespan startup to register the running loop."""
    global _main_loop
    _main_loop = loop


def main_loop() -> asyncio.AbstractEventLoop | None:
    """The loop `set_main_loop` registered, or None before the lifespan ran.

    An accessor rather than a re-exported global: `_main_loop` is None at import
    time, so a caller that did `from ... import _main_loop` would capture the
    None and never see the loop. `discovery_service.schedule_discovery_scan_job`
    needs the live value because it can be reached from a `run_in_executor`
    worker thread, which has no running loop of its own.
    """
    return _main_loop


def _running_scan_count(db: Session) -> int:
    return db.query(ScanJob).filter(ScanJob.status == "running").count()


def _max_concurrent_scans(settings: object) -> int:
    return max(1, int(getattr(settings, "max_concurrent_scans", 2) or 2))


def _schedule_queued_scan_jobs(db: Session) -> None:
    """Hand as much of the queued backlog to the scan executor as the ceiling allows.

    A job parked in `waiting_for_agent` is deliberately excluded (D-5). That row
    is owned by `agent_discovery_reconcile`, which retries it when its agent is
    back and expires it as `agent_unavailable` when the agent never returns;
    handing it back to `dispatch_discovery_job` while the agent is still away
    has `agent_discovery._release_to_waiting` stamp a fresh
    `dispatch_deadline_at = now + DISPATCH_DEADLINE_S` over the deadline that
    was about to expire it. This drain runs whenever *any* job anywhere
    finishes, so without the guard an unrelated scan completing resets a parked
    job's clock and D-5's expiry can never arrive.
    `agent_discovery_reconcile._drain_queued_jobs` documents and guards the same
    treadmill; the two paths now agree. (Making `_release_to_waiting` preserve
    an existing deadline instead of re-stamping it would fix it from the other
    end and would be a reasonable second belt — but the guard is what the
    reconciler already does, so it is the one behaviour to copy.)
    """
    # Imported here, not at module scope: `agent_discovery` imports
    # `discovery_service`, which imports this module.
    from app.services.agent_discovery import PHASE_WAITING_FOR_AGENT
    from app.services.discovery_service import schedule_discovery_scan_job

    settings = get_or_create_settings(db)
    available_slots = _max_concurrent_scans(settings) - _running_scan_count(db)
    if available_slots <= 0:
        return

    queued_jobs = (
        db.query(ScanJob)
        .filter(
            ScanJob.status == "queued",
            # `IS DISTINCT FROM` rather than `!=`: a NULL phase is an ordinary
            # queued job, and `!=` would drop it from the backlog entirely.
            ScanJob.progress_phase.is_distinct_from(PHASE_WAITING_FOR_AGENT),
        )
        .order_by(ScanJob.created_at.asc(), ScanJob.id.asc())
        .limit(available_slots)
        .all()
    )

    for queued in queued_jobs:
        schedule_discovery_scan_job(queued.id)


async def _run_profile_job_async(profile_id: int) -> None:
    """Internal async helper to create and run a profile job.

    The job inherits the profile's execution location and is then routed by
    `discovery_service.execute_scan_job`, which is the one branch between the
    server scanner and an agent. Both halves matter: a job created without
    `scan_agent_id` could not be routed anywhere even by a correct router, and a
    cron that called `run_scan_job` directly would run an agent-targeted profile
    from the server's vantage point — which plan §3 forbids, because it silently
    changes what the scan can see.
    """
    from app.services.discovery_service import execute_scan_job  # lazy import

    db = SessionLocal()
    try:
        from app.db.models import DiscoveryProfile
        from app.services.discovery_service import create_scan_job

        profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()
        if not profile or not profile.enabled:
            return

        from app.core.time import utcnow_iso

        profile.last_run = utcnow_iso()
        db.commit()

        scan_types = json.loads(profile.scan_types)
        vlan_ids = []
        if profile.vlan_ids:
            try:
                vlan_ids = json.loads(profile.vlan_ids)
            except Exception as e:
                logger.debug(
                    "Discovery: vlan_ids parse failed for profile %s: %s",
                    profile.id,
                    e,
                    exc_info=True,
                )

        job = create_scan_job(
            db,
            target_cidr=profile.cidr,
            vlan_ids=vlan_ids,
            scan_types=scan_types,
            profile_id=profile.id,
            triggered_by="scheduler",
            # Copied onto the job rather than read back off the profile later:
            # a profile repointed at another agent must not rewrite the
            # attribution of scans that already ran.
            scan_agent_id=profile.scan_agent_id,
        )
        await execute_scan_job(db, job.id)
    finally:
        db.close()


def _run_scan_job_by_profile_impl(profile_id: int) -> None:
    """Inner implementation for APScheduler profile scan (called under advisory lock)."""
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_run_profile_job_async(profile_id), _main_loop)
    else:
        asyncio.run(_run_profile_job_async(profile_id))


def run_scan_job_by_profile(profile_id: int) -> None:
    """Entry point for APScheduler to kick off a profile scan. Single-run via advisory lock."""
    from app.core.job_lock import run_with_advisory_lock

    run_with_advisory_lock(
        "discovery_profile", profile_id, job_fn=lambda: _run_scan_job_by_profile_impl(profile_id)
    )


def _purge_old_scan_results_impl() -> None:
    """Daily cron job body: purge old scan results and jobs (called under advisory lock)."""
    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        retention_days = settings.discovery_retention_days
        if retention_days <= 0:
            return

        logger.info(f"Purging discovery results older than {retention_days} days.")

        cutoff_date = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff_iso = cutoff_date.isoformat() + "Z"

        result_count = (
            db.query(ScanResult)
            .filter(ScanResult.created_at < cutoff_iso)
            .delete(synchronize_session=False)
        )
        job_count = (
            db.query(ScanJob)
            .filter(ScanJob.created_at < cutoff_iso)
            .delete(synchronize_session=False)
        )
        db.commit()

        logger.info(f"Purged {result_count} old scan results and {job_count} old scan jobs.")
    except Exception as e:
        logger.error(f"Purger error: {e}")
    finally:
        db.close()


def purge_old_scan_results() -> None:
    """Daily cron job to purge old scan results and jobs. Single-run via advisory lock."""
    from app.core.job_lock import run_with_advisory_lock

    run_with_advisory_lock("discovery_purge", job_fn=_purge_old_scan_results_impl)


def refresh_ip_pool() -> None:
    """
    Scheduled job to refresh IP statuses in the live_metrics table.
    Checks reachability of known IP addresses and updates last_seen and status.
    """
    db = SessionLocal()
    try:
        from concurrent.futures import ThreadPoolExecutor

        from app.db.models import LiveMetric
        from app.services.discovery_safe import _ping_host

        metrics = db.query(LiveMetric).all()
        now = datetime.now(UTC)

        def check_metric(metric: LiveMetric) -> tuple[LiveMetric, bool]:
            if not metric.ip:
                return metric, False
            # Ping with a short timeout to prevent long hangs
            is_up = _ping_host(metric.ip, timeout=1.0)
            return metric, is_up

        # Use ThreadPoolExecutor for concurrent pings
        with ThreadPoolExecutor(max_workers=50) as executor:
            results = list(executor.map(check_metric, metrics))

        for metric, _is_up in results:
            if metric.last_seen and (now - metric.last_seen) > timedelta(days=1):
                metric.status = "offline"

        db.commit()
    except Exception as e:
        logger.error(f"Error in refresh_ip_pool: {e}")
    finally:
        db.close()
