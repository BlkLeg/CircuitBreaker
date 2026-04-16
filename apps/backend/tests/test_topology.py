"""
Tests for topology management endpoints:
  GET  /api/v1/topologies
  POST /api/v1/topologies
  PUT  /api/v1/topologies/{id}/nodes
"""

import pytest
from sqlalchemy import select

from app.db.models import TopologyNode

TOPOLOGIES_URL = "/api/v1/topologies"


@pytest.mark.asyncio
async def test_list_topologies_empty(client, auth_headers):
    """GET /topologies → 200 with an empty list when no topologies exist."""
    resp = await client.get(TOPOLOGIES_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_topology(client, auth_headers):
    """POST /topologies → 201 with id and name."""
    resp = await client.post(TOPOLOGIES_URL, json={"name": "home-lab"}, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "home-lab"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_topologies_returns_created(client, auth_headers):
    """After creation, GET /topologies includes the new topology."""
    await client.post(TOPOLOGIES_URL, json={"name": "visible-topo"}, headers=auth_headers)
    resp = await client.get(TOPOLOGIES_URL, headers=auth_headers)
    names = [t["name"] for t in resp.json()]
    assert "visible-topo" in names


@pytest.mark.asyncio
async def test_assign_nodes_creates_topology_node_rows(client, auth_headers, db_session, factories):
    """PUT nodes writes TopologyNode rows for each provided entity."""
    hw = factories.hardware(name="topo-hw", ip_address="10.9.9.1")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "assign-test"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]

    payload = {"nodes": [{"entity_type": "hardware", "entity_id": hw.id, "x": 100, "y": 200}]}
    resp = await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["node_count"] == 1

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1
    assert nodes[0].entity_type == "hardware"
    assert nodes[0].entity_id == hw.id


@pytest.mark.asyncio
async def test_assign_nodes_idempotent(client, auth_headers, db_session, factories):
    """Replacing nodes with same entity twice keeps a single TopologyNode row."""
    hw = factories.hardware(name="idem-hw", ip_address="10.9.9.2")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "idem-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"nodes": [{"entity_type": "hardware", "entity_id": hw.id, "x": 1, "y": 2}]}

    await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_assign_nodes_invalid_entity_type_skipped(client, auth_headers):
    """Unknown entity types are accepted as opaque topology node references."""
    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "skip-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"nodes": [{"entity_type": "unicorn", "entity_id": 1, "x": 0, "y": 0}]}

    resp = await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["node_count"] == 1


@pytest.mark.asyncio
async def test_assign_nodes_to_missing_topology(client, auth_headers):
    """Updating nodes on a non-existent topology returns 404."""
    resp = await client.put(
        f"{TOPOLOGIES_URL}/99999/nodes",
        json={"nodes": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_save_layout_rejects_invalid_json(client, auth_headers):
    """POST /graph/layout returns 422 when layout_data is not valid JSON."""
    resp = await client.post(
        "/api/v1/graph/layout",
        json={"name": "default", "layout_data": "not-json{{{", "map_id": None},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_layout_rejects_non_object_json(client, auth_headers):
    """POST /graph/layout returns 422 when layout_data is not a JSON object."""
    resp = await client.post(
        "/api/v1/graph/layout",
        json={"name": "default", "layout_data": "[1,2,3]", "map_id": None},
        headers=auth_headers,
    )
    assert resp.status_code == 422
