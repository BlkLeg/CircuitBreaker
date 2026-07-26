"""Tests for the Proxmox VM-poll path setting telemetry_last_polled."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_poll_vm_telemetry_sets_telemetry_last_polled(async_db_session):
    from app.db.models import ComputeUnit, Hardware, IntegrationConfig
    from app.services.proxmox_telemetry import poll_vm_telemetry

    config = IntegrationConfig(
        type="proxmox", name="pve", config_url="https://pve.local:8006", auto_sync=True
    )
    async_db_session.add(config)
    await async_db_session.flush()

    hw = Hardware(name="pve-node-1", proxmox_node_name="pve1", integration_config_id=config.id)
    async_db_session.add(hw)
    await async_db_session.flush()

    cu = ComputeUnit(
        name="vm-100",
        kind="vm",
        hardware_id=hw.id,
        proxmox_vmid=100,
        proxmox_type="qemu",
        integration_config_id=config.id,
    )
    async_db_session.add(cu)
    await async_db_session.flush()
    assert cu.telemetry_last_polled is None

    fake_client = AsyncMock()
    fake_client.get_vm_status.return_value = {
        "status": "running",
        "cpu": 0.1,
        "maxmem": 1024,
        "mem": 512,
        "netin": 0,
        "netout": 0,
        "maxdisk": 0,
        "disk": 0,
    }
    with (
        patch(
            "app.services.proxmox_telemetry._get_client_async",
            AsyncMock(return_value=fake_client),
        ),
        patch("app.services.proxmox_telemetry._publish", AsyncMock()),
        patch("app.services.telemetry_cache.publish_telemetry", AsyncMock()),
    ):
        await poll_vm_telemetry(async_db_session)

    await async_db_session.refresh(cu)
    assert cu.status == "active"
    assert cu.telemetry_last_polled is not None
