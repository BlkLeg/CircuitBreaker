"""Agent listing and the agent-detail endpoint: fleet summaries, the pending-only
filter, capability rendering, hardware-proposal matching, and the duplicate-
machine-id warning shared with pairing lookup.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest


@pytest.mark.asyncio
async def test_list_agents_requires_viewer_auth(client):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_agents_returns_summaries(client, factories, viewer_headers):
    factories.agent(status="active", hostname="box1")
    factories.agent(status="pending", hostname="box2")

    resp = await client.get("/api/v1/agents", headers=viewer_headers)
    assert resp.status_code == 200
    hostnames = {a["hostname"] for a in resp.json()}
    assert hostnames == {"box1", "box2"}


@pytest.mark.asyncio
async def test_pending_endpoint_only_returns_pending(client, factories, viewer_headers):
    factories.agent(status="active", hostname="active-one")
    pending = factories.agent(status="pending", hostname="pending-one")

    resp = await client.get("/api/v1/agents/pending", headers=viewer_headers)
    assert resp.status_code == 200
    ids = [a["id"] for a in resp.json()]
    assert ids == [pending.id]


@pytest.mark.asyncio
async def test_get_agent_detail_includes_capabilities(client, factories, viewer_headers):
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["capabilities"] == {
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
        }
    }


@pytest.mark.asyncio
async def test_get_agent_detail_names_the_endpoint_the_agent_dialed(
    client, factories, viewer_headers
):
    """The stored address has to leave the database to be worth storing.

    `ws_agents` writes `enrolled_via_endpoint` from the agent's hello, but the
    agent-detail view is the only place an operator can compare the address an
    agent actually used against the one they meant to hand it.
    """
    agent = factories.agent(status="active", enrolled_via_endpoint="https://cb.example.com")

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["enrolled_via_endpoint"] == "https://cb.example.com"


@pytest.mark.asyncio
async def test_get_agent_detail_reports_no_endpoint_for_an_older_agent(
    client, factories, viewer_headers
):
    """An agent that enrolled before this existed reports null, not a guess."""
    agent = factories.agent(status="active")

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["enrolled_via_endpoint"] is None


@pytest.mark.asyncio
async def test_get_agent_detail_includes_hardware_proposal(client, factories, viewer_headers):
    from app.db.models import Hardware

    hw = Hardware(name="matched-box", machine_id_hash="mid-hash-1")
    factories.session.add(hw)
    factories.session.flush()

    agent = factories.agent(status="pending", machine_id_hash="mid-hash-1")

    resp = await client.get(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposed_hardware_id"] == hw.id
    assert body["proposed_hardware_name"] == "matched-box"
    assert body["duplicate_machine_id"] is False


@pytest.mark.asyncio
async def test_agent_detail_and_pairing_lookup_report_identical_duplicate_warning(
    client, factories, auth_headers
):
    """Two agents sharing a machine_id_hash (e.g. a cloned VM image) must be
    flagged identically by both the agent-detail endpoint and the
    pairing-lookup endpoint — an operator reviewing from either screen sees
    the same warning."""
    from unittest.mock import AsyncMock

    factories.agent(status="active", machine_id_hash="dup-hash")
    pending = factories.agent(status="pending", machine_id_hash="dup-hash", hostname="pending-box")

    detail_resp = await client.get(f"/api/v1/agents/{pending.id}", headers=auth_headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["duplicate_machine_id"] is True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.agent_enrollment.consume_pairing_code",
            AsyncMock(return_value=pending.id),
        )
        lookup_resp = await client.post(
            "/api/v1/agents/pairing/lookup",
            json={"code": "ABCD-EFGH-JKMN"},
            headers=auth_headers,
        )
    assert lookup_resp.status_code == 200
    assert lookup_resp.json()["duplicate_machine_id"] is True
    assert lookup_resp.json()["duplicate_machine_id"] == detail_resp.json()["duplicate_machine_id"]
