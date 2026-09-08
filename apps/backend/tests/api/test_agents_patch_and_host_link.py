"""PATCH /agents/{id}: renaming an agent, and editing its hardware (host) link
after approval -- relinking, unlinking, and the host_link_changed audit trail
(Task 19).

Split out of the former tests/api/test_agents_api.py.
"""

import pytest


@pytest.mark.asyncio
async def test_patch_requires_editor_not_viewer(client, factories, viewer_headers):
    agent = factories.agent()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=viewer_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_renames_agent(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}", json={"name": "renamed"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


# ── Task 19: host-link editing after approval ──────────────────────────────


@pytest.mark.asyncio
async def test_patch_requires_editor_not_viewer_for_hardware_link(
    client, factories, viewer_headers
):
    agent = factories.agent(status="active")
    hardware = factories.hardware()
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_relinks_approved_agent_to_different_hardware(client, factories, auth_headers):
    original = factories.hardware()
    replacement = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": replacement.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == replacement.id

    detail_resp = await client.get(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert detail_resp.json()["hardware_id"] == replacement.id


@pytest.mark.asyncio
async def test_patch_relink_records_host_link_changed_event(client, factories, auth_headers):
    original = factories.hardware()
    replacement = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": replacement.id},
        headers=auth_headers,
    )

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {
        "previous_hardware_id": original.id,
        "hardware_id": replacement.id,
    }


@pytest.mark.asyncio
async def test_patch_unlinks_approved_agent_hardware(client, factories, auth_headers):
    original = factories.hardware()
    agent = factories.agent(status="active", hardware_id=original.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] is None

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {"previous_hardware_id": original.id, "hardware_id": None}


@pytest.mark.asyncio
async def test_patch_links_previously_unlinked_agent(client, factories, auth_headers):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=None)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["hardware_id"] == hardware.id

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    changed = next(e for e in events_resp.json() if e["event_type"] == "host_link_changed")
    assert changed["detail"] == {"previous_hardware_id": None, "hardware_id": hardware.id}


@pytest.mark.asyncio
async def test_patch_hardware_id_unchanged_records_no_event(client, factories, auth_headers):
    hardware = factories.hardware()
    agent = factories.agent(status="active", hardware_id=hardware.id)

    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": hardware.id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    events_resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=auth_headers)
    types = [e["event_type"] for e in events_resp.json()]
    assert "host_link_changed" not in types


@pytest.mark.asyncio
async def test_patch_rejects_unknown_hardware_id(client, factories, auth_headers):
    agent = factories.agent(status="active")
    resp = await client.patch(
        f"/api/v1/agents/{agent.id}",
        json={"hardware_id": 999999999},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_returns_404_for_unknown_agent(client, auth_headers):
    resp = await client.patch("/api/v1/agents/999999999", json={"name": "x"}, headers=auth_headers)
    assert resp.status_code == 404
