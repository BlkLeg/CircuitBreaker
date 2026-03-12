import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rate_limit import get_limit, limiter
from app.core.rbac import require_role, require_scope
from app.core.security import require_auth_always
from app.db.models import ComputeUnit, Hardware, Storage, TelemetryTimeseries, User
from app.db.session import get_db
from app.integrations.dispatcher import poll_hardware
from app.schemas.hardware import TelemetryConfig
from app.schemas.telemetry import TelemetryResponse
from app.services.credential_vault import CredentialVault, get_vault
from app.services.telemetry_service import get_telemetry_for_hardware, write_telemetry

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])


def _safe_json(val) -> dict | None:
    """Parse a JSON string to dict, returning None on any failure."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


@router.get("/{hardware_id}/telemetry", response_model=TelemetryResponse)
@limiter.limit(lambda: get_limit("telemetry"))
async def get_telemetry(
    request: Request,
    response: Response,
    hardware_id: int,
    db: Session = Depends(get_db),
    _user_id: int = Depends(require_auth_always),
):
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if hw is None:
        raise HTTPException(status_code=404, detail="Hardware not found")
    return await get_telemetry_for_hardware(hardware_id, db)


@router.post("/{hardware_id}/telemetry/config")
def configure_telemetry(
    hardware_id: int,
    config: TelemetryConfig,
    request: Request,
    db: Session = Depends(get_db),
    vault: CredentialVault = Depends(get_vault),
    current_user: User = require_scope("write", "telemetry"),
):
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    config_dict = config.model_dump()
    if config_dict.get("password"):
        config_dict["password"] = vault.encrypt(config_dict["password"])

    hw.telemetry_config = config_dict
    db.commit()
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="telemetry_config_updated",
        resource=f"hardware:{hardware_id}",
        status="ok",
    )
    return {"message": "Telemetry config saved.", "hardware_id": hardware_id}


@router.post("/{hardware_id}/telemetry/poll")
async def poll_now(
    hardware_id: int,
    request: Request,
    db: Session = Depends(get_db),
    vault: CredentialVault = Depends(get_vault),
    current_user: User = require_role("admin"),
):
    """Manual on-demand poll."""
    hw = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Hardware not found")

    result = poll_hardware(hw, vault)
    if "status" not in result and "error" in result:
        result = {"status": "unreachable", "error_msg": str(result["error"]), "data": {}}
    elif result.get("status") == "unknown" and "error" in result:
        result["status"] = "unreachable"
        result["error_msg"] = str(result["error"])

    response = await write_telemetry(
        hardware_id=hardware_id,
        payload=result,
        source="manual_poll",
        db=db,
    )
    log_audit(
        db,
        request,
        user_id=current_user.id,
        action="telemetry_poll_triggered",
        resource=f"hardware:{hardware_id}",
        status="ok",
    )

    return response.model_dump()


# ── Generic entity telemetry (Proxmox sidebar) ──────────────────────────────

_ENTITY_TYPES = {"hardware", "compute_unit", "storage"}


@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_telemetry(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    _user: User = require_scope("read", "*"),
):
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {_ENTITY_TYPES}")

    try:
        return _get_entity_telemetry_inner(entity_type, entity_id, db)
    except HTTPException:
        raise
    except Exception as exc:
        _logger.warning("Entity telemetry %s:%d failed: %s", entity_type, entity_id, exc)
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": "error",
            "error": "Telemetry temporarily unavailable",
        }


def _get_entity_telemetry_inner(entity_type: str, entity_id: int, db: Session) -> dict:
    result: dict = {"entity_type": entity_type, "entity_id": entity_id}

    if entity_type == "hardware":
        hw = db.get(Hardware, entity_id)
        if not hw:
            raise HTTPException(status_code=404, detail="Hardware not found")
        tdata = _safe_json(hw.telemetry_data) or {}
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
        pve_status = _safe_json(cu.proxmox_status) or {}
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
