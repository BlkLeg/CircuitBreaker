from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ServiceBase(BaseModel):
    name: str
    slug: str
    compute_id: Optional[int] = None
    hardware_id: Optional[int] = None
    icon_slug: Optional[str] = None
    category: Optional[str] = None
    url: Optional[str] = None
    ports: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None  # running | stopped | degraded | maintenance
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
    url: Optional[str] = None
    ports: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None  # running | stopped | degraded | maintenance
    tags: Optional[list[str]] = None


class Service(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


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
