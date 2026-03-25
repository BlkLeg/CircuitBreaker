"""Tests for the Proxmox VE integration API endpoints."""

import asyncio
import json

from unittest.mock import MagicMock, patch

import pytest


# ── Model / Schema tests ────────────────────────────────────────────────────


def test_integration_config_model_exists(db):
    from app.db.models import IntegrationConfig

    config = IntegrationConfig(
        type="proxmox",
        name="Test Cluster",
        config_url="https://pve.local:8006",
        auto_sync=True,
        sync_interval_s=300,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    assert config.id is not None
    assert config.type == "proxmox"
    assert config.name == "Test Cluster"


def test_telemetry_timeseries_model(db):
    from app.db.models import TelemetryTimeseries

    ts = TelemetryTimeseries(
        entity_type="hardware",
        entity_id=1,
        metric="cpu_pct",
        value=42.5,
        source="proxmox",
    )
    db.add(ts)
    db.commit()
    db.refresh(ts)

    assert ts.id is not None
    assert ts.value == 42.5


def test_hardware_proxmox_columns(db):
    from app.db.models import Hardware

    hw = Hardware(
        name="pve-node-1",
        role="hypervisor",
        proxmox_node_name="node1",
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)

    assert hw.proxmox_node_name == "node1"


def test_compute_unit_proxmox_columns(db):
    from app.db.models import ComputeUnit, Hardware

    hw = Hardware(name="host", role="hypervisor")
    db.add(hw)
    db.flush()

    cu = ComputeUnit(
        name="vm-web01",
        kind="vm",
        hardware_id=hw.id,
        proxmox_vmid=100,
        proxmox_type="qemu",
    )
    db.add(cu)
    db.commit()
    db.refresh(cu)

    assert cu.proxmox_vmid == 100
    assert cu.proxmox_type == "qemu"


# ── API endpoint tests ───────────────────────────────────────────────────────


def test_list_proxmox_configs_empty(client):
    r = client.get("/api/v1/integrations/proxmox")
    assert r.status_code == 200
    assert r.json() == []


def test_create_proxmox_config(client, monkeypatch):
    _mock_vault(monkeypatch)
    r = client.post("/api/v1/integrations/proxmox", json={
        "name": "Test PVE",
        "config_url": "https://8.8.8.8:8006",
        "api_token": "root@pam!cbtoken=secret123",
        "auto_sync": True,
        "sync_interval_s": 300,
        "verify_ssl": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test PVE"
    assert data["type"] == "proxmox"
    assert data["config_url"] == "https://8.8.8.8:8006"
    assert "api_token" not in data  # token must not leak


def test_get_proxmox_config(client, monkeypatch):
    _mock_vault(monkeypatch)
    create = client.post("/api/v1/integrations/proxmox", json={
        "name": "My Cluster",
        "config_url": "https://8.8.8.8:8006",
        "api_token": "user@pam!tok=val",
    })
    cid = create.json()["id"]

    r = client.get(f"/api/v1/integrations/proxmox/{cid}")
    assert r.status_code == 200
    assert r.json()["name"] == "My Cluster"


def test_update_proxmox_config(client, monkeypatch):
    _mock_vault(monkeypatch)
    create = client.post("/api/v1/integrations/proxmox", json={
        "name": "Old Name",
        "config_url": "https://8.8.8.8:8006",
        "api_token": "user@pam!tok=val",
    })
    cid = create.json()["id"]

    r = client.put(f"/api/v1/integrations/proxmox/{cid}", json={"name": "New Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"


def test_delete_proxmox_config(client, monkeypatch):
    _mock_vault(monkeypatch)
    create = client.post("/api/v1/integrations/proxmox", json={
        "name": "ToDelete",
        "config_url": "https://8.8.8.8:8006",
        "api_token": "user@pam!tok=val",
    })
    cid = create.json()["id"]

    r = client.delete(f"/api/v1/integrations/proxmox/{cid}")
    assert r.status_code == 200

    r = client.get(f"/api/v1/integrations/proxmox/{cid}")
    assert r.status_code == 404


def test_get_proxmox_status(client, monkeypatch):
    _mock_vault(monkeypatch)
    create = client.post("/api/v1/integrations/proxmox", json={
        "name": "Status Test",
        "config_url": "https://8.8.8.8:8006",
        "api_token": "user@pam!tok=val",
    })
    cid = create.json()["id"]

    r = client.get(f"/api/v1/integrations/proxmox/{cid}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["integration_id"] == cid
    assert data["nodes_count"] == 0
    assert data["vms_count"] == 0


def test_cluster_overview_uses_quorate_and_online_fields(db, monkeypatch):
    from app.db.models import IntegrationConfig
    from app.services import proxmox_service
    from app.services import proxmox_queries

    cfg = IntegrationConfig(
        type="proxmox",
        name="Overview Parse Test",
        config_url="https://8.8.8.8:8006",
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)

    class _FakeClient:
        async def get_cluster_status(self):
            return [
                {"type": "cluster", "name": "pve-cluster", "quorum": 0, "quorate": 1},
                {"type": "node", "name": "pve1", "online": 1},
                {"type": "node", "name": "pve2", "online": 1},
                {"type": "node", "name": "pve3", "online": 1},
                {"type": "node", "name": "pve4", "online": 1},
            ]

    monkeypatch.setattr(proxmox_queries, "_get_client", lambda _db, _cfg: _FakeClient())
    payload = asyncio.run(proxmox_service.get_cluster_overview(db, cfg.id))
    cluster = payload["cluster"]
    assert cluster["quorum"] is True
    assert cluster["nodes_total"] == 4
    assert cluster["nodes_online"] == 4


def test_discover_imports_nodes_and_workloads_directly(client, db, monkeypatch):
    from app.db.models import Hardware, ScanJob
    from app.services import proxmox_service

    _mock_vault(monkeypatch)
    create = client.post(
        "/api/v1/integrations/proxmox",
        json={
            "name": "Direct Import Test",
            "config_url": "https://8.8.8.8:8006",
            "api_token": "user@pam!tok=val",
        },
    )
    integration_id = create.json()["id"]

    class _FakeClient:
        async def discover_cluster(self):
            return {
                "resources": [
                    {"type": "node", "node": "pve1", "status": "online"},
                    {"type": "qemu", "vmid": 101, "name": "vm-web", "node": "pve1", "status": "running"},
                    {"type": "lxc", "vmid": 202, "name": "ct-dns", "node": "pve1", "status": "stopped"},
                ],
                "cluster_status": [{"type": "cluster", "name": "pve-cluster"}],
            }

        async def get_node_storage(self, _node):
            return []

    from app.services import proxmox_discovery
    monkeypatch.setattr(proxmox_service, "_get_client", lambda _db, _cfg: _FakeClient())
    monkeypatch.setattr(proxmox_discovery, "_get_client", lambda _db, _cfg: _FakeClient())

    resp = client.post(f"/api/v1/integrations/proxmox/{integration_id}/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["nodes_imported"] == 1
    assert data["vms_imported"] == 1
    assert data["cts_imported"] == 1
    # Direct import — nothing queued for review
    assert data["results_queued"] == 0
    assert data.get("review_job_id") is None

    # Node is directly imported, not held in review queue
    imported_node = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == integration_id,
            Hardware.proxmox_node_name == "pve1",
        )
        .first()
    )
    assert imported_node is not None

    # No ScanJob created for direct import path
    job = db.query(ScanJob).filter(ScanJob.source_type == "proxmox").first()
    assert job is None


def test_accepting_proxmox_node_reattaches_queued_storage(db):
    from app.core.time import utcnow_iso
    from app.db.models import IntegrationConfig, ScanJob, ScanResult, Storage
    from app.services.discovery_service import merge_scan_result

    now = utcnow_iso()
    config = IntegrationConfig(
        type="proxmox",
        name="Attach Storage Cluster",
        config_url="https://8.8.8.8:8006",
    )
    db.add(config)
    db.flush()

    db.add(
        Storage(
            name="local-lvm@pve1",
            kind="pool",
            hardware_id=None,
            integration_config_id=config.id,
            proxmox_storage_name="local-lvm",
            capacity_gb=200,
            used_gb=50,
            protocol="lvmthin",
        )
    )

    job = ScanJob(
        scan_types_json='["proxmox"]',
        status="completed",
        source_type="proxmox",
        created_at=now,
    )
    db.add(job)
    db.flush()

    payload = {
        "source": "proxmox",
        "kind": "node",
        "integration_id": config.id,
        "node_name": "pve1",
        "status": "online",
        "cpu": 0.3,
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,
        "uptime": 12345,
    }
    result = ScanResult(
        scan_job_id=job.id,
        ip_address="10.0.0.10",
        hostname="pve1",
        source_type="proxmox",
        state="new",
        merge_status="pending",
        raw_nmap_xml=json.dumps(payload),
        created_at=now,
    )
    db.add(result)
    db.commit()

    merged = merge_scan_result(db, result.id, "accept", actor="test")
    assert merged["entity_type"] == "hardware"
    hardware_id = merged["entity_id"]
    assert hardware_id is not None

    storage = (
        db.query(Storage)
        .filter(
            Storage.integration_config_id == config.id,
            Storage.proxmox_storage_name == "local-lvm",
        )
        .one()
    )
    assert storage.hardware_id == hardware_id


def test_proxmox_not_found(client):
    r = client.get("/api/v1/integrations/proxmox/9999")
    assert r.status_code == 404


# ── Client token parsing ─────────────────────────────────────────────────────


def test_build_client_from_token():
    """build_client_from_token parses URL and token correctly."""
    with patch.dict("sys.modules", {"proxmoxer": MagicMock()}):
        from app.integrations.proxmox_client import build_client_from_token

        c = build_client_from_token("https://pve.local:8006", "root@pam!cbtoken=secret123")
        assert c.host == "pve.local:8006"


def test_build_client_invalid_token():
    from app.integrations.proxmox_client import build_client_from_token

    with pytest.raises(ValueError, match="Invalid Proxmox API token"):
        build_client_from_token("https://pve.local:8006", "bad-token-no-bang")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_vault(monkeypatch):
    """Provide a working vault for tests that create integrations."""
    from app.services.credential_vault import get_vault

    vault = get_vault()
    if not vault.is_initialized:
        from cryptography.fernet import Fernet
        vault.reinitialize(Fernet.generate_key().decode())


# ── CPU percentage clamping tests ───────────────────────────────────────────

def _make_cluster(db, config):
    from app.db.models import HardwareCluster

    cluster = HardwareCluster(name="test-cluster", type="proxmox", integration_config_id=config.id)
    db.add(cluster)
    db.flush()
    return cluster


def test_node_cpu_percentage_conversion(db):
    """Test that node CPU values are correctly converted from decimal to percentage."""
    from app.db.models import IntegrationConfig
    from app.services.proxmox_discovery import _upsert_node

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()
    cluster = _make_cluster(db, config)

    # Test normal CPU values: 0.3 should become 30%
    node_res = {
        "node": "pve1",
        "status": "online",
        "cpu": 0.3,
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,
        "uptime": 12345,
    }

    hw = _upsert_node(db, config, cluster, "pve1", node_res)
    telemetry = hw.telemetry_data or {}

    assert telemetry.get("cpu_pct") == 30.0, "CPU 0.3 should convert to 30%"
    assert 0 <= telemetry.get("cpu_pct", 0) <= 100, "CPU percentage should be between 0-100"


def test_node_cpu_percentage_clamped_at_100(db):
    """Test that CPU values are clamped to 100% maximum (defensive against API anomalies)."""
    from app.db.models import IntegrationConfig
    from app.services.proxmox_discovery import _upsert_node

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()
    cluster = _make_cluster(db, config)

    # Even if API returns > 1.0 (shouldn't happen, but defensive)
    node_res = {
        "node": "pve1",
        "status": "online",
        "cpu": 1.5,  # Should clamp to 100%
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,
        "uptime": 12345,
    }

    hw = _upsert_node(db, config, cluster, "pve1", node_res)
    telemetry = hw.telemetry_data or {}

    assert telemetry.get("cpu_pct") == 100.0, "CPU > 1.0 should clamp to 100%"
    assert telemetry.get("cpu_pct") <= 100, "CPU percentage must never exceed 100%"


def test_node_cpu_zero_value(db):
    """Test that zero CPU value is handled correctly."""
    from app.db.models import IntegrationConfig
    from app.services.proxmox_discovery import _upsert_node

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()
    cluster = _make_cluster(db, config)

    node_res = {
        "node": "pve1",
        "status": "online",
        "cpu": 0,
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,
        "uptime": 12345,
    }

    hw = _upsert_node(db, config, cluster, "pve1", node_res)
    telemetry = hw.telemetry_data or {}

    assert telemetry.get("cpu_pct") == 0.0, "CPU 0 should be 0%"


def test_vm_cpu_percentage_conversion(db):
    """Test that VM CPU values are correctly converted from decimal to percentage."""
    from app.db.models import IntegrationConfig, Hardware
    from app.services.proxmox_discovery import _upsert_vm

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()

    hw = Hardware(name="pve1", role="hypervisor", proxmox_node_name="pve1")
    db.add(hw)
    db.flush()

    # Test VM CPU values: 0.5 should become 50%
    vm_res = {
        "vmid": 100,
        "name": "vm-test",
        "node": "pve1",
        "status": "running",
        "cpu": 0.5,
        "maxcpu": 4,
        "mem": 4 * 1024**3,
        "maxmem": 8 * 1024**3,
        "maxdisk": 100 * 1024**3,
    }

    cu = _upsert_vm(db, config, vm_res, "qemu", {"pve1": hw}, None)
    pve_status = cu.proxmox_status or {}

    assert pve_status.get("cpu_pct") == 50.0, "CPU 0.5 should convert to 50%"
    assert 0 <= pve_status.get("cpu_pct", 0) <= 100, "CPU percentage should be between 0-100"


def test_vm_cpu_percentage_clamped_at_100(db):
    """Test that VM CPU values are clamped to 100% maximum."""
    from app.db.models import IntegrationConfig, Hardware
    from app.services.proxmox_discovery import _upsert_vm

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()

    hw = Hardware(name="pve1", role="hypervisor", proxmox_node_name="pve1")
    db.add(hw)
    db.flush()

    # Edge case: CPU value > 1.0 should clamp to 100%
    vm_res = {
        "vmid": 101,
        "name": "vm-test2",
        "node": "pve1",
        "status": "running",
        "cpu": 2.5,  # Defensive: shouldn't happen but we clamp it
        "maxcpu": 4,
        "mem": 4 * 1024**3,
        "maxmem": 8 * 1024**3,
        "maxdisk": 100 * 1024**3,
    }

    cu = _upsert_vm(db, config, vm_res, "qemu", {"pve1": hw}, None)
    pve_status = cu.proxmox_status or {}

    assert pve_status.get("cpu_pct") == 100.0, "CPU > 1.0 should clamp to 100%"
    assert pve_status.get("cpu_pct") <= 100, "CPU percentage must never exceed 100%"


def test_telemetry_status_based_on_cpu(db):
    """Test that telemetry_status is correctly set based on CPU percentage."""
    from app.db.models import IntegrationConfig
    from app.services.proxmox_discovery import _upsert_node

    config = IntegrationConfig(
        type="proxmox",
        name="Test",
        config_url="https://test:8006",
    )
    db.add(config)
    db.flush()
    cluster = _make_cluster(db, config)

    # High CPU (> 90%) should mark as critical
    node_res_critical = {
        "node": "pve1",
        "status": "online",
        "cpu": 0.95,  # 95% — critical
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,  # 25% memory
        "uptime": 12345,
    }

    hw_critical = _upsert_node(db, config, cluster, "pve1", node_res_critical)
    assert hw_critical.telemetry_status == "critical", "CPU > 90% should mark as critical"

    # Medium CPU (70-90%) should mark as degraded
    node_res_degraded = {
        "node": "pve2",
        "status": "online",
        "cpu": 0.75,  # 75% — degraded
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,  # 25% memory
        "uptime": 12345,
    }

    hw_degraded = _upsert_node(db, config, cluster, "pve2", node_res_degraded)
    assert hw_degraded.telemetry_status == "degraded", "CPU 70-90% should mark as degraded"

    # Low CPU (< 70%) with low memory should mark as healthy
    node_res_healthy = {
        "node": "pve3",
        "status": "online",
        "cpu": 0.30,  # 30% — healthy
        "maxmem": 32 * 1024**3,
        "mem": 8 * 1024**3,  # 25% memory
        "uptime": 12345,
    }

    hw_healthy = _upsert_node(db, config, cluster, "pve3", node_res_healthy)
    assert hw_healthy.telemetry_status == "healthy", "CPU < 70% should mark as healthy"


# ── Existing helper ────────────────────────────────────────────────────────

