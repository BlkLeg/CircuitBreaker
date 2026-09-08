"""Integration tests for blast-radius dependency graph traversal and intel API."""

from __future__ import annotations

from app.db.models import (
    HardwareNetwork,
    ServiceDependency,
    ServiceStorage,
    Storage,
)
from app.services.intelligence.dependency_graph import (
    calculate_blast_radius,
)


def test_blast_radius_hw_to_compute_to_service(db_session, factories):
    """Hardware → 3 VMs → 2 services: total impact = 5."""
    hw = factories.hardware(name="hypervisor-01", ip_address="10.0.0.1")
    cu1 = factories.compute_unit(name="vm1", hardware_id=hw.id)
    cu2 = factories.compute_unit(name="vm2", hardware_id=hw.id)
    cu3 = factories.compute_unit(name="vm3", hardware_id=hw.id)
    factories.service(name="svc-a", compute_id=cu1.id)
    factories.service(name="svc-b", compute_id=cu2.id)

    result = calculate_blast_radius(db_session, "hardware", hw.id)

    assert result.total_impact_count == 5
    assert len(result.impacted_compute_units) == 3
    assert len(result.impacted_services) == 2
    cu_ids = {r.asset_id for r in result.impacted_compute_units}
    assert cu_ids == {cu1.id, cu2.id, cu3.id}


def test_blast_radius_service_dependency_chain(db_session, factories):
    """Service B depends on Service A; A going down impacts B."""
    svc_a = factories.service(name="db-service")
    svc_b = factories.service(name="api-service")
    dep = ServiceDependency(service_id=svc_b.id, depends_on_id=svc_a.id)
    db_session.add(dep)
    db_session.flush()

    result = calculate_blast_radius(db_session, "service", svc_a.id)

    assert result.total_impact_count == 1
    assert result.impacted_services[0].asset_id == svc_b.id


def test_blast_radius_isolated_node(db_session, factories):
    """A standalone hardware node with nothing downstream returns empty impact."""
    hw = factories.hardware(name="isolated-hw", ip_address="10.99.0.1")

    result = calculate_blast_radius(db_session, "hardware", hw.id)

    assert result.total_impact_count == 0
    assert result.root_asset.asset_id == hw.id


def test_blast_radius_summary_text(db_session, factories):
    """Summary text mentions root asset name and downstream count."""
    hw = factories.hardware(name="core-switch", ip_address="10.0.0.2")
    factories.compute_unit(name="vm-x", hardware_id=hw.id)

    result = calculate_blast_radius(db_session, "hardware", hw.id)

    assert "core-switch" in result.summary
    assert "1" in result.summary
    assert "Potential impact" in result.summary


def test_shared_network_is_connectivity_not_operational_dependency(db_session, factories):
    first = factories.hardware(name="first")
    second = factories.hardware(name="second")
    network = factories.network(name="shared")
    db_session.add_all(
        [
            HardwareNetwork(hardware_id=first.id, network_id=network.id),
            HardwareNetwork(hardware_id=second.id, network_id=network.id),
        ]
    )
    db_session.flush()

    result = calculate_blast_radius(db_session, "hardware", first.id)

    assert result.impacted_hardware == []
    assert result.total_impact_count == 0
    assert len(result.connectivity) == 1


def test_storage_failure_includes_explicit_consumers_with_path(db_session, factories):
    hardware = factories.hardware(name="nas")
    storage = Storage(name="pool", kind="pool", hardware_id=hardware.id)
    service = factories.service(name="database")
    db_session.add(storage)
    db_session.flush()
    db_session.add(ServiceStorage(service_id=service.id, storage_id=storage.id, purpose="data"))
    db_session.flush()

    result = calculate_blast_radius(db_session, "storage", storage.id)

    assert [item.asset_id for item in result.impacted_services] == [service.id]
    assert result.paths[0].edges[0].source_kind == "service_storage"
    assert result.paths[0].provenance == "confirmed"


def test_dependency_cycle_terminates_and_deduplicates_assets(db_session, factories):
    first = factories.service(name="first")
    second = factories.service(name="second")
    db_session.add_all(
        [
            ServiceDependency(service_id=second.id, depends_on_id=first.id),
            ServiceDependency(service_id=first.id, depends_on_id=second.id),
        ]
    )
    db_session.flush()

    result = calculate_blast_radius(db_session, "service", first.id)

    assert [item.asset_id for item in result.impacted_services] == [second.id]
    assert len(result.paths) == 1
    assert result.completeness == "complete"


def test_traversal_limit_is_disclosed(db_session, factories):
    root = factories.service(name="root")
    previous = root
    for index in range(3):
        current = factories.service(name=f"dependent-{index}")
        db_session.add(ServiceDependency(service_id=current.id, depends_on_id=previous.id))
        previous = current
    db_session.flush()

    result = calculate_blast_radius(db_session, "service", root.id, max_depth=1)

    assert result.completeness == "truncated"
    assert result.truncation_reason == "depth_limit"
    assert result.total_impact_count == 1


# ── API tests ─────────────────────────────────────────────────────────────────


async def test_blast_radius_api_returns_impact(client, auth_headers, db_session, factories):
    """GET /intel/blast-radius returns correct impact count."""
    hw = factories.hardware(name="api-test-hw", ip_address="10.1.1.1")
    factories.compute_unit(name="api-cu", hardware_id=hw.id)

    resp = await client.get(
        f"/api/v1/intel/blast-radius/hardware/{hw.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_asset"]["name"] == "api-test-hw"
    assert data["total_impact_count"] == 1
    assert "summary" in data


async def test_blast_radius_api_invalid_type(client, auth_headers):
    """GET /intel/blast-radius with invalid asset_type returns 400."""
    resp = await client.get(
        "/api/v1/intel/blast-radius/badtype/1",
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_capacity_forecasts_endpoint_empty(client, auth_headers):
    """GET /intel/capacity-forecasts returns empty list when no forecasts exist."""
    resp = await client.get("/api/v1/intel/capacity-forecasts", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_resource_efficiency_endpoint_empty(client, auth_headers):
    """GET /intel/resource-efficiency returns empty list when no recommendations exist."""
    resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
