"""Proxmox telemetry polling — node, RRD, VM, and storage background jobs."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.db.models import (
    ComputeUnit,
    Hardware,
    IntegrationConfig,
    Storage,
    TelemetryTimeseries,
)
from app.services.proxmox_client import (
    _get_client_async,
    _publish,
)

_logger = logging.getLogger(__name__)


# ── Storage refresh (used/total for cluster overview) ──────────────────────────


async def refresh_proxmox_storage(db: AsyncSession) -> None:
    """Update used_gb/capacity_gb for all Proxmox Storage rows from PVE nodes.
    Lighter than full sync; run on a schedule so cluster overview has fresh storage data."""
    configs = (
        (
            await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for config in configs:
        try:
            client = await _get_client_async(db, config)
            nodes = (
                (
                    await db.execute(
                        select(Hardware).where(
                            Hardware.integration_config_id == config.id,
                            Hardware.proxmox_node_name.isnot(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for hw in nodes:
                if not hw.proxmox_node_name:
                    continue
                try:
                    storage_list = await client.get_node_storage(hw.proxmox_node_name)
                except Exception as e:
                    _logger.debug("Storage refresh failed for node %s: %s", hw.proxmox_node_name, e)
                    continue
                for st_data in storage_list:
                    name = st_data.get("storage", "")
                    if not name:
                        continue
                    total_bytes = st_data.get("total", 0)
                    used_bytes = st_data.get("used", 0)
                    existing = (
                        await db.execute(
                            select(Storage).where(
                                Storage.proxmox_storage_name == name,
                                Storage.hardware_id == hw.id,
                                Storage.integration_config_id == config.id,
                            )
                        )
                    ).scalar_one_or_none()
                    if existing:
                        existing.capacity_gb = (
                            round(total_bytes / (1024**3)) if total_bytes else None
                        )
                        existing.used_gb = round(used_bytes / (1024**3)) if used_bytes else None
            await db.commit()
        except Exception as e:
            _logger.warning("Storage refresh failed for integration %d: %s", config.id, e)
            await db.rollback()


# ── Telemetry polling ────────────────────────────────────────────────────────


async def poll_node_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
    """Poll all active Proxmox nodes for CPU/RAM/load metrics (parallel per integration)."""
    configs = (
        (
            await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    poll_outcomes: dict[int, Exception | None] = {}

    from app.core.circuit_breaker import get_breaker

    for config in configs:
        config_id = config.id
        breaker = get_breaker(f"proxmox:{config_id}:poll")
        if breaker.is_open():
            _logger.debug(
                "Proxmox integration %d circuit open — skipping telemetry poll", config_id
            )
            poll_outcomes[config_id] = RuntimeError("Circuit breaker open — telemetry poll skipped")
            continue
        try:
            client = await _get_client_async(db, config)
            nodes = (
                (
                    await db.execute(
                        select(Hardware).where(
                            Hardware.integration_config_id == config_id,
                            Hardware.proxmox_node_name.isnot(None),
                        )
                    )
                )
                .scalars()
                .all()
            )

            async def _fetch_node(hw: Hardware, _client: Any = client) -> tuple[Hardware, Any]:
                return hw, await _client.get_node_status(hw.proxmox_node_name)

            results = await asyncio.gather(
                *[_fetch_node(hw) for hw in nodes],
                return_exceptions=True,
            )

            now = utcnow()
            node_success_count = 0
            node_fail_errors: list[str] = []
            for result in results:
                if isinstance(result, Exception):
                    err_str = str(result)
                    _logger.debug("Telemetry poll failed for a node: %s", result)
                    node_fail_errors.append(err_str)
                    continue
                hw, status = result  # type: ignore[misc]
                try:
                    cpu_raw = status.get("cpu", 0)
                    # Proxmox API returns CPU as decimal fraction (0.0-1.0);
                    # convert to percentage and clamp to 0-100
                    cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
                    # PVE can return memory as nested (memory.used/total) or top-level (mem, maxmem)
                    mem = status.get("memory", {})
                    mem_used = mem.get("used") or status.get("mem", 0)
                    mem_total = mem.get("total") or status.get("maxmem", 0)
                    load = status.get("loadavg", [0, 0, 0])
                    rootfs = status.get("rootfs", {})
                    root_used = rootfs.get("used") if isinstance(rootfs, dict) else 0
                    root_total = rootfs.get("total") if isinstance(rootfs, dict) else 0
                    if not root_used and "root" in status:
                        root_used = status.get("root", 0)
                    if not root_total and "maxroot" in status:
                        root_total = status.get("maxroot", 0)
                    netin = status.get("netin", 0)
                    netout = status.get("netout", 0)
                    swap_used = status.get("swap", 0)
                    maxswap = status.get("maxswap", 0)

                    telemetry = {
                        "cpu_pct": cpu_pct,
                        "mem_used_gb": round(mem_used / (1024**3), 1) if mem_used else 0,
                        "mem_total_gb": round(mem_total / (1024**3), 1) if mem_total else 0,
                        "load_1m": load[0] if load else 0,
                        "load_5m": load[1] if len(load) > 1 else 0,
                        "load_15m": load[2] if len(load) > 2 else 0,
                        "disk_used_gb": round((root_used or 0) / (1024**3), 1),
                        "disk_total_gb": round((root_total or 0) / (1024**3), 1),
                        "uptime_s": status.get("uptime", 0),
                        "netin": netin,
                        "netout": netout,
                        "swap_gb": round(swap_used / (1024**3), 1) if swap_used else 0,
                        "maxswap_gb": round(maxswap / (1024**3), 1) if maxswap else 0,
                    }

                    hw.telemetry_data = telemetry
                    hw.telemetry_last_polled = now

                    if cpu_pct > 90 or (mem_used / max(mem_total, 1) > 0.95):
                        hw.telemetry_status = "critical"
                    elif cpu_pct > 70 or (mem_used / max(mem_total, 1) > 0.85):
                        hw.telemetry_status = "degraded"
                    else:
                        hw.telemetry_status = "healthy"

                    for metric_name, value in [
                        ("cpu_pct", cpu_pct),
                        ("mem_used_gb", round(mem_used / (1024**3), 1) if mem_used else 0),
                        ("netin", netin),
                        ("netout", netout),
                    ]:
                        db.add(
                            TelemetryTimeseries(
                                entity_type="hardware",
                                entity_id=hw.id,
                                metric=metric_name,
                                value=value,
                                source="proxmox",
                                ts=now,
                            )
                        )

                    await _publish(
                        "telemetry.proxmox.node",
                        {
                            "hardware_id": hw.id,
                            "node": hw.proxmox_node_name,
                            "telemetry": telemetry,
                            "status": hw.telemetry_status,
                        },
                    )

                    from app.services.telemetry_cache import (
                        cache_telemetry as _redis_cache,
                    )
                    from app.services.telemetry_cache import (
                        publish_telemetry as _redis_pub,
                    )

                    _tdata = {"data": telemetry, "status": hw.telemetry_status}
                    await _redis_cache(hw.id, _tdata)
                    await _redis_pub(hw.id, _tdata)

                    node_success_count += 1
                except Exception as e:
                    _logger.debug("Telemetry apply failed for node %s: %s", hw.proxmox_node_name, e)

            # Surface auth/permission failures when every node poll failed
            if nodes and node_success_count == 0 and node_fail_errors:
                first_err = node_fail_errors[0]
                is_auth = any(
                    kw in first_err for kw in ("403", "Forbidden", "Permission check failed", "401")
                )
                if is_auth:
                    hint = (
                        f"All {len(nodes)} node(s) returned permission errors "
                        f"({first_err.strip()[:120]}). "
                        "The API token likely lacks Sys.Audit. Fix: Proxmox → Datacenter → "
                        "Permissions → Add → API Token Permission, "
                        "Role=PVEAuditor, Path=/, Propagate=yes."
                    )
                    _logger.warning("Proxmox integration %d: %s", config_id, hint)
                    config.last_poll_error = hint

            await db.commit()
            breaker.record_success()
            poll_outcomes[config_id] = None
        except Exception as e:
            breaker.record_failure()
            _logger.warning("Telemetry poll failed for integration %d: %s", config_id, e)
            poll_outcomes[config_id] = e
    return poll_outcomes


async def poll_rrd_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
    """Poll RRD data for each Proxmox node and store in TelemetryTimeseries (source=proxmox_rrd).
    Provides time-series for CPU, memory, disk, network, io_delay for cluster overview charts."""
    configs = (
        (
            await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    poll_outcomes: dict[int, Exception | None] = {}

    for config in configs:
        try:
            client = await _get_client_async(db, config)
            nodes = (
                (
                    await db.execute(
                        select(Hardware).where(
                            Hardware.integration_config_id == config.id,
                            Hardware.proxmox_node_name.isnot(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for hw in nodes:
                node = hw.proxmox_node_name
                if not node:
                    continue
                try:
                    raw = await client.get_node_rrddata(node, timeframe="hour")
                except Exception as e:
                    _logger.debug("RRD poll failed for node %s: %s", node, e)
                    continue
                if not isinstance(raw, list):
                    continue  # type: ignore[unreachable]
                # PVE returns list of dicts: time (unix), cpu, mem, maxmem,
                # diskread, diskwrite, netin, netout, etc.
                for point in raw:
                    if not isinstance(point, dict):
                        continue  # type: ignore[unreachable]
                    ts_unix = point.get("time")
                    if ts_unix is None:
                        continue
                    try:
                        ts = datetime.datetime.fromtimestamp(int(ts_unix), tz=datetime.UTC)
                    except (ValueError, TypeError, OSError):
                        continue
                    # Store metrics that are present (float or int)
                    metrics_to_store = [
                        (
                            "rrd_cpu",
                            point.get("cpu"),
                            lambda v: float(v) * 100 if v is not None else None,
                        ),
                        (
                            "rrd_memused",
                            point.get("mem"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_memtotal",
                            point.get("maxmem"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_netin",
                            point.get("netin"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_netout",
                            point.get("netout"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_diskread",
                            point.get("diskread"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_diskwrite",
                            point.get("diskwrite"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_io_delay",
                            point.get("io_delay"),
                            lambda v: float(v) if v is not None else None,
                        ),
                        (
                            "rrd_zfs_arc_size",
                            point.get("zfs_arc_size"),
                            lambda v: float(v) if v is not None else None,
                        ),
                    ]
                    for metric_name, raw_val, normalize in metrics_to_store:
                        val = normalize(raw_val)
                        if val is not None:
                            db.add(
                                TelemetryTimeseries(
                                    entity_type="hardware",
                                    entity_id=hw.id,
                                    metric=metric_name,
                                    value=val,
                                    source="proxmox_rrd",
                                    ts=ts,
                                )
                            )
            await db.commit()
            poll_outcomes[config.id] = None
        except Exception as e:
            _logger.warning("RRD telemetry poll failed for integration %d: %s", config.id, e)
            poll_outcomes[config.id] = e
            await db.rollback()
    return poll_outcomes


async def poll_vm_telemetry(db: AsyncSession) -> dict[int, Exception | None]:
    """Poll all active Proxmox VMs/CTs for live stats (parallel per integration)."""
    configs = (
        (
            await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.type == "proxmox",
                    IntegrationConfig.auto_sync.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    poll_outcomes: dict[int, Exception | None] = {}

    for config in configs:
        config_id = config.id
        try:
            client = await _get_client_async(db, config)
            compute_units = (
                (
                    await db.execute(
                        select(ComputeUnit).where(
                            ComputeUnit.integration_config_id == config_id,
                            ComputeUnit.proxmox_vmid.isnot(None),
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Batch-load hardware for this integration to avoid N+1 per VM.
            hw_map = {
                hw.id: hw
                for hw in (
                    await db.execute(
                        select(Hardware).where(
                            Hardware.integration_config_id == config_id,
                        )
                    )
                )
                .scalars()
                .all()
            }

            async def _fetch_vm(
                cu: ComputeUnit, _hw_map: Any = hw_map, _client: Any = client
            ) -> tuple[ComputeUnit, Any] | None:
                hw = _hw_map.get(cu.hardware_id)
                if not hw or not hw.proxmox_node_name:
                    return None
                vm_type = cu.proxmox_type or "qemu"
                status = await _client.get_vm_status(
                    hw.proxmox_node_name,
                    cu.proxmox_vmid,
                    vm_type,
                )
                return cu, status

            results = await asyncio.gather(
                *[_fetch_vm(cu) for cu in compute_units],
                return_exceptions=True,
            )

            now = utcnow()
            for result in results:
                if isinstance(result, Exception):
                    _logger.debug("Telemetry poll failed for a VM: %s", result)
                    continue
                if result is None:
                    continue
                cu, status = result  # type: ignore[misc]
                try:
                    cpu_pct = round(status.get("cpu", 0) * 100, 1)
                    maxmem = status.get("maxmem", 0)
                    mem = status.get("mem", 0)
                    netin = status.get("netin", 0)
                    netout = status.get("netout", 0)
                    maxdisk = status.get("maxdisk", 0)
                    disk = status.get("disk", 0)

                    pve_status = json.dumps(
                        {
                            "status": status.get("status", "unknown"),
                            "cpu_pct": cpu_pct,
                            "mem_used_bytes": mem,
                            "mem_total_bytes": maxmem,
                            "disk_used_bytes": disk,
                            "disk_total_bytes": maxdisk,
                            "netin": netin,
                            "netout": netout,
                        }
                    )

                    cu.proxmox_status = pve_status
                    cu.status = "active" if status.get("status") == "running" else "inactive"

                    db.add(
                        TelemetryTimeseries(
                            entity_type="compute_unit",
                            entity_id=cu.id,
                            metric="cpu_pct",
                            value=cpu_pct,
                            source="proxmox",
                            ts=now,
                        )
                    )

                    await _publish(
                        "telemetry.proxmox.vm",
                        {
                            "compute_unit_id": cu.id,
                            "vmid": cu.proxmox_vmid,
                            "status": cu.status,
                            "telemetry": json.loads(pve_status),
                        },
                    )

                    from app.services.telemetry_cache import publish_telemetry as _redis_pub_vm

                    await _redis_pub_vm(
                        cu.id,
                        {
                            "data": json.loads(pve_status),
                            "status": cu.status,
                            "entity_type": "compute_unit",
                        },
                    )
                except Exception as e:
                    _logger.debug("Telemetry apply failed for VM %s: %s", cu.proxmox_vmid, e)

            await db.commit()
            poll_outcomes[config_id] = None
        except Exception as e:
            _logger.warning("VM telemetry poll failed for integration %d: %s", config_id, e)
            poll_outcomes[config_id] = e
    return poll_outcomes
