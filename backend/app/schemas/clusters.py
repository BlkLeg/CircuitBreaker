from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class HardwareClusterBase(BaseModel):
    name: str
    description: Optional[str] = None
    environment: Optional[str] = None
    location: Optional[str] = None


class HardwareClusterCreate(HardwareClusterBase):
    pass


class HardwareClusterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    location: Optional[str] = None


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
    role: Optional[str] = None
    hardware_name: Optional[str] = None


class HardwareClusterMemberLink(BaseModel):
    hardware_id: int
    role: Optional[str] = None


class HardwareClusterMemberUpdate(BaseModel):
    role: Optional[str] = None
