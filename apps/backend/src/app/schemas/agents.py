from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

HOST_TELEMETRY_DEFAULTS = {
    "interval_s": 30,
    "include_filesystems": True,
    "include_disks": True,
    "include_network": True,
    "include_temperatures": True,
    "include_virtual": False,
    "include_docker": False,
}


class CapabilityGrant(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


CapabilityValue = bool | CapabilityGrant


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
    capabilities: dict[str, CapabilityGrant] = {}
    # Populated by api/agents.py's `_to_read` (not ORM attributes) from
    # `agent_registry.propose_hardware_match`/`has_duplicate_machine_id` —
    # the same host-linkage proposal and duplicate-machine warning the
    # pairing-lookup endpoint (`PairingLookupResponse`) surfaces, so the
    # agent-detail view and the pairing-code approval flow never disagree.
    proposed_hardware_id: int | None = None
    proposed_hardware_name: str | None = None
    duplicate_machine_id: bool = False


class HardwareSummary(BaseModel):
    """Linked-hardware summary for a fleet table row.

    Mirrors the "id + name" shape `HardwareClusterMemberRead.hardware_name`
    and `PairingLookupResponse.proposed_hardware_name` already use elsewhere
    for hardware display, plus the identifying fields (`hostname`,
    `ip_address`, `mac_address`) — the same fields `agent_registry.
    propose_hardware_match` matches an agent against — rather than the full
    `Hardware` row.
    """

    id: int
    name: str
    hostname: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None

    model_config = {"from_attributes": True}


class AgentPresenceRead(BaseModel):
    """One fleet table row's worth of presence + grant + hardware data —
    the bulk lookup Task 12 adds so `AgentsPage` (Task 14) can render the
    whole fleet from a single request instead of one per-agent call."""

    agent_id: int
    online: bool
    connected_since: datetime | None
    last_seen_at: datetime | None
    capabilities: Mapping[str, CapabilityValue] = {}
    hardware: HardwareSummary | None = None


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
    # Explicit record of which host-link path the approver took
    # (`AgentApprovalModal`, Task 18) — "accept" the proposed match, "select"
    # a different existing Hardware row, "create" one from reported facts
    # (frontend creates it via POST /hardware first, then approves with the
    # resulting id), or leave the agent "unlinked". Purely descriptive for
    # the approval event's audit detail; `hardware_id` above is what
    # actually drives linkage. Optional/omittable so existing untyped
    # callers (and tests predating Task 18) keep working.
    host_link_action: Literal["accept", "select", "create", "unlinked"] | None = None
    capabilities: dict[str, CapabilityValue] | None = None


class RevokeRequest(BaseModel):
    reason: str | None = None


class CapabilitiesUpdateRequest(BaseModel):
    capabilities: dict[str, CapabilityValue]

    @field_validator("capabilities")
    @classmethod
    def validate_host_config(cls, values: dict[str, CapabilityValue]) -> dict[str, CapabilityValue]:
        host = values.get("host_telemetry")
        if isinstance(host, CapabilityGrant):
            unknown = set(host.config) - set(HOST_TELEMETRY_DEFAULTS)
            if unknown:
                raise ValueError(f"unknown host_telemetry settings: {', '.join(sorted(unknown))}")
            interval = host.config.get("interval_s", 30)
            if (
                isinstance(interval, bool)
                or not isinstance(interval, int)
                or not 10 <= interval <= 900
            ):
                raise ValueError("host_telemetry.interval_s must be between 10 and 900")
            for name in set(HOST_TELEMETRY_DEFAULTS) - {"interval_s"}:
                if name in host.config and not isinstance(host.config[name], bool):
                    raise ValueError(f"host_telemetry.{name} must be a boolean")
        return values


class UpdateRequest(BaseModel):
    version: str | None = None


class InstallCommandResponse(BaseModel):
    tls_mode: str
    command: str
    script_sha256: str


class ServerKeyRotationStatus(BaseModel):
    """Task 28: the server's identity-key rotation state, as surfaced to
    admins. Never carries key material — fingerprints only, same convention
    as `app.core.agent_crypto.server_fingerprint`."""

    active: bool
    current_key_fingerprint: str
    successor_key_fingerprint: str | None = None
    started_at: datetime | None = None
    overlap_expires_at: datetime | None = None
