from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class HardwareBase(BaseModel):
    name: str
    role: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []


class HardwareCreate(HardwareBase):
    pass


class HardwareUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    cpu: Optional[str] = None
    memory_gb: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


class Hardware(HardwareBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
