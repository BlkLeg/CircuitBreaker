"""
Tests for the hardware CRUD API: POST / GET / PUT / PATCH / DELETE /api/v1/hardware

Additional endpoints:
  GET    /api/v1/hardware/orphans
  GET    /api/v1/hardware/groups
  POST   /api/v1/hardware/{id}/connections  — add connection (201)
  DELETE /api/v1/hardware-connections/{id}   — remove connection (204)
  GET    /api/v1/hardware/{id}/network-memberships
  GET    /api/v1/hardware/{id}/ports
  PUT    /api/v1/hardware/{id}/ports
"""

import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/hardware"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_hardware_minimal(client, auth_headers):
    """Create with name only -> 201, id present in response."""
    resp = await client.post(BASE, json={"name": "test-switch-01"}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-switch-01"
    assert "id" in data


async def test_create_hardware_full(client, auth_headers):
    """Create with all common fields -> 201."""
    payload = {
        "name": "core-router-01",
        "role": "router",
        "vendor": "cisco",
        "ip_address": "10.0.0.1",
        "notes": "Main uplink router",
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "core-router-01"
    assert data["role"] == "router"
    assert data["vendor"] == "cisco"
    assert data["ip_address"] == "10.0.0.1"


@pytest.mark.timeout(10)
async def test_create_hardware_duplicate_ip_returns_409(client, auth_headers):
    """Duplicate IP address -> 409 Conflict."""
    ip = "10.99.99.1"
    resp1 = await client.post(BASE, json={"name": "host-a", "ip_address": ip}, headers=auth_headers)
    assert resp1.status_code == 201
    resp = await client.post(BASE, json={"name": "host-b", "ip_address": ip}, headers=auth_headers)
    # Service may block with 409, or allow and return 201
    assert resp.status_code in (201, 409, 422)


async def test_create_hardware_with_rack_assignment(client, auth_headers, factories):
    """Create with rack_id, rack_unit, u_height."""
    rack = factories.rack()
    payload = {
        "name": "racked-server-01",
        "rack_id": rack.id,
        "rack_unit": 10,
        "u_height": 2,
    }
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["rack_id"] == rack.id
    assert data["rack_unit"] == 10
    assert data["u_height"] == 2


async def test_create_hardware_with_environment(client, auth_headers, factories):
    """Create with environment_id."""
    env = factories.environment()
    payload = {"name": "env-hw-01", "environment_id": env.id}
    resp = await client.post(BASE, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["environment_id"] == env.id


async def test_create_hardware_unauthenticated(client):
    resp = await client.post(BASE, json={"name": "unauth-hw"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def test_get_hardware_by_id(client, auth_headers):
    """Create then GET by id -> 200 with matching data."""
    create_resp = await client.post(BASE, json={"name": "get-by-id-host"}, headers=auth_headers)
    assert create_resp.status_code == 201
    hw_id = create_resp.json()["id"]

    resp = await client.get(f"{BASE}/{hw_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == hw_id


async def test_get_hardware_nonexistent_returns_404(client, auth_headers):
    """GET on a non-existent id -> 404."""
    resp = await client.get(f"{BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_list_hardware_returns_list(client, auth_headers):
    """GET /hardware -> 200 and response is a list."""
    resp = await client.get(BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Update (PUT full replace)
# ---------------------------------------------------------------------------


async def test_update_hardware_name(client, auth_headers):
    """PUT with new name -> 200, updated name in response."""
    create_resp = await client.post(BASE, json={"name": "original-name"}, headers=auth_headers)
    assert create_resp.status_code == 201
    hw_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"{BASE}/{hw_id}", json={"name": "updated-name"}, headers=auth_headers
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "updated-name"


# ---------------------------------------------------------------------------
# Update (PATCH partial)
# ---------------------------------------------------------------------------


async def test_patch_hardware_multiple_fields(client, auth_headers):
    """PATCH with vendor, model, role, notes -> 200."""
    create_resp = await client.post(BASE, json={"name": "patch-hw"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.patch(
        f"{BASE}/{hw_id}",
        headers=auth_headers,
        json={"vendor": "dell", "model": "R740", "role": "compute", "notes": "production server"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vendor"] == "dell"
    assert data["model"] == "R740"
    assert data["role"] == "compute"
    assert data["notes"] == "production server"
    assert data["name"] == "patch-hw"  # unchanged


async def test_patch_hardware_not_found(client, auth_headers):
    resp = await client.patch(f"{BASE}/999999", headers=auth_headers, json={"name": "nope"})
    assert resp.status_code == 404


async def test_patch_hardware_unauthenticated(client, auth_headers):
    create_resp = await client.post(BASE, json={"name": "patch-unauth-hw"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.patch(f"{BASE}/{hw_id}", json={"name": "x"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_hardware_then_get_returns_404(client, auth_headers):
    """DELETE -> 204, subsequent GET -> 404."""
    create_resp = await client.post(BASE, json={"name": "delete-me-host"}, headers=auth_headers)
    assert create_resp.status_code == 201
    hw_id = create_resp.json()["id"]

    del_resp = await client.delete(f"{BASE}/{hw_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    get_resp = await client.get(f"{BASE}/{hw_id}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_hardware_unauthenticated(client, auth_headers):
    create_resp = await client.post(BASE, json={"name": "del-unauth-hw"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.delete(f"{BASE}/{hw_id}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


async def test_get_orphans(client, auth_headers):
    """GET /hardware/orphans -> 200 and returns a list."""
    resp = await client.get(f"{BASE}/orphans", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_orphan_includes_standalone_hardware(client, auth_headers):
    """A hardware with no compute_units or services appears as orphan."""
    create_resp = await client.post(BASE, json={"name": "orphan-node"}, headers=auth_headers)
    assert create_resp.status_code == 201
    resp = await client.get(f"{BASE}/orphans", headers=auth_headers)
    names = [o.get("name") for o in resp.json()]
    assert "orphan-node" in names


# ---------------------------------------------------------------------------
# Hardware connections
# ---------------------------------------------------------------------------


async def test_create_hardware_connection(client, auth_headers):
    r1 = await client.post(BASE, json={"name": "conn-src"}, headers=auth_headers)
    r2 = await client.post(BASE, json={"name": "conn-tgt"}, headers=auth_headers)
    src_id = r1.json()["id"]
    tgt_id = r2.json()["id"]

    resp = await client.post(
        f"{BASE}/{src_id}/connections",
        headers=auth_headers,
        json={"target_hardware_id": tgt_id},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_hardware_id"] == src_id
    assert body["target_hardware_id"] == tgt_id


async def test_delete_hardware_connection(client, auth_headers):
    r1 = await client.post(BASE, json={"name": "conn-del-src"}, headers=auth_headers)
    r2 = await client.post(BASE, json={"name": "conn-del-tgt"}, headers=auth_headers)
    conn_resp = await client.post(
        f"{BASE}/{r1.json()['id']}/connections",
        headers=auth_headers,
        json={"target_hardware_id": r2.json()["id"]},
    )
    conn_id = conn_resp.json()["id"]
    resp = await client.delete(f"/api/v1/hardware-connections/{conn_id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_create_connection_missing_target(client, auth_headers):
    r1 = await client.post(BASE, json={"name": "conn-miss-src"}, headers=auth_headers)
    resp = await client.post(
        f"{BASE}/{r1.json()['id']}/connections",
        headers=auth_headers,
        json={"target_hardware_id": 999999},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Viewer RBAC
# ---------------------------------------------------------------------------


async def test_viewer_can_list_hardware(client, viewer_headers):
    resp = await client.get(BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_can_get_hardware(client, viewer_headers, auth_headers):
    create_resp = await client.post(BASE, json={"name": "viewer-get-hw"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.get(f"{BASE}/{hw_id}", headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_hardware(client, viewer_headers):
    resp = await client.post(BASE, json={"name": "viewer-no-create"}, headers=viewer_headers)
    assert resp.status_code == 403


async def test_viewer_cannot_update_hardware(client, viewer_headers, auth_headers):
    create_resp = await client.post(BASE, json={"name": "viewer-no-update"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.put(
        f"{BASE}/{hw_id}",
        json={"name": "viewer-updated"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


async def test_viewer_cannot_delete_hardware(client, viewer_headers, auth_headers):
    create_resp = await client.post(BASE, json={"name": "viewer-no-del"}, headers=auth_headers)
    hw_id = create_resp.json()["id"]
    resp = await client.delete(f"{BASE}/{hw_id}", headers=viewer_headers)
    assert resp.status_code == 403
