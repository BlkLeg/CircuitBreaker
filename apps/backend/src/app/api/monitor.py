import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.monitor import (
    MonitorCreate,
    MonitorEventRead,
    MonitorHistoryPoint,
    MonitorRead,
    MonitorUpdate,
    TargetMonitorCreate,
    TargetMonitorSummary,
    TargetType,
)
from app.services import monitor_service

_NOT_FOUND = "Monitor not found"
_NO_TARGET = "Target not found or has no address to probe"
_logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitors"])


@router.get("", response_model=list[MonitorRead])
def list_monitors(
    target_type: str | None = Query(default=None),
    target_id: int | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    return monitor_service.list_monitors(
        db, target_type=target_type, target_id=target_id, enabled=enabled
    )


# ── Target-scoped actions (inventory list pages, detail drawers, map) ─────────
# Declared before "/{monitor_id}" so "target" isn't parsed as a monitor id.


@router.get("/target-summary", response_model=list[TargetMonitorSummary])
def target_summary(
    target_type: TargetType = Query(...),
    target_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    """Per-target monitor rollup for an inventory page."""
    return monitor_service.list_target_summaries(db, target_type, target_ids)


@router.post("/target/{target_type}/{target_id}", response_model=MonitorRead)
def create_target_monitor(
    target_type: TargetType,
    target_id: int,
    payload: TargetMonitorCreate | None = None,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    try:
        monitor = monitor_service.create_target_monitor(
            db,
            target_type,
            target_id,
            check_type=payload.check_type if payload else None,
            config=payload.config if payload else None,
        )
    except ValidationError as exc:
        # A config override is only validated once the check type is resolved,
        # so it lands here rather than in request validation.
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    if not monitor:
        raise HTTPException(status_code=404, detail=_NO_TARGET)
    return monitor


@router.post("/target/{target_type}/{target_id}/pause")
def pause_target_monitor(
    target_type: TargetType,
    target_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.set_target_paused(db, target_type, target_id, True):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {"status": "ok"}


@router.post("/target/{target_type}/{target_id}/resume")
def resume_target_monitor(
    target_type: TargetType,
    target_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.set_target_paused(db, target_type, target_id, False):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {"status": "ok"}


@router.post("/target/{target_type}/{target_id}/check")
def run_target_check(
    target_type: TargetType,
    target_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.run_target_check(db, target_type, target_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {"status": "ok"}


@router.post("", response_model=MonitorRead)
def create_monitor(
    payload: MonitorCreate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    return monitor_service.create_monitor(db, payload)


@router.get("/{monitor_id}", response_model=MonitorRead)
def get_monitor(monitor_id: int, db: Session = Depends(get_db)) -> Any:
    monitor = monitor_service.get_monitor(db, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.patch("/{monitor_id}", response_model=MonitorRead)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.update_monitor(db, monitor_id, payload)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> None:
    if not monitor_service.delete_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


@router.post("/{monitor_id}/pause", response_model=MonitorRead)
def pause_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.set_paused(db, monitor_id, True)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.post("/{monitor_id}/resume", response_model=MonitorRead)
def resume_monitor(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.set_paused(db, monitor_id, False)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor


@router.post("/{monitor_id}/check", response_model=MonitorRead)
def run_immediate_check(
    monitor_id: int,
    user_id: int = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Any:
    monitor = monitor_service.get_monitor(db, monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    monitor_service.run_immediate_check(db, monitor_id)
    return monitor


@router.get("/{monitor_id}/events", response_model=list[MonitorEventRead])
def get_events(
    monitor_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_events(db, monitor_id, limit=limit)


@router.get("/{monitor_id}/history", response_model=list[MonitorHistoryPoint])
def get_history(
    monitor_id: int,
    metric: str = Query(default="latency_ms"),
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_history(db, monitor_id, metric=metric, hours=hours)


@router.get("/{monitor_id}/uptime")
def get_uptime(monitor_id: int, db: Session = Depends(get_db)) -> Any:
    if not monitor_service.get_monitor(db, monitor_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return monitor_service.get_uptime(db, monitor_id)
