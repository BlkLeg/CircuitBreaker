"""Proxmox-specific entity upsert and merge helpers for discovery."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utcnow_iso  # noqa: F401 — re-exported for callers
from app.db.models import ComputeUnit, Hardware, ScanResult, Storage
from app.services.discovery_network import _norm_mac  # noqa: F401
from app.services.log_service import write_log

logger = logging.getLogger(__name__)


def _parse_proxmox_metadata(result: ScanResult) -> dict[str, Any] | None:
    if result.source_type != "proxmox":
        return None
    if not result.raw_nmap_xml:
        return None
    try:
        payload = json.loads(result.raw_nmap_xml)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("source") != "proxmox":
        return None
    return payload


def _reattach_proxmox_storage_to_node(
    db: Session,
    integration_id: int | None,
    node_name: str | None,
    hardware_id: int,
) -> None:
    """Attach queued Proxmox storage rows to their accepted node entity."""
    if not integration_id:
        return

    node = (node_name or "").strip()
    if not node:
        return

    suffix = f"@{node}"
    orphaned = (
        db.query(Storage)
        .filter(
            Storage.integration_config_id == integration_id,
            Storage.hardware_id.is_(None),
        )
        .all()
    )

    for st in orphaned:
        if not st.name or not st.name.endswith(suffix):
            continue

        duplicate = (
            db.query(Storage)
            .filter(
                Storage.integration_config_id == integration_id,
                Storage.hardware_id == hardware_id,
                Storage.proxmox_storage_name == st.proxmox_storage_name,
            )
            .first()
        )
        if duplicate:
            # Keep a single row per (integration, node, proxmox storage) and refresh metrics.
            duplicate.kind = st.kind or duplicate.kind
            duplicate.capacity_gb = st.capacity_gb
            duplicate.used_gb = st.used_gb
            duplicate.protocol = st.protocol or duplicate.protocol
            if st.notes:
                duplicate.notes = st.notes
            db.delete(st)
            continue

        st.hardware_id = hardware_id

    db.flush()


def _upsert_proxmox_node_entity(
    db: Session,
    payload: dict[str, Any],
    now_iso: str,
) -> Hardware:
    integration_id = payload.get("integration_id")
    node_name = str(payload.get("node_name") or "").strip()
    if not node_name:
        node_name = str(payload.get("name") or "proxmox-node").strip()

    hw = (
        db.query(Hardware)
        .filter(
            Hardware.integration_config_id == integration_id,
            Hardware.proxmox_node_name == node_name,
        )
        .first()
    )

    status_str = str(payload.get("status") or "unknown")
    cpu_pct = payload.get("cpu", 0) or 0
    maxmem = payload.get("maxmem", 0) or 0
    mem = payload.get("mem", 0) or 0
    uptime = payload.get("uptime", 0) or 0
    telemetry = json.dumps(
        {
            "cpu_pct": round(float(cpu_pct) * 100, 1) if cpu_pct else 0,
            "mem_used_bytes": mem,
            "mem_total_bytes": maxmem,
            "uptime_s": uptime,
            "status": status_str,
        }
    )
    now_dt = datetime.fromisoformat(now_iso) if "T" in now_iso else datetime.now(UTC)

    if not hw:
        hw = Hardware(
            name=node_name,
            role="hypervisor",
            vendor="Proxmox",
            vendor_icon_slug="proxmox-dark",
            proxmox_node_name=node_name,
            integration_config_id=integration_id,
            status="active" if status_str == "online" else "inactive",
            source="discovery",
            telemetry_data=telemetry,
            telemetry_status="healthy" if status_str == "online" else "unknown",
            telemetry_last_polled=now_iso,
            ip_address=payload.get("ip"),
            memory_gb=round(maxmem / (1024**3)) if maxmem else None,
            discovered_at=now_iso,
            last_seen=now_iso,
            created_at=now_dt,
            updated_at=now_dt,
        )
        db.add(hw)
    else:
        hw.name = node_name or hw.name
        hw.status = "active" if status_str == "online" else "inactive"
        hw.vendor = "Proxmox"
        hw.vendor_icon_slug = hw.vendor_icon_slug or "proxmox-dark"
        hw.telemetry_data = telemetry  # type: ignore[assignment]
        hw.telemetry_status = "healthy" if status_str == "online" else "unknown"
        hw.telemetry_last_polled = now_iso  # type: ignore[assignment]
        if payload.get("ip"):
            hw.ip_address = payload.get("ip")
        hw.last_seen = now_iso
    db.flush()
    _reattach_proxmox_storage_to_node(db, integration_id, node_name, hw.id)
    return hw


def _upsert_proxmox_vm_entity(
    db: Session,
    payload: dict[str, Any],
    now_iso: str,
) -> ComputeUnit:
    integration_id = payload.get("integration_id")
    node_name = str(payload.get("node_name") or "").strip()
    vmid_raw = payload.get("vmid")
    vmid = int(vmid_raw) if vmid_raw is not None else None
    vm_type = str(payload.get("vm_type") or "qemu").strip().lower()
    vm_name = str(payload.get("name") or f"{vm_type}-{vmid or 'unknown'}").strip()

    parent = None
    if node_name:
        parent = (
            db.query(Hardware)
            .filter(
                Hardware.integration_config_id == integration_id,
                Hardware.proxmox_node_name == node_name,
            )
            .first()
        )
    if not parent:
        now_dt = datetime.fromisoformat(now_iso) if "T" in now_iso else datetime.now(UTC)
        parent = Hardware(
            name=node_name or f"Proxmox node {integration_id}",
            role="hypervisor",
            vendor="Proxmox",
            vendor_icon_slug="proxmox-dark",
            proxmox_node_name=node_name or None,
            integration_config_id=integration_id,
            status="unknown",
            source="discovery",
            discovered_at=now_iso,
            last_seen=now_iso,
            created_at=now_dt,
            updated_at=now_dt,
        )
        db.add(parent)
        db.flush()
    _reattach_proxmox_storage_to_node(db, integration_id, node_name, parent.id)

    cu = (
        db.query(ComputeUnit)
        .filter(
            ComputeUnit.integration_config_id == integration_id,
            ComputeUnit.proxmox_vmid == vmid,
        )
        .first()
    )

    status_str = str(payload.get("status") or "unknown")
    pve_status = {
        "status": status_str,
        "cpu_pct": round(float(payload.get("cpu", 0) or 0) * 100, 1),
        "mem_used_bytes": payload.get("mem", 0) or 0,
        "mem_total_bytes": payload.get("maxmem", 0) or 0,
        "disk_total_bytes": payload.get("maxdisk", 0) or 0,
    }

    kind = "container" if vm_type == "lxc" else "vm"
    if not cu:
        cu = ComputeUnit(
            name=vm_name,
            kind=kind,
            hardware_id=parent.id,
            proxmox_vmid=vmid,
            proxmox_type=vm_type,
            proxmox_status=pve_status,
            integration_config_id=integration_id,
            status="active" if status_str == "running" else "inactive",
            cpu_cores=payload.get("maxcpu") or None,
            memory_mb=round((payload.get("maxmem", 0) or 0) / (1024**2))
            if payload.get("maxmem")
            else None,
            disk_gb=round((payload.get("maxdisk", 0) or 0) / (1024**3))
            if payload.get("maxdisk")
            else None,
        )
        db.add(cu)
    else:
        cu.name = vm_name
        cu.kind = kind
        cu.hardware_id = parent.id
        cu.proxmox_type = vm_type
        cu.proxmox_status = pve_status
        cu.status = "active" if status_str == "running" else "inactive"
        if payload.get("maxcpu"):
            cu.cpu_cores = payload.get("maxcpu")
        if payload.get("maxmem"):
            cu.memory_mb = round((payload.get("maxmem") or 0) / (1024**2))
        if payload.get("maxdisk"):
            cu.disk_gb = round((payload.get("maxdisk") or 0) / (1024**3))
    db.flush()
    return cu


def _merge_proxmox_result(
    db: Session,
    result: ScanResult,
    overrides: dict,
    actor: str,
    now_iso: str,
) -> dict:
    from fastapi import HTTPException

    from app.services.discovery_merge import _assign_to_default_map, _emit_result_processed_event

    payload = _parse_proxmox_metadata(result)
    if payload is None:
        raise HTTPException(status_code=400, detail="Invalid Proxmox discovery payload")

    kind = str(payload.get("kind") or "").strip().lower()
    entity: Hardware | ComputeUnit
    if kind == "node":
        entity = _upsert_proxmox_node_entity(db, payload, now_iso)
        result.matched_entity_type = "hardware"
        result.matched_entity_id = entity.id
        allowed_override_keys = {"name", "ip_address", "vendor", "status", "notes"}
    elif kind == "vm":
        entity = _upsert_proxmox_vm_entity(db, payload, now_iso)
        result.matched_entity_type = "compute_unit"
        result.matched_entity_id = entity.id
        allowed_override_keys = {"name", "status", "cpu_cores", "memory_mb", "disk_gb", "notes"}
    else:
        raise HTTPException(status_code=400, detail="Unsupported Proxmox discovery entity type")

    for k, v in overrides.items():
        if k in allowed_override_keys and hasattr(entity, k):
            setattr(entity, k, v)

    result.merge_status = "accepted"
    result.reviewed_by = actor
    result.reviewed_at = now_iso

    # Assign entity to the default map
    # matched_entity_type uses "compute_unit" for other systems (IP reservation, CVE);
    # the topology map uses "compute" for ComputeUnit nodes.
    map_entity_type = (
        "compute" if result.matched_entity_type == "compute_unit" else result.matched_entity_type
    )
    _assign_to_default_map(db, map_entity_type, entity.id)
    # For VMs, also ensure the parent hypervisor node is on the map
    if kind == "vm" and hasattr(entity, "hardware_id") and entity.hardware_id:
        _assign_to_default_map(db, "hardware", entity.hardware_id)

    db.commit()

    write_log(
        db,
        action="result_accepted",
        entity_type=result.matched_entity_type or "hardware",
        entity_id=result.matched_entity_id,
        category="discovery",
        actor=actor,
        details=json.dumps(
            {
                "scan_result_id": result.id,
                "source": "proxmox",
                "kind": kind,
                "ip": result.ip_address,
                "hostname": result.hostname,
                "overrides": overrides,
            }
        ),
    )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_emit_result_processed_event(db, result.id, "accept"))
        else:
            asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
    except Exception as e:
        logger.debug("Discovery: WebSocket emit accept (proxmox) failed: %s", e, exc_info=True)

    return {
        "entity_type": result.matched_entity_type,
        "entity_id": result.matched_entity_id,
        "source": "proxmox",
    }
