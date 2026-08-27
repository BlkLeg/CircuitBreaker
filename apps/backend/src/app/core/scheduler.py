# backend/app/core/scheduler.py

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SingleOwnerScheduler(AsyncIOScheduler):
    """An `AsyncIOScheduler` whose every job runs on exactly one process (SRV-02).

    Each job registered here is wrapped in `job_lock.single_owner`, keyed by
    its APScheduler id, so a second API replica — a rolling restart with
    overlap, `uvicorn --workers 2`, a second container — skips the run instead
    of repeating the purge, the backup, or the integration sync. Wrapping at
    registration rather than at each of the ~30 call sites is deliberate: a job
    added later is guarded by construction, and forgetting is not an option a
    future edit has.

    An anonymous job is refused. APScheduler would give it a fresh UUID in
    every process, which is a lock name that can never collide and therefore an
    ownership guarantee that silently does not exist.
    """

    def add_job(self, func: "Any", *args: "Any", **kwargs: "Any") -> "Any":
        job_id = kwargs.get("id")
        if not job_id:
            raise ValueError(
                "SingleOwnerScheduler requires an explicit, stable job id: it is the "
                "advisory-lock name that makes the job single-owner across processes"
            )
        from app.core.job_lock import single_owner

        return super().add_job(single_owner(func, job_id=job_id), *args, **kwargs)


_scheduler = SingleOwnerScheduler()

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


async def run_scheduled_snapshot() -> None:
    """Scheduled wrapper for run_full_snapshot — called by APScheduler daily at 02:00.

    The job body lives here; its *registration* lives in `app.main.lifespan`.
    This function used to be registered by `reload_discovery_jobs` below, which
    runs only when an administrator writes a discovery profile — so a process
    that never saw such a write took no full-state snapshot at all, and nothing
    surfaced the gap: `latest_backup_info()` reports the `pg_backup` artifact,
    which is scheduled separately and kept being produced either way.
    """
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
    from app.services.discovery_scheduler import run_scan_job_by_profile
    from app.services.discovery_service import profiles_due_for_scheduling

    # Remove all existing discovery jobs
    scheduler = get_scheduler()

    # Only the per-profile crons. `discovery_purge` used to be removed here too,
    # because this function also registered it — see the note below the loop.
    for job in scheduler.get_jobs():
        if job.id.startswith("discovery_profile_"):
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

    # The daily scan-result purge is **not** registered here. `app.main.lifespan`
    # already registers the same callable at 03:00 under the id
    # `purge_old_scan_results`, and this function used to add a second copy of it
    # under the id `discovery_purge` (B43) — so every discovery-profile write left
    # two jobs running one purge on the same trigger. `SingleOwnerScheduler` keys
    # its advisory lock on the *job id*, so two ids are two locks: the copies did
    # not exclude each other, and the only reason the DELETE did not actually run
    # twice at once was `discovery_scheduler.purge_old_scan_results`' own inner
    # `run_with_advisory_lock("discovery_purge")` — a lock the scheduler knows
    # nothing about, and one a maintainer could reasonably delete on the grounds
    # that `SingleOwnerScheduler` is supposed to make it redundant. At that point
    # the duplicate becomes a genuine concurrent double purge. Do not re-add a
    # registration here: the purge has to exist on every boot, not only in the
    # stretch between a profile write and the next restart, which is the same
    # reason the nightly snapshot moved out of this function (B09).

    # Register daily aggregation rollup job
    from app.workers.rollup_worker import run_rollup_job

    scheduler.add_job(
        run_rollup_job,
        trigger=CronTrigger(hour=0, minute=5),  # Run at 12:05 AM
        id="daily_uptime_rollup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
