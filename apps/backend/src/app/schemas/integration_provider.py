"""Pydantic schemas for the unified integration provider CRUD endpoint."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

VALID_PROVIDERS = {"proxmox", "docker", "truenas", "unifi"}


class IntegrationProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    config_url: str = Field(..., min_length=1)
    credential_type: str = Field(
        default="api_key",
        description="snmp | ssh | ipmi | smtp | api_key | proxmox_api",
    )
    credential_value: str | None = Field(
        default=None,
        description="Plaintext credential — encrypted at rest via Fernet vault",
    )
    auto_sync: bool = True
    sync_interval_s: int = Field(default=300, ge=30, le=86400)
    extra_config: dict | None = None


class IntegrationProviderUpdate(BaseModel):
    name: str | None = None
    config_url: str | None = None
    credential_value: str | None = None
    auto_sync: bool | None = None
    sync_interval_s: int | None = Field(default=None, ge=30, le=86400)
    extra_config: dict | None = None


class IntegrationProviderRead(BaseModel):
    id: int
    type: str
    name: str
    config_url: str
    credential_id: int | None = None
    cluster_name: str | None = None
    auto_sync: bool
    sync_interval_s: int
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    extra_config: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
