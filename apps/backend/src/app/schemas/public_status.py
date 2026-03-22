"""Pydantic schemas for the public (unauthenticated) status page API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PublicMonitor(BaseModel):
    id: int
    name: str
    url: str | None
    status: str
    uptime_7d: float | None
    uptime_30d: float | None
    last_checked_at: datetime | None
    integration_name: str


class PublicIncident(BaseModel):
    monitor_name: str
    integration_name: str
    previous_status: str
    new_status: str
    detected_at: datetime
    resolved_at: datetime | None


class PublicGroup(BaseModel):
    id: int
    name: str
    monitors: list[PublicMonitor]


class PublicStatusPageResponse(BaseModel):
    id: int
    title: str
    slug: str
    is_public: bool
    overall_status: str  # "operational" | "partial" | "major" | "unknown"
    updated_at: datetime
    groups: list[PublicGroup]
    incidents: list[PublicIncident]  # last 30 days, newest first
