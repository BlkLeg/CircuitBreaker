"""Tests for Proxmox sync reconciliation logic.

Verifies that stale Storage, Hardware, and ComputeUnit records are deleted
when Proxmox no longer reports them after a sync.
"""

from unittest.mock import AsyncMock

import pytest

from app.db.models import ComputeUnit, Hardware, IntegrationConfig, Storage
from app.services.proxmox_discovery import (
    _import_node_storage,
    _reconcile_nodes,
    _reconcile_vms,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def integration(db_session):
    """Minimal IntegrationConfig for Proxmox tests."""
    cfg = IntegrationConfig(
        type="proxmox",
        name="test-cluster",
        config_url="https://pve.test:8006",
    )
    db_session.add(cfg)
    db_session.flush()
    return cfg


@pytest.fixture()
def hardware(db_session, integration):
    """A Hardware node linked to the integration."""
    hw = Hardware(
        name="pve1",
        role="hypervisor",
        proxmox_node_name="pve1",
        integration_config_id=integration.id,
    )
    db_session.add(hw)
    db_session.flush()
    return hw


# ── Storage reconciliation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_reconcile_removes_stale(setup_db, db_session, integration, hardware):
    """Storage entries no longer returned by Proxmox are deleted on sync."""
    # Seed 3 storage rows for the same node
    for name in ("local", "local-lvm", "old-pool"):
        db_session.add(
            Storage(
                name=f"{name}@pve1",
                kind="pool",
                hardware_id=hardware.id,
                integration_config_id=integration.id,
                proxmox_storage_name=name,
            )
        )
    db_session.flush()

    assert db_session.query(Storage).filter_by(hardware_id=hardware.id).count() == 3

    # Proxmox now only returns 2 of the 3 pools
    mock_client = AsyncMock()
    mock_client.get_node_storage.return_value = [
        {"storage": "local", "type": "dir", "total": 0, "used": 0, "active": 1},
        {"storage": "local-lvm", "type": "lvm", "total": 0, "used": 0, "active": 1},
    ]

    upserted, removed = await _import_node_storage(
        db_session, integration, mock_client, "pve1", hardware
    )

    # existing "local" + "local-lvm" are updated (not newly created), so upserted=0
    assert upserted == 0
    assert removed == 1

    remaining = db_session.query(Storage).filter_by(hardware_id=hardware.id).all()
    remaining_names = {s.proxmox_storage_name for s in remaining}
    assert remaining_names == {"local", "local-lvm"}
    assert "old-pool" not in remaining_names


# ── Node reconciliation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_nodes_removes_stale(setup_db, db_session, integration):
    """Hardware nodes no longer in the cluster are deleted on sync."""
    for node_name in ("pve1", "pve2", "pve3"):
        db_session.add(
            Hardware(
                name=node_name,
                role="hypervisor",
                proxmox_node_name=node_name,
                integration_config_id=integration.id,
            )
        )
    db_session.flush()

    assert db_session.query(Hardware).filter_by(integration_config_id=integration.id).count() == 3

    removed = await _reconcile_nodes(db_session, integration, {"pve1"})

    assert removed == 2

    remaining = db_session.query(Hardware).filter_by(integration_config_id=integration.id).all()
    assert len(remaining) == 1
    assert remaining[0].proxmox_node_name == "pve1"


# ── VM/CT reconciliation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_vms_removes_stale(setup_db, db_session, integration, hardware):
    """ComputeUnit records for deleted VMs/CTs are removed on sync."""
    for vmid in (100, 101, 102):
        db_session.add(
            ComputeUnit(
                name=f"vm-{vmid}",
                kind="vm",
                hardware_id=hardware.id,
                proxmox_vmid=vmid,
                proxmox_type="qemu",
                integration_config_id=integration.id,
            )
        )
    db_session.flush()

    assert (
        db_session.query(ComputeUnit).filter_by(integration_config_id=integration.id).count() == 3
    )

    removed = await _reconcile_vms(db_session, integration, {100, 101})

    assert removed == 1

    remaining = db_session.query(ComputeUnit).filter_by(integration_config_id=integration.id).all()
    assert len(remaining) == 2
    remaining_vmids = {cu.proxmox_vmid for cu in remaining}
    assert remaining_vmids == {100, 101}
    assert 102 not in remaining_vmids
