"""Per-agent discovery pause / resume, and deletion against a live discovery-
profile assignment (Task 26). The pause is a distinct hold from a capability
disable -- it stops scheduling without cancelling in-flight work.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

from tests.api.agent_fakes import (
    _agent_profile,
    _build_discovery_frames,
    _discovery_agent,
    _discovery_cancels,
    _live_dispatch,
    _scheduled_profile_ids,
)

# ---------------------------------------------------------------------------
# Per-agent pause / resume, and deletion against a live assignment (Task 26)
# ---------------------------------------------------------------------------


@pytest.fixture
def discovery_frames(monkeypatch):
    """Every control frame these routes put on the wire."""
    return _build_discovery_frames(monkeypatch)


@pytest.mark.asyncio
async def test_pausing_an_agents_discovery_stops_its_crons_and_cancels_nothing(
    client, factories, auth_headers, db_session, discovery_frames
):
    """M14's per-agent hold. It is *not* a capability disable: D-14 retires
    every in-flight dispatch when the grant goes off, and a pause that did the
    same would make "hold this agent for an hour" destroy work in progress."""
    from app.core.scheduler import reload_discovery_jobs

    agent = _discovery_agent(factories)
    profile = _agent_profile(db_session, agent)
    job = _live_dispatch(db_session, agent, profile_id=profile.id)
    reload_discovery_jobs(db_session)
    assert profile.id in _scheduled_profile_ids()

    resp = await client.post(f"/api/v1/agents/{agent.id}/discovery/pause", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["paused"] is True
    assert resp.json()["granted"] is True
    assert profile.id not in _scheduled_profile_ids()
    db_session.refresh(job)
    assert job.status == "running"
    assert _discovery_cancels(discovery_frames) == []


@pytest.mark.asyncio
async def test_resuming_an_agents_discovery_puts_its_crons_back(
    client, factories, auth_headers, db_session
):
    agent = _discovery_agent(factories)
    profile = _agent_profile(db_session, agent)

    await client.post(f"/api/v1/agents/{agent.id}/discovery/pause", headers=auth_headers)
    assert profile.id not in _scheduled_profile_ids()

    resp = await client.post(f"/api/v1/agents/{agent.id}/discovery/resume", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["paused"] is False
    assert profile.id in _scheduled_profile_ids()


@pytest.mark.asyncio
async def test_pausing_an_agents_discovery_leaves_the_rest_of_the_grant_alone(
    client, factories, auth_headers, db_session
):
    """The hold rides the grant config, so writing it is a grant write — and a
    grant write that reset `tcp_ports` or `excluded_cidrs` to the registry
    defaults would silently widen or narrow what the agent may scan."""
    agent = _discovery_agent(
        factories, config={"tcp_ports": [22, 443], "excluded_cidrs": ["10.30.40.128/25"]}
    )

    await client.post(f"/api/v1/agents/{agent.id}/discovery/pause", headers=auth_headers)

    from app.services import agent_registry

    grant = agent_registry.structured_grants_dict(db_session, agent.id)["local_discovery"]
    assert grant["enabled"] is True
    assert grant["config"]["auto_discovery_paused"] is True
    assert grant["config"]["tcp_ports"] == [22, 443]
    assert grant["config"]["excluded_cidrs"] == ["10.30.40.128/25"]


@pytest.mark.asyncio
async def test_pausing_an_agents_discovery_requires_admin(client, factories, viewer_headers):
    agent = _discovery_agent(factories)
    resp = await client.post(f"/api/v1/agents/{agent.id}/discovery/pause", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_pausing_discovery_for_an_unknown_agent_is_a_404(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999/discovery/pause", headers=auth_headers)
    assert resp.status_code == 404
