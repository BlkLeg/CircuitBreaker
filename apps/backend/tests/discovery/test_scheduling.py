"""Tests for discovery scheduling across process restarts and at fire time:
restart survival re-registers what should still be scheduled, and a firing
cron re-checks pause state before it scans.

Split out of the former tests/test_discovery.py.
"""

import pytest

from app.services import discovery_admission
from tests.discovery.helpers import _agent_profile_row, _eligible_agent

# ---------------------------------------------------------------------------
# Restart survival (Phase D close-out): the startup path asks the same question
# ---------------------------------------------------------------------------
#
# Task 25 made `discovery_admission.profiles_due_for_scheduling` the one place
# that decides whether a profile gets a cron, and every *runtime* writer of the
# three holds goes through `core.scheduler.reload_discovery_jobs`, which asks it.
# `app.main`'s startup registration is the second, easily-forgotten caller: it is
# not reached by any API request, so a hold written through a route was applied
# to the live scheduler and then discarded the next time the process came up.
# A restart is the event *most likely* to follow an operator changing
# configuration, which is what makes "correct until restart" the worst possible
# shape for a safety control.
#
# These exercise `app.main`'s real startup helper against a brand-new scheduler,
# because that is what a restart actually has: an empty scheduler and the
# database.


def _restarted_scheduler():
    """The scheduler a freshly-started process has: a new one, with no jobs.

    Not the process-global instance other suites have been registering jobs on —
    nothing that survived in memory may be allowed to decide the outcome, since
    surviving in memory is exactly what a restart does not do.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    return AsyncIOScheduler()


def _profile_ids_registered_on(scheduler) -> set[int]:
    return {
        int(job.id.removeprefix("discovery_profile_"))
        for job in scheduler.get_jobs()
        if job.id.startswith("discovery_profile_")
    }


def _startup_schedule(db_session) -> set[int]:
    """Rebuild the discovery schedule the way `app.main`'s lifespan does."""
    from app.startup.scheduler import register_discovery_profile_crons

    scheduler = _restarted_scheduler()
    register_discovery_profile_crons(scheduler, db_session)
    return _profile_ids_registered_on(scheduler)


def test_a_restart_reschedules_a_profile_that_is_not_held(db_session, factories):
    """The control for the three below: without it they would all pass against a
    startup path that registered nothing at all."""
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)

    assert profile.id in _startup_schedule(db_session)


def test_a_restart_does_not_reschedule_a_subnet_held_on_its_own(db_session, factories):
    """M14's per-subnet hold has to be a property of the row, not of one
    process's scheduler state: `paused_at` is set, so no restart may hand the
    profile its cadence back."""
    from app.core.time import utcnow

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    profile.paused_at = utcnow()
    db_session.flush()

    assert profile.id not in _startup_schedule(db_session)


def test_a_restart_does_not_reschedule_a_profile_whose_agent_is_held(db_session, factories):
    """M14's per-agent hold lives in the `local_discovery` grant, so a restart
    that re-read only `discovery_profiles` could not see it at all."""
    from app.db.models import AgentCapabilityGrant

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    # The grant `_eligible_agent` already created, held: one row per
    # (agent, capability), so the hold is an edit and not a second grant.
    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="local_discovery")
        .one()
    )
    grant.config = {discovery_admission.AGENT_DISCOVERY_PAUSE_KEY: True}
    db_session.flush()

    assert profile.id not in _startup_schedule(db_session)


def test_a_restart_does_not_reschedule_an_agent_profile_while_the_fleet_is_held(
    db_session, factories
):
    """M14's widest hold, and the one whose loss is quietest: nothing about the
    profile row or the grant looks paused, so the resumed cadence would be
    indistinguishable from a fleet that was never held."""
    from app.services.settings_service import get_or_create_settings

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    get_or_create_settings(db_session).agent_discovery_paused = True
    db_session.flush()

    assert profile.id not in _startup_schedule(db_session)


# ---------------------------------------------------------------------------
# The fire-time re-check (Phase D close-out)
# ---------------------------------------------------------------------------
#
# APScheduler is PROCESS-LOCAL and production runs `uvicorn --workers 2`, so a
# pause applied through an API request rebuilds the schedule of the ONE worker
# that served the request. The other worker's already-registered cron keeps its
# fire times until something independently rebuilds its schedule — which nothing
# does, because `reload_discovery_jobs` is only ever reached from a request that
# landed in that worker.
#
# A registration-time-only gate is therefore not a hold at all on a multi-worker
# deployment; it is a hold on one worker. It is also the exact shape that made
# the startup defect above and the earlier per-agent-pause defect possible. So
# the pause is re-read when the cron fires, through the same function, and the
# scopes have one definition rather than two that agree today.


def _held_scopes(db_session, profile):
    """`(single-profile answer, withheld from the fleet-wide answer)`.

    Both readers, asked about the same row, so a fix that taught one scope to the
    fire-time gate and not to the startup gate cannot pass.
    """

    due = {p.id for p in discovery_admission.profiles_due_for_scheduling(db_session)}
    return (
        discovery_admission.profile_scheduling_held(db_session, profile),
        profile.id not in due,
    )


