from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.storage import Storage, StorageCreate, StorageUpdate
from app.services import storage_service

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("", response_model=list[Storage])
def list_storage(
    kind: str | None = Query(None),
    hardware_id: int | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return storage_service.list_storage(db, kind=kind, hardware_id=hardware_id, tag=tag, q=q)


@router.post("", response_model=Storage, status_code=201)
def create_storage(payload: StorageCreate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return storage_service.create_storage(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.get("/{storage_id}", response_model=Storage)
def get_storage(storage_id: int, db: Session = Depends(get_db)):
    try:
        return storage_service.get_storage(db, storage_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{storage_id}", response_model=Storage)
def patch_storage(storage_id: int, payload: StorageUpdate, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        return storage_service.update_storage(db, storage_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{storage_id}", status_code=204)
def delete_storage(storage_id: int, db: Session = Depends(get_db), _=Depends(require_write_auth)):
    try:
        storage_service.delete_storage(db, storage_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
