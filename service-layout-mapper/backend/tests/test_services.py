import pytest


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
