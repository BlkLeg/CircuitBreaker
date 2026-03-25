from __future__ import annotations

from pydantic import BaseModel, Field


class MapOut(BaseModel):
    id: int
    name: str
    is_default: bool
    sort_order: int
    entity_count: int = 0

    model_config = {"from_attributes": True}


class MapCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class MapUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None


class EntityAssign(BaseModel):
    entity_type: str = Field(
        ..., description="hardware|network|cluster|compute|service|storage|external"
    )
    entity_id: int


class EntityPin(BaseModel):
    entity_type: str
    entity_id: int
