"""Shared, bounded inventory selector endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_scope
from app.db.session import get_db
from app.schemas.inventory import (
    MAX_PAGE_LIMIT,
    MAX_QUERY_LENGTH,
    EntityOptionResult,
    EntityRef,
    EntityType,
    SelectionAction,
)
from app.services.inventory_queries import (
    ENTITY_SPECS,
    FULL_INVENTORY_ACCESS,
    eligible_types,
    list_entity_options,
    normalize_entity_type,
)

router = APIRouter(tags=["inventory"], dependencies=[require_scope("read", "*")])


def _parse_refs(values: list[str]) -> list[EntityRef]:
    if len(values) > MAX_PAGE_LIMIT:
        raise HTTPException(
            status_code=422, detail=f"At most {MAX_PAGE_LIMIT} selected values are allowed"
        )
    refs: list[EntityRef] = []
    for value in values:
        type_value, separator, id_value = value.partition(":")
        if not separator:
            raise HTTPException(status_code=422, detail="Selected values must use type:id")
        try:
            entity_type = normalize_entity_type(type_value)
            entity_id = int(id_value)
            refs.append(EntityRef(entity_type=entity_type, entity_id=entity_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422, detail="Selected values must use valid type:id"
            ) from exc
    return refs


@router.get("/options", response_model=EntityOptionResult)
def list_options(
    db: Annotated[Session, Depends(get_db)],
    action: Annotated[SelectionAction, Query()] = "view",
    types: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    selected: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = 25,
) -> EntityOptionResult:
    """List minimal options for an authorized, purpose-specific selector."""
    try:
        requested_types: list[EntityType]
        if types is None:
            requested_types = [
                entity_type for entity_type in ENTITY_SPECS if entity_type in eligible_types(action)
            ]
        else:
            requested_types = [normalize_entity_type(value) for value in types]
        return list_entity_options(
            db,
            requested_types,
            q,
            _parse_refs(selected or []),
            action,
            FULL_INVENTORY_ACCESS,
            limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
