"""Discovery-dispatch cancellation (Slice 4, D-14 / D-16): the three triggers on
this router -- turning the local_discovery grant off, revoking the agent, and a
grant-scope edit that moves the dispatch's snapshot -- that must retire an in-
flight dispatch, and the security property that a late finding is refused once
the dispatch is closed even if the agent was never told.

Split out of the former tests/api/test_agents_api.py.
"""

from unittest.mock import AsyncMock

import pytest

from tests.api.agent_fakes import (
    _build_discovery_frames,
    _discovery_agent,
    _discovery_cancels,
    _live_dispatch,
)

# ---------------------------------------------------------------------------
# Discovery-dispatch cancellation (Slice 4, D-14 / D-16)
# ---------------------------------------------------------------------------
#
# Three of D-14's five triggers live on this router: turning the
# `local_discovery` grant off, revoking the agent, and editing the grant's scope
# so a live dispatch's snapshot no longer matches. All three close the job in the
# database *before* trying to tell the agent, because `dispatch_frame`'s grant
# gate drops the agent's own terminal summary the moment the grant is off — a
# dispatch nobody closed would then stay open until Task 23's pass expired it.


@pytest.fixture
def discovery_frames(monkeypatch):
    return _build_discovery_frames(monkeypatch)


async def _assert_a_late_finding_is_refused(db_session, agent, job, *, reason=None):
    """The security property D-14 turns on: rejection follows from the closed
    row, never from the agent having received the `discovery.cancel`.

    `reason` names which gate is expected to answer. Revocation trips
    `agent_inactive` before the lease is even looked at — two independent
    refusals rather than one, which is why the caller also asserts the job row
    itself went terminal.
    """
    import secrets

    from app.core.time import utcnow
    from app.db.models import ScanResult
    from app.services import agent_discovery

    with pytest.raises(agent_discovery.InvalidDiscoveryFinding) as excinfo:
        await agent_discovery.ingest_discovery_finding(
            db_session,
            agent,
            {
                "dispatch_id": job.dispatch_id,
                "scan_job_id": job.id,
                "finding_id": secrets.token_hex(16),
                "kind": "host",
                "observed_at": utcnow().isoformat(),
                "ip_address": "10.30.40.77",
            },
        )
    assert (reason or agent_discovery.REASON_DISPATCH_CLOSED) in str(excinfo.value)
    assert db_session.query(ScanResult).filter(ScanResult.scan_job_id == job.id).count() == 0


@pytest.mark.asyncio
async def test_disabling_local_discovery_cancels_in_flight_dispatches(
    client, factories, auth_headers, db_session, discovery_frames
):
    from app.services import agent_discovery

    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"local_discovery": False}},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.dispatch_status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_CAPABILITY_DISABLED
    assert _discovery_cancels(discovery_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_CAPABILITY_DISABLED}
    ]
    await _assert_a_late_finding_is_refused(db_session, agent, job)


@pytest.mark.asyncio
async def test_disabling_a_different_capability_cancels_no_discovery_dispatch(
    client, factories, auth_headers, db_session, discovery_frames
):
    agent = _discovery_agent(factories)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    job = _live_dispatch(db_session, agent)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": False}},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "running"
    assert _discovery_cancels(discovery_frames) == []


@pytest.mark.asyncio
async def test_revoking_the_agent_cancels_in_flight_dispatches(
    client, factories, auth_headers, db_session, discovery_frames
):
    from app.services import agent_discovery

    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)

    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke", json={"reason": "decommissioned"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_AGENT_UNAVAILABLE
    assert _discovery_cancels(discovery_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_AGENT_UNAVAILABLE}
    ]
    await _assert_a_late_finding_is_refused(
        db_session, agent, job, reason=agent_discovery.REASON_AGENT_INACTIVE
    )


@pytest.mark.asyncio
async def test_a_grant_scope_edit_cancels_a_dispatch_whose_version_moved(
    client, factories, auth_headers, db_session, discovery_frames
):
    """D-16's second trigger. `EffectiveScope.version` is derived from the grant
    as well as from what the agent reported, so excluding a /25 moves it and the
    ingest path would refuse every subsequent finding under a version nobody
    authorized."""
    from app.services import agent_discovery

    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={
            "capabilities": {
                "local_discovery": {
                    "enabled": True,
                    "config": {"excluded_cidrs": ["10.30.40.128/25"]},
                }
            }
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_reason == agent_discovery.ERROR_SCOPE_CHANGED
    assert _discovery_cancels(discovery_frames) == [
        {"dispatch_id": job.dispatch_id, "reason": agent_discovery.ERROR_SCOPE_CHANGED}
    ]


@pytest.mark.asyncio
async def test_a_grant_edit_that_leaves_the_scope_alone_cancels_nothing(
    client, factories, auth_headers, db_session, discovery_frames
):
    """The steady state: a capability write that does not touch scope must not
    retire work. Without the version comparison every grant edit would be a
    fleet-wide cancellation."""
    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={
            "capabilities": {
                "local_discovery": {"enabled": True, "config": {"max_concurrent_hosts": 8}}
            }
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(job)
    assert job.status == "running"
    assert _discovery_cancels(discovery_frames) == []


def _undeliverable_cancels(monkeypatch):
    """A publisher that blows up on `discovery.cancel` and only on it.

    `put_capabilities` and `post_revoke` each publish a second, unrelated control
    frame (`capabilities.set`, `disconnect`); failing those too would prove the
    wrong thing, since `publish_agent_control_frame` never raises in production
    and those call sites have their own pinned behaviour above.
    """
    from app.schemas.agent_frame import TYPE_DISCOVERY_CANCEL
    from app.services import agent_registry

    async def _spy(agent_id: int, frame: dict) -> bool:
        if frame["type"] == TYPE_DISCOVERY_CANCEL:
            raise RuntimeError("redis is gone")
        return True

    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", AsyncMock(side_effect=_spy))


@pytest.mark.asyncio
async def test_capability_disable_succeeds_when_the_cancel_cannot_be_delivered(
    client, factories, auth_headers, db_session, monkeypatch
):
    """An agent that vanished must not turn an administrator's grant edit into a
    500, and must not leave its lease open either."""
    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)
    _undeliverable_cancels(monkeypatch)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"local_discovery": False}},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    db_session.refresh(job)
    assert job.status == "cancelled"
    # The undelivered cancel changes nothing about what the agent is allowed to
    # report. D-14's security property is that refusal follows from the closed
    # row, so the one case where the agent provably never heard the cancel is
    # the case that has to be asserted.
    await _assert_a_late_finding_is_refused(db_session, agent, job)


@pytest.mark.asyncio
async def test_revoke_succeeds_when_the_cancel_cannot_be_delivered(
    client, factories, auth_headers, db_session, monkeypatch
):
    from app.services import agent_discovery

    agent = _discovery_agent(factories)
    job = _live_dispatch(db_session, agent)
    _undeliverable_cancels(monkeypatch)

    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke", json={"reason": "gone"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    db_session.refresh(job)
    assert job.status == "cancelled"
    await _assert_a_late_finding_is_refused(
        db_session, agent, job, reason=agent_discovery.REASON_AGENT_INACTIVE
    )
