"""
Tests for the hardware-clusters API.

Routes (clusters.router mounted at /api/v1/hardware-clusters):
  GET    /api/v1/hardware-clusters                         — list
  POST   /api/v1/hardware-clusters                         — create (201)
  GET    /api/v1/hardware-clusters/{id}                    — get
  PATCH  /api/v1/hardware-clusters/{id}                    — update
  DELETE /api/v1/hardware-clusters/{id}                    — delete (204)
  GET    /api/v1/hardware-clusters/{id}/members            — list members
  POST   /api/v1/hardware-clusters/{id}/members            — add member (201)
  PATCH  /api/v1/hardware-clusters/{id}/members/{mid}      — update member role
  DELETE /api/v1/hardware-clusters/{id}/members/{mid}      — remove member (204)
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/hardware-clusters"


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_list_clusters_empty(client, auth_headers):
    resp = await client.get(_BASE, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_cluster(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "test-cluster"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "test-cluster"
    assert "id" in body


async def test_create_cluster_with_description(client, auth_headers):
    resp = await client.post(
        _BASE,
        headers=auth_headers,
        json={"name": "desc-cluster", "description": "HA cluster", "environment": "prod"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["description"] == "HA cluster"
    assert body["environment"] == "prod"


async def test_get_cluster_by_id(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "get-cluster"})
    cid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == cid


async def test_get_cluster_not_found(client, auth_headers):
    resp = await client.get(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_cluster(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "update-cluster"})
    cid = create_resp.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{cid}",
        headers=auth_headers,
        json={"name": "updated-cluster", "description": "changed"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated-cluster"
    assert resp.json()["description"] == "changed"


async def test_delete_cluster(client, auth_headers):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "del-cluster"})
    cid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cid}", headers=auth_headers)
    assert resp.status_code == 204
    # Verify gone
    get_resp = await client.get(f"{_BASE}/{cid}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_cluster_not_found(client, auth_headers):
    resp = await client.delete(f"{_BASE}/999999", headers=auth_headers)
    assert resp.status_code == 404


# ── Members ───────────────────────────────────────────────────────────────────


async def test_list_members_empty(client, auth_headers):
    create_resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "empty-members-cluster"}
    )
    cid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cid}/members", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_add_member(client, auth_headers, factories):
    create_resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "add-member-cluster"}
    )
    cid = create_resp.json()["id"]
    hw = factories.hardware(name="cluster-member-hw")
    resp = await client.post(
        f"{_BASE}/{cid}/members",
        headers=auth_headers,
        json={"hardware_id": hw.id, "role": "worker"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["hardware_id"] == hw.id
    assert body["role"] == "worker"


async def test_update_member_role(client, auth_headers, factories):
    create_resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "upd-member-cluster"}
    )
    cid = create_resp.json()["id"]
    hw = factories.hardware(name="upd-member-hw")
    add_resp = await client.post(
        f"{_BASE}/{cid}/members",
        headers=auth_headers,
        json={"hardware_id": hw.id, "role": "worker"},
    )
    mid = add_resp.json()["id"]
    resp = await client.patch(
        f"{_BASE}/{cid}/members/{mid}",
        headers=auth_headers,
        json={"role": "controller"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "controller"


async def test_remove_member(client, auth_headers, factories):
    create_resp = await client.post(_BASE, headers=auth_headers, json={"name": "rm-member-cluster"})
    cid = create_resp.json()["id"]
    hw = factories.hardware(name="rm-member-hw")
    add_resp = await client.post(
        f"{_BASE}/{cid}/members",
        headers=auth_headers,
        json={"hardware_id": hw.id},
    )
    mid = add_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cid}/members/{mid}", headers=auth_headers)
    assert resp.status_code == 204


# ── Viewer RBAC ───────────────────────────────────────────────────────────────


async def test_viewer_can_list_clusters(client, viewer_headers):
    resp = await client.get(_BASE, headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_can_get_cluster(client, viewer_headers, auth_headers):
    create_resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "viewer-get-cluster"}
    )
    cid = create_resp.json()["id"]
    resp = await client.get(f"{_BASE}/{cid}", headers=viewer_headers)
    assert resp.status_code == 200


async def test_viewer_cannot_create_cluster(client, viewer_headers):
    resp = await client.post(_BASE, headers=viewer_headers, json={"name": "viewer-no-create"})
    assert resp.status_code == 403


async def test_viewer_cannot_delete_cluster(client, viewer_headers, auth_headers):
    create_resp = await client.post(
        _BASE, headers=auth_headers, json={"name": "viewer-no-del-cluster"}
    )
    cid = create_resp.json()["id"]
    resp = await client.delete(f"{_BASE}/{cid}", headers=viewer_headers)
    assert resp.status_code == 403
