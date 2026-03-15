"""
Tests for IPAM (IP Address Management) endpoints:
  IPAddress: GET /api/v1/ipam, POST /api/v1/ipam, PATCH /api/v1/ipam/{id}, DELETE /api/v1/ipam/{id}
  VLAN: GET /api/v1/vlans, POST /api/v1/vlans, PATCH /api/v1/vlans/{id}, DELETE /api/v1/vlans/{id}
  Site: GET /api/v1/sites, POST /api/v1/sites, PATCH /api/v1/sites/{id}, DELETE /api/v1/sites/{id}
  NodeRelation: GET /api/v1/node-relations, POST /api/v1/node-relations, PATCH /api/v1/node-relations/{id}, DELETE /api/v1/node-relations/{id}

All tests use real database operations, no mocks.
"""

import pytest

from app.db.models import VLAN, IPAddress, NodeRelation, Site

IPAM_URL = "/api/v1/ipam"
VLAN_URL = "/api/v1/vlans"
SITE_URL = "/api/v1/sites"
NODE_REL_URL = "/api/v1/node-relations"


# ── IPAddress CRUD Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_ip_addresses_empty(client, auth_headers):
    """GET /ipam returns empty list when no IP addresses exist."""
    resp = await client.get(IPAM_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_ip_address(client, auth_headers, db_session):
    """POST /ipam creates a new IP address entry."""
    payload = {
        "address": "192.168.1.100",
        "status": "allocated",
        "hostname": "test-host",
    }
    resp = await client.post(IPAM_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201

    body = resp.json()
    assert body["address"] == "192.168.1.100"
    assert body["status"] == "allocated"
    assert body["hostname"] == "test-host"
    assert "id" in body

    # Verify in database
    ip_in_db = db_session.get(IPAddress, body["id"])
    assert ip_in_db is not None
    assert str(ip_in_db.address) == "192.168.1.100"


@pytest.mark.asyncio
async def test_create_ip_duplicate_returns_409(client, auth_headers, db_session):
    """POST /ipam with duplicate address returns 409."""
    payload = {"address": "10.0.0.1", "status": "allocated"}
    resp1 = await client.post(IPAM_URL, json=payload, headers=auth_headers)
    assert resp1.status_code == 201

    resp2 = await client.post(IPAM_URL, json=payload, headers=auth_headers)
    assert resp2.status_code == 409
    assert "already tracked" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_ip_addresses_returns_created(client, auth_headers):
    """GET /ipam includes previously created IP addresses."""
    await client.post(IPAM_URL, json={"address": "172.16.0.50"}, headers=auth_headers)
    resp = await client.get(IPAM_URL, headers=auth_headers)

    addresses = [ip["address"] for ip in resp.json()]
    assert "172.16.0.50" in addresses


@pytest.mark.asyncio
async def test_get_ip_address_by_id(client, auth_headers):
    """GET /ipam/{id} returns specific IP address."""
    create_resp = await client.post(
        IPAM_URL, json={"address": "10.1.1.1", "hostname": "gateway"}, headers=auth_headers
    )
    ip_id = create_resp.json()["id"]

    resp = await client.get(f"{IPAM_URL}/{ip_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["hostname"] == "gateway"


@pytest.mark.asyncio
async def test_get_ip_address_404_for_missing(client, auth_headers):
    """GET /ipam/{id} returns 404 for non-existent IP."""
    resp = await client.get(f"{IPAM_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_ip_address(client, auth_headers, db_session):
    """PATCH /ipam/{id} updates IP address fields."""
    create_resp = await client.post(
        IPAM_URL, json={"address": "10.2.2.2", "status": "free"}, headers=auth_headers
    )
    ip_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{IPAM_URL}/{ip_id}",
        json={"status": "reserved", "hostname": "reserved-host"},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "reserved"
    assert update_resp.json()["hostname"] == "reserved-host"

    # Verify in database
    ip_in_db = db_session.get(IPAddress, ip_id)
    assert ip_in_db.status == "reserved"
    assert ip_in_db.hostname == "reserved-host"


@pytest.mark.asyncio
async def test_update_ip_address_404_for_missing(client, auth_headers):
    """PATCH /ipam/{id} returns 404 for non-existent IP."""
    resp = await client.patch(
        f"{IPAM_URL}/99999", json={"status": "allocated"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_ip_address(client, auth_headers, db_session):
    """DELETE /ipam/{id} removes IP address."""
    create_resp = await client.post(IPAM_URL, json={"address": "10.3.3.3"}, headers=auth_headers)
    ip_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{IPAM_URL}/{ip_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    ip_in_db = db_session.get(IPAddress, ip_id)
    assert ip_in_db is None


@pytest.mark.asyncio
async def test_delete_ip_address_404_for_missing(client, auth_headers):
    """DELETE /ipam/{id} returns 404 for non-existent IP."""
    resp = await client.delete(f"{IPAM_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_filter_ip_addresses_by_status(client, auth_headers):
    """GET /ipam?status=allocated filters by status."""
    await client.post(
        IPAM_URL, json={"address": "10.4.1.1", "status": "allocated"}, headers=auth_headers
    )
    await client.post(
        IPAM_URL, json={"address": "10.4.1.2", "status": "free"}, headers=auth_headers
    )

    resp = await client.get(f"{IPAM_URL}?status=allocated", headers=auth_headers)
    assert resp.status_code == 200

    addresses = resp.json()
    statuses = {ip["status"] for ip in addresses}
    assert statuses == {"allocated"}


# ── VLAN CRUD Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_vlans_empty(client, auth_headers):
    """GET /vlans returns empty list when no VLANs exist."""
    resp = await client.get(VLAN_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_vlan(client, auth_headers, db_session):
    """POST /vlans creates a new VLAN."""
    payload = {"vlan_id": 100, "name": "Production", "description": "Production network"}
    resp = await client.post(VLAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201

    body = resp.json()
    assert body["vlan_id"] == 100
    assert body["name"] == "Production"
    assert "id" in body

    # Verify in database
    vlan_in_db = db_session.get(VLAN, body["id"])
    assert vlan_in_db is not None
    assert vlan_in_db.vlan_id == 100


@pytest.mark.asyncio
async def test_create_vlan_duplicate_returns_409(client, auth_headers):
    """POST /vlans with duplicate vlan_id returns 409."""
    payload = {"vlan_id": 200, "name": "Test VLAN"}
    resp1 = await client.post(VLAN_URL, json=payload, headers=auth_headers)
    assert resp1.status_code == 201

    resp2 = await client.post(VLAN_URL, json=payload, headers=auth_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_get_vlan_by_id(client, auth_headers):
    """GET /vlans/{id} returns specific VLAN."""
    create_resp = await client.post(
        VLAN_URL, json={"vlan_id": 300, "name": "Guest Network"}, headers=auth_headers
    )
    vlan_id = create_resp.json()["id"]

    resp = await client.get(f"{VLAN_URL}/{vlan_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Guest Network"


@pytest.mark.asyncio
async def test_get_vlan_404_for_missing(client, auth_headers):
    """GET /vlans/{id} returns 404 for non-existent VLAN."""
    resp = await client.get(f"{VLAN_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_vlan(client, auth_headers, db_session):
    """PATCH /vlans/{id} updates VLAN fields."""
    create_resp = await client.post(
        VLAN_URL, json={"vlan_id": 400, "name": "Old Name"}, headers=auth_headers
    )
    vlan_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{VLAN_URL}/{vlan_id}",
        json={"name": "New Name", "description": "Updated description"},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "New Name"

    # Verify in database
    vlan_in_db = db_session.get(VLAN, vlan_id)
    assert vlan_in_db.name == "New Name"
    assert vlan_in_db.description == "Updated description"


@pytest.mark.asyncio
async def test_update_vlan_404_for_missing(client, auth_headers):
    """PATCH /vlans/{id} returns 404 for non-existent VLAN."""
    resp = await client.patch(f"{VLAN_URL}/99999", json={"name": "Test"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_vlan(client, auth_headers, db_session):
    """DELETE /vlans/{id} removes VLAN."""
    create_resp = await client.post(
        VLAN_URL, json={"vlan_id": 500, "name": "Temporary"}, headers=auth_headers
    )
    vlan_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{VLAN_URL}/{vlan_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    vlan_in_db = db_session.get(VLAN, vlan_id)
    assert vlan_in_db is None


@pytest.mark.asyncio
async def test_delete_vlan_404_for_missing(client, auth_headers):
    """DELETE /vlans/{id} returns 404 for non-existent VLAN."""
    resp = await client.delete(f"{VLAN_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── Site CRUD Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sites_empty(client, auth_headers):
    """GET /sites returns empty list when no sites exist."""
    resp = await client.get(SITE_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_site(client, auth_headers, db_session):
    """POST /sites creates a new site."""
    payload = {
        "name": "Datacenter A",
        "location": "New York",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "notes": "Primary datacenter",
    }
    resp = await client.post(SITE_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201

    body = resp.json()
    assert body["name"] == "Datacenter A"
    assert body["latitude"] == 40.7128
    assert "id" in body

    # Verify in database
    site_in_db = db_session.get(Site, body["id"])
    assert site_in_db is not None
    assert site_in_db.name == "Datacenter A"


@pytest.mark.asyncio
async def test_create_site_minimal_fields(client, auth_headers):
    """POST /sites works with only required field (name)."""
    resp = await client.post(SITE_URL, json={"name": "Minimal Site"}, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["name"] == "Minimal Site"


@pytest.mark.asyncio
async def test_get_site_by_id(client, auth_headers):
    """GET /sites/{id} returns specific site."""
    create_resp = await client.post(
        SITE_URL, json={"name": "Site B", "location": "London"}, headers=auth_headers
    )
    site_id = create_resp.json()["id"]

    resp = await client.get(f"{SITE_URL}/{site_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["location"] == "London"


@pytest.mark.asyncio
async def test_get_site_404_for_missing(client, auth_headers):
    """GET /sites/{id} returns 404 for non-existent site."""
    resp = await client.get(f"{SITE_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_site(client, auth_headers, db_session):
    """PATCH /sites/{id} updates site fields."""
    create_resp = await client.post(
        SITE_URL, json={"name": "Site C", "latitude": 0.0}, headers=auth_headers
    )
    site_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{SITE_URL}/{site_id}",
        json={"location": "Paris", "latitude": 48.8566, "longitude": 2.3522},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["location"] == "Paris"
    assert update_resp.json()["latitude"] == 48.8566

    # Verify in database
    site_in_db = db_session.get(Site, site_id)
    assert site_in_db.location == "Paris"


@pytest.mark.asyncio
async def test_update_site_404_for_missing(client, auth_headers):
    """PATCH /sites/{id} returns 404 for non-existent site."""
    resp = await client.patch(f"{SITE_URL}/99999", json={"name": "Test"}, headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_site(client, auth_headers, db_session):
    """DELETE /sites/{id} removes site."""
    create_resp = await client.post(SITE_URL, json={"name": "Temp Site"}, headers=auth_headers)
    site_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{SITE_URL}/{site_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    site_in_db = db_session.get(Site, site_id)
    assert site_in_db is None


@pytest.mark.asyncio
async def test_delete_site_404_for_missing(client, auth_headers):
    """DELETE /sites/{id} returns 404 for non-existent site."""
    resp = await client.delete(f"{SITE_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── NodeRelation CRUD Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_node_relations_empty(client, auth_headers):
    """GET /node-relations returns empty list when no relations exist."""
    resp = await client.get(NODE_REL_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_node_relation(client, auth_headers, db_session, factories):
    """POST /node-relations creates a new relation."""
    hw1 = factories.hardware(name="node-a", ip_address="10.0.0.1")
    hw2 = factories.hardware(name="node-b", ip_address="10.0.0.2")

    payload = {
        "source_type": "hardware",
        "source_id": hw1.id,
        "target_type": "hardware",
        "target_id": hw2.id,
        "relation_type": "connected",
        "metadata_json": {"port": "eth0"},
    }
    resp = await client.post(NODE_REL_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201

    body = resp.json()
    assert body["source_id"] == hw1.id
    assert body["target_id"] == hw2.id
    assert body["relation_type"] == "connected"
    assert body["metadata_json"]["port"] == "eth0"

    # Verify in database
    rel_in_db = db_session.get(NodeRelation, body["id"])
    assert rel_in_db is not None
    assert rel_in_db.source_type == "hardware"


@pytest.mark.asyncio
async def test_list_node_relations_with_filters(client, auth_headers, factories):
    """GET /node-relations filters by source/target type/id."""
    hw1 = factories.hardware(name="filter-a", ip_address="10.0.1.1")
    hw2 = factories.hardware(name="filter-b", ip_address="10.0.1.2")
    svc = factories.service(name="filter-svc", ip_address="10.0.1.3")

    # Create multiple relations
    await client.post(
        NODE_REL_URL,
        json={
            "source_type": "hardware",
            "source_id": hw1.id,
            "target_type": "hardware",
            "target_id": hw2.id,
            "relation_type": "peer",
        },
        headers=auth_headers,
    )
    await client.post(
        NODE_REL_URL,
        json={
            "source_type": "hardware",
            "source_id": hw1.id,
            "target_type": "service",
            "target_id": svc.id,
            "relation_type": "hosts",
        },
        headers=auth_headers,
    )

    # Filter by source_type and source_id
    resp = await client.get(
        f"{NODE_REL_URL}?source_type=hardware&source_id={hw1.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    relations = resp.json()
    assert len(relations) == 2
    assert all(r["source_id"] == hw1.id for r in relations)


@pytest.mark.asyncio
async def test_update_node_relation_metadata(client, auth_headers, db_session, factories):
    """PATCH /node-relations/{id} updates metadata and relation_type."""
    hw1 = factories.hardware(name="update-a", ip_address="10.0.2.1")
    hw2 = factories.hardware(name="update-b", ip_address="10.0.2.2")

    create_resp = await client.post(
        NODE_REL_URL,
        json={
            "source_type": "hardware",
            "source_id": hw1.id,
            "target_type": "hardware",
            "target_id": hw2.id,
            "relation_type": "connected",
            "metadata_json": {"speed": "1Gbps"},
        },
        headers=auth_headers,
    )
    rel_id = create_resp.json()["id"]

    # Update metadata and relation_type
    update_resp = await client.patch(
        f"{NODE_REL_URL}/{rel_id}",
        json={
            "relation_type": "redundant",
            "metadata_json": {"speed": "10Gbps", "interface": "eth0"},
        },
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["relation_type"] == "redundant"
    assert update_resp.json()["metadata_json"]["speed"] == "10Gbps"

    # Verify in database
    rel_in_db = db_session.get(NodeRelation, rel_id)
    assert rel_in_db.relation_type == "redundant"
    assert rel_in_db.metadata_json["interface"] == "eth0"


@pytest.mark.asyncio
async def test_update_node_relation_404_for_missing(client, auth_headers):
    """PATCH /node-relations/{id} returns 404 for non-existent relation."""
    resp = await client.patch(
        f"{NODE_REL_URL}/99999", json={"relation_type": "test"}, headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_node_relation(client, auth_headers, db_session, factories):
    """DELETE /node-relations/{id} removes relation."""
    hw1 = factories.hardware(name="delete-a", ip_address="10.0.3.1")
    hw2 = factories.hardware(name="delete-b", ip_address="10.0.3.2")

    create_resp = await client.post(
        NODE_REL_URL,
        json={
            "source_type": "hardware",
            "source_id": hw1.id,
            "target_type": "hardware",
            "target_id": hw2.id,
            "relation_type": "temp",
        },
        headers=auth_headers,
    )
    rel_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"{NODE_REL_URL}/{rel_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Verify removed from database
    rel_in_db = db_session.get(NodeRelation, rel_id)
    assert rel_in_db is None


@pytest.mark.asyncio
async def test_delete_node_relation_404_for_missing(client, auth_headers):
    """DELETE /node-relations/{id} returns 404 for non-existent relation."""
    resp = await client.delete(f"{NODE_REL_URL}/99999", headers=auth_headers)
    assert resp.status_code == 404


# ── IP Address Association with Hardware/Service ──────────────────────────────


@pytest.mark.asyncio
async def test_create_ip_address_associated_with_hardware(client, auth_headers, factories):
    """POST /ipam can associate IP with hardware."""
    hw = factories.hardware(name="server-1", ip_address="10.0.4.1")

    payload = {"address": "10.0.4.10", "status": "allocated", "hardware_id": hw.id}
    resp = await client.post(IPAM_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["hardware_id"] == hw.id


@pytest.mark.asyncio
async def test_update_ip_address_change_hardware_association(client, auth_headers, factories):
    """PATCH /ipam/{id} can change hardware association."""
    hw1 = factories.hardware(name="old-hw", ip_address="10.0.5.1")
    hw2 = factories.hardware(name="new-hw", ip_address="10.0.5.2")

    create_resp = await client.post(
        IPAM_URL, json={"address": "10.0.5.10", "hardware_id": hw1.id}, headers=auth_headers
    )
    ip_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{IPAM_URL}/{ip_id}", json={"hardware_id": hw2.id}, headers=auth_headers
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["hardware_id"] == hw2.id


# ── VLAN Network Association ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_vlan_with_network_ids(client, auth_headers, factories):
    """POST /vlans can associate multiple networks."""
    net1 = factories.network(name="net-1", cidr="10.1.0.0/24")
    net2 = factories.network(name="net-2", cidr="10.2.0.0/24")

    payload = {
        "vlan_id": 600,
        "name": "Multi-Network VLAN",
        "network_ids": [net1.id, net2.id],
    }
    resp = await client.post(VLAN_URL, json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert set(resp.json()["network_ids"]) == {net1.id, net2.id}


@pytest.mark.asyncio
async def test_update_vlan_network_ids(client, auth_headers, factories, db_session):
    """PATCH /vlans/{id} updates network associations."""
    net1 = factories.network(name="net-a", cidr="10.3.0.0/24")
    net2 = factories.network(name="net-b", cidr="10.4.0.0/24")

    create_resp = await client.post(
        VLAN_URL,
        json={"vlan_id": 700, "name": "Test VLAN", "network_ids": [net1.id]},
        headers=auth_headers,
    )
    vlan_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"{VLAN_URL}/{vlan_id}", json={"network_ids": [net2.id]}, headers=auth_headers
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["network_ids"] == [net2.id]

    # Verify in database
    vlan_in_db = db_session.get(VLAN, vlan_id)
    assert vlan_in_db.network_ids == [net2.id]


# ── Error Handling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_ip_invalid_address_returns_422(client, auth_headers):
    """POST /ipam with invalid IP address format returns 422."""
    resp = await client.post(
        IPAM_URL, json={"address": "not-an-ip", "status": "free"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_site_missing_required_field_returns_422(client, auth_headers):
    """POST /sites without required 'name' field returns 422."""
    resp = await client.post(SITE_URL, json={"location": "Somewhere"}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_vlan_invalid_type_returns_422(client, auth_headers):
    """POST /vlans with non-integer vlan_id returns 422."""
    resp = await client.post(
        VLAN_URL, json={"vlan_id": "not-a-number", "name": "Bad VLAN"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_filter_ip_addresses_by_network(client, auth_headers, factories):
    """GET /ipam?network_id={id} filters by network."""
    net1 = factories.network(name="filter-net-1", cidr="10.10.0.0/24")
    net2 = factories.network(name="filter-net-2", cidr="10.20.0.0/24")

    await client.post(
        IPAM_URL,
        json={"address": "10.10.0.5", "network_id": net1.id},
        headers=auth_headers,
    )
    await client.post(
        IPAM_URL,
        json={"address": "10.20.0.5", "network_id": net2.id},
        headers=auth_headers,
    )

    resp = await client.get(f"{IPAM_URL}?network_id={net1.id}", headers=auth_headers)
    assert resp.status_code == 200

    addresses = resp.json()
    assert len(addresses) >= 1
    assert all(ip["network_id"] == net1.id for ip in addresses if ip["network_id"])


@pytest.mark.asyncio
async def test_node_relation_unique_constraint(client, auth_headers, factories):
    """POST /node-relations duplicate edge returns 409."""
    hw1 = factories.hardware(name="unique-a", ip_address="10.0.6.1")
    hw2 = factories.hardware(name="unique-b", ip_address="10.0.6.2")

    payload = {
        "source_type": "hardware",
        "source_id": hw1.id,
        "target_type": "hardware",
        "target_id": hw2.id,
        "relation_type": "connected",
    }

    resp1 = await client.post(NODE_REL_URL, json=payload, headers=auth_headers)
    assert resp1.status_code == 201

    # Attempt to create duplicate
    resp2 = await client.post(NODE_REL_URL, json=payload, headers=auth_headers)
    assert resp2.status_code in (409, 422)  # Either duplicate or constraint violation
