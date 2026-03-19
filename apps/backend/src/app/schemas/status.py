"""Pydantic schemas for status pages, groups, and history."""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatusPageBase(BaseModel):
    slug: str
    name: str
    config: dict | None = None


class StatusPageCreate(StatusPageBase):
    pass


class StatusPageUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    config: dict | None = None


class StatusPageRead(StatusPageBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else None
            except json.JSONDecodeError:
                return None
        return None


# Node ref: {"type": "hardware"|"compute_unit"|"service", "id": int}
class StatusGroupBase(BaseModel):
    name: str
    nodes: list[dict] = Field(default_factory=list)  # [{"type": "hardware", "id": 1}, ...]
    services: list[int] = Field(default_factory=list)  # service IDs


class StatusGroupCreate(StatusGroupBase):
    status_page_id: int


class StatusGroupUpdate(BaseModel):
    name: str | None = None
    nodes: list[dict] | None = None
    services: list[int] | None = None
    add_node: dict | None = None  # e.g. {"type": "hardware", "id": 1} to append to group


class StatusGroupRead(StatusGroupBase):
    id: int
    status_page_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("nodes", mode="before")
    @classmethod
    def parse_nodes(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else []
            except json.JSONDecodeError:
                return []
        return []

    @field_validator("services", mode="before")
    @classmethod
    def parse_services(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else []
            except json.JSONDecodeError:
                return []
        return []


class StatusHistoryRead(BaseModel):
    id: int
    group_id: int
    timestamp: datetime
    overall_status: str
    uptime_pct: float
    avg_ping: float | None
    metrics: dict | None
    raw_telemetry: dict | None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("metrics", "raw_telemetry", mode="before")
    @classmethod
    def parse_json_dict(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else None
            except json.JSONDecodeError:
                return None
        return None


class HistoryFilter(BaseModel):
    group_id: int | None = None
    range: str | None = Field(default="7d", description="1h | 24h | 7d")
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class DashboardGroupSnapshot(BaseModel):
    """One group's latest metrics for dashboard."""

    id: int
    name: str
    status_page_id: int
    overall_status: str
    uptime_pct: float
    avg_ping: float | None
    last_poll: datetime | None
    metrics: dict | None


class DashboardResponse(BaseModel):
    pages: list[StatusPageRead]
    groups: list[DashboardGroupSnapshot]
    history_sample: dict | None = None  # group_id -> list of recent history for charts


# ── Dashboard v2 (Zabbix-density: groups + global + history per group) ──────────


class HistoryPoint(BaseModel):
    """One point in a group's history for charts."""

    ts: str  # ISO8601
    uptime_pct: float
    status: str
    cpu_pct: float | None = None
    mem_pct: float | None = None


class StatusEventRead(BaseModel):
    """One event for events table / timeline."""

    ts: str
    message: str
    severity: str  # info | warning | critical


class DashboardGroupItem(BaseModel):
    """One group in dashboard v2 response with full metrics and history."""

    id: int
    name: str
    status_page_id: int
    status: str  # up | degraded | down | unknown
    uptime: float
    avg_ping: float | None
    entities: int
    metrics: dict | None = None  # e.g. { "cpu": {"avg": 45, "max": 92}, "mem": {}, "events": [] }
    history: list[HistoryPoint] = Field(default_factory=list)
    last_poll: datetime | None = None
    is_proxmox: bool = False  # True when group's nodes are all from one Proxmox integration
    integration_id: int | None = None  # Set when is_proxmox; use for cluster-overview API


class DashboardGlobalSummary(BaseModel):
    """Global stats for dashboard header."""

    overall_uptime: float
    alerts: int
    total_entities: int


class DashboardV2Response(BaseModel):
    """Dashboard response with groups + global for Zabbix-density UI."""

    model_config = ConfigDict(populate_by_name=True)

    groups: list[DashboardGroupItem]
    global_: DashboardGlobalSummary = Field(alias="global")


# ── Available-Entities (for Settings / bulk-assign UX) ───────────────────────


class AvailableEntity(BaseModel):
    """A hardware or service entity visible in the Status Settings entity table."""

    id: int
    name: str
    type: str  # 'hardware' | 'service'
    role: str | None = None  # e.g. 'server', 'router', 'switch'
    status: str | None = None  # 'up' | 'down' | 'degraded' | 'unknown'
    source: str | None = None  # 'manual' | 'scan' | 'proxmox' | 'docker'
    last_seen: str | None = None  # ISO8601 string
    telemetry_summary: str | None = None  # short human label e.g. "CPU 42%"
    already_grouped: bool = False  # True if already in at least one StatusGroup


class AvailableEntitiesResponse(BaseModel):
    entities: list[AvailableEntity]
    total: int


class BulkGroupCreate(BaseModel):
    """Payload for creating one group with multiple entities in one shot."""

    name: str
    page_id: int
    entity_ids: list[int]
    entity_type: str  # 'hardware' | 'service'


class BulkGroupResponse(BaseModel):
    group_id: int
    added: int
