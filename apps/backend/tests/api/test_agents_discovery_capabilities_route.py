"""The same per-agent discovery pause/resume hold, written through the generic PUT
/agents/{id}/capabilities route instead of the dedicated pause endpoint (Phase
D); plus agent deletion against a discovery profile's live assignment, and the
fleet-wide pause reported separately from the per-agent one.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

from tests.api.agent_fakes import (
    DISCOVERY_SUBNET_B,
    _agent_profile,
    _discovery_agent,
    _discovery_url,
    _live_dispatch,
    _scheduled_profile_ids,
)

# ---------------------------------------------------------------------------
# The same hold, written through the generic capabilities route (Phase D)
# ---------------------------------------------------------------------------
#
# `auto_discovery_paused` is an ordinary client-settable key of the
# `local_discovery` grant, so `PUT /agents/{id}/capabilities` is a second, fully
# supported writer of the flag the dedicated pause route writes. Both writers
# have to leave the fleet in the same state; a hold that is accepted but not
# applied until some unrelated profile write happens to rebuild the schedule is
# a hold the operator was told they had and did not.


@pytest.mark.asyncio
async def test_pausing_through_the_capabilities_route_stops_the_crons_immediately(
    client, factories, auth_headers, db_session
):
    """Whichever route writes the flag has to be the thing that rebuilds the
    schedule. `profiles_due_for_scheduling` is asked once per
    `reload_discovery_jobs`, so a write that did not rebuild would leave the
    already-registered cron with its fire times and the operator with a hold they
    were told they had. `discovery_admission.profile_scheduling_held` re-reads the
    same three scopes when a cron fires and would keep the scan from running, but
    it is the second line and not the first: the schedule an operator reads off
    `next_scheduled` has to stop showing runs that will not happen."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _discovery_agent(factories)
    profile = _agent_profile(db_session, agent)
    reload_discovery_jobs(db_session)
    assert profile.id in _scheduled_profile_ids()

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={
            "capabilities": {
                "local_discovery": {"enabled": True, "config": {"auto_discovery_paused": True}}
            }
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    grant = resp.json()["capabilities"]["local_discovery"]
    assert grant["config"]["auto_discovery_paused"] is True
    assert profile.id not in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_resuming_through_the_capabilities_route_puts_the_crons_back(
    client, factories, auth_headers, db_session
):
    """The clearing edge of the same write. A resume that needed a second,
    unrelated write to take effect would leave an operator staring at an agent
    they had just un-paused and no next scheduled run."""
    agent = _discovery_agent(factories, config={"auto_discovery_paused": True})
    profile = _agent_profile(db_session, agent)

    from app.core.scheduler import reload_discovery_jobs

    reload_discovery_jobs(db_session)
    assert profile.id not in _scheduled_profile_ids()

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={
            "capabilities": {
                "local_discovery": {"enabled": True, "config": {"auto_discovery_paused": False}}
            }
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert profile.id in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_a_capabilities_write_that_leaves_the_hold_alone_does_not_rebuild_the_schedule(
    client, factories, auth_headers, db_session, monkeypatch
):
    """The rebuild is conditional on the flag actually moving. Every capability
    edit in the product would otherwise tear down and re-register every discovery
    cron in the installation, which is a fleet-wide cost for a per-agent write
    that changed nothing the schedule is derived from."""
    from app.api import agents as agents_api

    agent = _discovery_agent(factories)
    _agent_profile(db_session, agent)
    reloads: list[bool] = []
    monkeypatch.setattr(agents_api, "reload_discovery_jobs", lambda db: reloads.append(True))

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"host_telemetry": True}},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert reloads == []


@pytest.mark.asyncio
async def test_deleting_an_agent_a_discovery_profile_names_returns_409(
    client, factories, auth_headers, db_session
):
    """D-1: `discovery_profiles.scan_agent_id` is `ON DELETE RESTRICT`, so
    without a pre-check the delete surfaces as an unhandled `IntegrityError` and
    a 500 — and the operator learns nothing about which profiles are in the way.
    Repointing or deleting them is a decision they make explicitly."""
    from app.db.models import Agent

    agent = _discovery_agent(factories)
    _agent_profile(db_session, agent, name="lab subnet")
    _agent_profile(
        db_session,
        agent,
        name="dmz subnet",
        cidr=DISCOVERY_SUBNET_B,
        normalized_cidr=DISCOVERY_SUBNET_B,
    )

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "2" in detail
    assert "lab subnet" in detail and "dmz subnet" in detail
    assert db_session.get(Agent, agent.id) is not None


@pytest.mark.asyncio
async def test_deleting_an_agent_with_only_finished_discovery_history_succeeds(
    client, factories, auth_headers, db_session
):
    """The other half of D-1's split. Jobs and results are CASCADE because they
    are finished history; only the *live assignment* a profile makes is
    RESTRICT. A pre-check that counted jobs would make an agent that ever ran a
    scan permanently undeletable."""
    from app.db.models import Agent

    agent = _discovery_agent(factories)
    _live_dispatch(db_session, agent, status="completed", dispatch_status="completed")

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)

    assert resp.status_code == 204, resp.text
    db_session.expunge_all()
    assert db_session.query(Agent).filter(Agent.id == agent.id).count() == 0


@pytest.mark.asyncio
async def test_deleting_an_agent_succeeds_once_no_profile_names_it(
    client, factories, auth_headers, db_session
):
    from app.db.models import Agent

    agent = _discovery_agent(factories)
    profile = _agent_profile(db_session, agent)

    blocked = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert blocked.status_code == 409

    profile.scan_agent_id = None
    db_session.flush()

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text
    db_session.expunge_all()
    assert db_session.query(Agent).filter(Agent.id == agent.id).count() == 0


@pytest.mark.asyncio
async def test_agent_discovery_reports_the_fleet_wide_hold_separately(
    client, factories, viewer_headers, db_session
):
    """M14's three pause scopes have no precedence between them: each holds on
    its own and none releases either of the others (Task 25). So the section
    reports them as two independent fields — an operator who resumed the agent
    and saw nothing start needs to be told the fleet is still held, not shown one
    derived boolean that flipped back on its own.

    The fleet-wide hold is written here as the mapped column
    `app_settings.agent_discovery_paused`, real since migration
    `0101_discovery_retention_and_global_pause` (Fix A2). It used to be written by
    name through a constant and `setattr`, under a docstring claiming the column
    was not in the schema yet — a form that succeeds against *any* attribute name
    and so could not fail when the storage did not exist, which is exactly how the
    global scope stayed unstorable behind green tests. Naming the attribute
    directly is what makes a dropped or renamed column break this test.
    """
    from app.services.settings_service import get_or_create_settings

    agent = _discovery_agent(factories)
    settings = get_or_create_settings(db_session)

    before = (await client.get(_discovery_url(agent), headers=viewer_headers)).json()
    assert before["globally_paused"] is False
    assert before["paused"] is False

    settings.agent_discovery_paused = True
    db_session.flush()

    body = (await client.get(_discovery_url(agent), headers=viewer_headers)).json()
    assert body["globally_paused"] is True
    # The per-agent scope is untouched by the fleet-wide one.
    assert body["paused"] is False
