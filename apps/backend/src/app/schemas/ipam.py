from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IPAddressBase(BaseModel):
    network_id: int | None = None
    address: str
    status: str = "free"
    hardware_id: int | None = None
    service_id: int | None = None
    hostname: str | None = None
    notes: str | None = None


class IPAddressCreate(IPAddressBase):
    pass


class IPAddressUpdate(BaseModel):
    status: str | None = None
    hardware_id: int | None = None
    service_id: int | None = None
    hostname: str | None = None
    notes: str | None = None


class IPAddressRead(IPAddressBase):
    id: int | None = None
    tenant_id: int | None = None
    allocated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: Literal["manual", "discovered"] = "manual"

    model_config = {"from_attributes": True}


class VLANBase(BaseModel):
    vlan_id: int
    name: str | None = None
    description: str | None = None
    network_ids: list[int] = Field(default_factory=list)


class VLANCreate(VLANBase):
    pass


class VLANUpdate(BaseModel):
    vlan_id: int | None = None
    name: str | None = None
    description: str | None = None
    network_ids: list[int] | None = None


class VLANRead(VLANBase):
    id: int
    tenant_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SiteBase(BaseModel):
    name: str
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None


class SiteRead(SiteBase):
    id: int
    tenant_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeRelationBase(BaseModel):
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    relation_type: str
    metadata_json: dict | None = None


class NodeRelationCreate(NodeRelationBase):
    pass


class NodeRelationRead(NodeRelationBase):
    id: int
    tenant_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
