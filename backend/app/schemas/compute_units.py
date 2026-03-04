from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ComputeUnitBase(BaseModel):
    name: str
    kind: str  # 'vm' | 'container'
    hardware_id: int
    os: str | None = None
    icon_slug: str | None = None
    cpu_cores: int | None = None
    cpu_brand: str | None = None
    memory_mb: int | None = None
    disk_gb: int | None = None
    ip_address: str | None = None
    download_speed_mbps: int | None = None
    upload_speed_mbps: int | None = None
    environment: str | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    # v0.1.4-cortex: derived status
    status: str | None = None
    notes: str | None = None
    tags: list[str] = []


class ComputeUnitCreate(ComputeUnitBase):
    pass


class ComputeUnitUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    hardware_id: int | None = None
    os: str | None = None
    icon_slug: str | None = None
    cpu_cores: int | None = None
    cpu_brand: str | None = None
    memory_mb: int | None = None
    disk_gb: int | None = None
    ip_address: str | None = None
    download_speed_mbps: int | None = None
    upload_speed_mbps: int | None = None
    environment: str | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    # v0.1.4-cortex: derived status
    status: str | None = None
    # v2: manual status override (clears auto-derivation when set)
    status_override: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class ComputeUnit(ComputeUnitBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    storage_allocated: dict | None = None
    # v0.1.4: environment registry
    environment_name: str | None = None
    # v2: manual status override
    status_override: str | None = None
