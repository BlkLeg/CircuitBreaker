from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# The one capability registry (Task 14 / D-14). Imported at module scope: it is
# dependency-free (typing/stdlib only), so the schema layer does not pull in a
# DB-touching service and there is no cycle to work around.
from app.services.agent_capabilities import normalize_grant


class CapabilityGrant(BaseModel):
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


# **Input-only.** Referenced solely by `ApproveRequest.capabilities` and
# `CapabilitiesUpdateRequest.capabilities`: every REST *request* keeps
# accepting a bare boolean or an `{enabled, config}` object per capability,
# indefinitely. It is never emitted on a response — every response carrying
# grants uses `CapabilityGrant` with server-normalized config (Task 15,
# **D-11**). The agent wire protocol is separate and unaffected:
# `api/ws_agents._wire_grants` still downgrades to booleans for
# `capability_schema < 2`.
CapabilityValue = bool | CapabilityGrant


def _validate_capability_map(values: dict[str, CapabilityValue]) -> dict[str, CapabilityValue]:
    """Run every requested grant through the server capability registry so an
    unknown capability name or an invalid config is a 422 at the edge rather
    than a `ValueError` escaping the service layer as a 500.

    Validation only — the persisted value is produced by `normalize_grant`
    again inside `agent_registry`, there against the grant's currently stored
    config. Merging the registry default here (with no `current_config`) is
    strictly the weaker check of the two, so nothing that passes here can be
    rejected there for a reason this pass would have caught.
    """
    for capability, value in values.items():
        try:
            normalize_grant(capability, value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    return values


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
    # Last-reported outbound-spool backlog (Task 16, D-12). NULL means the
    # agent has never reported one — a build predating `HeartbeatPayload` —
    # which is deliberately distinct from 0 ("reported, and drained").
    spool_depth: int | None = None
    spool_bytes: int | None = None
    spool_reported_at: datetime | None = None
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
    whole fleet from a single request instead of one per-agent call.

    `capabilities` is the canonical `{name: {enabled, config}}` shape,
    unconditionally and with no `?capability_shape` escape hatch (Task 15,
    **D-11**) — byte-identical to `AgentRead.capabilities` for the same grant
    rows, both projected by `agent_registry._structured_grant`. Consumers must
    read `.enabled`; the object itself is always truthy.
    """

    agent_id: int
    online: bool
    connected_since: datetime | None
    last_seen_at: datetime | None
    capabilities: dict[str, CapabilityGrant] = {}
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

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls, values: dict[str, CapabilityValue] | None
    ) -> dict[str, CapabilityValue] | None:
        return None if values is None else _validate_capability_map(values)


class RevokeRequest(BaseModel):
    reason: str | None = None


class CapabilitiesUpdateRequest(BaseModel):
    capabilities: dict[str, CapabilityValue]

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls, values: dict[str, CapabilityValue]
    ) -> dict[str, CapabilityValue]:
        return _validate_capability_map(values)


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
