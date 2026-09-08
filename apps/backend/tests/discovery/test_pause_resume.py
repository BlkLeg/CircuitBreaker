"""Tests for pausing and resuming discovery scheduling: the per-subnet scope
and the fleet-wide hold.

Split out of the former tests/test_discovery.py.
"""

import pytest

from app.services import discovery_admission
from tests.discovery.helpers import (
    PROFILES_URL,
    _agent_profile_row,
    _cancels,
    _dispatched_job,
    _eligible_agent,
)

# ---------------------------------------------------------------------------
# Per-subnet pause / resume (Slice 4, §3/§6 M14 / Task 26)
# ---------------------------------------------------------------------------
#
# Task 25 landed the *reading* half of all three pause scopes: which profiles
# `core.scheduler.reload_discovery_jobs` may register a cron for is
# `discovery_admission.profiles_due_for_scheduling`'s answer, and a profile with
# `paused_at` set is withheld from it. These are the writers for the per-subnet
# scope.
#
# Pausing is not disabling, and the two must never be confused:
# `enabled = 0` means the subnet is *gone* (plan §3 step 6) and is D-14's
# cancellation trigger — it retires every dispatch the profile has in flight.
# A pause leaves the row, its cadence, its jobs and its results exactly where
# they are, and cancels nothing.


def _scheduled_profile_ids():
    from app.core.scheduler import get_scheduler

    return {
        int(job.id.removeprefix("discovery_profile_"))
        for job in get_scheduler().get_jobs()
        if job.id.startswith("discovery_profile_")
    }


@pytest.mark.asyncio
async def test_pausing_a_subnet_stops_its_cron_and_deletes_nothing(
    client, auth_headers, db_session, factories, cancel_frames
):
    """M14's per-subnet hold: the cadence stops, the row and its history stay,
    and the in-flight dispatch is *not* retired — that is what disabling does."""
    from app.core.scheduler import reload_discovery_jobs
    from app.db.models import DiscoveryProfile

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)
    reload_discovery_jobs(db_session)
    assert profile.id in _scheduled_profile_ids()

    resp = await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["paused_at"] is not None
    assert resp.json()["enabled"] is True

    db_session.refresh(profile)
    assert profile.paused_at is not None
    assert profile.enabled == 1
    assert profile.schedule_cron == "0 */6 * * *"
    assert db_session.get(DiscoveryProfile, profile.id) is not None
    assert profile.id not in _scheduled_profile_ids()

    # Pause is not disable (D-14): nothing is cancelled and nothing is told to stop.
    db_session.refresh(job)
    assert job.status == "running"
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_resuming_a_subnet_puts_its_cron_back(client, auth_headers, db_session, factories):
    """The hold has to be releasable, and releasing it must re-register the cron
    — `reload_discovery_jobs` removes every discovery job it owns before it
    re-registers, so a resume that only cleared the column would leave the
    profile silently unscheduled until some unrelated profile write happened."""
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)

    await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=auth_headers)
    assert profile.id not in _scheduled_profile_ids()

    resp = await client.post(f"{PROFILES_URL}/{profile.id}/resume", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["paused_at"] is None

    db_session.refresh(profile)
    assert profile.paused_at is None
    assert profile.id in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_pausing_a_subnet_twice_keeps_the_moment_it_was_held(
    client, auth_headers, db_session, factories
):
    """`paused_at` is "held since", which is what an operator reads off the row.
    A second pause that re-stamped it would erase how long the hold has been on."""
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)

    first = await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=auth_headers)
    second = await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=auth_headers)

    assert first.json()["paused_at"] == second.json()["paused_at"]


