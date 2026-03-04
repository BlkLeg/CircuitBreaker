from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.rack import RackCreate, RackOut, RackUpdate
from app.services import rack_service

router = APIRouter(tags=["racks"])


@router.get("", response_model=list[RackOut])
def list_racks(db: Session = Depends(get_db)):
    return rack_service.list_racks(db)


@router.post("", response_model=RackOut, status_code=201)
def create_rack(payload: RackCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    return rack_service.create_rack(db, payload)


@router.get("/{rack_id}", response_model=RackOut)
def get_rack(rack_id: int, db: Session = Depends(get_db)):
    try:
        return rack_service.get_rack(db, rack_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{rack_id}", response_model=RackOut)
def update_rack(rack_id: int, payload: RackUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return rack_service.update_rack(db, rack_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{rack_id}", status_code=204)
def delete_rack(rack_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        rack_service.delete_rack(db, rack_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
