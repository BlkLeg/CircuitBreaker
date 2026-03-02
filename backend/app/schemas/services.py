from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PortEntry(BaseModel):
    ip: Optional[str] = None          # per-port IP override; inherits service ip_address if None
    port: Optional[int] = None
    protocol: Optional[str] = "tcp"   # "tcp" | "udp" | "sctp"
    label: Optional[str] = None


class ServiceBase(BaseModel):
    name: str
    slug: Optional[str] = None   # auto-derived from name if not provided
    compute_id: Optional[int] = None
    hardware_id: Optional[int] = None
    icon_slug: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[int] = None
    url: Optional[str] = None
    ports: Optional[list[PortEntry]] = None   # structured port bindings (replaces freeform string)
    description: Optional[str] = None
    environment: Optional[str] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    status: Optional[str] = None  # running | stopped | degraded | maintenance
    ip_address: Optional[str] = None
    tags: list[str] = []


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    compute_id: Optional[int] = None
    hardware_id: Optional[int] = None
    icon_slug: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[int] = None
    url: Optional[str] = None
    ports: Optional[list[PortEntry]] = None   # structured port bindings
    description: Optional[str] = None
    environment: Optional[str] = None
    # v0.1.4: environment registry
    environment_id: Optional[int] = None
    status: Optional[str] = None  # running | stopped | degraded | maintenance
    ip_address: Optional[str] = None
    tags: Optional[list[str]] = None


class Service(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_name: Optional[str] = None
    # v0.1.4: environment registry
    environment_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # IP conflict classification
    ip_mode: str = "explicit"
    ip_conflict: bool = False
    ip_conflict_with: list[dict] = []


class ServiceDependencyCreate(BaseModel):
    depends_on_id: int


class ServiceDependency(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    depends_on_id: int


class ServiceStorageLink(BaseModel):
    storage_id: int
    purpose: Optional[str] = None


class ServiceStorageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    storage_id: int
    purpose: Optional[str] = None


class ServiceMiscLink(BaseModel):
    misc_id: int
    purpose: Optional[str] = None


class ServiceMiscRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    misc_id: int
    purpose: Optional[str] = None
