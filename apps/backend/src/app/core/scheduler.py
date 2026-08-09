# backend/app/core/scheduler.py

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler()

#: Catch-up window for a discovery-profile cron whose fire time was missed.
#: Named and exported because `app.main` registers the same jobs at startup:
#: a profile that changed its catch-up behaviour the moment an unrelated
#: profile write triggered the first reload of a process would be
#: untraceable from the outside.
DISCOVERY_PROFILE_MISFIRE_GRACE_S = 300


def set_scheduler_instance(scheduler: AsyncIOScheduler) -> None:
    """Bind scheduler helpers to the app's active scheduler instance."""
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler:
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler started")


def shutdown_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


async def _run_scheduled_snapshot() -> None:
    """Scheduled wrapper for run_full_snapshot — called by APScheduler daily at 02:00."""
    from app.db.session import SessionLocal
    from app.services.backup.snapshot import BackupError
    from app.services.db_backup import run_full_snapshot

    try:
        with SessionLocal() as db:
            tarball = await run_full_snapshot(db)
            logger.info("Scheduled snapshot completed: %s", tarball.name)
    except BackupError as exc:
        logger.error("Scheduled snapshot failed: %s", exc)
    except Exception as exc:
        logger.error("Unexpected error in scheduled snapshot: %s", exc)


def reload_discovery_jobs(db: Session) -> None:
    """
    Read all enabled discovery_profiles with a schedule_cron.
    Remove any stale APScheduler jobs whose profile no longer exists
    or is disabled. Register CronTrigger jobs for active profiles.
    Job IDs follow the pattern: "discovery_profile_{profile_id}"

    Which profiles are due is `discovery_service.profiles_due_for_scheduling`'s
    answer, not a query written here: Slice 4 plan §3 lets an operator pause
    automatic discovery globally, per agent or per subnet, and a pause has to be
    a decision of the discovery domain rather than of the module that turns the
    answer into `CronTrigger`s. Because this function removes every discovery job
    it owns before re-registering, withholding a profile here is the whole
    mechanism: nothing is deleted, and the profile resumes on the next reload.
    """
    from app.services.discovery_scheduler import purge_old_scan_results, run_scan_job_by_profile
    from app.services.discovery_service import profiles_due_for_scheduling

    # Remove all existing discovery jobs
    scheduler = get_scheduler()

    for job in scheduler.get_jobs():
        if job.id.startswith("discovery_profile_") or job.id == "discovery_purge":
            job.remove()

    profiles = profiles_due_for_scheduling(db)

    for profile in profiles:
        try:
            trigger = CronTrigger.from_crontab(profile.schedule_cron)
            scheduler.add_job(
                run_scan_job_by_profile,
                trigger=trigger,
                id=f"discovery_profile_{profile.id}",
                args=[profile.id],
                replace_existing=True,
                misfire_grace_time=DISCOVERY_PROFILE_MISFIRE_GRACE_S,
            )
            logger.info(
                f"Scheduled discovery profile {profile.id}"
                f" ({profile.name}): {profile.schedule_cron}"
            )
        except Exception as e:
            logger.error(f"Failed to schedule profile {profile.id}: {e}")

    # Register daily purge job
    scheduler.add_job(
        purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="discovery_purge",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Register daily aggregation rollup job
    from app.workers.rollup_worker import run_rollup_job

    scheduler.add_job(
        run_rollup_job,
        trigger=CronTrigger(hour=0, minute=5),  # Run at 12:05 AM
        id="daily_uptime_rollup",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Daily full-state snapshot at 02:00
    scheduler.add_job(
        _run_scheduled_snapshot,
        CronTrigger(hour=2, minute=0),
        id="daily_db_snapshot",
        replace_existing=True,
    )
