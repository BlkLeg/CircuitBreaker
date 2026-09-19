"""Public contracts for legacy and bounded entity search."""

from pydantic import BaseModel, Field

from app.schemas.inventory import MAX_SEARCH_LIMIT, EntityType


class SearchResult(BaseModel):
    """An entity search hit with legacy and canonical identity fields."""

    id: str
    type: str
    title: str
    description: str | None = None
    action_url: str
    entity_type: EntityType
    entity_id: int = Field(gt=0)


class SearchPage(BaseModel):
    """A bounded search response that states whether results were truncated."""

    items: list[SearchResult]
    limit: int = Field(ge=1, le=MAX_SEARCH_LIMIT)
    has_more: bool
