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
    """Admin can update a string field (default_environment) via PUT."""
    resp = await client.put(
        _BASE,
        headers=auth_headers,
        json={"default_environment": "test-env"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("default_environment") == "test-env"


async def test_put_settings_viewer_returns_403(client, viewer_headers):
    resp = await client.put(
        _BASE,
        headers=viewer_headers,
        json={"default_environment": "should-fail"},
    )
    assert resp.status_code == 403


async def test_put_settings_unauthenticated_returns_401(client):
    resp = await client.put(_BASE, json={"default_environment": "should-fail"})
    assert resp.status_code == 401


# ── Multiple fields at once ──────────────────────────────────────────────────


async def test_put_settings_updates_multiple_fields(client, auth_headers):
    """Admin can update several fields in one PUT call."""
    resp = await client.put(
        _BASE,
        headers=auth_headers,
        json={
            "default_environment": "staging",
            "show_experimental_features": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("default_environment") == "staging"
    assert body.get("show_experimental_features") is True


# ── Timezone ─────────────────────────────────────────────────────────────────


async def test_put_settings_valid_timezone(client, auth_headers):
    """Admin can set a valid IANA timezone."""
    resp = await client.put(
        _BASE,
        headers=auth_headers,
        json={"timezone": "America/New_York"},
    )
    assert resp.status_code == 200
    assert resp.json().get("timezone") == "America/New_York"


async def test_put_settings_invalid_timezone_returns_422(client, auth_headers):
    """An invalid timezone string is rejected with 422."""
    resp = await client.put(
        _BASE,
        headers=auth_headers,
        json={"timezone": "Fake/Nowhere"},
    )
    assert resp.status_code == 422


# ── Reset to defaults ───────────────────────────────────────────────────────


async def test_reset_settings_to_defaults(client, auth_headers):
    """POST /api/v1/settings/reset restores factory defaults."""
    # Change something first
    await client.put(
        _BASE,
        headers=auth_headers,
        json={"default_environment": "custom-env"},
    )
    resp = await client.post(f"{_BASE}/reset", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    # After reset, default_environment should be back to default (empty or None)
    assert body.get("default_environment") in (None, "", "production")


async def test_reset_settings_viewer_returns_403(client, viewer_headers):
    resp = await client.post(f"{_BASE}/reset", headers=viewer_headers)
    assert resp.status_code == 403
