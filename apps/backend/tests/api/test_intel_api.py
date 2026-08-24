"""Integration tests for the /api/v1/intel endpoints."""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import event

from app.db.models import CapacityForecast, ResourceEfficiencyRecommendation


@contextlib.contextmanager
def _capture_sql():
    from app.db.session import engine

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "after_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", _record)


@pytest.mark.asyncio
async def test_capacity_forecasts_include_the_hardware_name(
    client, auth_headers, factories, db_session
):
    hw = factories.hardware(name="nas-01")
    db_session.add(
        CapacityForecast(
            hardware_id=hw.id,
            metric="disk",
            slope_per_day=0.9,
            current_value=87.0,
            warning_threshold_days=30,
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/capacity-forecasts", headers=auth_headers)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["hardware_id"] == hw.id
    assert row["hardware_name"] == "nas-01"


@pytest.mark.asyncio
async def test_resource_efficiency_includes_the_asset_name(
    client, auth_headers, factories, db_session
):
    hw = factories.hardware(name="host-01")
    cu = factories.compute_unit(name="vm-jellyfin", hardware_id=hw.id)
    db_session.add(
        ResourceEfficiencyRecommendation(
            asset_type="compute_unit",
            asset_id=cu.id,
            classification="over_provisioned",
            cpu_avg_pct=3.0,
            cpu_peak_pct=11.0,
            mem_avg_pct=18.0,
            recommendation="Reduce from 8 vCPU to 2",
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["asset_name"] == "vm-jellyfin"


@pytest.mark.asyncio
async def test_resource_efficiency_tolerates_a_deleted_asset(client, auth_headers, db_session):
    db_session.add(
        ResourceEfficiencyRecommendation(
            asset_type="service",
            asset_id=999_999,
            classification="under_provisioned",
            recommendation="Increase memory allocation",
        )
    )
    db_session.flush()

    resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["asset_name"] is None


@pytest.mark.asyncio
async def test_intel_requires_authentication_but_not_a_role(client, viewer_headers):
    for path in ("capacity-forecasts", "resource-efficiency"):
        resp = await client.get(f"/api/v1/intel/{path}", headers=viewer_headers)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_efficiency_names_do_not_scale_queries_with_row_count(
    client, auth_headers, factories, db_session
):
    hw = factories.hardware(name="host-batch")
    for i in range(15):
        cu = factories.compute_unit(name=f"vm-{i}", hardware_id=hw.id)
        db_session.add(
            ResourceEfficiencyRecommendation(
                asset_type="compute_unit",
                asset_id=cu.id,
                classification="over_provisioned",
                recommendation="Reduce vCPU",
            )
        )
    db_session.flush()

    with _capture_sql() as statements:
        resp = await client.get("/api/v1/intel/resource-efficiency", headers=auth_headers)

    assert resp.status_code == 200
    assert len(resp.json()) == 15
    compute_selects = [
        s
        for s in statements
        if "compute_units" in s.lower() and s.lstrip().upper().startswith("SELECT")
    ]
    assert len(compute_selects) == 1, compute_selects
