from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RackCreate(BaseModel):
    name: str
    height_u: int = 42
    location: str | None = None
    notes: str | None = None


class RackUpdate(BaseModel):
    name: str | None = None
    height_u: int | None = None
    location: str | None = None
    notes: str | None = None


class RackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    height_u: int
    location: str | None = None
    notes: str | None = None
    hardware_count: int = 0
    created_at: datetime
    updated_at: datetime
