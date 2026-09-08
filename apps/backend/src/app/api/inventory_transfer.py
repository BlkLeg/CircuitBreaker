"""Authorized portable inventory export, preview, apply, and result routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.rbac import require_role
from app.db import models
from app.db.session import get_db
from app.schemas.inventory_transfer import (
    PortableInventory,
    TransferApplyRequest,
    TransferApplyResult,
    TransferPreviewRequest,
    TransferPreviewResult,
)
from app.services.inventory_transfer.apply import apply_import, completed_operation_result
from app.services.inventory_transfer.export import export_inventory
from app.services.inventory_transfer.format import parse_inventory_document
from app.services.inventory_transfer.plan import build_import_plan, save_preview

router = APIRouter(tags=["inventory-transfer"])


@router.get("/export", response_model=PortableInventory)
def export_portable_inventory(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[models.User, require_role("admin")],
) -> PortableInventory:
    return export_inventory(db)


@router.post("/preview", response_model=TransferPreviewResult, status_code=201)
def preview_inventory_transfer(
    payload: TransferPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, require_role("admin")],
) -> TransferPreviewResult:
    try:
        document = parse_inventory_document(payload.document)
        built = build_import_plan(db, document, payload.resolutions)
        result = save_preview(db, document, built, actor_id=user.id)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc


@router.post("/plans/{plan_id}/apply", response_model=TransferApplyResult)
def apply_inventory_transfer(
    plan_id: str,
    payload: TransferApplyRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, require_role("admin")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=160)],
) -> TransferApplyResult:
    try:
        result = apply_import(
            db,
            plan_id,
            payload.plan_digest,
            idempotency_key,
            actor_id=user.id,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/operations/{operation_id}", response_model=TransferApplyResult)
def get_inventory_transfer_result(
    operation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, require_role("admin")],
) -> TransferApplyResult:
    return completed_operation_result(db, operation_id, actor_id=user.id)
