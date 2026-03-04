from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class RackCreate(BaseModel):
    name: str
    height_u: int = 42
    location: Optional[str] = None
    notes: Optional[str] = None


class RackUpdate(BaseModel):
    name: Optional[str] = None
    height_u: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class RackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    height_u: int
    location: Optional[str] = None
    notes: Optional[str] = None
    hardware_count: int = 0
    created_at: datetime
    updated_at: datetime
