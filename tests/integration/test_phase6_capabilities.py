"""Phase 6 — Capabilities endpoint tests.

Verifies:
  - GET /api/v1/capabilities returns the expected JSON shape
  - Safe fallback when no AppSettings row exists in the DB
  - Each subsystem key reflects the correct live setting value
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_caps(client):
    r = client.get("/api/v1/capabilities")
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Shape tests (no AppSettings row → all-false fallback)
# ---------------------------------------------------------------------------

class TestCapabilitiesShape:
    def test_returns_all_top_level_keys(self, client):
        data = _get_caps(client)
        assert set(data.keys()) >= {"nats", "realtime", "cve", "listener", "docker", "auth"}

    def test_nats_key_has_available(self, client):
        data = _get_caps(client)
        assert "available" in data["nats"]

    def test_realtime_key_has_available_and_transport(self, client):
        data = _get_caps(client)
        assert "available" in data["realtime"]
        assert "transport" in data["realtime"]

    def test_cve_key_has_available_and_last_sync(self, client):
        data = _get_caps(client)
        assert "available" in data["cve"]
        assert "last_sync" in data["cve"]

    def test_listener_key_has_available_mdns_ssdp(self, client):
        data = _get_caps(client)
        assert "available" in data["listener"]
        assert "mdns" in data["listener"]
        assert "ssdp" in data["listener"]

    def test_docker_key_has_available_and_discovery_enabled(self, client):
        data = _get_caps(client)
        assert "available" in data["docker"]
        assert "discovery_enabled" in data["docker"]

    def test_auth_key_has_enabled(self, client):
        data = _get_caps(client)
        assert "enabled" in data["auth"]

    def test_fallback_when_no_settings_row(self, client, db):
        """With empty DB there is no AppSettings row; endpoint must return safe defaults."""
        from app.db.models import AppSettings

        db.query(AppSettings).delete()
        db.commit()
        data = _get_caps(client)
        assert data["auth"]["enabled"] is True
        assert data["realtime"]["available"] is False
        assert data["cve"]["available"] is False
        assert data["listener"]["available"] is False


# ---------------------------------------------------------------------------
# Live setting value tests (create AppSettings row first)
# ---------------------------------------------------------------------------

def _create_settings(client, **kwargs):
    """Seed an AppSettings row via the settings PATCH endpoint."""
    r = client.put("/api/v1/settings", json=kwargs)
    assert r.status_code in (200, 201), r.text
    return r.json()


class TestCapabilitiesReflectsSettings:
    def test_auth_always_enabled(self, client):
        _create_settings(client)
        data = _get_caps(client)
        assert data["auth"]["enabled"] is True

    def test_cve_enabled_reflects_setting(self, client):
        _create_settings(client, cve_sync_enabled=True)
        data = _get_caps(client)
        assert data["cve"]["available"] is True

    def test_realtime_transport_reflects_setting(self, client):
        _create_settings(client, realtime_transport="sse")
        data = _get_caps(client)
        assert data["realtime"]["transport"] == "sse"

    def test_listener_mdns_ssdp_reflects_setting(self, client):
        _create_settings(client, listener_enabled=True, mdns_enabled=True, ssdp_enabled=False)
        data = _get_caps(client)
        assert data["listener"]["available"] is True
        assert data["listener"]["mdns"] is True
        assert data["listener"]["ssdp"] is False

    def test_docker_discovery_enabled_reflects_setting(self, client):
        _create_settings(client, docker_discovery_enabled=True)
        data = _get_caps(client)
        assert data["docker"]["discovery_enabled"] is True

    def test_nats_available_false_when_not_connected(self, client):
        """NATS client is not connected in test env (mocked away)."""
        data = _get_caps(client)
        assert data["nats"]["available"] is False

    def test_nats_available_true_when_connected(self, client):
        """Mock is_connected as a property to simulate NATS connected state."""
        _create_settings(client)  # ensure s is not None so the live branch is hit
        from app.core.nats_client import NATSClient
        with patch.object(NATSClient, "is_connected", new=property(lambda self: True)):
            data = _get_caps(client)
        assert data["nats"]["available"] is True

    def test_docker_socket_available_false_when_missing(self, client):
        """Docker socket at a non-existent path reports available=False."""
        _create_settings(client, docker_socket_path="/tmp/no-such-docker.sock")
        data = _get_caps(client)
        assert data["docker"]["available"] is False
