from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExternalNodeBase(BaseModel):
    name: str
    provider: str | None = None
    kind: str | None = None
    region: str | None = None
    ip_address: str | None = None
    icon_slug: str | None = None
    notes: str | None = None
    environment: str | None = None
    tags: list[str] = []


class ExternalNodeCreate(ExternalNodeBase):
    pass


class ExternalNodeUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    kind: str | None = None
    region: str | None = None
    ip_address: str | None = None
    icon_slug: str | None = None
    notes: str | None = None
    environment: str | None = None
    tags: list[str] | None = None


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
    link_type: str | None = None
    notes: str | None = None


class ExternalNodeNetworkRead(BaseModel):
    id: int
    external_node_id: int
    network_id: int
    link_type: str | None = None
    notes: str | None = None
    network_name: str | None = None


class ServiceExternalNodeLink(BaseModel):
    external_node_id: int
    purpose: str | None = None


class ServiceExternalNodeRead(BaseModel):
    id: int
    service_id: int
    external_node_id: int
    purpose: str | None = None
    external_node_name: str | None = None
    service_name: str | None = None
