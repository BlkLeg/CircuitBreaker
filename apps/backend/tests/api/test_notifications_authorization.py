"""The notifications surface is admin governance.

`data/navigation.js` has always declared it `require: 'admin'`, while the API accepted
viewer reads and editor writes. Sink `provider_config` carries webhook URLs, which INC-06
established are bearer credentials for posting into a channel. Raising the API to admin is
a deliberate tightening: editors who manage sinks today lose that access.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_viewer_cannot_list_sinks(client, viewer_headers):
    resp = await client.get("/api/v1/notifications/sinks", headers=viewer_headers)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_list_routes(client, viewer_headers):
    resp = await client.get("/api/v1/notifications/routes", headers=viewer_headers)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_editor_cannot_create_a_sink(client, editor_headers):
    resp = await client.post(
        "/api/v1/notifications/sinks",
        json={
            "name": "ops",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
            "enabled": True,
        },
        headers=editor_headers,
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_editor_cannot_list_sinks(client, editor_headers):
    resp = await client.get("/api/v1/notifications/sinks", headers=editor_headers)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_sinks(client, auth_headers):
    resp = await client.get("/api/v1/notifications/sinks", headers=auth_headers)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_can_create_and_delete_a_sink(client, auth_headers):
    created = await client.post(
        "/api/v1/notifications/sinks",
        json={
            "name": "ops",
            "provider_type": "slack",
            "provider_config": {"webhook_url": "https://hooks.slack.com/services/T/B/X"},
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    sink_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/notifications/sinks/{sink_id}", headers=auth_headers)
    assert deleted.status_code == 200
