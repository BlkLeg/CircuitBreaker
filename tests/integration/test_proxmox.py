"""Tests for the Proxmox VE integration API endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

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
        "config_url": "https://pve.local:8006",
        "api_token": "root@pam!cbtoken=secret123",
        "auto_sync": True,
        "sync_interval_s": 300,
        "verify_ssl": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test PVE"
    assert data["type"] == "proxmox"
    assert data["config_url"] == "https://pve.local:8006"
    assert "api_token" not in data  # token must not leak


def test_get_proxmox_config(client, monkeypatch):
    _mock_vault(monkeypatch)
    create = client.post("/api/v1/integrations/proxmox", json={
        "name": "My Cluster",
        "config_url": "https://pve.local:8006",
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
        "config_url": "https://pve.local:8006",
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
        "config_url": "https://pve.local:8006",
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
        "config_url": "https://pve.local:8006",
        "api_token": "user@pam!tok=val",
    })
    cid = create.json()["id"]

    r = client.get(f"/api/v1/integrations/proxmox/{cid}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["integration_id"] == cid
    assert data["nodes_count"] == 0
    assert data["vms_count"] == 0


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
