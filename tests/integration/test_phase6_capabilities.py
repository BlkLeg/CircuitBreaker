"""Phase 6 — Capabilities endpoint tests.

Verifies:
  - GET /api/v1/capabilities returns the expected JSON shape
  - Safe fallback when no AppSettings row exists in the DB
  - Each subsystem key reflects the correct live setting value

Every test takes ``auth_headers``: since cd1724ff withdrew the open first-run
admin sentinel, /capabilities and /settings answer 401 until an admin exists and
authenticates. The fixture bootstraps the instance and logs in, which is the only
state in which these endpoints are reachable at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_caps(client, auth_headers):
    r = client.get("/api/v1/capabilities", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Shape tests — the response carries every documented key
# ---------------------------------------------------------------------------

class TestCapabilitiesShape:
    def test_returns_all_top_level_keys(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert set(data.keys()) >= {"nats", "realtime", "cve", "listener", "docker", "auth"}

    def test_nats_key_has_available(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "available" in data["nats"]

    def test_realtime_key_has_available_and_transport(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "available" in data["realtime"]
        assert "transport" in data["realtime"]

    def test_cve_key_has_available_and_last_sync(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "available" in data["cve"]
        assert "last_sync" in data["cve"]

    def test_listener_key_has_available_mdns_ssdp(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "available" in data["listener"]
        assert "mdns" in data["listener"]
        assert "ssdp" in data["listener"]

    def test_docker_key_has_available_and_discovery_enabled(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "available" in data["docker"]
        assert "discovery_enabled" in data["docker"]

    def test_auth_key_has_enabled(self, client, auth_headers):
        data = _get_caps(client, auth_headers)
        assert "enabled" in data["auth"]

    @pytest.mark.asyncio
    async def test_fallback_when_no_settings_row(self, db, monkeypatch):
        """No AppSettings row → the handler must return safe defaults.

        Called in-process rather than over HTTP, because no HTTP request can put
        the handler in front of a missing row any more. AppSettings is where
        ``auth_enabled`` and ``jwt_secret`` live, and auth resolution runs
        ``get_or_create_settings()`` — which re-inserts the row — before the
        handler ever queries it. An authenticated caller therefore always finds a
        row (and deleting it mid-session invalidates the very secret that signed
        the session), while since cd1724ff an unauthenticated caller is turned
        away at 401 and never reaches the handler at all. That leaves this
        defensive branch reachable only by calling the coroutine directly.
        """
        from app.api import capabilities as capabilities_api
        from app.db.models import AppSettings

        assert db.query(AppSettings).count() == 0, (
            "the db fixture truncates every table, so this test should start with no "
            "AppSettings row — something seeded one"
        )

        # Stub the Redis singleton rather than awaiting it: get_redis() caches a
        # client on a module global bound to whichever loop first touched it, and
        # this test's loop dies with the test. Redis availability is not what the
        # fallback branch is being checked for.
        monkeypatch.setattr(capabilities_api, "get_redis", AsyncMock(return_value=None))

        data = await capabilities_api.get_capabilities(db=db)
        assert data["auth"]["enabled"] is True
        assert data["realtime"]["available"] is False
        assert data["cve"]["available"] is False
        assert data["listener"]["available"] is False


# ---------------------------------------------------------------------------
# Live setting value tests (create AppSettings row first)
# ---------------------------------------------------------------------------

def _create_settings(client, auth_headers, **kwargs):
    """Seed an AppSettings row via the settings PATCH endpoint."""
    r = client.put("/api/v1/settings", json=kwargs, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestCapabilitiesReflectsSettings:
    def test_auth_always_enabled(self, client, auth_headers):
        _create_settings(client, auth_headers)
        data = _get_caps(client, auth_headers)
        assert data["auth"]["enabled"] is True

    def test_cve_enabled_reflects_setting(self, client, auth_headers):
        _create_settings(client, auth_headers, cve_sync_enabled=True)
        data = _get_caps(client, auth_headers)
        assert data["cve"]["available"] is True

    def test_realtime_transport_reflects_setting(self, client, auth_headers):
        _create_settings(client, auth_headers, realtime_transport="sse")
        data = _get_caps(client, auth_headers)
        assert data["realtime"]["transport"] == "sse"

    def test_listener_mdns_ssdp_reflects_setting(self, client, auth_headers):
        _create_settings(client, auth_headers, listener_enabled=True, mdns_enabled=True, ssdp_enabled=False)
        data = _get_caps(client, auth_headers)
        assert data["listener"]["available"] is True
        assert data["listener"]["mdns"] is True
        assert data["listener"]["ssdp"] is False

    def test_docker_discovery_enabled_reflects_setting(self, client, auth_headers):
        _create_settings(client, auth_headers, docker_discovery_enabled=True)
        data = _get_caps(client, auth_headers)
        assert data["docker"]["discovery_enabled"] is True

    def test_nats_available_false_when_not_connected(self, client, auth_headers):
        """NATS client is not connected in test env (mocked away)."""
        data = _get_caps(client, auth_headers)
        assert data["nats"]["available"] is False

    def test_nats_available_true_when_connected(self, client, auth_headers):
        """Mock is_connected as a property to simulate NATS connected state."""
        _create_settings(client, auth_headers)  # ensure s is not None so the live branch is hit
        from app.core.nats_client import NATSClient
        with patch.object(NATSClient, "is_connected", new=property(lambda self: True)):
            data = _get_caps(client, auth_headers)
        assert data["nats"]["available"] is True

    def test_docker_socket_available_false_when_missing(self, client, auth_headers):
        """Docker socket at a non-existent path reports available=False."""
        _create_settings(client, auth_headers, docker_socket_path="/tmp/no-such-docker.sock")
        data = _get_caps(client, auth_headers)
        assert data["docker"]["available"] is False
