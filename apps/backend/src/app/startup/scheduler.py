"""Startup-time background-work registration.

The scheduler jobs ``main.lifespan`` registers by hand stay in the lifespan —
they are one composition, and splitting them across files would hide the order
they run in.  What lives here is the work that has its own policy: which
discovery profiles are due a cron, and the one-shot enrichment backfill.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only — both are startup-path import costs
    from apscheduler.schedulers.base import BaseScheduler
    from sqlalchemy.orm import Session

_logger = logging.getLogger(__name__)


def register_discovery_profile_crons(scheduler: "BaseScheduler", db: "Session") -> None:
    """Give every discovery profile that is due one a cron, at process start.

    Which profiles those are is `discovery_service.profiles_due_for_scheduling`'s
    answer and nothing else's. That function is where Slice 4 plan §3/§6's three
    pause scopes are read — the fleet-wide `app_settings.agent_discovery_paused`,
    the per-agent `local_discovery.auto_discovery_paused` grant key, and the
    per-subnet `discovery_profiles.paused_at` — so **there is exactly one place
    in the product that decides whether a profile gets a cron**, and both
    registration sites (this one and `core.scheduler.reload_discovery_jobs`) ask
    it rather than deciding for themselves.

    This carried a verbatim copy of the predicate that function replaced
    (`enabled == 1 AND schedule_cron IS NOT NULL AND schedule_cron != ''`), which
    knew about none of the three holds. Every runtime writer of a hold rebuilds
    the live scheduler through `reload_discovery_jobs`, so the hold worked — and
    was then discarded by the next process start, the event *most likely* to
    follow an operator changing configuration. A pause has to be a property of
    the database, not of one process's scheduler state.

    `DISCOVERY_PROFILE_MISFIRE_GRACE_S` is shared with `reload_discovery_jobs`
    deliberately: the first profile write after startup re-registers every one of
    these jobs, and a cron that silently changed its catch-up behaviour the
    moment an unrelated profile was saved would be untraceable from the outside.
    """
    from apscheduler.triggers.cron import CronTrigger

    from app.core.scheduler import DISCOVERY_PROFILE_MISFIRE_GRACE_S
    from app.services import discovery_service

    for profile in discovery_service.profiles_due_for_scheduling(db):
        try:
            trigger = CronTrigger.from_crontab(profile.schedule_cron)
            scheduler.add_job(
                discovery_service.run_scan_job_by_profile,
                trigger=trigger,
                args=[profile.id],
                id=f"discovery_profile_{profile.id}",
                replace_existing=True,
                misfire_grace_time=DISCOVERY_PROFILE_MISFIRE_GRACE_S,
            )
            _logger.info("Scheduled discovery profile %d (%s)", profile.id, profile.name)
        except Exception as exc:
            _logger.warning("Could not schedule profile %d: %s", profile.id, exc)


def run_discovery_enrichment_backfill() -> None:
    """Owns the session for Phase 11's `backfill_pending_matched` call."""
    from app.db.session import SessionLocal
    from app.services.discovery_enrich import backfill_pending_matched

    db = SessionLocal()
    try:
        enriched = backfill_pending_matched(db)
        if enriched:
            _logger.info(
                "[discovery] enriched %d existing scan results out of the review queue",
                enriched,
            )
    finally:
        db.close()


async def shutdown_scheduler(scheduler: "BaseScheduler") -> None:
    """Stop the scheduler, giving running jobs ten seconds to finish.

    `shutdown(wait=True)` blocks, so it runs in an executor rather than on the
    event loop the departing workers still need. Past the budget it is forced,
    because a job that will not finish must not hold the process open past the
    unit's TimeoutStopSec.
    """
    import asyncio

    async def _shutdown() -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: scheduler.shutdown(wait=True))

    try:
        await asyncio.wait_for(_shutdown(), timeout=10.0)
        _logger.info("Scheduler shutdown complete")
    except TimeoutError:
        _logger.warning("Scheduler shutdown timed out after 10s — forcing stop")
        scheduler.shutdown(wait=False)
