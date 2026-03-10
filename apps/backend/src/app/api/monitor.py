import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.monitor import MonitorCreate, MonitorRead, MonitorUpdate, UptimeEventRead
from app.services import monitor_service

_NOT_FOUND = "Monitor not found"
_logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitors"])


@router.get("", response_model=list[MonitorRead])
def list_monitors(db: Session = Depends(get_db)):
    """List all hardware monitors with their latest status."""
    from sqlalchemy import select

    from app.db.models import HardwareMonitor

    return list(db.scalars(select(HardwareMonitor).order_by(HardwareMonitor.hardware_id)).all())


@router.get("/{hardware_id}", response_model=MonitorRead)
def get_monitor(hardware_id: int, db: Session = Depends(get_db)):
    monitor = monitor_service.get_monitor(db, hardware_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.post("", response_model=MonitorRead)
def create_monitor(
    payload: MonitorCreate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
):
    existing = monitor_service.get_monitor(db, payload.hardware_id)
    if existing:
        raise HTTPException(status_code=409, detail="Monitor already exists for this hardware")
    from app.db.models import Hardware

    if not db.get(Hardware, payload.hardware_id):
        raise HTTPException(status_code=404, detail="Hardware not found")
    return monitor_service.create_monitor(
        db,
        hardware_id=payload.hardware_id,
        probe_methods=payload.probe_methods,
        interval_secs=payload.interval_secs,
        enabled=payload.enabled,
    )


@router.put("/{hardware_id}", response_model=MonitorRead)
def update_monitor(
    hardware_id: int,
    payload: MonitorUpdate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
):
    monitor = monitor_service.update_monitor(
        db,
        hardware_id,
        enabled=payload.enabled,
        interval_secs=payload.interval_secs,
        probe_methods=payload.probe_methods,
    )
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.delete("/{hardware_id}", status_code=204)
def delete_monitor(
    hardware_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
):
    if not monitor_service.delete_monitor(db, hardware_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return None


@router.get("/{hardware_id}/history", response_model=list[UptimeEventRead])
def get_history(
    hardware_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return monitor_service.get_history(db, hardware_id, limit=limit)


@router.post("/{hardware_id}/check", response_model=MonitorRead)
def run_immediate_check(
    hardware_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
):
    """Trigger an immediate probe for the given hardware device."""
    monitor = monitor_service.get_monitor(db, hardware_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    monitor_service.run_monitor(db, monitor)
    db.refresh(monitor)
    return monitor
