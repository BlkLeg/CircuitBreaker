from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.misc import MiscItem, MiscItemCreate, MiscItemUpdate
from app.services import misc_service

router = APIRouter(prefix="/misc", tags=["misc"])


@router.get("", response_model=list[MiscItem])
def list_misc(
    kind: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return misc_service.list_misc(db, kind=kind, tag=tag, q=q)


@router.post("", response_model=MiscItem, status_code=201)
def create_misc_item(payload: MiscItemCreate, db: Session = Depends(get_db)):
    try:
        return misc_service.create_misc_item(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.get("/{item_id}", response_model=MiscItem)
def get_misc_item(item_id: int, db: Session = Depends(get_db)):
    try:
        return misc_service.get_misc_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{item_id}", response_model=MiscItem)
def patch_misc_item(item_id: int, payload: MiscItemUpdate, db: Session = Depends(get_db)):
    try:
        return misc_service.update_misc_item(db, item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this identifier already exists.")


@router.delete("/{item_id}", status_code=204)
def delete_misc_item(item_id: int, db: Session = Depends(get_db)):
    try:
        misc_service.delete_misc_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
