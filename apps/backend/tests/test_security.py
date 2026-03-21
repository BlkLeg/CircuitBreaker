"""
Security regression tests derived from the Circuit Breaker audit report.

All tests in this module are marked with @pytest.mark.security automatically
via the module-level pytestmark.  Individual tests also carry audit reference
IDs as comments for traceability.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt(payload: dict) -> str:
    secret = os.environ["CB_JWT_SECRET"]
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _bad_aud_token(user_id: int, audience: str) -> str:
    return _make_jwt(
        {
            "user_id": user_id,
            "sub": str(user_id),
            "aud": audience,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
        }
    )


# ---------------------------------------------------------------------------
# C-01 — nmap argument injection
# ---------------------------------------------------------------------------

_NMAP_INJECTION_PAYLOADS = [
    "-oX /tmp/evil.sh && id",
    "-sV; rm -rf /",
    "$(whoami)",
    "`id`",
    "-sV | nc",
    "-sV > /data/leak",
    "-sV --script=<script>",
    # 8th payload: path traversal in nmap args
    "-sV -oX ../../../etc/cron.d/pwn",
]


class TestC01NmapInjection:
    """C-01: nmap_arguments must be sanitised; shell metacharacters → 422."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", _NMAP_INJECTION_PAYLOADS)
    async def test_nmap_injection_returns_422(self, client, auth_headers, payload):
        resp = await client.post(
            "/api/v1/discovery/scan",
            headers=auth_headers,
            json={"cidr": "192.168.1.0/24", "nmap_arguments": payload},
        )
        assert resp.status_code == 422, (
            f"Injection payload {payload!r} was not rejected (got {resp.status_code})"
        )


# ---------------------------------------------------------------------------
# C-02 — SNMP community string injection + C-02b valid values accepted
# ---------------------------------------------------------------------------

_BAD_SNMP_COMMUNITIES = [
    "public;id",
    "pub&&id",
    "pub$(id)",
    "a" * 65,  # too long
]

_GOOD_SNMP_COMMUNITIES = [
    "public",
    "my-community",
    "test.1",
]


