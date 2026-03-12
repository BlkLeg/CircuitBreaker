"""Pydantic schemas for Proxmox VE integration endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.core.url_validation import reject_ssrf_url_proxmox

# ── Config CRUD ──────────────────────────────────────────────────────────────


class ProxmoxConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    config_url: HttpUrl | str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    auto_sync: bool = True
    sync_interval_s: int = Field(default=300, ge=30, le=86400)
    verify_ssl: bool = True

    @field_validator("config_url")
    @classmethod
    def validate_config_url(cls, v: HttpUrl | str) -> str:
        url_str = str(v).strip().rstrip("/")
        if url_str and "://" not in url_str:
            url_str = "https://" + url_str
        reject_ssrf_url_proxmox(url_str)
        return url_str


class ProxmoxConfigUpdate(BaseModel):
    name: str | None = None
    config_url: HttpUrl | str | None = None

    @field_validator("config_url")
    @classmethod
    def validate_config_url(cls, v: HttpUrl | str | None) -> str | None:
        if v is None:
            return None
        url_str = str(v).strip().rstrip("/")
        if url_str and "://" not in url_str:
            url_str = "https://" + url_str
        reject_ssrf_url_proxmox(url_str)
        return url_str

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


class ProxmoxDiscoverRunOut(BaseModel):
    """One Proxmox discovery run (for history and detail)."""

    id: int
    integration_id: int
    status: str  # running | completed | failed
    started_at: datetime
    completed_at: datetime | None = None
    nodes_imported: int = 0
    vms_imported: int = 0
    cts_imported: int = 0
    storage_imported: int = 0
    networks_imported: int = 0
    errors: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProxmoxDiscoverResponse(BaseModel):
    ok: bool
    cluster_name: str | None = None
    nodes_imported: int = 0
    vms_imported: int = 0
    cts_imported: int = 0
    networks_imported: int = 0
    storage_imported: int = 0
    results_queued: int = 0
    review_job_id: int | None = None
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


# ── Cluster overview (dashboard) ──────────────────────────────────────────────


class ProxmoxClusterOverviewCluster(BaseModel):
    name: str = ""
    quorum: bool = False
    nodes_online: int = 0
    nodes_total: int = 0
    vms: int = 0
    lxcs: int = 0
    uptime: str = ""


class ProxmoxClusterOverviewProblem(BaseModel):
    time: str = ""
    severity: str = "info"
    host: str = ""
    problem: str = ""
    status: str = "PROBLEM"


class ProxmoxClusterOverviewStorage(BaseModel):
    name: str
    used_gb: float | None = None
    total_gb: float | None = None
    content: str = ""


class ProxmoxClusterOverviewTimeSeries(BaseModel):
    """Per-node time-series for charts. Keys are node names."""

    cpu: dict[str, list[dict[str, float | str]]] = {}  # node -> [{time, value}, ...]
    memory: dict[str, list[dict[str, float | str]]] = {}
    network_in: dict[str, list[dict[str, float | str]]] = {}
    network_out: dict[str, list[dict[str, float | str]]] = {}


class ProxmoxClusterOverviewResponse(BaseModel):
    cluster: ProxmoxClusterOverviewCluster
    problems: list[ProxmoxClusterOverviewProblem] = []
    time_series: ProxmoxClusterOverviewTimeSeries = Field(
        default_factory=ProxmoxClusterOverviewTimeSeries
    )
    storage: list[ProxmoxClusterOverviewStorage] = []
