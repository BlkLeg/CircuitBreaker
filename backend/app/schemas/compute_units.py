from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ComputeUnitBase(BaseModel):
    name: str
    kind: str  # 'vm' | 'container'
    hardware_id: int
    os: Optional[str] = None
    icon_slug: Optional[str] = None
    cpu_cores: Optional[int] = None
    cpu_brand: Optional[str] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[int] = None
    ip_address: Optional[str] = None
    environment: Optional[str] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    notes: Optional[str] = None
    tags: list[str] = []


class ComputeUnitCreate(ComputeUnitBase):
    pass


class ComputeUnitUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    hardware_id: Optional[int] = None
    os: Optional[str] = None
    icon_slug: Optional[str] = None
    cpu_cores: Optional[int] = None
    cpu_brand: Optional[str] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[int] = None
    ip_address: Optional[str] = None
    environment: Optional[str] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


class ComputeUnit(ComputeUnitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    storage_allocated: Optional[dict] = None
    # v0.1.4: environment registry
    environment_name: Optional[str] = None
