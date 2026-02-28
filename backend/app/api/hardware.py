from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.hardware import Hardware, HardwareCreate, HardwareUpdate
from app.services import hardware_service

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("", response_model=list[Hardware])
def list_hardware(
    tag: str | None = Query(None),
    role: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return hardware_service.list_hardware(db, tag=tag, role=role, q=q)


@router.post("", response_model=Hardware, status_code=201)
def create_hardware(payload: HardwareCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return hardware_service.create_hardware(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.get("/{hardware_id}", response_model=Hardware)
def get_hardware(hardware_id: int, db: Session = Depends(get_db)):
    try:
        return hardware_service.get_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{hardware_id}", response_model=Hardware)
def replace_hardware(hardware_id: int, payload: HardwareCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    update = HardwareUpdate(**payload.model_dump())
    try:
        return hardware_service.update_hardware(db, hardware_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.patch("/{hardware_id}", response_model=Hardware)
def patch_hardware(hardware_id: int, payload: HardwareUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return hardware_service.update_hardware(db, hardware_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{hardware_id}", status_code=204)
def delete_hardware(hardware_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        hardware_service.delete_hardware(db, hardware_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Cannot delete: other records still reference this hardware.")


@router.get("/{hardware_id}/network-memberships")
def get_network_memberships(hardware_id: int, db: Session = Depends(get_db)):
    """Return all networks this hardware node is directly a member of."""
    try:
        hardware_service.get_hardware(db, hardware_id)  # 404 guard
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return hardware_service.list_network_memberships(db, hardware_id)
