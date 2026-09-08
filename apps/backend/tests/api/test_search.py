"""Legacy-compatible and bounded entity search API contracts."""

import secrets

import pytest

from app.core.security import create_salted_api_token_hash
from app.db.models import APIToken


def _scoped_headers(db_session, factories, scopes):
    raw_token = secrets.token_urlsafe(24)
    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash(raw_token),
            label="search scope test",
            created_by=owner.id,
            scopes=scopes,
        )
    )
    db_session.flush()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.mark.asyncio
async def test_legacy_search_adds_canonical_identity(client, auth_headers, factories):
    hardware = factories.hardware(name="Navigator target")

    response = await client.get("/api/v1/search", params={"q": "Navigator"}, headers=auth_headers)

    assert response.status_code == 200, response.text
    item = response.json()[0]
    assert item["id"] == f"hardware-{hardware.id}"
    assert item["type"] == "hardware"
    assert item["entity_type"] == "hardware"
    assert item["entity_id"] == hardware.id
    assert item["action_url"] == "/hardware"


@pytest.mark.asyncio
async def test_search_page_reports_truncation(client, auth_headers, factories):
    for index in range(3):
        factories.hardware(name=f"Truncated target {index}")

    response = await client.get(
        "/api/v1/search/page",
        params={"q": "Truncated", "limit": 2, "types": "hardware"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 2
    assert response.json()["has_more"] is True


@pytest.mark.asyncio
async def test_search_requires_read_scope(client):
    response = await client.get("/api/v1/search", params={"q": "host"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_rejects_whitespace_only_query(client, auth_headers):
    response = await client.get("/api/v1/search", params={"q": "   "}, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_honors_narrowed_token_scope(client, db_session, factories):
    denied = _scoped_headers(db_session, factories, ["write:hardware"])
    allowed = _scoped_headers(db_session, factories, ["read:*"])

    assert (
        await client.get("/api/v1/search", params={"q": "host"}, headers=denied)
    ).status_code == 403
    assert (
        await client.get("/api/v1/search", params={"q": "host"}, headers=allowed)
    ).status_code == 200


@pytest.mark.asyncio
async def test_validation_errors_do_not_reflect_secret_input(client, auth_headers):
    secret = "do-not-reflect-this-password"
    response = await client.post(
        "/api/v1/hardware",
        json={"name": "invalid", "telemetry_config": {"password": secret}},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert secret not in response.text
    assert "body" not in response.json()


@pytest.mark.asyncio
async def test_ip_conflict_returns_safe_structured_metadata(client, auth_headers):
    first = await client.post(
        "/api/v1/hardware",
        json={"name": "first", "ip_address": "192.0.2.44"},
        headers=auth_headers,
    )
    assert first.status_code == 201

    response = await client.post(
        "/api/v1/hardware",
        json={"name": "second", "ip_address": "192.0.2.44"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    data = response.json()
    assert data["error_code"] == "ip_conflict"
    assert data["fields"] == {"ip_address": "Choose an available address."}
    assert data["context"]["conflicts"][0]["entity_id"] == first.json()["id"]
    assert "entity_name" not in data["context"]["conflicts"][0]
