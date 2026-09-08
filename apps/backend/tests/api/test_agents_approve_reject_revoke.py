"""The pending-agent lifecycle transitions -- approve (including the registry-
default capability preset and per-capability overrides), reject, and revoke --
plus the capabilities PUT route's grant updates and control-frame push (Task 9,
Task 14).

Split out of the former tests/api/test_agents_api.py.
"""

import pytest

from tests.api.agent_fakes import LOCAL_DISCOVERY_DEFAULT_CONFIG, REMOTE_PROBE_DEFAULT_CONFIG


@pytest.mark.asyncio
async def test_approve_requires_admin(client, factories, viewer_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_with_omitted_capabilities_grants_the_full_normal_preset(
    client, factories, auth_headers
):
    """Task 14 / D-10: an approve body with no `capabilities` grants all three
    capabilities enabled, each carrying the server registry's default config."""
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["capabilities"] == {
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        },
        "remote_probe": {"enabled": True, "config": REMOTE_PROBE_DEFAULT_CONFIG},
        "local_discovery": {"enabled": True, "config": LOCAL_DISCOVERY_DEFAULT_CONFIG},
    }


@pytest.mark.asyncio
async def test_approve_rejects_invalid_host_telemetry_config_with_422(
    client, factories, auth_headers
):
    """Task 14: `ApproveRequest` validates capability config the same way
    `CapabilitiesUpdateRequest` does, so a bad cadence is a 422 — not the 500
    the un-validated approve body used to produce via a bare `ValueError`."""
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"host_telemetry": {"enabled": True, "config": {"interval_s": 5}}}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approve_rejects_unknown_capability_name(client, factories, auth_headers):
    """Task 14: the registry is the closed set of capability names; approving
    with anything else is a 422, not a grant row for an arbitrary string."""
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"not_a_capability": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_capabilities_update_rejects_malformed_remote_probe_scope_with_422(
    client, factories, auth_headers
):
    """Slice 3 Task 5: a scope field of the wrong *type* is administrator error,
    so it has to surface as a 422 like every other bad config. Only `ValueError`
    reaches `_validate_capability_map`'s handler — a `TypeError` raised while
    iterating a non-list would escape as a 500 from an admin route instead."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True, config={})

    for config in ({"additional_cidrs": 5}, {"excluded_cidrs": None}, {"scope_mode": []}):
        resp = await client.put(
            f"/api/v1/agents/{agent.id}/capabilities",
            json={"capabilities": {"remote_probe": {"enabled": True, "config": config}}},
            headers=auth_headers,
        )
        assert resp.status_code == 422, config


@pytest.mark.asyncio
async def test_capability_defaults_endpoint_matches_what_an_omitted_approve_grants(
    client, factories, auth_headers
):
    """Structural lock (Task 14): the frontend's approval preset is fetched from
    this endpoint, so it can never drift from what the server actually grants."""
    defaults = await client.get("/api/v1/agents/capability-defaults", headers=auth_headers)
    assert defaults.status_code == 200

    agent = factories.agent(status="pending")
    approve = await client.post(f"/api/v1/agents/{agent.id}/approve", json={}, headers=auth_headers)
    assert approve.status_code == 200
    assert approve.json()["capabilities"] == defaults.json()


@pytest.mark.asyncio
async def test_capability_defaults_is_readable_by_a_viewer(client, viewer_headers):
    """Declared above "/{agent_id}" so "capability-defaults" is never parsed as
    an agent id (which would 422 on the int path param for a viewer)."""
    resp = await client.get("/api/v1/agents/capability-defaults", headers=viewer_headers)
    assert resp.status_code == 200
    assert set(resp.json()) == {"host_telemetry", "remote_probe", "local_discovery"}


@pytest.mark.asyncio
async def test_approve_honors_capability_overrides(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_approve_accepts_hardware_id_and_host_link_action(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    hardware = factories.hardware()
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"hardware_id": hardware.id, "host_link_action": "accept"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == hardware.id


@pytest.mark.asyncio
async def test_approve_records_host_link_action_on_approved_event(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    hardware = factories.hardware()
    await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"hardware_id": hardware.id, "host_link_action": "create"},
        headers=auth_headers,
    )

    resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    approved = next(e for e in resp.json() if e["event_type"] == "approved")
    assert approved["detail"] == {"hardware_id": hardware.id, "host_link_action": "create"}


@pytest.mark.asyncio
async def test_approve_rejects_unknown_host_link_action(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/approve",
        json={"host_link_action": "bogus"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approve_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999999/approve", json={}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_sets_rejected_status(client, factories, auth_headers):
    agent = factories.agent(status="pending")
    resp = await client.post(f"/api/v1/agents/{agent.id}/reject", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post("/api/v1/agents/999999999/reject", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_records_reason(client, factories, auth_headers):
    agent = factories.agent(status="active")
    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        json={"reason": "lost device"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.post(
        "/api/v1/agents/999999999/revoke", json={"reason": "n/a"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_capabilities_put_updates_grants(client, factories, auth_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_capabilities_put_publishes_control_frame_for_immediate_delivery(
    client, factories, auth_headers, monkeypatch
):
    """Task 9: put_capabilities also pushes the change through
    agent_registry.publish_agent_control_frame — the cross-worker delivery
    primitive Task 8 added — on top of the DB write, so a connected agent
    picks it up immediately regardless of which worker holds its /link
    socket. See test_ws_agents_link.py's
    test_link_delivers_capabilities_set_published_by_another_worker for the
    matching end-to-end proof that a published frame actually reaches the
    socket; this test only pins the call site's payload."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    publish = AsyncMock(return_value=True)
    monkeypatch.setattr(agent_registry, "publish_agent_control_frame", publish)

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    publish.assert_called_once()
    published_agent_id, frame = publish.call_args[0]
    assert published_agent_id == agent.id
    assert frame["type"] == "capabilities.set"
    # The full, authoritative grants set — not just the one capability this
    # request changed — same as the connect-time capabilities.set send.
    assert frame["payload"] == {
        "remote_probe": {"enabled": True, "config": REMOTE_PROBE_DEFAULT_CONFIG},
        "host_telemetry": {
            "enabled": True,
            "config": {
                "interval_s": 30,
                "include_filesystems": True,
                "include_disks": True,
                "include_network": True,
                "include_temperatures": True,
                "include_virtual": False,
                "include_docker": False,
            },
        },
    }