class TestC02SnmpCommunityValidation:
    """C-02 / C-02b: SNMP community string validation on telemetry config."""

    async def _create_hardware(self, client, auth_headers) -> int:
        resp = await client.post(
            "/api/v1/hardware",
            headers=auth_headers,
            json={"name": f"snmp-test-hw-{id(auth_headers)}"},
        )
        assert resp.status_code == 201, f"Hardware create failed: {resp.text}"
        return resp.json()["id"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("community", _BAD_SNMP_COMMUNITIES)
    async def test_bad_snmp_community_returns_422(self, client, auth_headers, community):
        hw_id = await self._create_hardware(client, auth_headers)
        resp = await client.post(
            f"/api/v1/hardware/{hw_id}/telemetry/config",
            headers=auth_headers,
            json={
                "profile": "snmp_generic",
                "host": "192.168.1.50",
                "snmp_community": community,
            },
        )
        assert resp.status_code == 422, (
            f"Malicious community string {community!r} was not rejected (got {resp.status_code})"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("community", _GOOD_SNMP_COMMUNITIES)
    async def test_valid_snmp_community_accepted(self, client, auth_headers, community):
        hw_id = await self._create_hardware(client, auth_headers)
        resp = await client.post(
            f"/api/v1/hardware/{hw_id}/telemetry/config",
            headers=auth_headers,
            json={
                "profile": "snmp_generic",
                "host": "192.168.1.50",
                "snmp_community": community,
            },
        )
        assert resp.status_code in (200, 201, 204), (
            f"Valid community string {community!r} was rejected: {resp.status_code} {resp.text}"
        )


# ---------------------------------------------------------------------------
# C-03 — Wrong JWT audience rejected on hardware endpoint
# ---------------------------------------------------------------------------

_WRONG_AUDIENCES = [
    "cb:change-password",
    "cb:mfa-challenge",
    "wrong",
    "",
    "cb:api",
]


class TestC03WrongAudience:
    """C-03: JWTs with non-session audiences must return 401."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("audience", _WRONG_AUDIENCES)
    async def test_wrong_audience_returns_401(self, client, factories, audience):
        user = factories.user(role="admin")
        token = _bad_aud_token(user.id, audience)
        resp = await client.get(
            "/api/v1/hardware",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, (
            f"Audience {audience!r} was accepted — expected 401, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# C-07 — SSRF via webhook target_url
# ---------------------------------------------------------------------------

_SSRF_WEBHOOK_URLS = [
    "http://127.0.0.1:5432/",
    "http://0.0.0.0/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://10.0.0.1/",  # private — blocked for webhooks
]


class TestC07SSRFWebhook:
    """C-07: Webhook URLs targeting loopback/private addresses must return 422."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", _SSRF_WEBHOOK_URLS)
    async def test_ssrf_webhook_url_rejected(self, client, auth_headers, url):
        resp = await client.post(
            "/api/v1/webhooks",
            headers=auth_headers,
            json={
                "label": "ssrf-test",
                "url": url,
                "events_enabled": ["topology.hardware.created"],
            },
        )
        assert resp.status_code == 422, f"SSRF URL {url!r} was not blocked (got {resp.status_code})"

    @pytest.mark.asyncio
    async def test_legitimate_webhook_url_accepted(self, client, auth_headers):
        """C-07b: A real public webhook URL must be accepted."""
        resp = await client.post(
            "/api/v1/webhooks",
            headers=auth_headers,
            json={
                "label": "slack-hook",
                "url": "https://hooks.slack.com/services/T000/B000/xxxx",
                "events_enabled": ["topology.hardware.created"],
            },
        )
        assert resp.status_code in (200, 201), (
            f"Legitimate webhook URL rejected: {resp.status_code} {resp.text}"
        )


# ---------------------------------------------------------------------------
# C-08 — Proxmox loopback blocked; LAN allowed
# ---------------------------------------------------------------------------

_PROXMOX_LOOPBACK_URLS = [
    "http://localhost:8006/",
    "http://127.0.0.1:8006/",
]


class TestC08ProxmoxLoopback:
    """C-08: Proxmox loopback URLs blocked; 192.168.x.x LAN URLs allowed."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", _PROXMOX_LOOPBACK_URLS)
    async def test_proxmox_loopback_rejected(self, client, auth_headers, url):
        resp = await client.post(
            "/api/v1/integrations/proxmox",
            headers=auth_headers,
            json={
                "name": "test-proxmox",
                "config_url": url,
                "api_token": "PVEAPIToken=root@pam!ci=fake-token",
            },
        )
        assert resp.status_code == 422, (
            f"Proxmox loopback URL {url!r} was not blocked (got {resp.status_code})"
        )

    @pytest.mark.asyncio
    async def test_proxmox_lan_ip_allowed(self, client, auth_headers):
        """LAN (192.168.x.x) must be accepted for Proxmox (has a LAN exception)."""
        resp = await client.post(
            "/api/v1/integrations/proxmox",
            headers=auth_headers,
            json={
                "name": "lan-proxmox",
                "config_url": "http://192.168.1.100:8006/",
                "api_token": "PVEAPIToken=root@pam!ci=fake-token",
            },
        )
        # 422 means validation failed — that's a bug.  Any other status (200/201/400/409/503)
        # means the URL passed SSRF validation (the vault may not be ready, etc.).
        assert resp.status_code != 422, (
            f"LAN Proxmox URL was incorrectly blocked by SSRF filter: {resp.text}"
        )


# ---------------------------------------------------------------------------
# H-12 — Avatar upload path traversal + executable disguised as image
# ---------------------------------------------------------------------------


class TestH12AvatarUpload:
    """H-12: Avatar endpoint must reject path traversal filenames and
    executable file contents masquerading as images."""

    @pytest.mark.asyncio
    async def test_path_traversal_filename_rejected(self, client, auth_headers):
        evil_filename = "../../etc/cron.d/evil.png"
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # minimal PNG header
        resp = await client.put(
            "/api/v1/auth/me/avatar",
            headers=auth_headers,
            files={"profile_photo": (evil_filename, io.BytesIO(fake_png), "image/png")},
        )
        assert resp.status_code in (400, 422), (
            f"Path traversal filename was accepted: {resp.status_code} {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_exe_renamed_to_jpg_rejected(self, client, auth_headers):
        # MZ header = Windows PE / DOS executable magic bytes
        mz_header = b"MZ" + b"\x90\x00" * 30
        resp = await client.put(
            "/api/v1/auth/me/avatar",
            headers=auth_headers,
            files={"profile_photo": ("photo.jpg", io.BytesIO(mz_header), "image/jpeg")},
        )
        assert resp.status_code == 422, (
            f"Executable disguised as JPEG was accepted: {resp.status_code} {resp.text}"
        )


# ---------------------------------------------------------------------------
# H-14 — Telemetry secrets masked in GET response
# ---------------------------------------------------------------------------


class TestH14TelemetryMasking:
    """H-14: snmp_community and password must appear as '****' in GET response."""

    @pytest.mark.asyncio
    async def test_telemetry_secrets_masked_in_hardware_get(self, client, auth_headers, factories):
        hw = factories.hardware()
        secret_community = "secret-string"

        # Write telemetry config with sensitive data
        config_resp = await client.post(
            f"/api/v1/hardware/{hw.id}/telemetry/config",
            headers=auth_headers,
            json={
                "profile": "snmp_generic",
                "host": "192.168.1.50",
                "snmp_community": secret_community,
                "password": "super-secret-password",
            },
        )
        assert config_resp.status_code in (200, 201, 204), (
            f"Telemetry config write failed: {config_resp.status_code} {config_resp.text}"
        )

        # Retrieve the hardware and inspect the raw response body
        get_resp = await client.get(f"/api/v1/hardware/{hw.id}", headers=auth_headers)
        assert get_resp.status_code == 200
        body_text = get_resp.text

        assert secret_community not in body_text, (
            f"Plain-text snmp_community {secret_community!r} leaked in GET /hardware/{hw.id}"
        )
        assert "super-secret-password" not in body_text, (
            f"Plain-text password leaked in GET /hardware/{hw.id}"
        )
        assert "****" in body_text, (
            f"Expected masked '****' value in telemetry config response, found none.\n"
            f"Body: {body_text[:500]}"
        )


# ---------------------------------------------------------------------------
# M-04 — CORS: evil origin must not be reflected
# ---------------------------------------------------------------------------


class TestM04CORS:
    """M-04: Preflight/OPTIONS with a hostile Origin must not be echoed back."""

    @pytest.mark.asyncio
    async def test_evil_origin_not_reflected_in_cors_header(self, client):
        evil_origin = "https://evil.example.com"
        resp = await client.options(
            "/api/v1/hardware",
            headers={
                "Origin": evil_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        acao = resp.headers.get("access-control-allow-origin", "")
        assert "evil.example.com" not in acao, (
            f"Evil origin was reflected in Access-Control-Allow-Origin: {acao!r}"
        )


# ---------------------------------------------------------------------------
# M-17 — CIDR size enforcement on discovery scan
# ---------------------------------------------------------------------------


class TestM17CIDRSizeEnforcement:
    """M-17: /8 CIDRs must be rejected; /24 must be accepted."""

    @pytest.mark.asyncio
    async def test_slash8_cidr_returns_422(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/discovery/scan",
            headers=auth_headers,
            json={"cidr": "10.0.0.0/8"},
        )
        assert resp.status_code == 422, (
            f"/8 CIDR was accepted — should have been rejected (got {resp.status_code})"
        )

    @pytest.mark.asyncio
    async def test_slash24_cidr_accepted(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/discovery/scan",
            headers=auth_headers,
            json={"cidr": "192.168.1.0/24"},
        )
        # 200/202 = queued; 400 = ack not accepted; anything but 422 means validation passed
        assert resp.status_code != 422, (
            f"/24 CIDR was incorrectly rejected by validation: {resp.status_code} {resp.text}"
        )


# ---------------------------------------------------------------------------
# RBAC — viewer & unauthenticated enforcement
# ---------------------------------------------------------------------------


class TestRBAC:
    """Viewer role and unauthenticated access restrictions."""

    @pytest.mark.asyncio
    async def test_viewer_cannot_post_hardware(self, client, viewer_headers):
        resp = await client.post(
            "/api/v1/hardware",
            headers=viewer_headers,
            json={"name": "viewer-created"},
        )
        assert resp.status_code == 403, f"Viewer must not POST hardware, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_viewer_cannot_delete_hardware(self, client, viewer_headers, factories):
        hw = factories.hardware()
        resp = await client.delete(
            f"/api/v1/hardware/{hw.id}",
            headers=viewer_headers,
        )
        assert resp.status_code == 403, f"Viewer must not DELETE hardware, got {resp.status_code}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/hardware"),
            ("GET", "/api/v1/discovery/status"),
            ("GET", "/api/v1/logs"),
            ("GET", "/api/v1/tags"),
            ("POST", "/api/v1/discovery/scan"),
        ],
    )
    async def test_unauthenticated_returns_401(self, client, method, path):
        func = getattr(client, method.lower())
        resp = await func(path)
        assert resp.status_code == 401, (
            f"Unauthenticated {method} {path} returned {resp.status_code} instead of 401"
        )
