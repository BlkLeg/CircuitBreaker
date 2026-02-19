from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class NetworkBase(BaseModel):
    name: str
    cidr: Optional[str] = None
    vlan_id: Optional[int] = None
    gateway: Optional[str] = None
    description: Optional[str] = None


class NetworkCreate(NetworkBase):
    tags: list[str] = []


class NetworkUpdate(BaseModel):
    name: Optional[str] = None
    cidr: Optional[str] = None
    vlan_id: Optional[int] = None
    gateway: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class Network(NetworkBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime


class ComputeNetworkLink(BaseModel):
    compute_id: int
    ip_address: Optional[str] = None


class ComputeNetworkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    compute_id: int
    network_id: int
    ip_address: Optional[str] = None
