import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

_logger = logging.getLogger(__name__)

from app.core.time import utcnow
from app.db.models import Hardware
from app.db.session import get_db
from app.integrations.dispatcher import poll_hardware
from app.schemas.hardware import TelemetryConfig
from app.services.credential_vault import CredentialVault, get_vault

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
            data = {}

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
