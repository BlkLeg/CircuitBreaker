"""Integration tests for blast-radius dependency graph traversal and intel API."""

from __future__ import annotations

from app.db.models import ServiceDependency
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
