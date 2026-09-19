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


@pytest.mark.asyncio
async def test_a_url_with_a_path_is_rejected(client, auth_headers):
    """`https://example.com/cb` validates today and then cannot work: every
    fetch is built as `{url}/install-agent.sh`, so it becomes
    `https://example.com/cb/install-agent.sh` and 404s on the target machine,
    after the operator has already saved it and pasted the command."""
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "Subpath", "url": "https://example.com/cb"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Subpath" in detail, detail
    assert "path" in detail.lower(), detail


@pytest.mark.asyncio
async def test_a_bare_host_with_a_trailing_slash_is_still_accepted(client, auth_headers):
    """The slash is stripped before the path check, so the shape a browser's
    address bar hands the operator keeps working."""
    resp = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "Public", "url": "https://example.com/"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["agent_endpoints"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_omitting_endpoints_leaves_the_stored_ones_alone(client, auth_headers):
    """`update_settings` iterates `model_dump(exclude_unset=True)`, so an
    omitted `agent_endpoints` never reaches the loop and the stored list
    survives. That is load-bearing — the settings screen PUTs whatever section
    the operator touched — and `agent_endpoints` now has a bespoke branch in
    that loop, so it is worth pinning rather than inferring."""
    created = await client.put(
        "/api/v1/settings",
        json={"agent_endpoints": [{"label": "Public", "url": "https://cb.example.com"}]},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    stored = created.json()["agent_endpoints"]

    unrelated = await client.put("/api/v1/settings", json={"theme": "dark"}, headers=auth_headers)

    assert unrelated.status_code == 200, unrelated.text
    assert unrelated.json()["agent_endpoints"] == stored

    reread = await client.get("/api/v1/settings", headers=auth_headers)
    assert reread.status_code == 200, reread.text
    assert reread.json()["agent_endpoints"] == stored
