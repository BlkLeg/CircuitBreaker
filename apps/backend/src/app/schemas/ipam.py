from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IPAddressBase(BaseModel):
    network_id: int | None = None
    address: str
    status: str = "free"
    hardware_id: int | None = None
    service_id: int | None = None
    hostname: str | None = None


class IPAddressCreate(IPAddressBase):
    pass


class IPAddressUpdate(BaseModel):
    status: str | None = None
    hardware_id: int | None = None
    service_id: int | None = None
    hostname: str | None = None


class IPAddressRead(IPAddressBase):
    id: int
    tenant_id: int | None = None
    allocated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

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


class NodeRelationUpdate(BaseModel):
    relation_type: str | None = None
    metadata_json: dict | None = None


class NodeRelationRead(NodeRelationBase):
    id: int
    tenant_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IPReservationQueueRead(BaseModel):
    id: int
    tenant_id: int | None = None
    hardware_id: int | None = None
    ip_address: str
    hostname: str | None = None
    network_id: int | None = None
    status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class IPConflictRead(BaseModel):
    id: int
    tenant_id: int | None = None
    address: str
    entity_a_type: str
    entity_a_id: int
    entity_b_type: str
    entity_b_id: int
    conflict_type: str
    port: int | None = None
    protocol: str | None = None
    status: str
    resolution: str | None = None
    resolved_by: int | None = None
    resolved_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class IPConflictResolve(BaseModel):
    resolution: str  # reassign | keep_existing | free_and_assign
    user_id: int | None = None
    notes: str | None = None


class VLANTrunkCreate(BaseModel):
    hardware_id: int
    vlan_id: int
    port_label: str | None = None
    tagged: bool = True
    tenant_id: int | None = None


class VLANTrunkRead(BaseModel):
    id: int
    tenant_id: int | None = None
    hardware_id: int
    vlan_id: int
    port_label: str | None = None
    tagged: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── DHCP schemas ──────────────────────────────────────────────────────────────


class DHCPPoolBase(BaseModel):
    network_id: int
    name: str
    start_ip: str
    end_ip: str
    lease_duration_seconds: int = 86400
    tenant_id: int | None = None


class DHCPPoolCreate(DHCPPoolBase):
    pass


class DHCPPoolUpdate(BaseModel):
    name: str | None = None
    start_ip: str | None = None
    end_ip: str | None = None
    lease_duration_seconds: int | None = None
    enabled: bool | None = None


class DHCPPoolRead(DHCPPoolBase):
    id: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class DHCPLeaseRead(BaseModel):
    id: int
    tenant_id: int | None = None
    pool_id: int
    ip_address: str
    mac_address: str | None = None
    hostname: str | None = None
    lease_start: datetime | None = None
    lease_expiry: datetime | None = None
    status: str
    source: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class DHCPLeaseEntry(BaseModel):
    ip_address: str
    mac_address: str | None = None
    hostname: str | None = None


class DHCPLeaseImport(BaseModel):
    leases: list[DHCPLeaseEntry]
