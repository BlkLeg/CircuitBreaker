"""Pydantic schemas for Proxmox VE integration endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ── Config CRUD ──────────────────────────────────────────────────────────────


class ProxmoxConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    config_url: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    auto_sync: bool = True
    sync_interval_s: int = Field(default=300, ge=30, le=86400)
    verify_ssl: bool = False


class ProxmoxConfigUpdate(BaseModel):
    name: str | None = None
    config_url: str | None = None
    api_token: str | None = None
    auto_sync: bool | None = None
    sync_interval_s: int | None = Field(default=None, ge=30, le=86400)
    verify_ssl: bool | None = None


class ProxmoxConfigOut(BaseModel):
    id: int
    type: str
    name: str
    config_url: str
    cluster_name: str | None = None
    auto_sync: bool
    sync_interval_s: int
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    verify_ssl: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── Connection test ──────────────────────────────────────────────────────────


class ProxmoxTestResponse(BaseModel):
    ok: bool
    version: str | None = None
    release: str | None = None
    cluster_name: str | None = None
    error: str | None = None


# ── Discovery ────────────────────────────────────────────────────────────────


class ProxmoxDiscoverResponse(BaseModel):
    ok: bool
    cluster_name: str | None = None
    nodes_imported: int = 0
    vms_imported: int = 0
    cts_imported: int = 0
    networks_imported: int = 0
    storage_imported: int = 0
    errors: list[str] = []


# ── Sync status ──────────────────────────────────────────────────────────────


class ProxmoxSyncStatus(BaseModel):
    integration_id: int
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    cluster_name: str | None = None
    nodes_count: int = 0
    vms_count: int = 0
    cts_count: int = 0
    storage_count: int = 0


# ── VM action ────────────────────────────────────────────────────────────────


class ProxmoxActionRequest(BaseModel):
    action: str = Field(..., pattern="^(start|stop|reboot|shutdown|reset|suspend|resume)$")


class ProxmoxActionResponse(BaseModel):
    ok: bool
    upid: str | None = None
    error: str | None = None