@pytest.mark.asyncio
async def test_capabilities_put_succeeds_even_when_control_frame_publish_fails(
    client, factories, auth_headers, monkeypatch
):
    """publish_agent_control_frame never raises (see its docstring), but this
    pins the caller-side contract too: a degraded/unavailable Redis must not
    fail the request or leave the DB write unapplied — the agent still picks
    the change up on its own next reconnect/poll."""
    from unittest.mock import AsyncMock

    from app.services import agent_registry

    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=False)

    monkeypatch.setattr(
        agent_registry, "publish_agent_control_frame", AsyncMock(return_value=False)
    )

    resp = await client.put(
        f"/api/v1/agents/{agent.id}/capabilities",
        json={"capabilities": {"remote_probe": True}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["remote_probe"]["enabled"] is True


@pytest.mark.asyncio
async def test_detail_says_who_revoked_the_agent(client, factories, auth_headers):
    """An operator revoke and a `cb-agent uninstall` both land on
    `status=revoked`, and until now the API said nothing that could tell them
    apart — so the UI told an operator to go and clean up a host that had
    already cleaned itself up.

    `revoked_by_user_id` is the authoritative discriminator (the agent-initiated
    path passes `actor_user_id=None` precisely so the audit trail can tell), but
    it is a user id, and the answer the UI needs is which *kind* of actor.
    """
    agent = factories.agent(status="active")

    resp = await client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        json={"reason": "lost device"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["revoked_by"] == "operator"
    assert body["revoke_reason"] == "lost device"
    assert body["revoked_at"] is not None


@pytest.mark.asyncio
async def test_detail_reports_an_agent_initiated_revoke_as_the_agents_own(
    client, factories, auth_headers
):
    """The `cb-agent uninstall` half of the same field, through the real
    handler rather than a hand-written row: an uninstall frame revokes with no
    actor, and the detail response has to carry that distinction."""
    from app.schemas.agent_frame import AgentFrame
    from app.services import agent_link

    agent = factories.agent(status="active")
    await agent_link.dispatch_frame(
        factories.session,
        agent,
        AgentFrame(type="uninstall", ts="2026-09-08T12:00:00Z", payload={}),
    )

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "revoked"
    assert body["revoked_by"] == "agent"
    assert body["revoke_reason"] == "uninstalled by agent"


@pytest.mark.asyncio
async def test_detail_leaves_the_revoke_fields_empty_for_a_live_agent(
    client, factories, auth_headers
):
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=auth_headers)

    body = resp.json()
    assert body["revoked_by"] is None
    assert body["revoked_at"] is None
    assert body["revoke_reason"] is None
