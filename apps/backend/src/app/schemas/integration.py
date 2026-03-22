"""Pydantic schemas for the Integrations API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IntegrationCreate(BaseModel):
    type: str
    name: str
    base_url: str
    api_key: str | None = None
    slug: str | None = None
    sync_interval_s: int = Field(default=60, ge=30)
    enabled: bool = True


class IntegrationUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # if present, re-encrypt and store; if omitted, leave unchanged
    slug: str | None = None
    sync_interval_s: int | None = Field(default=None, ge=30)
    enabled: bool | None = None


class IntegrationRead(BaseModel):
    id: int
    type: str
    name: str
    base_url: str
    slug: str | None = None
    sync_interval_s: int
    enabled: bool
    last_synced_at: datetime | None
    sync_status: str
    sync_error: str | None
    monitor_count: int = 0

    model_config = {"from_attributes": True}


class IntegrationMonitorRead(BaseModel):
    id: int
    integration_id: int
    integration_name: str = ""
    external_id: str
    name: str
    url: str | None
    status: str
    uptime_7d: float | None
    uptime_30d: float | None
    last_checked_at: datetime | None

    model_config = {"from_attributes": True}


class TestConnectionResult(BaseModel):
    ok: bool
    message: str
