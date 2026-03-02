"""Derived status intelligence — avoids circular imports by living in its own module.

CB-STATE-001: recalculate_hardware_status() — worst-case of telemetry + child compute statuses
CB-STATE-002: recalculate_compute_status() — worst-case of child service statuses
"""
import logging

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models import Hardware, ComputeUnit, Service

_logger = logging.getLogger(__name__)

# Status severity ordering: higher index = worse
_STATUS_RANK = {
    "healthy": 0,
    "running": 0,
    "online": 0,
    "unknown": 1,
    "stopped": 2,
    "degraded": 3,
    "maintenance": 3,
    "critical": 4,
    "offline": 4,
}


def _worst_status(statuses: list[str]) -> str:
    """Return the worst status from a list, using severity ranking."""
    if not statuses:
        return "unknown"
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 1))


def recalculate_hardware_status(db: Session, hardware_id: int) -> str:
    """CB-STATE-001: Derive hardware status from telemetry_status + child compute statuses.

    Writes hw.status and returns the computed value.
    """
    hw = db.get(Hardware, hardware_id)
    if hw is None:
        return "unknown"
    child_statuses = []
    if hw.telemetry_status:
        child_statuses.append(hw.telemetry_status)
    for cu in db.execute(select(ComputeUnit).where(ComputeUnit.hardware_id == hardware_id)).scalars().all():
        if cu.status:
            child_statuses.append(cu.status)
    new_status = _worst_status(child_statuses)
    hw.status = new_status
    db.flush()
    return new_status


def recalculate_compute_status(db: Session, cu_id: int) -> str:
    """CB-STATE-002: Derive compute unit status from child service statuses.

    Writes cu.status and returns the computed value.
    """
    cu = db.get(ComputeUnit, cu_id)
    if cu is None:
        return "unknown"
    svc_statuses = []
    for svc in db.execute(select(Service).where(Service.compute_id == cu_id)).scalars().all():
        if svc.status:
            svc_statuses.append(svc.status)
    new_status = _worst_status(svc_statuses)
    cu.status = new_status
    db.flush()
    return new_status
