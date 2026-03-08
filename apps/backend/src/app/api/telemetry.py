import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeUnit, Hardware, Storage, TelemetryTimeseries
from app.db.session import get_db
from app.integrations.dispatcher import poll_hardware
from app.schemas.hardware import TelemetryConfig
from app.services.credential_vault import CredentialVault, get_vault

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])


@router.get("/{hardware_id}/telemetry")
def get_telemetry(hardware_id: int, db: Session = Depends(get_db)):
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    config = hw.telemetry_config
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (json.JSONDecodeError, TypeError):
            config = None

    data = hw.telemetry_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = {}  # type: ignore[assignment]

    return {
        "hardware_id": hardware_id,
        "name": hw.name,
        "vendor": hw.vendor,
        "model": hw.model,
        "telemetry_profile": config.get("profile") if config else None,
        "data": data or {},
        "status": hw.telemetry_status or "unknown",
        "last_polled": hw.telemetry_last_polled,
    }


@router.post("/{hardware_id}/telemetry/config")
def configure_telemetry(
    hardware_id: int,
    config: TelemetryConfig,
    db: Session = Depends(get_db),
    vault: CredentialVault = Depends(get_vault),
):
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    config_dict = config.model_dump()
    if config_dict.get("password"):
        config_dict["password"] = vault.encrypt(config_dict["password"])

    hw.telemetry_config = json.dumps(config_dict)
    db.commit()
    return {"message": "Telemetry config saved.", "hardware_id": hardware_id}


@router.post("/{hardware_id}/telemetry/poll")
def poll_now(
    hardware_id: int,
    db: Session = Depends(get_db),
    vault: CredentialVault = Depends(get_vault),
):
    """Manual on-demand poll."""
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    result = poll_hardware(hw, vault)
    if "error" in result and "status" not in result:
        _logger.error("Telemetry poll failed for hardware %d: %s", hardware_id, result["error"])
        raise HTTPException(status_code=502, detail="Telemetry poll failed.")
    if result.get("status") == "unknown" and "error" in result:
        _logger.error("Telemetry poll error for hardware %d: %s", hardware_id, result["error"])
        raise HTTPException(status_code=502, detail="Telemetry poll returned an error status.")

    hw.telemetry_data = json.dumps(result.get("data", {}))
    hw.telemetry_status = result.get("status", "unknown")
    hw.telemetry_last_polled = utcnow()
    # CB-STATE-005: touch last_seen on successful poll
    hw.last_seen = utcnow().isoformat()
    db.flush()
    # CB-STATE-001: recalculate derived hardware status from telemetry + children
    from app.services.status_service import recalculate_hardware_status

    recalculate_hardware_status(db, hardware_id)
    db.commit()

    return {
        "hardware_id": hardware_id,
        "data": result.get("data", {}),
        "status": hw.telemetry_status,
        "last_polled": hw.telemetry_last_polled,
    }


# ── Generic entity telemetry (Proxmox sidebar) ──────────────────────────────

_ENTITY_TYPES = {"hardware", "compute_unit", "storage"}


def _parse_json(val: str | None) -> dict:
    if not val:
        return {}
    try:
        return json.loads(val) if isinstance(val, str) else val
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_telemetry(entity_type: str, entity_id: int, db: Session = Depends(get_db)):
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {_ENTITY_TYPES}")

    result: dict = {"entity_type": entity_type, "entity_id": entity_id}

    if entity_type == "hardware":
        hw = db.get(Hardware, entity_id)
        if not hw:
            raise HTTPException(status_code=404, detail="Hardware not found")
        tdata = _parse_json(hw.telemetry_data)
        result.update(
            {
                "name": hw.name,
                "status": hw.status,
                "telemetry_status": hw.telemetry_status,
                "telemetry_last_polled": hw.telemetry_last_polled,
                **tdata,
            }
        )
        vms_running = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "qemu",
                ComputeUnit.status == "active",
            )
            .count()
        )
        vms_stopped = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "qemu",
                ComputeUnit.status != "active",
            )
            .count()
        )
        cts_running = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "lxc",
                ComputeUnit.status == "active",
            )
            .count()
        )
        cts_stopped = (
            db.query(ComputeUnit)
            .filter(
                ComputeUnit.hardware_id == hw.id,
                ComputeUnit.proxmox_type == "lxc",
                ComputeUnit.status != "active",
            )
            .count()
        )
        result["child_vms"] = {"running": vms_running, "stopped": vms_stopped}
        result["child_cts"] = {"running": cts_running, "stopped": cts_stopped}

        storage_items = db.query(Storage).filter(Storage.hardware_id == hw.id).all()
        result["storage_summary"] = [
            {"name": s.name, "kind": s.kind, "capacity_gb": s.capacity_gb, "used_gb": s.used_gb}
            for s in storage_items
        ]

    elif entity_type == "compute_unit":
        cu = db.get(ComputeUnit, entity_id)
        if not cu:
            raise HTTPException(status_code=404, detail="Compute unit not found")
        pve_status = _parse_json(cu.proxmox_status)
        result.update(
            {
                "name": cu.name,
                "status": cu.status,
                "proxmox_vmid": cu.proxmox_vmid,
                "proxmox_type": cu.proxmox_type,
                **pve_status,
            }
        )

    elif entity_type == "storage":
        st = db.get(Storage, entity_id)
        if not st:
            raise HTTPException(status_code=404, detail="Storage not found")
        result.update(
            {
                "name": st.name,
                "kind": st.kind,
                "protocol": st.protocol,
                "capacity_gb": st.capacity_gb,
                "used_gb": st.used_gb,
                "parent_node": st.hardware.name if st.hardware else None,
            }
        )

    # Attach recent timeseries if available
    recent = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.entity_type == entity_type,
            TelemetryTimeseries.entity_id == entity_id,
        )
        .order_by(desc(TelemetryTimeseries.ts))
        .limit(20)
        .all()
    )
    result["timeseries"] = [
        {"metric": r.metric, "value": r.value, "ts": r.ts.isoformat() if r.ts else None}
        for r in recent
    ]

    return result
