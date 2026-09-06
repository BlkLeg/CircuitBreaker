"""Endpoints are configured through the normal settings route."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_endpoints_round_trip_through_settings(client, auth_headers):
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "Public", "url": "https://cb.example.com"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()["agent_endpoints"]
    assert stored[0]["label"] == "Public"
    assert stored[0]["id"], "the server mints the id"


@pytest.mark.asyncio
async def test_a_bad_url_is_rejected_with_a_readable_message(client, auth_headers):
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "bad", "url": "file:///etc/passwd"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "scheme" in resp.json()["detail"].lower()
