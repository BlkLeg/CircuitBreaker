"""
Tests for the misc items API.

Routes (misc router mounted at /api/v1/misc):
  GET    /api/v1/misc              — list misc items (optional ?kind= filter)
  POST   /api/v1/misc              — create misc item (write auth)
  GET    /api/v1/misc/{id}         — get single item
  PATCH  /api/v1/misc/{id}         — update item (write auth)
  DELETE /api/v1/misc/{id}         — delete item (write auth)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/misc"


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def test_list_misc_empty(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_misc_item(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "Patch Cable A", "kind": "cable"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Patch Cable A"
    assert body["kind"] == "cable"
    assert "id" in body


async def test_create_misc_with_description_and_url(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={
            "name": "USB-C Hub",
            "kind": "accessory",
            "description": "7-port hub",
            "url": "https://example.com/hub",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["description"] == "7-port hub"
    assert body["url"] == "https://example.com/hub"


async def test_get_misc_item(client, auth_headers):
    create = await client.post(
        _BASE, headers=auth_headers, json={"name": "KVM Switch", "kind": "peripheral"}
    )
    item_id = create.json()["id"]
    resp = await client.get(f"{_BASE}/{item_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "KVM Switch"


async def test_update_misc_item(client, auth_headers):
    create = await client.post(
        _BASE, headers=auth_headers, json={"name": "Old Label", "kind": "cable"}
    )
    item_id = create.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{item_id}",
        headers=auth_headers,
        json={"name": "New Label"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Label"


async def test_delete_misc_item(client, auth_headers):
    create = await client.post(
        _BASE, headers=auth_headers, json={"name": "Disposable", "kind": "cable"}
    )
    item_id = create.json()["id"]
    resp = await client.delete(f"{_BASE}/{item_id}", headers=auth_headers)
    assert resp.status_code == 204


# ── Filter by kind ───────────────────────────────────────────────────────────


async def test_filter_by_kind(client, auth_headers):
    await client.post(_BASE, headers=auth_headers, json={"name": "Cable-A", "kind": "cable"})
    await client.post(_BASE, headers=auth_headers, json={"name": "Shelf-A", "kind": "shelf"})
    resp = await client.get(f"{_BASE}?kind=cable", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()
    assert all(i["kind"] == "cable" for i in items)


# ── Viewer RBAC ──────────────────────────────────────────────────────────────


async def test_viewer_can_list_misc(client, viewer_headers):
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_misc(client, viewer_headers):
    resp = await client.post(
        _BASE, headers=viewer_headers, json={"name": "blocked", "kind": "cable"}
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_misc(client, viewer_headers, factories):
    item = factories.misc_item(name="viewer-nodelete")
    resp = await client.delete(f"{_BASE}/{item.id}", headers=viewer_headers)
    assert resp.status_code == 403
