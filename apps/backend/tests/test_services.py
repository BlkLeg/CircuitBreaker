"""
Tests for the services API.

Routes (services.router mounted at /api/v1/services):
  GET    /api/v1/services           — list (200)
  POST   /api/v1/services           — create (201)
  GET    /api/v1/services/{id}      — retrieve (200)
  DELETE /api/v1/services/{id}      — delete (204)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/services"


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_service_returns_201(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "my-test-service"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my-test-service"
    assert "id" in body


async def test_create_service_unauthenticated_returns_401(client):
    resp = await client.post(_BASE, json={"name": "unauth-svc"})
    assert resp.status_code == 401


async def test_create_service_duplicate_name_returns_409(client, auth_headers):
    await client.post(_BASE, headers=auth_headers, json={"name": "dup-svc"})
    resp = await client.post(_BASE, headers=auth_headers, json={"name": "dup-svc"})
    assert resp.status_code == 409


# ── List ──────────────────────────────────────────────────────────────────────


async def test_list_services_returns_200(client, auth_headers, factories):
    factories.service(name="list-svc-a")
    factories.service(name="list-svc-b")
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_services_viewer_returns_200(client, viewer_headers):
    """Listing services does not require write auth."""
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


# ── Retrieve ──────────────────────────────────────────────────────────────────


async def test_get_service_by_id(client, auth_headers, factories):
    svc = factories.service(name="get-svc")
    resp = await client.get(f"{_BASE}/{svc.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == svc.id


async def test_get_service_not_found(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete_service_returns_204(client, auth_headers, factories):
    svc = factories.service(name="delete-svc")
    resp = await client.delete(f"{_BASE}/{svc.id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_deleted_service_no_longer_found(client, auth_headers, factories):
    svc = factories.service(name="gone-svc")
    await client.delete(f"{_BASE}/{svc.id}", headers=auth_headers)
    resp = await client.get(f"{_BASE}/{svc.id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_service_unauthenticated_returns_401(client, factories):
    svc = factories.service(name="unauth-delete-svc")
    resp = await client.delete(f"{_BASE}/{svc.id}")
    assert resp.status_code == 401