@pytest.mark.asyncio
async def test_pausing_an_unknown_subnet_is_a_404(client, auth_headers):
    resp = await client.post(f"{PROFILES_URL}/999999/pause", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pausing_a_subnet_requires_admin(client, viewer_headers, db_session, factories):
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    resp = await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=viewer_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# The fleet-wide hold (M14's third scope, Fix A2)
# ---------------------------------------------------------------------------
#
# `app_settings.agent_discovery_paused` did not exist as a column and was read
# through `getattr(settings, ..., False)` by way of a name constant, so the global
# scope answered "not paused" on every deployment and there was no route to change
# it either. Six scheduling tests reached it only by writing an *unmapped*
# attribute. These exercise the real column through the real endpoint.

PAUSE_URL = "/api/v1/discovery/pause"
RESUME_URL = "/api/v1/discovery/resume"


def _stored_global_pause(db_session) -> bool:
    """The column, by name, straight out of PostgreSQL.

    Deliberately raw SQL rather than the ORM attribute: this is the assertion
    that fails if the column is dropped or renamed, which is the failure mode
    the whole of Fix A2 exists for. An ORM read of a mapper that no longer maps
    it would just be an `AttributeError` somewhere else.
    """
    from sqlalchemy import text

    return bool(
        db_session.execute(
            text("SELECT agent_discovery_paused FROM app_settings ORDER BY id LIMIT 1")
        ).scalar()
    )


@pytest.mark.asyncio
async def test_pausing_the_fleet_stops_every_agent_cron_and_deletes_nothing(
    client, auth_headers, db_session, factories, cancel_frames
):
    """M14's widest hold: every agent-executed cadence stops, every row stays."""
    from app.core.scheduler import reload_discovery_jobs
    from app.db.models import DiscoveryProfile

    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)
    job = _dispatched_job(db_session, agent, profile_id=profile.id)
    reload_discovery_jobs(db_session)
    assert profile.id in _scheduled_profile_ids()

    resp = await client.post(PAUSE_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"paused": True}

    assert _stored_global_pause(db_session) is True
    assert profile.id not in _scheduled_profile_ids()
    # Pause is not disable (D-14): the subnet keeps its row, its cadence and its
    # in-flight dispatch, and nothing is told to stop.
    db_session.refresh(profile)
    assert profile.enabled == 1
    assert profile.paused_at is None
    assert profile.schedule_cron == "0 */6 * * *"
    assert db_session.get(DiscoveryProfile, profile.id) is not None
    db_session.refresh(job)
    assert job.status == "running"
    assert _cancels(cancel_frames) == []


@pytest.mark.asyncio
async def test_resuming_the_fleet_puts_the_agent_crons_back(
    client, auth_headers, db_session, factories
):
    """The hold has to be releasable, and releasing it must re-register the crons
    — `reload_discovery_jobs` drops every discovery job it owns first, so a
    resume that only cleared the column would leave the fleet silently
    unscheduled until some unrelated profile write rebuilt the schedule."""
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)

    await client.post(PAUSE_URL, headers=auth_headers)
    assert profile.id not in _scheduled_profile_ids()

    resp = await client.post(RESUME_URL, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"paused": False}

    assert _stored_global_pause(db_session) is False
    assert profile.id in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_resuming_the_fleet_does_not_release_a_subnet_held_on_its_own(
    client, auth_headers, db_session, factories
):
    """Task 25: three scopes, no precedence in either direction.

    A global resume that also released the per-subnet hold would let an operator
    clear a hold they never set — and, worse, would look identical to the
    correct behaviour until the subnet they meant to keep held started scanning.
    """
    agent = _eligible_agent(factories)
    profile = _agent_profile_row(db_session, agent)

    await client.post(f"{PROFILES_URL}/{profile.id}/pause", headers=auth_headers)
    await client.post(PAUSE_URL, headers=auth_headers)
    await client.post(RESUME_URL, headers=auth_headers)

    db_session.refresh(profile)
    assert profile.paused_at is not None, "the per-subnet hold is not the global one's to release"
    assert profile.id not in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_the_fleet_hold_leaves_server_executed_discovery_alone(
    client, auth_headers, db_session, factories
):
    """The global scope is narrower than it sounds, exactly as
    `global_agent_discovery_paused` documents: it holds *agent-executed*
    profiles. `app_settings.discovery_enabled` is already the product's master
    discovery switch, and a second flag that also stopped the server's own crons
    would mean holding an agent fleet silently stopped scanning the networks the
    server can see itself."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _eligible_agent(factories)
    agent_profile = _agent_profile_row(db_session, agent)
    server_profile = _agent_profile_row(
        db_session,
        agent,
        name="server-executed",
        scan_agent_id=None,
        managed_by=None,
        scan_types='["nmap"]',
    )
    reload_discovery_jobs(db_session)

    await client.post(PAUSE_URL, headers=auth_headers)

    assert agent_profile.id not in _scheduled_profile_ids()
    assert server_profile.id in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_the_fleet_hold_is_what_the_agent_detail_page_reports(
    client, auth_headers, db_session, factories
):
    """`AgentDiscoveryRead.globally_paused` is the field §6 renders the hold
    from, and it is fed by the same reader the scheduler uses — so the route and
    the page cannot disagree about whether the fleet is held."""

    _eligible_agent(factories)

    await client.post(PAUSE_URL, headers=auth_headers)
    assert discovery_admission.global_agent_discovery_paused(db_session) is True

    await client.post(RESUME_URL, headers=auth_headers)
    assert discovery_admission.global_agent_discovery_paused(db_session) is False


@pytest.mark.asyncio
async def test_pausing_the_fleet_requires_admin(client, viewer_headers):
    resp = await client.post(PAUSE_URL, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_resuming_the_fleet_requires_admin(client, viewer_headers):
    resp = await client.post(RESUME_URL, headers=viewer_headers)
    assert resp.status_code == 403
