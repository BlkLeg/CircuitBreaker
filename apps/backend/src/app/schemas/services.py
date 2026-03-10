from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PortEntry(BaseModel):
    ip: str | None = None  # per-port IP override; inherits service ip_address if None
    port: int | None = None
    protocol: str | None = "tcp"  # "tcp" | "udp" | "sctp"
    label: str | None = None


class ServiceBase(BaseModel):
    name: str
    slug: str | None = None  # auto-derived from name if not provided
    compute_id: int | None = None
    hardware_id: int | None = None
    icon_slug: str | None = None
    custom_icon: str | None = None
    category: str | None = None
    category_id: int | None = None
    url: str | None = None
    ports: list[PortEntry] | None = None  # structured port bindings (replaces freeform string)
    description: str | None = None
    environment: str | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    status: str | None = None  # running | stopped | degraded | maintenance
    ip_address: str | None = None
    tags: list[str] = []


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    compute_id: int | None = None
    hardware_id: int | None = None
    icon_slug: str | None = None
    custom_icon: str | None = None
    category: str | None = None
    category_id: int | None = None
    url: str | None = None
    ports: list[PortEntry] | None = None  # structured port bindings
    description: str | None = None
    environment: str | None = None
    # v0.1.4: environment registry
    environment_id: int | None = None
    status: str | None = None  # running | stopped | degraded | maintenance
    ip_address: str | None = None
    tags: list[str] | None = None


class Service(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_name: str | None = None
    # v0.1.4: environment registry
    environment_name: str | None = None
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
    purpose: str | None = None


class ServiceStorageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    storage_id: int
    purpose: str | None = None


class ServiceMiscLink(BaseModel):
    misc_id: int
    purpose: str | None = None


class ServiceMiscRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    misc_id: int
    purpose: str | None = None
