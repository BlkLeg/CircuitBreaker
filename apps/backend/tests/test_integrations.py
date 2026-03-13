"""
Tests for the Proxmox integration API.

Route: POST /api/v1/integrations/proxmox
  (proxmox_router mounted at /api/v1/integrations/proxmox, route @router.post(""))

SSRF protection (url_validation.reject_ssrf_url_proxmox):
  - Loopback addresses (127.x, ::1) → rejected (422)
  - Link-local (169.254.x) → rejected (422)
  - Private/LAN addresses (192.168.x, 10.x, 172.16-31.x) → ALLOWED (Proxmox
    is typically on a LAN; only loopback/link-local are blocked)
  - Public internet URLs → accepted (200/201)

The endpoint also requires an initialized vault (503 when vault not ready) and
admin auth (401/403 without credentials).
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/integrations/proxmox"

_VALID_PAYLOAD = {
    "name": "test-proxmox",
    "config_url": "https://proxmox.example.com:8006",
    "api_token": "root@pam!test=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "auto_sync": False,
    "verify_ssl": True,
}


# ── Auth guards ───────────────────────────────────────────────────────────────


async def test_proxmox_create_unauthenticated_returns_401(client):
    resp = await client.post(_BASE, json=_VALID_PAYLOAD)
    assert resp.status_code == 401


async def test_proxmox_create_viewer_returns_403(client, viewer_headers):
    resp = await client.post(_BASE, headers=viewer_headers, json=_VALID_PAYLOAD)
    assert resp.status_code == 403


# ── SSRF / URL validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8006",
        "http://127.0.0.1:8006",
        "http://127.1.2.3:8006",
        "http://[::1]:8006",
    ],
)
async def test_proxmox_loopback_url_rejected(client, auth_headers, url):
    """Loopback URLs must be rejected with 422 (SSRF protection)."""
    payload = {**_VALID_PAYLOAD, "config_url": url, "name": f"ssrf-test-{url[:20]}"}
    resp = await client.post(_BASE, headers=auth_headers, json=payload)
    assert resp.status_code == 422, (
        f"Expected 422 for loopback URL {url!r}, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.0.1:8006",
        "http://169.254.169.254",  # AWS metadata service
    ],
)
async def test_proxmox_link_local_url_rejected(client, auth_headers, url):
    """Link-local URLs must be rejected with 422."""
    payload = {**_VALID_PAYLOAD, "config_url": url, "name": f"ssrf-ll-{url[:20]}"}
    resp = await client.post(_BASE, headers=auth_headers, json=payload)
    assert resp.status_code == 422, (
        f"Expected 422 for link-local URL {url!r}, got {resp.status_code}: {resp.text}"
    )


async def test_proxmox_valid_public_url_accepted(client, auth_headers):
    """A public-looking URL should pass URL validation (vault may not be ready → 503 is OK)."""
    payload = {**_VALID_PAYLOAD, "config_url": "https://proxmox.example.com:8006"}
    resp = await client.post(_BASE, headers=auth_headers, json=payload)
    # 422 means URL validation failed — that's a test failure.
    # 503 means vault not initialized (acceptable in CI without vault setup).
    # 200/201 means full success.
    assert resp.status_code != 422, f"Valid public URL was rejected as SSRF: {resp.text}"
    assert resp.status_code in (200, 201, 503), f"Unexpected status {resp.status_code}: {resp.text}"


async def test_proxmox_verify_ssl_defaults_true(client, auth_headers):
    """verify_ssl should default to True in request schema."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "verify_ssl"}
    payload["config_url"] = "https://proxmox2.example.com:8006"
    payload["name"] = "proxmox-default-ssl"
    resp = await client.post(_BASE, headers=auth_headers, json=payload)
    # If vault ready and accepted, confirm verify_ssl=True in response
    if resp.status_code in (200, 201):
        assert resp.json().get("verify_ssl") is True
    else:
        # 503 vault not ready is acceptable; just ensure URL was not rejected
        assert resp.status_code != 422