def test_the_two_pause_readers_agree_that_a_held_subnet_is_held(db_session, factories):
    from app.core.time import utcnow

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    assert _held_scopes(db_session, profile) == (False, False)

    profile.paused_at = utcnow()
    db_session.flush()

    assert _held_scopes(db_session, profile) == (True, True)


def test_the_two_pause_readers_agree_that_a_held_agents_profile_is_held(db_session, factories):
    from app.db.models import AgentCapabilityGrant

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="local_discovery")
        .one()
    )
    grant.config = {discovery_admission.AGENT_DISCOVERY_PAUSE_KEY: True}
    db_session.flush()

    assert _held_scopes(db_session, profile) == (True, True)


def test_the_two_pause_readers_agree_that_a_held_fleet_holds_an_agent_profile(
    db_session, factories
):
    from app.services.settings_service import get_or_create_settings

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    get_or_create_settings(db_session).agent_discovery_paused = True
    db_session.flush()

    assert _held_scopes(db_session, profile) == (True, True)


def test_the_fleet_hold_does_not_hold_a_server_executed_profile_at_fire_time(db_session, factories):
    """The narrower scope `global_agent_discovery_paused` documents, asked of the
    single-profile reader too: a server-executed profile has no agent, and the
    fleet-wide hold is a hold on the agent fleet."""
    from app.services.settings_service import get_or_create_settings

    agent = _eligible_agent(factories)
    server_profile = _agent_profile_row(
        db_session,
        agent,
        name="server-executed-fire-time",
        scan_agent_id=None,
        managed_by=None,
        scan_types='["nmap"]',
    )
    get_or_create_settings(db_session).agent_discovery_paused = True
    db_session.flush()

    assert _held_scopes(db_session, server_profile) == (False, False)


@pytest.fixture
def cron_session_on_the_test_connection(db_session, monkeypatch):
    """Point `_run_profile_job_async`'s own `SessionLocal()` at this test's rows.

    The cron entry point deliberately opens its own session — it runs on an
    APScheduler thread with no request scope. That session cannot see
    `db_session`'s SAVEPOINT, so it is bound to the same connection here instead
    of committing the fixture data on a second connection: the pause being tested
    is `app_settings.agent_discovery_paused` in one case, and a real commit of a
    fleet-wide hold would outlive the test and silently pause every suite that
    ran after it.
    """
    from sqlalchemy.orm import Session as _Session

    from app.services import discovery_scheduler

    connection = db_session.connection()
    monkeypatch.setattr(
        discovery_scheduler,
        "SessionLocal",
        lambda: _Session(bind=connection, join_transaction_mode="create_savepoint"),
    )


@pytest.fixture
def executed_jobs(monkeypatch):
    """Records what `_run_profile_job_async` handed to the router, and runs none
    of it — the router's next step is a real network scan or an agent dispatch."""
    from app.services import discovery_dispatch

    seen: list[int] = []

    async def _record(db, job_id):  # type: ignore[no-untyped-def]
        seen.append(job_id)

    monkeypatch.setattr(discovery_dispatch, "execute_scan_job", _record)
    return seen


@pytest.mark.asyncio
async def test_a_firing_cron_scans_a_profile_that_is_not_held(
    db_session, factories, cron_session_on_the_test_connection, executed_jobs
):
    """The control: without it every assertion below would hold against a cron
    body that had stopped creating jobs entirely."""
    from app.db.models import ScanJob
    from app.services import discovery_scheduler

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    db_session.flush()

    await discovery_scheduler._run_profile_job_async(profile.id)

    jobs = db_session.query(ScanJob).filter(ScanJob.profile_id == profile.id).all()
    assert len(jobs) == 1, jobs
    assert executed_jobs == [jobs[0].id]


@pytest.mark.asyncio
async def test_a_firing_cron_does_not_scan_a_subnet_held_on_its_own(
    db_session, factories, cron_session_on_the_test_connection, executed_jobs
):
    """A pause has to be a property of the database, not of the scheduler that
    happened to serve the pause request: the other uvicorn worker's cron still
    fires, and this is the only thing standing between it and a scan the operator
    forbade."""
    from app.core.time import utcnow
    from app.db.models import ScanJob
    from app.services import discovery_scheduler

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    profile.paused_at = utcnow()
    db_session.flush()

    await discovery_scheduler._run_profile_job_async(profile.id)

    assert db_session.query(ScanJob).filter(ScanJob.profile_id == profile.id).all() == []
    assert executed_jobs == []
    # `last_run` is what §6 renders as "last scanned"; a hold that stamped it
    # would report a scan that never happened.
    db_session.refresh(profile)
    assert profile.last_run is None


@pytest.mark.asyncio
async def test_a_firing_cron_does_not_scan_while_the_fleet_is_held(
    db_session, factories, cron_session_on_the_test_connection, executed_jobs
):
    """The fleet-wide scope reaches the fire-time gate too — a gate that knew
    only the profile row would let the widest hold in the product be defeated by
    a second worker."""
    from app.db.models import ScanJob
    from app.services import discovery_scheduler
    from app.services.settings_service import get_or_create_settings

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    get_or_create_settings(db_session).agent_discovery_paused = True
    db_session.flush()

    await discovery_scheduler._run_profile_job_async(profile.id)

    assert db_session.query(ScanJob).filter(ScanJob.profile_id == profile.id).all() == []
    assert executed_jobs == []
