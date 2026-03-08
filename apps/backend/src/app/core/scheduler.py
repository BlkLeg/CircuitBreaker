# backend/app/core/scheduler.py

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler()


def start_scheduler():
    if not _scheduler.running:
        _scheduler.start()
        logger.info("APScheduler started")


def shutdown_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


def reload_discovery_jobs(db):
    """
    Read all enabled discovery_profiles with a schedule_cron.
    Remove any stale APScheduler jobs whose profile no longer exists
    or is disabled. Register CronTrigger jobs for active profiles.
    Job IDs follow the pattern: "discovery_profile_{profile_id}"
    """
    from app.db.models import DiscoveryProfile
    from app.services.discovery_service import purge_old_scan_results, run_scan_job_by_profile

    # Remove all existing discovery jobs
    for job in _scheduler.get_jobs():
        if job.id.startswith("discovery_profile_") or job.id == "discovery_purge":
            job.remove()

    profiles = (
        db.query(DiscoveryProfile)
        .filter(
            DiscoveryProfile.enabled == 1,
            DiscoveryProfile.schedule_cron.isnot(None),
            DiscoveryProfile.schedule_cron != "",
        )
        .all()
    )

    for profile in profiles:
        try:
            trigger = CronTrigger.from_crontab(profile.schedule_cron)
            _scheduler.add_job(
                run_scan_job_by_profile,
                trigger=trigger,
                id=f"discovery_profile_{profile.id}",
                args=[profile.id],
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(
                f"Scheduled discovery profile {profile.id} ({profile.name}): {profile.schedule_cron}"
            )
        except Exception as e:
            logger.error(f"Failed to schedule profile {profile.id}: {e}")

    # Register daily purge job
    _scheduler.add_job(
        purge_old_scan_results,
        trigger=CronTrigger(hour=3, minute=0),
        id="discovery_purge",
        replace_existing=True,
        misfire_grace_time=3600,
    )
