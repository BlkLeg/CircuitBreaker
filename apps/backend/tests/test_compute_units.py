"""
Tests for the compute-units API.

Routes (compute_units.router mounted at /api/v1/compute-units):
  GET    /api/v1/compute-units             — list
  POST   /api/v1/compute-units             — create (201)
  GET    /api/v1/compute-units/{id}        — get
  PATCH  /api/v1/compute-units/{id}        — update
  DELETE /api/v1/compute-units/{id}        — delete (204)
  GET    /api/v1/compute-units/{id}/networks — list network memberships
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/compute-units"


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_list_compute_units(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_compute_unit_minimal(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-01")
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "vm-01", "kind": "vm", "hardware_id": hw.id},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "vm-01"
    assert body["kind"] == "vm"
    assert body["hardware_id"] == hw.id
    assert "id" in body


async def test_create_compute_unit_with_details(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-02")
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={
            "name": "vm-full",
            "kind": "vm",
            "hardware_id": hw.id,
            "ip_address": "192.168.1.100",
            "os": "Ubuntu 22.04",
            "cpu_cores": 4,
            "memory_mb": 8192,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ip_address"] == "192.168.1.100"
    assert body["os"] == "Ubuntu 22.04"
    assert body["cpu_cores"] == 4
    assert body["memory_mb"] == 8192


async def test_create_compute_unit_container(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-03")
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "container-01", "kind": "container", "hardware_id": hw.id},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "container"


async def test_create_compute_unit_unauthenticated(client, factories):
    hw = factories.hardware(name="cu-host-unauth")
    resp = await client.post(
        _BASE,
        json={"name": "unauth-vm", "kind": "vm", "hardware_id": hw.id},
    )
    assert resp.status_code in (401, 403)


async def test_get_compute_unit(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-get")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "get-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cuid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == cuid


async def test_get_compute_unit_not_found(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_compute_unit(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-upd")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "upd-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{cuid}",
        headers=auth_headers,
        json={"name": "upd-vm-v2", "cpu_cores": 8, "memory_mb": 16384},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "upd-vm-v2"
    assert body["cpu_cores"] == 8
    assert body["memory_mb"] == 16384


async def test_update_compute_unit_not_found(client, auth_headers):
    resp = await client.patch(f"{_BASE}/999999", headers=auth_headers, json={"name": "nope"})
    assert resp.status_code == 404


async def test_delete_compute_unit(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-del")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "del-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cuid}", headers=auth_headers)
    assert resp.status_code == 204
    # Verify gone
    get_resp = await client.get(f"{_BASE}/{cuid}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_compute_unit_unauthenticated(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-del-unauth")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "del-unauth-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cuid}")
    assert resp.status_code in (401, 403)


# ── Network memberships ──────────────────────────────────────────────────────


async def test_list_compute_unit_networks(client, auth_headers, factories):
    hw = factories.hardware(name="cu-host-nets")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "net-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cuid}/networks", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Viewer RBAC ───────────────────────────────────────────────────────────────


async def test_viewer_can_list_compute_units(client, viewer_headers):
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_can_get_compute_unit(client, viewer_headers, auth_headers, factories):
    hw = factories.hardware(name="cu-host-viewer")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "viewer-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cuid}", headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_compute_unit(client, viewer_headers, factories):
    hw = factories.hardware(name="cu-host-viewer-no")
    resp = await client.post(
        _BASE,
        headers=viewer_headers,
        json={"name": "viewer-no-vm", "kind": "vm", "hardware_id": hw.id},
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_compute_unit(client, viewer_headers, auth_headers, factories):
    hw = factories.hardware(name="cu-host-viewer-del")
    create_resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "viewer-del-vm", "kind": "vm", "hardware_id": hw.id},
    )
    cuid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cuid}", headers=viewer_headers)
    assert resp.status_code == 403
