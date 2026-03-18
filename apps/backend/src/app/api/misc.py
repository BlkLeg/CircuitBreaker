from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.security import require_write_auth
from app.db.session import get_db
from app.schemas.misc import MiscItem, MiscItemCreate, MiscItemUpdate
from app.services import misc_service

router = APIRouter(tags=["misc"])


@router.get("", response_model=list[MiscItem])
def list_misc(
    kind: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    return misc_service.list_misc(db, kind=kind, tag=tag, q=q)


@router.post("", response_model=MiscItem, status_code=201)
def create_misc_item(
    payload: MiscItemCreate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = misc_service.create_misc_item(db, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A record with this identifier already exists."
        ) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="misc_item_created",
        resource=f"misc:{result.id}",
        status="ok",
    )
    return result


@router.get("/{item_id}", response_model=MiscItem)
def get_misc_item(item_id: int, db: Session = Depends(get_db)) -> Any:
    try:
        return misc_service.get_misc_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{item_id}", response_model=MiscItem)
def patch_misc_item(
    item_id: int,
    payload: MiscItemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> Any:
    try:
        result = misc_service.update_misc_item(db, item_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A record with this identifier already exists."
        ) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="misc_item_updated",
        resource=f"misc:{item_id}",
        status="ok",
    )
    return result


@router.delete("/{item_id}", status_code=204)
def delete_misc_item(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user_id: int | None = Depends(require_write_auth),
) -> None:
    try:
        misc_service.delete_misc_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log_audit(
        db,
        request,
        user_id=user_id,
        action="misc_item_deleted",
        resource=f"misc:{item_id}",
        status="ok",
        severity="warn",
    )
