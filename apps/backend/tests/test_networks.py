"""
Tests for the networks API.

Routes (networks.router mounted at /api/v1/networks):
  GET    /api/v1/networks           — list
  POST   /api/v1/networks           — create (201)
  GET    /api/v1/networks/{id}      — retrieve
  DELETE /api/v1/networks/{id}      — delete (204)
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
