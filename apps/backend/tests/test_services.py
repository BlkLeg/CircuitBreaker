"""
Tests for the services API.

Routes (services.router mounted at /api/v1/services):
  GET    /api/v1/services                          — list (200)
  POST   /api/v1/services                          — create (201)
  GET    /api/v1/services/{id}                     — retrieve (200)
  PATCH  /api/v1/services/{id}                     — update (200)
  DELETE /api/v1/services/{id}                     — delete (204)
  GET    /api/v1/services/{id}/dependencies        — list deps
  POST   /api/v1/services/{id}/dependencies        — add dep (201)
  DELETE /api/v1/services/{id}/dependencies/{did}  — remove dep (204)
  GET    /api/v1/services/{id}/storage             — list storage links
  POST   /api/v1/services/{id}/storage             — add storage link (201)
  DELETE /api/v1/services/{id}/storage/{sid}       — remove storage link (204)
  GET    /api/v1/services/{id}/misc                — list misc links
  POST   /api/v1/services/{id}/misc                — add misc link (201)
  DELETE /api/v1/services/{id}/misc/{mid}          — remove misc link (204)
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


async def test_create_service_with_url_and_description(client, auth_headers):
    """Create with optional url, description, category fields."""
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={
            "name": "svc-with-url",
            "url": "https://example.com",
            "description": "A test service",
            "category": "monitoring",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["url"] == "https://example.com"
    assert body["description"] == "A test service"
    assert body["category_name"] == "monitoring"


async def test_create_service_with_environment(client, auth_headers, factories):
    """Create with environment string."""
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "svc-env", "environment": "production"},
    )
    assert resp.status_code == 201
    assert resp.json()["environment_name"] == "production"


async def test_create_service_with_ports(client, auth_headers):
    """Create with structured port bindings."""
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={
            "name": "svc-ports",
            "ports": [{"port": 8080, "protocol": "tcp"}],
        },
    )
    assert resp.status_code == 201


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


# ── Update (PATCH) ────────────────────────────────────────────────────────────


async def test_patch_service_name(client, auth_headers, factories):
    svc = factories.service(name="patch-orig")
    resp = await client.patch(
        f"{_BASE}/{svc.id}",
        headers=auth_headers,
        json={"name": "patch-updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "patch-updated"


async def test_patch_service_partial_fields(client, auth_headers, factories):
    svc = factories.service(name="patch-partial")
    resp = await client.patch(
        f"{_BASE}/{svc.id}",
        headers=auth_headers,
        json={"url": "https://patched.example.com", "description": "new desc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "https://patched.example.com"
    assert body["description"] == "new desc"
    assert body["name"] == "patch-partial"  # unchanged


async def test_patch_service_not_found(client, auth_headers):
    resp = await client.patch(
        f"{_BASE}/999999",
        headers=auth_headers,
        json={"name": "nope"},
    )
    assert resp.status_code == 404


async def test_patch_service_unauthenticated(client, factories):
    svc = factories.service(name="patch-unauth")
    resp = await client.patch(f"{_BASE}/{svc.id}", json={"name": "x"})
    assert resp.status_code == 401


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


# ── Dependencies ──────────────────────────────────────────────────────────────


async def test_add_dependency(client, auth_headers, factories):
    svc_a = factories.service(name="dep-parent")
    svc_b = factories.service(name="dep-child")
    resp = await client.post(
        f"{_BASE}/{svc_a.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_id": svc_b.id},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["service_id"] == svc_a.id
    assert body["depends_on_id"] == svc_b.id


async def test_list_dependencies(client, auth_headers, factories):
    svc_a = factories.service(name="dep-list-a")
    svc_b = factories.service(name="dep-list-b")
    await client.post(
        f"{_BASE}/{svc_a.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_id": svc_b.id},
    )
    resp = await client.get(f"{_BASE}/{svc_a.id}/dependencies", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


async def test_remove_dependency(client, auth_headers, factories):
    svc_a = factories.service(name="dep-rm-a")
    svc_b = factories.service(name="dep-rm-b")
    await client.post(
        f"{_BASE}/{svc_a.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_id": svc_b.id},
    )
    resp = await client.delete(
        f"{_BASE}/{svc_a.id}/dependencies/{svc_b.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


async def test_add_dependency_missing_service(client, auth_headers, factories):
    svc = factories.service(name="dep-miss")
    resp = await client.post(
        f"{_BASE}/{svc.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_id": 999999},
    )
    assert resp.status_code == 404


# ── Storage links ─────────────────────────────────────────────────────────────


async def test_add_storage_link(client, auth_headers, factories):
    svc = factories.service(name="stor-link-svc")
    stor = factories.storage()
    resp = await client.post(
        f"{_BASE}/{svc.id}/storage",
        headers=auth_headers,
        json={"storage_id": stor.id, "purpose": "database"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["service_id"] == svc.id
    assert body["storage_id"] == stor.id
    assert body["purpose"] == "database"


async def test_list_storage_links(client, auth_headers, factories):
    svc = factories.service(name="stor-list-svc")
    stor = factories.storage()
    await client.post(
        f"{_BASE}/{svc.id}/storage",
        headers=auth_headers,
        json={"storage_id": stor.id},
    )
    resp = await client.get(f"{_BASE}/{svc.id}/storage", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_remove_storage_link(client, auth_headers, factories):
    svc = factories.service(name="stor-rm-svc")
    stor = factories.storage()
    await client.post(
        f"{_BASE}/{svc.id}/storage",
        headers=auth_headers,
        json={"storage_id": stor.id},
    )
    resp = await client.delete(
        f"{_BASE}/{svc.id}/storage/{stor.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


# ── Misc links ────────────────────────────────────────────────────────────────


async def test_add_misc_link(client, auth_headers, factories):
    svc = factories.service(name="misc-link-svc")
    mi = factories.misc_item()
    resp = await client.post(
        f"{_BASE}/{svc.id}/misc",
        headers=auth_headers,
        json={"misc_id": mi.id, "purpose": "adapter"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["service_id"] == svc.id
    assert body["misc_id"] == mi.id


async def test_list_misc_links(client, auth_headers, factories):
    svc = factories.service(name="misc-list-svc")
    mi = factories.misc_item()
    await client.post(
        f"{_BASE}/{svc.id}/misc",
        headers=auth_headers,
        json={"misc_id": mi.id},
    )
    resp = await client.get(f"{_BASE}/{svc.id}/misc", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_remove_misc_link(client, auth_headers, factories):
    svc = factories.service(name="misc-rm-svc")
    mi = factories.misc_item()
    await client.post(
        f"{_BASE}/{svc.id}/misc",
        headers=auth_headers,
        json={"misc_id": mi.id},
    )
    resp = await client.delete(
        f"{_BASE}/{svc.id}/misc/{mi.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


# ── Viewer RBAC ───────────────────────────────────────────────────────────────


async def test_viewer_can_read_service(client, viewer_headers, factories):
    svc = factories.service(name="viewer-read-svc")
    resp = await client.get(f"{_BASE}/{svc.id}", headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_service(client, viewer_headers):
    resp = await client.post(_BASE, headers=viewer_headers, json={"name": "viewer-no-create"})
    assert resp.status_code == 403


async def test_viewer_cannot_patch_service(client, viewer_headers, factories):
    svc = factories.service(name="viewer-no-patch")
    resp = await client.patch(
        f"{_BASE}/{svc.id}",
        headers=viewer_headers,
        json={"name": "viewer-patched"},
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_service(client, viewer_headers, factories):
    svc = factories.service(name="viewer-no-del")
    resp = await client.delete(f"{_BASE}/{svc.id}", headers=viewer_headers)
    assert resp.status_code == 403
