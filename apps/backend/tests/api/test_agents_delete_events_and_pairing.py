"""Agent deletion (blocked by an assigned monitor, succeeding once it is
reassigned), the events-history endpoint, and pairing-code lookup.

Split out of the former tests/api/test_agents_api.py.
"""

import pytest


@pytest.mark.asyncio
async def test_delete_requires_admin(client, factories, auth_headers):
    agent = factories.agent()
    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_requires_admin_not_viewer(client, factories, viewer_headers):
    agent = factories.agent()
    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_deleting_an_agent_with_assigned_monitors_returns_409(
    client, factories, auth_headers
):
    """`monitor_items.probe_agent_id` is RESTRICT (Task 6), so without this
    pre-check the delete surfaces as an unhandled IntegrityError and a 500.
    §8: agent deletion is blocked while assignments remain — unassigning is a
    decision the operator makes explicitly, never a side effect of a delete."""
    from app.db.models import Agent

    agent = factories.agent(status="active")
    factories.monitor_item(probe_agent_id=agent.id)

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]
    assert factories.session.get(Agent, agent.id) is not None


@pytest.mark.asyncio
async def test_delete_succeeds_after_the_monitors_are_reassigned(client, factories, auth_headers):
    agent = factories.agent(status="active")
    other = factories.agent(status="active")
    monitor = factories.monitor_item(probe_agent_id=agent.id)

    blocked = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert blocked.status_code == 409

    monitor.probe_agent_id = other.id
    factories.session.flush()

    resp = await client.delete(f"/api/v1/agents/{agent.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_events_endpoint_lists_history(client, factories, viewer_headers):
    agent = factories.agent()
    factories.agent_event(agent, event_type="enrolled")
    factories.agent_event(agent, event_type="approved")

    resp = await client.get(f"/api/v1/agents/{agent.id}/events", headers=viewer_headers)
    assert resp.status_code == 200
    types = [e["event_type"] for e in resp.json()]
    assert types == ["approved", "enrolled"]  # newest first


@pytest.mark.asyncio
async def test_events_endpoint_returns_404_for_unknown_agent(client, viewer_headers):
    resp = await client.get("/api/v1/agents/999999999/events", headers=viewer_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pairing_lookup_resolves_pending_agent(client, factories, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    agent = factories.agent(status="pending", hostname="box1")
    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=agent.id)
    )

    resp = await client.post(
        "/api/v1/agents/pairing/lookup",
        json={"code": "ABCD-EFGH-JKMN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent.id


@pytest.mark.asyncio
async def test_pairing_lookup_records_miss_on_unknown_code(client, auth_headers, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.agent_enrollment.consume_pairing_code", AsyncMock(return_value=None)
    )
    miss = AsyncMock()
    monkeypatch.setattr("app.services.agent_enrollment.record_pairing_miss", miss)

    resp = await client.post(
        "/api/v1/agents/pairing/lookup",
        json={"code": "ZZZZ-ZZZZ-ZZZZ"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    miss.assert_called_once()
