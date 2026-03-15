"""
Tests for the racks API.

Routes (rack router mounted at /api/v1/racks):
  GET    /api/v1/racks              — list racks
  POST   /api/v1/racks              — create rack (write auth)
  GET    /api/v1/racks/{id}         — get rack
  PATCH  /api/v1/racks/{id}         — update rack (write auth)
  DELETE /api/v1/racks/{id}         — delete rack (write auth)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/racks"


# ── CRUD ─────────────────────────────────────────────────────────────────────


async def test_list_racks_empty(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_rack(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "Rack-01", "height_u": 42, "location": "DC-1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Rack-01"
    assert body["height_u"] == 42
    assert body["location"] == "DC-1"
    assert "id" in body


async def test_get_rack(client, auth_headers):
    create = await client.post(_BASE, headers=auth_headers, json={"name": "Rack-02"})
    rack_id = create.json()["id"]
    resp = await client.get(f"{_BASE}/{rack_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Rack-02"


async def test_get_nonexistent_rack_returns_404(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_rack(client, auth_headers):
    create = await client.post(_BASE, headers=auth_headers, json={"name": "Rack-Old"})
    rack_id = create.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{rack_id}",
        headers=auth_headers,
        json={"name": "Rack-New", "height_u": 48},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Rack-New"
    assert body["height_u"] == 48


async def test_delete_rack(client, auth_headers):
    create = await client.post(_BASE, headers=auth_headers, json={"name": "Rack-Del"})
    rack_id = create.json()["id"]
    resp = await client.delete(f"{_BASE}/{rack_id}", headers=auth_headers)
    assert resp.status_code == 204


# ── Delete nullifies hardware rack_id ────────────────────────────────────────


async def test_delete_rack_nullifies_hardware_rack_id(client, auth_headers, factories):
    rack = factories.rack(name="Rack-Nullify")
    hw = factories.hardware(name="server-in-rack", rack_id=rack.id)
    resp = await client.delete(f"{_BASE}/{rack.id}", headers=auth_headers)
    assert resp.status_code == 204
    # Verify hardware no longer references the deleted rack

    factories.session.refresh(hw)
    assert hw.rack_id is None


# ── Viewer RBAC ──────────────────────────────────────────────────────────────


async def test_viewer_can_list_racks(client, viewer_headers):
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_rack(client, viewer_headers):
    resp = await client.post(_BASE, headers=viewer_headers, json={"name": "blocked"})
    assert resp.status_code == 403


async def test_viewer_cannot_delete_rack(client, viewer_headers, factories):
    rack = factories.rack(name="viewer-nodelete")
    resp = await client.delete(f"{_BASE}/{rack.id}", headers=viewer_headers)
    assert resp.status_code == 403
