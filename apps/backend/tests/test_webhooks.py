"""
Tests for the webhook management API: POST/GET/DELETE /api/v1/webhooks

Key schema facts (confirmed from source):
  - Create body: {label, url, events_enabled}
  - Response model: WebhookRuleOut (fields: id, label, url, events_enabled, ...)
  - List returns WebhookListResponse: {items, total, page, per_page}
  - SSRF check in Pydantic field_validator → 422 on loopback/private IPs
  - Delete returns {"status": "ok"} with 200
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
        "url": "https://8.8.8.8/circuit-breaker",
        "events_enabled": ["topology.hardware.created"],
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["label"] == "test-hook"


@pytest.mark.asyncio
async def test_create_webhook_ssrf_loopback_rejected(client, auth_headers):
    """Loopback target URL should be rejected — SSRF guard in Pydantic validator → 422."""
    payload = {
        "label": "ssrf-hook",
        "url": "http://127.0.0.1:1234/",
        "events_enabled": [],
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    # reject_ssrf_url raises ValueError inside field_validator → Pydantic returns 422
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks(client, auth_headers):
    """GET /webhooks → 200 and returns WebhookListResponse with 'items' list."""
    resp = await client.get(BASE, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert "items" in body
    assert isinstance(body["items"], list)
    assert "total" in body


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
            "url": "https://8.8.8.8/delete-target",
            "events_enabled": [],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 200
    rule_id = create_resp.json()["id"]

    del_resp = await client.delete(f"{BASE}/{rule_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json().get("status") == "ok"
