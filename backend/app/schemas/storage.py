from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StorageBase(BaseModel):
    name: str
    kind: str  # 'disk', 'pool', 'dataset', 'share'
    icon_slug: str | None = None
    hardware_id: int | None = None
    capacity_gb: int | None = None
    used_gb: int | None = None
    path: str | None = None
    protocol: str | None = None
    notes: str | None = None
    tags: list[str] = []


class StorageCreate(StorageBase):
    pass


class StorageUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    icon_slug: str | None = None
    hardware_id: int | None = None
    capacity_gb: int | None = None
    used_gb: int | None = None
    path: str | None = None
    protocol: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class Storage(StorageBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
