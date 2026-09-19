"""Shared contracts for bounded inventory reads and entity selection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

EntityType = Literal[
    "hardware",
    "compute_unit",
    "service",
    "storage",
    "network",
    "misc_item",
    "external_node",
]
SortDirection = Literal["asc", "desc"]
SelectionAction = Literal["view", "relate", "monitor", "docker_parent"]

DEFAULT_PAGE_LIMIT = 25
MAX_PAGE_LIMIT = 100
MAX_SEARCH_LIMIT = 20
MAX_QUERY_LENGTH = 100


class PageRequest(BaseModel):
    """Validated pagination and ordering requested by an inventory caller."""

    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(default=0, ge=0)
    sort: str = Field(default="name", min_length=1, max_length=40)
    direction: SortDirection = "asc"


class PageResult[ItemT](BaseModel):
    """One bounded, non-snapshot page from an inventory collection."""

    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(ge=0)
    sort: str
    direction: SortDirection


class EntityRef(BaseModel):
    """Canonical identity shared by selectors and new cross-domain APIs."""

    model_config = ConfigDict(frozen=True)

    entity_type: EntityType
    entity_id: int = Field(gt=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        """Return the stable serialized identity used by frontend controls."""
        return f"{self.entity_type}:{self.entity_id}"


class EntityOption(BaseModel):
    """Minimal entity metadata safe for a picker or selected-value label."""

    ref: EntityRef
    label: str
    description: str | None = None
    available: bool = True
    unavailable_reason: Literal["not_found", "unavailable"] | None = None


class EntityOptionResult(BaseModel):
    """Bounded option matches plus labels for values already selected."""

    items: list[EntityOption]
    selected: list[EntityOption]
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    has_more: bool
