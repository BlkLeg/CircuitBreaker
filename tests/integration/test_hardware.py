import pytest


@pytest.fixture(autouse=True)
def _authenticated_client(client, auth_headers):
    client.headers.update(auth_headers)


def test_create_and_list_hardware(client):
    resp = client.post("/api/v1/hardware", json={"name": "Node-1", "role": "hypervisor"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Node-1"
    assert data["role"] == "hypervisor"
    assert data["id"] > 0
    assert "created_at" in data

    resp = client.get("/api/v1/hardware")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "Node-1"


def test_get_hardware_not_found(client):
    resp = client.get("/api/v1/hardware/9999")
    assert resp.status_code == 404


def test_patch_hardware(client):
    resp = client.post("/api/v1/hardware", json={"name": "Node-1"})
    assert resp.status_code == 201
    hw_id = resp.json()["id"]

    resp = client.patch(f"/api/v1/hardware/{hw_id}", json={"role": "nas", "memory_gb": 32})
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "nas"
    assert data["memory_gb"] == 32


def test_delete_hardware(client):
    resp = client.post("/api/v1/hardware", json={"name": "Node-1"})
    hw_id = resp.json()["id"]

    resp = client.delete(f"/api/v1/hardware/{hw_id}")
    assert resp.status_code == 204

    resp = client.get(f"/api/v1/hardware/{hw_id}")
    assert resp.status_code == 404


def test_filter_hardware_by_role(client):
    client.post("/api/v1/hardware", json={"name": "Router", "role": "router"})
    client.post("/api/v1/hardware", json={"name": "Compute", "role": "hypervisor"})

    resp = client.get("/api/v1/hardware", params={"role": "router"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "Router"


def test_hardware_tags(client):
    resp = client.post(
        "/api/v1/hardware",
        json={"name": "Node-1", "tags": ["prod", "hypervisor"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert set(data["tags"]) == {"prod", "hypervisor"}
