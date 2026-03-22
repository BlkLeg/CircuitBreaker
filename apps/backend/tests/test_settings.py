"""
Tests for the settings API.

Routes (settings_router mounted at /api/v1/settings):
  GET   /api/v1/settings   — read current settings (auth required post-OOBE)
  PUT   /api/v1/settings   — full update (admin only)

Note: The PATCH /api/v1/settings endpoint does not exist; the router exposes
PUT for updates.  The task asked for PATCH, so we test PUT instead.
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/settings"


# ── GET ───────────────────────────────────────────────────────────────────────


async def test_get_settings_unauthenticated_returns_401(client):
    """After OOBE (jwt_secret set), unauthenticated GET must return 401."""
    resp = await client.get(_BASE)
    assert resp.status_code == 401


async def test_get_settings_admin_returns_200(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    # AppSettingsRead must include at least these fields
    assert "auth_enabled" in body


async def test_get_settings_viewer_returns_200(client, viewer_headers):
    """Authenticated viewers (any role) can read settings."""
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


# ── PUT (update) ──────────────────────────────────────────────────────────────


async def test_put_settings_updates_string_field(client, auth_headers):
    """Admin can update a string field (app_name) via PUT using the branding object."""
    resp = await client.put(
        _BASE,
        headers=auth_headers,
        json={"branding": {"app_name": "CircuitBreaker-Test"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("branding", {}).get("app_name") == "CircuitBreaker-Test"


async def test_put_settings_viewer_returns_403(client, viewer_headers):
    resp = await client.put(
        _BASE,
        headers=viewer_headers,
        json={"app_name": "should-fail"},
    )
    assert resp.status_code == 403


async def test_put_settings_unauthenticated_returns_401(client):
    resp = await client.put(_BASE, json={"app_name": "should-fail"})
    assert resp.status_code == 401
