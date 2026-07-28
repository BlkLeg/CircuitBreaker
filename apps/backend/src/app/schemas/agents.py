from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentSummary(BaseModel):
    id: int
    name: str | None
    hostname: str | None
    status: str
    os: str | None
    arch: str | None
    agent_version: str | None
    fingerprint: str
    hardware_id: int | None
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class AgentRead(AgentSummary):
    device_pk: str
    machine_id_hash: str | None
    reported_ip: str | None
    tenant_id: int | None
    notes: str | None
    enrolled_at: datetime
    approved_at: datetime | None
    connected_since: datetime | None
    capabilities: dict[str, bool] = {}


class AgentPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    hardware_id: int | None = None


class AgentEventRead(BaseModel):
    id: int
    event_type: str
    actor_user_id: int | None
    detail: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PairingLookupRequest(BaseModel):
    code: str


class PairingLookupResponse(BaseModel):
    agent_id: int
    hostname: str | None
    os: str | None
    arch: str | None
    fingerprint: str
    proposed_hardware_id: int | None
    proposed_hardware_name: str | None
    duplicate_machine_id: bool


class ApproveRequest(BaseModel):
    hardware_id: int | None = None
    capabilities: dict[str, bool] | None = None


class RevokeRequest(BaseModel):
    reason: str | None = None


class CapabilitiesUpdateRequest(BaseModel):
    capabilities: dict[str, bool]
