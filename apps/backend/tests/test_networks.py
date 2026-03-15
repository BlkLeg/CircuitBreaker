"""
Tests for the networks API.

Routes (networks.router mounted at /api/v1/networks):
  GET    /api/v1/networks                                — list
  POST   /api/v1/networks                                — create (201)
  GET    /api/v1/networks/{id}                           — retrieve
  PATCH  /api/v1/networks/{id}                           — update
  DELETE /api/v1/networks/{id}                           — delete (204)
  GET    /api/v1/networks/{id}/hardware-members          — list hw members
  POST   /api/v1/networks/{id}/hardware-members          — add hw member (201)
  DELETE /api/v1/networks/{id}/hardware-members/{hw_id}  — remove hw member (204)
  GET    /api/v1/networks/{id}/members                   — list compute members
  POST   /api/v1/networks/{id}/members                   — add compute member (201)
  DELETE /api/v1/networks/{id}/members/{cu_id}           — remove compute member (204)
  GET    /api/v1/networks/{id}/peers                     — list peers
  POST   /api/v1/networks/{id}/peers                     — add peer (201)
  DELETE /api/v1/networks/{id}/peers/{peer_id}           — remove peer (204)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/networks"


# ── Create ────────────────────────────────────────────────────────────────────


async def test_create_network_returns_201(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "test-net-create", "cidr": "192.168.10.0/24"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "test-net-create"
    assert body["cidr"] == "192.168.10.0/24"
    assert "id" in body


async def test_create_network_invalid_cidr_returns_422(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "bad-cidr-net", "cidr": "not-a-cidr"},
    )
    assert resp.status_code == 422


async def test_create_network_unauthenticated_rejected(client):
    resp = await client.post(
        _BASE,
        json={"name": "unauth-net", "cidr": "10.1.0.0/24"},
    )
    assert resp.status_code == 401


# ── Read ──────────────────────────────────────────────────────────────────────


async def test_get_network_by_id(client, auth_headers, factories):
    net = factories.network(name="get-by-id-net", cidr="10.20.0.0/24")
    resp = await client.get(f"{_BASE}/{net.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == net.id
    assert resp.json()["name"] == "get-by-id-net"


async def test_get_network_not_found(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_list_networks_returns_200(client, auth_headers, factories):
    factories.network(name="list-net-a", cidr="10.30.0.0/24")
    factories.network(name="list-net-b", cidr="10.31.0.0/24")
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Update (PATCH) ────────────────────────────────────────────────────────────


async def test_patch_network_name(client, auth_headers, factories):
    net = factories.network(name="patch-net-orig", cidr="10.50.0.0/24")
    resp = await client.patch(
        f"{_BASE}/{net.id}",
        headers=auth_headers,
        json={"name": "patch-net-updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "patch-net-updated"


async def test_patch_network_cidr(client, auth_headers, factories):
    net = factories.network(name="patch-cidr-net", cidr="10.51.0.0/24")
    resp = await client.patch(
        f"{_BASE}/{net.id}",
        headers=auth_headers,
        json={"cidr": "10.52.0.0/24"},
    )
    assert resp.status_code == 200
    assert resp.json()["cidr"] == "10.52.0.0/24"
    assert resp.json()["name"] == "patch-cidr-net"  # unchanged


async def test_patch_network_partial_fields(client, auth_headers, factories):
    net = factories.network(name="patch-partial-net", cidr="10.53.0.0/24")
    resp = await client.patch(
        f"{_BASE}/{net.id}",
        headers=auth_headers,
        json={"vlan_id": 100, "description": "updated desc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vlan_id"] == 100
    assert body["description"] == "updated desc"


async def test_patch_network_not_found(client, auth_headers):
    resp = await client.patch(f"{_BASE}/999999", headers=auth_headers, json={"name": "nope"})
    assert resp.status_code == 404


async def test_patch_network_unauthenticated(client, factories):
    net = factories.network(name="patch-unauth-net", cidr="10.54.0.0/24")
    resp = await client.patch(f"{_BASE}/{net.id}", json={"name": "x"})
    assert resp.status_code == 401


# ── Delete ────────────────────────────────────────────────────────────────────


async def test_delete_network_returns_204(client, auth_headers, factories):
    net = factories.network(name="delete-me-net", cidr="10.40.0.0/24")
    resp = await client.delete(f"{_BASE}/{net.id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_deleted_network_no_longer_found(client, auth_headers, factories):
    net = factories.network(name="gone-net", cidr="10.41.0.0/24")
    await client.delete(f"{_BASE}/{net.id}", headers=auth_headers)
    resp = await client.get(f"{_BASE}/{net.id}", headers=auth_headers)
    assert resp.status_code == 404


# ── Hardware members ──────────────────────────────────────────────────────────


async def test_add_hardware_member(client, auth_headers, factories):
    net = factories.network(name="hw-mem-net", cidr="10.60.0.0/24")
    hw = factories.hardware(name="hw-mem-node")
    resp = await client.post(
        f"{_BASE}/{net.id}/hardware-members",
        headers=auth_headers,
        json={"hardware_id": hw.id, "ip_address": "10.60.0.10"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert body["network_id"] == net.id


async def test_list_hardware_members(client, auth_headers, factories):
    net = factories.network(name="hw-list-net", cidr="10.61.0.0/24")
    hw = factories.hardware(name="hw-list-node")
    await client.post(
        f"{_BASE}/{net.id}/hardware-members",
        headers=auth_headers,
        json={"hardware_id": hw.id},
    )
    resp = await client.get(f"{_BASE}/{net.id}/hardware-members", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_remove_hardware_member(client, auth_headers, factories):
    net = factories.network(name="hw-rm-net", cidr="10.62.0.0/24")
    hw = factories.hardware(name="hw-rm-node")
    await client.post(
        f"{_BASE}/{net.id}/hardware-members",
        headers=auth_headers,
        json={"hardware_id": hw.id},
    )
    resp = await client.delete(
        f"{_BASE}/{net.id}/hardware-members/{hw.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


# ── Compute members ──────────────────────────────────────────────────────────


async def test_add_compute_member(client, auth_headers, factories):
    net = factories.network(name="cu-mem-net", cidr="10.70.0.0/24")
    cu = factories.compute_unit()
    resp = await client.post(
        f"{_BASE}/{net.id}/members",
        headers=auth_headers,
        json={"compute_id": cu.id, "ip_address": "10.70.0.10"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["compute_id"] == cu.id
    assert body["network_id"] == net.id


async def test_list_compute_members(client, auth_headers, factories):
    net = factories.network(name="cu-list-net", cidr="10.71.0.0/24")
    cu = factories.compute_unit()
    await client.post(
        f"{_BASE}/{net.id}/members",
        headers=auth_headers,
        json={"compute_id": cu.id},
    )
    resp = await client.get(f"{_BASE}/{net.id}/members", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_remove_compute_member(client, auth_headers, factories):
    net = factories.network(name="cu-rm-net", cidr="10.72.0.0/24")
    cu = factories.compute_unit()
    await client.post(
        f"{_BASE}/{net.id}/members",
        headers=auth_headers,
        json={"compute_id": cu.id},
    )
    resp = await client.delete(
        f"{_BASE}/{net.id}/members/{cu.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


# ── Network peers ─────────────────────────────────────────────────────────────


async def test_add_peer(client, auth_headers, factories):
    net_a = factories.network(name="peer-a", cidr="10.80.0.0/24")
    net_b = factories.network(name="peer-b", cidr="10.81.0.0/24")
    resp = await client.post(
        f"{_BASE}/{net_a.id}/peers",
        headers=auth_headers,
        json={"peer_network_id": net_b.id},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["network_a_id"] in (net_a.id, net_b.id)
    assert body["network_b_id"] in (net_a.id, net_b.id)


async def test_list_peers(client, auth_headers, factories):
    net_a = factories.network(name="peer-list-a", cidr="10.82.0.0/24")
    net_b = factories.network(name="peer-list-b", cidr="10.83.0.0/24")
    await client.post(
        f"{_BASE}/{net_a.id}/peers",
        headers=auth_headers,
        json={"peer_network_id": net_b.id},
    )
    resp = await client.get(f"{_BASE}/{net_a.id}/peers", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_remove_peer(client, auth_headers, factories):
    net_a = factories.network(name="peer-rm-a", cidr="10.84.0.0/24")
    net_b = factories.network(name="peer-rm-b", cidr="10.85.0.0/24")
    await client.post(
        f"{_BASE}/{net_a.id}/peers",
        headers=auth_headers,
        json={"peer_network_id": net_b.id},
    )
    resp = await client.delete(
        f"{_BASE}/{net_a.id}/peers/{net_b.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204


async def test_self_peer_error(client, auth_headers, factories):
    net = factories.network(name="self-peer-net", cidr="10.86.0.0/24")
    resp = await client.post(
        f"{_BASE}/{net.id}/peers",
        headers=auth_headers,
        json={"peer_network_id": net.id},
    )
    assert resp.status_code == 422
