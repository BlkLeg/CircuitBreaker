from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HardwareClusterBase(BaseModel):
    name: str
    icon_slug: str | None = None
    description: str | None = None
    environment: str | None = None
    location: str | None = None


class HardwareClusterCreate(HardwareClusterBase):
    pass


class HardwareClusterUpdate(BaseModel):
    name: str | None = None
    icon_slug: str | None = None
    description: str | None = None
    environment: str | None = None
    location: str | None = None


class HardwareClusterRead(HardwareClusterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class HardwareClusterMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cluster_id: int
    hardware_id: int
    role: str | None = None
    hardware_name: str | None = None


class HardwareClusterMemberLink(BaseModel):
    hardware_id: int
    role: str | None = None


class HardwareClusterMemberUpdate(BaseModel):
    role: str | None = None
