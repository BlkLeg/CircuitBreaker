from app.db import models


def test_update_edge_type_normalizes_alias_and_validates(client, db, auth_headers):
    svc_a = models.Service(name="Svc A", slug="svc-a")
    svc_b = models.Service(name="Svc B", slug="svc-b")
    db.add_all([svc_a, svc_b])
    db.flush()

    dep = models.ServiceDependency(service_id=svc_a.id, depends_on_id=svc_b.id, connection_type="ethernet")
    db.add(dep)
    db.commit()

    edge_id = f"e-dep-{dep.id}"

    ok = client.patch(
        f"/api/v1/graph/edges/{edge_id}",
        json={"connection_type": "wireguard"},
        headers=auth_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["connection_type"] == "wg"

    db.refresh(dep)
    assert dep.connection_type == "wg"

    bad = client.patch(
        f"/api/v1/graph/edges/{edge_id}",
        json={"connection_type": "not-a-real-type"},
        headers=auth_headers,
    )
    assert bad.status_code == 422


def test_topology_edge_payload_includes_relation_and_nullable_connection_fields(client, db):
    hw = models.Hardware(name="Host 01", download_speed_mbps=1000, upload_speed_mbps=250)
    db.add(hw)
    db.flush()

    cu = models.ComputeUnit(
        name="VM 01",
        kind="vm",
        hardware_id=hw.id,
        download_speed_mbps=500,
        upload_speed_mbps=120,
    )
    net = models.Network(name="LAN")
    db.add_all([cu, net])
    db.flush()

    cn = models.ComputeNetwork(
        compute_id=cu.id,
        network_id=net.id,
        connection_type="wireguard",
        bandwidth_mbps=250,
    )
    db.add(cn)
    db.commit()

    resp = client.get("/api/v1/graph/topology", params={"include": "hardware,compute,networks"})
    assert resp.status_code == 200
    edges = resp.json()["edges"]

    hosts_edge = next(e for e in edges if e["id"] == f"e-hw-cu-{cu.id}")
    assert hosts_edge["data"]["relation"] == "hosts"
    assert "connection_type" not in hosts_edge["data"]
    assert "bandwidth" not in hosts_edge["data"]

    conn_edge = next(e for e in edges if e["id"] == f"e-cn-{cn.id}")
    assert conn_edge["data"]["relation"] == "connects_to"
    assert conn_edge["data"]["connection_type"] == "wg"
    assert conn_edge["data"]["bandwidth"] == 250

    nodes = resp.json()["nodes"]
    hw_node = next(n for n in nodes if n["id"] == f"hw-{hw.id}")
    cu_node = next(n for n in nodes if n["id"] == f"cu-{cu.id}")
    assert hw_node["download_speed_mbps"] == 1000
    assert hw_node["upload_speed_mbps"] == 250
    assert cu_node["download_speed_mbps"] == 500
    assert cu_node["upload_speed_mbps"] == 120


def test_compute_unit_bandwidth_fields_persist_through_api(client):
    hw = client.post("/api/v1/hardware", json={"name": "Host Persist"}).json()

    created = client.post("/api/v1/compute-units", json={
        "name": "VM Persist",
        "kind": "vm",
        "hardware_id": hw["id"],
        "download_speed_mbps": 700,
        "upload_speed_mbps": 90,
    })
    assert created.status_code == 201
    body = created.json()
    assert body["download_speed_mbps"] == 700
    assert body["upload_speed_mbps"] == 90

    patched = client.patch(
        f"/api/v1/compute-units/{body['id']}",
        json={"download_speed_mbps": 850, "upload_speed_mbps": 150},
    )
    assert patched.status_code == 200
    updated = patched.json()
    assert updated["download_speed_mbps"] == 850
    assert updated["upload_speed_mbps"] == 150
