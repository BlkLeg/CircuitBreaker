"""
Tests for the webhook management API: POST/GET/DELETE /api/v1/webhooks

Key schema facts (confirmed from source):
  - Create body: {label, url, events_enabled}
  - Create has no explicit status_code override → returns 200
  - SSRF check raises HTTPException(400) for private/loopback IPs
  - Delete returns {"status": "ok"} with 200 (no status_code=204 decorator)
"""

import pytest

BASE = "/api/v1/webhooks"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_webhook_valid_url(client, auth_headers):
    """Create webhook with a public external URL → 200, id present."""
    payload = {
        "label": "test-hook",
        "url": "https://hooks.example.com/circuit-breaker",
        "events_enabled": ["topology.hardware.created"],
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data


@pytest.mark.asyncio
async def test_create_webhook_ssrf_loopback_rejected(client, auth_headers):
    """Loopback target URL should be rejected — SSRF guard returns 400."""
    payload = {
        "label": "ssrf-hook",
        "url": "http://127.0.0.1:1234/",
        "events_enabled": [],
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    # SSRF guard in reject_ssrf_url raises ValueError → HTTPException(400)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks(client, auth_headers):
    """GET /webhooks → 200 and returns an object with a rules list."""
    resp = await client.get(BASE, headers=auth_headers)
    assert resp.status_code == 200
    # The list endpoint returns WebhookListResponse which contains a 'rules' key
    body = resp.json()
    assert isinstance(body, dict)
    assert "rules" in body
    assert isinstance(body["rules"], list)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_webhook(client, auth_headers):
    """Create then delete → 200 with {status: ok}."""
    create_resp = await client.post(
        BASE,
        json={
            "label": "delete-me-hook",
            "url": "https://hooks.example.com/delete-target",
            "events_enabled": [],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200
    rule_id = create_resp.json()["id"]

    del_resp = await client.delete(f"{BASE}/{rule_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json().get("status") == "ok"
