"""Map nodes carry the monitor rollup for every entity type the engine can probe."""

import pytest

from app.services import monitor_service


def _node(nodes, node_id):
    return next(n for n in nodes if n["id"] == node_id)


@pytest.mark.asyncio
async def test_topology_nodes_carry_monitor_rollup(client, auth_headers, db_session, factories):
    hw = factories.hardware(ip_address="192.0.2.70")
    cu = factories.compute_unit(hardware_id=hw.id, ip_address="192.0.2.71")
    svc = factories.service(name="grafana-map", url="https://grafana.lan/health")
    ext = factories.external_node(ip_address="192.0.2.72")
    db_session.commit()

    for target_type, target_id in (
        ("hardware", hw.id),
        ("compute_unit", cu.id),
        ("service", svc.id),
        ("external_node", ext.id),
    ):
        assert monitor_service.create_target_monitor(db_session, target_type, target_id)
    monitor_service.set_target_paused(db_session, "compute_unit", cu.id, True)

    resp = await client.get("/api/v1/graph/topology", headers=auth_headers)
    assert resp.status_code == 200
    nodes = resp.json()["nodes"]

    for node_id in (f"hw-{hw.id}", f"cu-{cu.id}", f"svc-{svc.id}", f"ext-{ext.id}"):
        data = _node(nodes, node_id)
        assert data["monitor_id"] is not None, node_id
        assert data["monitor_status"] == "pending", node_id
        assert data["monitor_uptime_pct_24h"] is None, node_id

    assert _node(nodes, f"hw-{hw.id}")["monitor_enabled"] is True
    # A paused target still reports its monitor, flagged disabled.
    assert _node(nodes, f"cu-{cu.id}")["monitor_enabled"] is False


@pytest.mark.asyncio
async def test_unmonitored_nodes_report_no_monitor(client, auth_headers, db_session, factories):
    hw = factories.hardware(ip_address="192.0.2.80")
    db_session.commit()

    resp = await client.get("/api/v1/graph/topology", headers=auth_headers)
    data = _node(resp.json()["nodes"], f"hw-{hw.id}")
    assert data["monitor_id"] is None
    assert data["monitor_status"] is None
    assert data["monitor_enabled"] is None
