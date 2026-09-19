"""Authenticated, bounded entity search endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_scope
from app.db.session import get_db
from app.schemas.inventory import MAX_QUERY_LENGTH, MAX_SEARCH_LIMIT, EntityType
from app.schemas.search import SearchPage, SearchResult
from app.services.inventory_queries import FULL_INVENTORY_ACCESS
from app.services.search_service import search_entities

router = APIRouter(tags=["search"], dependencies=[require_scope("read", "*")])


@router.get("", response_model=list[SearchResult])
def search(
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH, pattern=r"\S")],
    db: Annotated[Session, Depends(get_db)],
) -> list[SearchResult]:
    """Preserve the legacy result list while adding canonical entity identity."""
    return search_entities(db, q, FULL_INVENTORY_ACCESS, MAX_SEARCH_LIMIT).items


@router.get("/page", response_model=SearchPage)
def search_page(
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LENGTH, pattern=r"\S")],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = MAX_SEARCH_LIMIT,
    types: Annotated[list[EntityType] | None, Query()] = None,
) -> SearchPage:
    """Return bounded entity results with an explicit truncation signal."""
    return search_entities(db, q, FULL_INVENTORY_ACCESS, limit, types)
