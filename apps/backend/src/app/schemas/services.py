import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

# `service.url` is rendered into an anchor href in the UI, so a stored
# `javascript:` payload executes in the viewer's session. The frontend refuses
# to render an untrusted scheme (`utils/validation.safeHref`) and this stops new
# rows carrying one; both are needed, because the frontend guard is what protects
# rows written before this validator existed.
_SAFE_URL_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


# Deliberately attached to the two request models rather than to `ServiceBase`:
# the `Service` response model inherits `ServiceBase`, and a row written before
# this validator existed would then raise on serialization and take out the whole
# services list. Reads stay permissive and the frontend refuses to link them.
def _validate_url_scheme(v: str | None) -> str | None:
    if v is None or not v.strip():
        return v
    if not _SAFE_URL_SCHEME.match(v.strip()):
        raise ValueError("Service URL must start with http:// or https://")
    return v


class PortEntry(BaseModel):
    ip: str | None = None  # per-port IP override; inherits service ip_address if None
    port: int | None = None
    protocol: str | None = "tcp"  # "tcp" | "udp" | "sctp"
    label: str | None = None


class LinkedDocument(BaseModel):
    id: int
    title: str
    category: str | None = None
    icon: str | None = None


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
    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_url_scheme(v)


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

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_url_scheme(v)


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
    documents: list[LinkedDocument] = []


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
    connection_type: str | None = None


class ServiceStorageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    storage_id: int
    purpose: str | None = None


class ServiceMiscLink(BaseModel):
    misc_id: int
    purpose: str | None = None
    connection_type: str | None = None


class ServiceMiscRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    misc_id: int
    purpose: str | None = None
