"""Bounded cross-entity search used by the global navigator."""

from sqlalchemy.orm import Session

from app.schemas.inventory import MAX_QUERY_LENGTH, EntityType
from app.schemas.search import SearchPage, SearchResult
from app.services.inventory_queries import (
    ENTITY_SPECS,
    InventoryAccess,
    list_entity_options,
)


def search_entities(
    db: Session,
    query: str,
    access: InventoryAccess,
    limit: int,
    types: list[EntityType] | None = None,
) -> SearchPage:
    """Search supported types with per-type SQL limits and deterministic ranking."""
    normalized = query.strip()
    if not normalized:
        raise ValueError("Search query must not be empty")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError(f"Search query must be at most {MAX_QUERY_LENGTH} characters")

    requested_types = types or list(ENTITY_SPECS)
    option_result = list_entity_options(
        db,
        requested_types,
        normalized,
        [],
        "view",
        access,
        limit,
    )
    items: list[SearchResult] = []
    for option in option_result.items:
        spec = ENTITY_SPECS[option.ref.entity_type]
        items.append(
            SearchResult(
                id=f"{spec.legacy_type}-{option.ref.entity_id}",
                type=spec.legacy_type,
                title=option.label,
                description=option.description,
                action_url=spec.action_url,
                entity_type=option.ref.entity_type,
                entity_id=option.ref.entity_id,
            )
        )
    return SearchPage(items=items, limit=limit, has_more=option_result.has_more)
