"""Tests for Explicit Topologies API (v0.2.0).

These tests run against a PostgreSQL database via the ``client`` / ``db``
fixtures from conftest.py.  JSONB columns require a real PostgreSQL instance.
"""

import pytest


def test_create_topology(client):
    """POST /api/v1/topologies creates a topology and returns 201."""
    resp = client.post("/api/v1/topologies", json={"name": "My Lab"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Lab"
    assert "id" in data


def test_list_topologies(client):
    """GET /api/v1/topologies returns a list."""
    client.post("/api/v1/topologies", json={"name": "Topology A"})
    client.post("/api/v1/topologies", json={"name": "Topology B"})
    resp = client.get("/api/v1/topologies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 2


def test_get_topology_detail(client):
    """GET /api/v1/topologies/{id} returns detail with nodes and edges."""
    create = client.post("/api/v1/topologies", json={"name": "Detail Test"})
    topology_id = create.json()["id"]
    resp = client.get(f"/api/v1/topologies/{topology_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Detail Test"
    assert "nodes" in body
    assert "edges" in body


def test_update_topology(client):
    """PUT /api/v1/topologies/{id} updates the name."""
    create = client.post("/api/v1/topologies", json={"name": "Old Name"})
    topology_id = create.json()["id"]
    resp = client.put(f"/api/v1/topologies/{topology_id}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_delete_topology(client):
    """DELETE /api/v1/topologies/{id} removes the topology (204)."""
    create = client.post("/api/v1/topologies", json={"name": "To Delete"})
    topology_id = create.json()["id"]
    resp = client.delete(f"/api/v1/topologies/{topology_id}")
    assert resp.status_code == 204
    # Verify gone
    get = client.get(f"/api/v1/topologies/{topology_id}")
    assert get.status_code == 404


def test_topology_not_found(client):
    """GET /api/v1/topologies/99999 returns 404."""
    resp = client.get("/api/v1/topologies/99999")
    assert resp.status_code == 404


def test_bulk_update_nodes(client):
    """PUT /api/v1/topologies/{id}/nodes replaces all node positions."""
    create = client.post("/api/v1/topologies", json={"name": "Node Test"})
    topology_id = create.json()["id"]

    nodes = [
        {"entity_type": "hardware", "entity_id": 1, "x": 100.0, "y": 200.0},
        {"entity_type": "hardware", "entity_id": 2, "x": 300.0, "y": 400.0},
        {"entity_type": "service", "entity_id": 5, "x": 500.0, "y": 50.0},
    ]
    resp = client.put(f"/api/v1/topologies/{topology_id}/nodes", json={"nodes": nodes})
    assert resp.status_code == 200
    assert resp.json()["node_count"] == 3

    # Verify nodes are stored
    detail = client.get(f"/api/v1/topologies/{topology_id}")
    assert len(detail.json()["nodes"]) == 3


def test_cytoscape_export(client):
    """GET /api/v1/topologies/{id}/graph returns Cytoscape format."""
    create = client.post("/api/v1/topologies", json={"name": "Cytoscape Test"})
    topology_id = create.json()["id"]

    client.put(
        f"/api/v1/topologies/{topology_id}/nodes",
        json={
            "nodes": [
                {"entity_type": "hardware", "entity_id": 10, "x": 0.0, "y": 0.0},
            ]
        },
    )

    resp = client.get(f"/api/v1/topologies/{topology_id}/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert "elements" in body
    assert "topology" in body
    # All node elements have group=nodes
    node_elements = [e for e in body["elements"] if e["group"] == "nodes"]
    assert len(node_elements) == 1
    assert node_elements[0]["data"]["entity_type"] == "hardware"
