"""
Tests for topology management endpoints:
  GET  /api/v1/graph/topologies
  POST /api/v1/graph/topologies
  POST /api/v1/graph/topologies/{id}/assign-nodes
"""

import pytest
from sqlalchemy import select

from app.db.models import TopologyNode

TOPOLOGIES_URL = "/api/v1/graph/topologies"


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
    """POST assign-nodes upserts TopologyNode rows for each valid entity."""
    hw = factories.hardware(name="topo-hw", ip_address="10.9.9.1")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "assign-test"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]

    payload = {"entities": [{"entity_type": "hardware", "entity_id": hw.id}]}
    resp = await client.post(
        f"{TOPOLOGIES_URL}/{topo_id}/assign-nodes", json=payload, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["assigned"] == 1

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1
    assert nodes[0].entity_type == "hardware"
    assert nodes[0].entity_id == hw.id


@pytest.mark.asyncio
async def test_assign_nodes_idempotent(client, auth_headers, db_session, factories):
    """Assigning the same entity twice does not create duplicate TopologyNode rows."""
    hw = factories.hardware(name="idem-hw", ip_address="10.9.9.2")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "idem-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"entities": [{"entity_type": "hardware", "entity_id": hw.id}]}

    await client.post(
        f"{TOPOLOGIES_URL}/{topo_id}/assign-nodes", json=payload, headers=auth_headers
    )
    await client.post(
        f"{TOPOLOGIES_URL}/{topo_id}/assign-nodes", json=payload, headers=auth_headers
    )

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_assign_nodes_invalid_entity_type_skipped(client, auth_headers):
    """Entities with unknown entity_type are silently skipped."""
    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "skip-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"entities": [{"entity_type": "unicorn", "entity_id": 1}]}

    resp = await client.post(
        f"{TOPOLOGIES_URL}/{topo_id}/assign-nodes", json=payload, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["assigned"] == 0


@pytest.mark.asyncio
async def test_assign_nodes_to_missing_topology(client, auth_headers):
    """Assigning to a non-existent topology returns 404."""
    resp = await client.post(
        f"{TOPOLOGIES_URL}/99999/assign-nodes",
        json={"entities": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404
