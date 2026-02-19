"""
Minimal CRUD smoke tests for storage, networks, and misc entities.
Verifies: create one object per entity, assert it appears in list response.
"""


def test_create_and_list_storage(client):
    resp = client.post("/api/v1/storage", json={"name": "tank", "kind": "pool"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "tank"
    assert data["kind"] == "pool"
    assert data["id"] > 0

    resp = client.get("/api/v1/storage")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "tank"


def test_storage_tags(client):
    resp = client.post(
        "/api/v1/storage",
        json={"name": "nvme-pool", "kind": "pool", "tags": ["fast", "prod"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert set(data["tags"]) == {"fast", "prod"}

    resp = client.get("/api/v1/storage", params={"tag": "fast"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_and_list_networks(client):
    resp = client.post("/api/v1/networks", json={"name": "LAN", "cidr": "192.168.1.0/24", "vlan_id": 10})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "LAN"
    assert data["cidr"] == "192.168.1.0/24"
    assert data["vlan_id"] == 10
    assert data["id"] > 0

    resp = client.get("/api/v1/networks")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "LAN"


def test_networks_tags(client):
    resp = client.post(
        "/api/v1/networks",
        json={"name": "DMZ", "tags": ["dmz", "prod"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert set(data["tags"]) == {"dmz", "prod"}

    resp = client.get("/api/v1/networks", params={"tag": "dmz"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_networks_vlan_filter(client):
    client.post("/api/v1/networks", json={"name": "VLAN10", "vlan_id": 10})
    client.post("/api/v1/networks", json={"name": "VLAN20", "vlan_id": 20})

    resp = client.get("/api/v1/networks", params={"vlan_id": 10})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "VLAN10"


def test_create_and_list_misc(client):
    resp = client.post("/api/v1/misc", json={"name": "Vault", "kind": "secrets-manager"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Vault"
    assert data["kind"] == "secrets-manager"
    assert data["id"] > 0

    resp = client.get("/api/v1/misc")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "Vault"


def test_misc_tags(client):
    resp = client.post(
        "/api/v1/misc",
        json={"name": "Grafana", "kind": "monitoring", "tags": ["observability"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["observability"]
