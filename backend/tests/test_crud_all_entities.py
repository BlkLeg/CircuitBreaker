"""
Comprehensive CRUD tests for all entity types.

Covers:
- Full lifecycle (create → read → update → delete) for hardware, compute, services,
  storage, networks, and misc.
- 404 responses for get/delete of nonexistent IDs.
- Service-specific field persistence (ip_address, status).
"""

API = "/api/v1"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_hardware(client, name="TestServer", **overrides):
    payload = {"name": name, "role": "server", **overrides}
    return client.post(f"{API}/hardware", json=payload)


def _create_compute(client, hardware_id, name="TestVM", **overrides):
    payload = {"name": name, "kind": "vm", "hardware_id": hardware_id, **overrides}
    return client.post(f"{API}/compute-units", json=payload)


def _create_service(client, name="TestSvc", slug="test-svc", **overrides):
    payload = {"name": name, "slug": slug, **overrides}
    return client.post(f"{API}/services", json=payload)


def _create_storage(client, name="TestPool", **overrides):
    payload = {"name": name, "kind": "pool", **overrides}
    return client.post(f"{API}/storage", json=payload)


def _create_network(client, name="TestLAN", **overrides):
    payload = {"name": name, **overrides}
    return client.post(f"{API}/networks", json=payload)


def _create_misc(client, name="TestMisc", **overrides):
    payload = {"name": name, "kind": "tool", **overrides}
    return client.post(f"{API}/misc", json=payload)


# ═══════════════════════════════════════════════════════════════════════════
# Hardware CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestHardwareCRUD:
    def test_create(self, client):
        resp = _create_hardware(client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "TestServer"
        assert data["role"] == "server"
        assert data["id"] > 0

    def test_read(self, client):
        hw_id = _create_hardware(client).json()["id"]
        resp = client.get(f"{API}/hardware/{hw_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestServer"

    def test_update(self, client):
        hw_id = _create_hardware(client).json()["id"]
        resp = client.patch(f"{API}/hardware/{hw_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        hw_id = _create_hardware(client).json()["id"]
        resp = client.delete(f"{API}/hardware/{hw_id}")
        assert resp.status_code == 204
        # Confirm gone
        resp = client.get(f"{API}/hardware/{hw_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/hardware/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/hardware/99999")
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════
# Compute Units CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeUnitsCRUD:
    def test_create(self, client):
        hw_id = _create_hardware(client).json()["id"]
        resp = _create_compute(client, hw_id)
        assert resp.status_code == 201
        assert resp.json()["name"] == "TestVM"

    def test_read(self, client):
        hw_id = _create_hardware(client).json()["id"]
        cu_id = _create_compute(client, hw_id).json()["id"]
        resp = client.get(f"{API}/compute-units/{cu_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestVM"

    def test_update(self, client):
        hw_id = _create_hardware(client).json()["id"]
        cu_id = _create_compute(client, hw_id).json()["id"]
        resp = client.patch(f"{API}/compute-units/{cu_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        hw_id = _create_hardware(client).json()["id"]
        cu_id = _create_compute(client, hw_id).json()["id"]
        resp = client.delete(f"{API}/compute-units/{cu_id}")
        assert resp.status_code == 204
        resp = client.get(f"{API}/compute-units/{cu_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/compute-units/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/compute-units/99999")
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════
# Services CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestServicesCRUD:
    def test_create(self, client):
        resp = _create_service(client)
        assert resp.status_code == 201
        assert resp.json()["name"] == "TestSvc"

    def test_read(self, client):
        svc_id = _create_service(client).json()["id"]
        resp = client.get(f"{API}/services/{svc_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestSvc"

    def test_update(self, client):
        svc_id = _create_service(client).json()["id"]
        resp = client.patch(f"{API}/services/{svc_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        svc_id = _create_service(client).json()["id"]
        resp = client.delete(f"{API}/services/{svc_id}")
        assert resp.status_code == 204
        resp = client.get(f"{API}/services/{svc_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/services/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/services/99999")
        assert resp.status_code == 404

    def test_create_with_status_and_ip(self, client):
        """Regression: ip_address and status must be persisted on create."""
        resp = _create_service(
            client,
            name="Nginx",
            slug="nginx",
            status="running",
            ip_address="10.0.0.50",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "running"
        assert data["ip_address"] == "10.0.0.50"

        # Verify via GET
        svc_id = data["id"]
        resp = client.get(f"{API}/services/{svc_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["ip_address"] == "10.0.0.50"


# ═══════════════════════════════════════════════════════════════════════════
# Storage CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestStorageCRUD:
    def test_create(self, client):
        resp = _create_storage(client)
        assert resp.status_code == 201
        assert resp.json()["name"] == "TestPool"

    def test_read(self, client):
        st_id = _create_storage(client).json()["id"]
        resp = client.get(f"{API}/storage/{st_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestPool"

    def test_update(self, client):
        st_id = _create_storage(client).json()["id"]
        resp = client.patch(f"{API}/storage/{st_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        st_id = _create_storage(client).json()["id"]
        resp = client.delete(f"{API}/storage/{st_id}")
        assert resp.status_code == 204
        resp = client.get(f"{API}/storage/{st_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/storage/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/storage/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Networks CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestNetworksCRUD:
    def test_create(self, client):
        resp = _create_network(client, cidr="10.0.0.0/24")
        assert resp.status_code == 201
        assert resp.json()["name"] == "TestLAN"
        assert resp.json()["cidr"] == "10.0.0.0/24"

    def test_read(self, client):
        net_id = _create_network(client).json()["id"]
        resp = client.get(f"{API}/networks/{net_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestLAN"

    def test_update(self, client):
        net_id = _create_network(client).json()["id"]
        resp = client.patch(f"{API}/networks/{net_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        net_id = _create_network(client).json()["id"]
        resp = client.delete(f"{API}/networks/{net_id}")
        assert resp.status_code == 204
        resp = client.get(f"{API}/networks/{net_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/networks/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/networks/99999")
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════
# Misc CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestMiscCRUD:
    def test_create(self, client):
        resp = _create_misc(client)
        assert resp.status_code == 201
        assert resp.json()["name"] == "TestMisc"

    def test_read(self, client):
        item_id = _create_misc(client).json()["id"]
        resp = client.get(f"{API}/misc/{item_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TestMisc"

    def test_update(self, client):
        item_id = _create_misc(client).json()["id"]
        resp = client.patch(f"{API}/misc/{item_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete(self, client):
        item_id = _create_misc(client).json()["id"]
        resp = client.delete(f"{API}/misc/{item_id}")
        assert resp.status_code == 204
        resp = client.get(f"{API}/misc/{item_id}")
        assert resp.status_code == 404

    def test_get_not_found(self, client):
        resp = client.get(f"{API}/misc/99999")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete(f"{API}/misc/99999")
        assert resp.status_code == 404
