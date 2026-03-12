import json

import pytest


@pytest.fixture(autouse=True)
def _authenticated_client(client, auth_headers):
    client.headers.update(auth_headers)


@pytest.fixture
def hardware_id(client):
    resp = client.post("/api/v1/hardware", json={"name": "Node-1"})
    return resp.json()["id"]


@pytest.fixture
def compute_id(client, hardware_id):
    resp = client.post(
        "/api/v1/compute-units",
        json={"name": "vm-1", "kind": "vm", "hardware_id": hardware_id},
    )
    return resp.json()["id"]


def test_create_and_list_services(client, compute_id):
    resp = client.post(
        "/api/v1/services",
        json={"name": "Plex", "slug": "plex", "compute_id": compute_id, "category": "media"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Plex"
    assert data["slug"] == "plex"
    assert data["id"] > 0

    resp = client.get("/api/v1/services")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_service_not_found(client):
    resp = client.get("/api/v1/services/9999")
    assert resp.status_code == 404


def test_service_dependency(client, compute_id):
    s1 = client.post(
        "/api/v1/services",
        json={"name": "Svc-A", "slug": "svc-a", "compute_id": compute_id},
    ).json()
    s2 = client.post(
        "/api/v1/services",
        json={"name": "Svc-B", "slug": "svc-b", "compute_id": compute_id},
    ).json()

    resp = client.post(
        f"/api/v1/services/{s2['id']}/dependencies",
        json={"depends_on_id": s1["id"]},
    )
    assert resp.status_code == 201
    dep = resp.json()
    assert dep["depends_on_id"] == s1["id"]

    resp = client.get(f"/api/v1/services/{s2['id']}/dependencies")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.delete(f"/api/v1/services/{s2['id']}/dependencies/{s1['id']}")
    assert resp.status_code == 204


def test_graph_topology(client, compute_id):
    client.post(
        "/api/v1/services",
        json={"name": "Plex", "slug": "plex", "compute_id": compute_id},
    )
    resp = client.get("/api/v1/graph/topology")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    node_ids = {n["id"] for n in data["nodes"]}
    assert any(nid.startswith("hw-") for nid in node_ids)
    assert any(nid.startswith("cu-") for nid in node_ids)
    assert any(nid.startswith("svc-") for nid in node_ids)


def test_graph_layout_scoped_name_roundtrip(client):
    scoped_name = "default::env:prod"
    payload = {"nodes": {"cluster-1": {"x": 120, "y": 80}}, "edges": {}}

    save = client.post(
        "/api/v1/graph/layout",
        json={"name": scoped_name, "layout_data": json.dumps(payload)},
    )
    assert save.status_code == 200

    res = client.get("/api/v1/graph/layout", params={"name": scoped_name})
    assert res.status_code == 200
    assert res.json()["layout_data"] is not None


def test_graph_layout_default_fallback_absent_scoped(client):
    default_payload = {"nodes": {"hw-1": {"x": 10, "y": 20}}, "edges": {}}
    save = client.post(
        "/api/v1/graph/layout",
        json={"name": "default", "layout_data": json.dumps(default_payload)},
    )
    assert save.status_code == 200

    scoped = client.get("/api/v1/graph/layout", params={"name": "default::env:dev"})
    assert scoped.status_code == 200
    assert scoped.json()["layout_data"] is None

    default = client.get("/api/v1/graph/layout", params={"name": "default"})
    assert default.status_code == 200
    assert default.json()["layout_data"] is not None


def test_graph_topology_filters_clusters_by_environment(client):
    hw_prod = client.post("/api/v1/hardware", json={"name": "PVE-Prod"}).json()
    hw_dev = client.post("/api/v1/hardware", json={"name": "PVE-Dev"}).json()

    cluster_prod = client.post(
        "/api/v1/hardware-clusters",
        json={"name": "Prod Cluster", "environment": "prod"},
    ).json()
    cluster_dev = client.post(
        "/api/v1/hardware-clusters",
        json={"name": "Dev Cluster", "environment": "dev"},
    ).json()

    add_prod = client.post(
        f"/api/v1/hardware-clusters/{cluster_prod['id']}/members",
        json={"hardware_id": hw_prod["id"]},
    )
    add_dev = client.post(
        f"/api/v1/hardware-clusters/{cluster_dev['id']}/members",
        json={"hardware_id": hw_dev["id"]},
    )
    assert add_prod.status_code == 201
    assert add_dev.status_code == 201

    topo_prod = client.get("/api/v1/graph/topology", params={"environment": "prod"})
    assert topo_prod.status_code == 200
    prod_cluster_labels = {
        n["label"] for n in topo_prod.json()["nodes"] if n.get("type") == "cluster"
    }
    assert "Prod Cluster" in prod_cluster_labels
    assert "Dev Cluster" not in prod_cluster_labels
