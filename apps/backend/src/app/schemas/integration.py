"""Pydantic schemas for the Integrations API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    avg_response_ms: float | None = None
    cert_expiry_days: int | None = None
    linked_hardware_id: int | None = None
    last_heartbeat_at: datetime | None = None
    # Native probe fields
    linked_service_id: int | None = None
    probe_type: str | None = None
    probe_target: str | None = None
    probe_port: int | None = None
    probe_interval_s: int = 60
    is_native: bool = False

    model_config = {"from_attributes": True}


class IntegrationMonitorEventRead(BaseModel):
    id: int
    monitor_id: int
    previous_status: str
    new_status: str
    detected_at: datetime
    reason: str | None = None
    reason_by: int | None = None
    reason_at: datetime | None = None

    model_config = {"from_attributes": True}


class NativeMonitorCreate(BaseModel):
    entity_type: Literal["hardware", "service"]
    entity_id: int
    probe_type: str | None = None  # auto-derived if omitted
    probe_target: str | None = None  # auto-derived if omitted
    probe_port: int | None = None
    probe_interval_s: int = Field(default=60, ge=10)
    name: str | None = None  # defaults to entity name


class EventAnnotate(BaseModel):
    reason: str


class MonitorLinkUpdate(BaseModel):
    linked_hardware_id: int | None = None


class TestConnectionResult(BaseModel):
    ok: bool
    message: str
