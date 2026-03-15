"""
Tests for the external-nodes API.

Routes (external_nodes.router mounted at /api/v1/external-nodes):
  GET    /api/v1/external-nodes                    — list
  POST   /api/v1/external-nodes                    — create (201)
  GET    /api/v1/external-nodes/{id}               — get
  PATCH  /api/v1/external-nodes/{id}               — update
  DELETE /api/v1/external-nodes/{id}               — delete (204)
  GET    /api/v1/external-nodes/{id}/networks      — list network links
  POST   /api/v1/external-nodes/{id}/networks      — link network (201)
  GET    /api/v1/external-nodes/{id}/services      — list service links
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/external-nodes"


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_list_external_nodes(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_external_node(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "aws-rds-01", "provider": "AWS", "kind": "rds"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "aws-rds-01"
    assert body["provider"] == "AWS"
    assert body["kind"] == "rds"
    assert "id" in body


async def test_create_external_node_with_tags(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={
            "name": "gcp-vm-01",
            "provider": "GCP",
            "kind": "vps",
            "tags": ["production", "us-east"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "production" in body.get("tags", [])


async def test_create_external_node_minimal(client, auth_headers):
    resp = await client.post(_BASE, headers=auth_headers, json={"name": "minimal-ext"})
    assert resp.status_code == 201


async def test_get_external_node(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "get-ext-node"})
    nid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{nid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == nid


async def test_get_external_node_not_found(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_external_node(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "upd-ext-node"})
    nid = create_resp.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{nid}",
        headers=auth_headers,
        json={"name": "upd-ext-node-v2", "region": "us-west-2"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "upd-ext-node-v2"
    assert resp.json()["region"] == "us-west-2"


async def test_update_external_node_not_found(client, auth_headers):
    resp = await client.patch(f"{_BASE}/999999", headers=auth_headers, json={"name": "nope"})
    assert resp.status_code == 404


async def test_delete_external_node(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "del-ext-node"})
    nid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{nid}", headers=auth_headers)
    assert resp.status_code == 204
    # Verify gone
    get_resp = await client.get(f"{_BASE}/{nid}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_external_node_unauthenticated(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "del-unauth-ext"})
    nid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{nid}")
    assert resp.status_code in (401, 403)


# ── Network links ─────────────────────────────────────────────────────────────


async def test_link_network(client, auth_headers, factories):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "net-link-ext"})
    nid = create_resp.json()["id"]
    net = factories.network(name="ext-net-link", cidr="10.90.0.0/24")
    resp = await client.post(
        f"{_BASE}/{nid}/networks",
        headers=auth_headers,
        json={"network_id": net.id, "link_type": "vpn"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["external_node_id"] == nid
    assert body["network_id"] == net.id


async def test_list_network_links(client, auth_headers, factories):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "net-list-ext"})
    nid = create_resp.json()["id"]
    net = factories.network(name="ext-net-list", cidr="10.91.0.0/24")
    await client.post(
        f"{_BASE}/{nid}/networks",
        headers=auth_headers,
        json={"network_id": net.id},
    )
    resp = await client.get(f"{_BASE}/{nid}/networks", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# ── Service links ─────────────────────────────────────────────────────────────


async def test_list_service_links(client, auth_headers, factories):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "svc-list-ext"})
    nid = create_resp.json()["id"]
    svc = factories.service(name="ext-svc-link")
    # Link via the services API
    await client.post(
        f"/api/v1/services/{svc.id}/external-dependencies",
        headers=auth_headers,
        json={"external_node_id": nid, "purpose": "database"},
    )
    resp = await client.get(f"{_BASE}/{nid}/services", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
