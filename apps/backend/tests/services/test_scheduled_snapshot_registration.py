"""Who owns the nightly full-state snapshot job.

The 02:00 snapshot is the tarball `cb restore` accepts — vault key, uploads and
config — so "the job is registered" is not a scheduling detail, it is whether
the product has a restorable artifact from last night at all. Registering it
inside `core.scheduler.reload_discovery_jobs` gets that wrong twice over: that
function runs only when an administrator writes a discovery profile, so a
process that never sees such a write never schedules the snapshot, and the
`pg_backup` artifact that `latest_backup_info()` surfaces keeps being produced
either way — nothing shows the gap until a restore needs a tarball that was
never taken.

The lifespan is the one place that runs on every boot, and
`agent_discovery_reconcile` is the precedent this mirrors: registered there,
tested for there.
"""

from pathlib import Path

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.core import scheduler as scheduler_module
from app.core.scheduler import SingleOwnerScheduler, reload_discovery_jobs, run_scheduled_snapshot

SNAPSHOT_JOB_ID = "daily_db_snapshot"


@pytest.fixture
def fresh_scheduler():  # type: ignore[no-untyped-def]
    """A scheduler of this test's own, bound in place of the process-global one.

    Left unstarted deliberately: `add_job` on a stopped scheduler parks the job
    in `_pending_jobs`, which `get_job`/`get_jobs` still read, so registration
    is observable without an event loop and without firing anything at 02:00.
    Other suites leave jobs on the global scheduler, and this one asserts on the
    *absence* of a job id.
    """
    previous = scheduler_module.get_scheduler()
    fresh = SingleOwnerScheduler()
    scheduler_module.set_scheduler_instance(fresh)
    try:
        yield fresh
    finally:
        scheduler_module.set_scheduler_instance(previous)


def test_reload_discovery_jobs_does_not_own_the_nightly_snapshot(fresh_scheduler, db_session):
    """A discovery-profile write is not the event that should decide whether a
    backup exists. If this function registers the snapshot, then an installation
    whose profiles are never touched — the common one — takes no snapshot for as
    long as it runs, and every restart of a busier one reopens the same window
    until the next profile write closes it."""
    reload_discovery_jobs(db_session)

    assert fresh_scheduler.get_job(SNAPSHOT_JOB_ID) is None, (
        "reload_discovery_jobs registered the nightly snapshot; it belongs in the "
        "lifespan, which runs on every boot"
    )


def test_a_profile_write_leaves_the_lifespans_snapshot_job_alone(fresh_scheduler, db_session):
    """The other half of the move: `reload_discovery_jobs` removes every job it
    owns before re-registering, and the id filter it removes by must not grow to
    include the snapshot. Registered the way the lifespan registers it, then put
    through the profile write that a lifespan-registered job has to survive."""
    fresh_scheduler.add_job(
        run_scheduled_snapshot,
        trigger=CronTrigger(hour=2, minute=0),
        id=SNAPSHOT_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )

    reload_discovery_jobs(db_session)

    job = fresh_scheduler.get_job(SNAPSHOT_JOB_ID)
    assert job is not None, "a profile write unregistered the nightly snapshot"
    assert "hour='2'" in str(job.trigger), str(job.trigger)


def test_the_snapshot_job_is_registered_in_the_lifespan_and_not_in_reload_discovery_jobs():
    """Registration is a single statement in `main.lifespan` and nothing calls
    it, so no test can reach it by running code — the lifespan itself needs a
    database, a vault and a scheduler thread. Asserted against the source, the
    way the `agent_discovery_reconcile` precedent next door is.

    `misfire_grace_time` is part of the assertion: APScheduler's default drops a
    fire time the process slept through, and a restart that straddles 02:00 is
    exactly when the snapshot matters most.
    """
    backend = Path(__file__).resolve().parents[2]
    main_py = (backend / "src/app/main.py").read_text()
    scheduler_py = (backend / "src/app/core/scheduler.py").read_text()

    assert f'id="{SNAPSHOT_JOB_ID}"' in main_py
    assert "run_scheduled_snapshot" in main_py
    assert f'id="{SNAPSHOT_JOB_ID}"' not in scheduler_py

    registration = main_py[main_py.index(f'id="{SNAPSHOT_JOB_ID}"') - 400 :][:600]
    assert "misfire_grace_time=3600" in registration, registration
