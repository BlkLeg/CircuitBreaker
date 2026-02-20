from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class StorageBase(BaseModel):
    name: str
    kind: str  # 'disk', 'pool', 'dataset', 'share'
    hardware_id: Optional[int] = None
    capacity_gb: Optional[int] = None
    used_gb: Optional[int] = None
    path: Optional[str] = None
    protocol: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []


class StorageCreate(StorageBase):
    pass


class StorageUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    hardware_id: Optional[int] = None
    capacity_gb: Optional[int] = None
    used_gb: Optional[int] = None
    path: Optional[str] = None
    protocol: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


class Storage(StorageBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
