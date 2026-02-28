from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ExternalNodeBase(BaseModel):
    name: str
    provider: Optional[str] = None
    kind: Optional[str] = None
    region: Optional[str] = None
    ip_address: Optional[str] = None
    icon_slug: Optional[str] = None
    notes: Optional[str] = None
    environment: Optional[str] = None
    tags: list[str] = []


class ExternalNodeCreate(ExternalNodeBase):
    pass


class ExternalNodeUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    kind: Optional[str] = None
    region: Optional[str] = None
    ip_address: Optional[str] = None
    icon_slug: Optional[str] = None
    notes: Optional[str] = None
    environment: Optional[str] = None
    tags: Optional[list[str]] = None


class ExternalNodeRead(ExternalNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    networks_count: int = 0
    services_count: int = 0


# ── Relationship payloads ────────────────────────────────────────────────────

class ExternalNodeNetworkLink(BaseModel):
    network_id: int
    link_type: Optional[str] = None
    notes: Optional[str] = None


class ExternalNodeNetworkRead(BaseModel):
    id: int
    external_node_id: int
    network_id: int
    link_type: Optional[str] = None
    notes: Optional[str] = None
    network_name: Optional[str] = None


class ServiceExternalNodeLink(BaseModel):
    external_node_id: int
    purpose: Optional[str] = None


class ServiceExternalNodeRead(BaseModel):
    id: int
    service_id: int
    external_node_id: int
    purpose: Optional[str] = None
    external_node_name: Optional[str] = None
    service_name: Optional[str] = None
