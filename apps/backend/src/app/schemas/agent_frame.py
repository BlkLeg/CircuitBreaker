"""The agent protocol v1 frame envelope — defined once here and in
apps/agent/internal/frame/frame.go, nowhere else, per
specs/2026-07-26-cb-agent-design.md §1's `agent_link.py` boundary note."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

FRAME_VERSION = 1

# agent -> server
TYPE_HELLO = "hello"
TYPE_HEARTBEAT = "heartbeat"
TYPE_TELEMETRY_HOST = "telemetry.host"
TYPE_PROBE_RESULT = "probe.result"
TYPE_DISCOVERY_FINDING = "discovery.finding"
TYPE_CAPABILITY_VIOLATION = "capability.violation"
TYPE_CAPABILITY_READINESS = "capability.readiness"
TYPE_LOG = "log"
TYPE_UNINSTALL = "uninstall"
# Task 24: explicit self-update progress signal — the agent reports the
# transition points the server can't otherwise observe (download-start,
# swap-success, failure, rollback; queue-time is already server-side, at
# POST /{agent_id}/update). Additive-only protocol-v1 addition per Global
# Constraints: an old agent that never sends this frame simply never
# produces update_started/succeeded/failed/rolled_back agent_events, same as
# any other frame type it predates.
TYPE_UPDATE_STATUS = "update.status"

# server -> agent
TYPE_HELLO_ACK = "hello.ack"
TYPE_CAPABILITIES_SET = "capabilities.set"
TYPE_PROBE_ASSIGN = "probe.assign"
TYPE_DISCOVERY_REQUEST = "discovery.request"
TYPE_KEY_ROTATE = "key.rotate"
TYPE_UPDATE = "update"
TYPE_DISCONNECT = "disconnect"
TYPE_PING = "ping"

# bidirectional — either side may send it about its own cipher
TYPE_TRANSPORT_REKEY = "transport.rekey"


class AgentFrame(BaseModel):
    v: int = FRAME_VERSION
    type: str
    seq: int = 0
    ts: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


# Payload models below are the structured wire format for a subset of frame types, mirroring
# apps/agent/internal/frame/frame.go's HelloPayload / HelloAckPayload / TransportRekeyPayload /
# KeyRotatePayload field-for-field. They are schema/codec only: AgentFrame.payload above stays a
# generic dict, and nothing here wires rekey or key-rotation *behavior* — callers that want the
# typed form validate ``AgentFrame.payload`` against one of these explicitly. The conformance
# corpus in fixtures/agent_frame_corpus.json pins their wire shape against the Go side.


class Readiness(BaseModel):
    """One collector's ability to run, carried in HelloPayload.readiness — see
    specs/2026-07-26-cb-agent-design.md §4.3."""

    collector: str
    state: str  # ready | degraded | unavailable
    reason: str | None = None
    remediation: str | None = None
    missing: list[str] = Field(default_factory=list)


class HelloPayload(BaseModel):
    """agent -> server `hello` payload (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6).

    Every field is optional so an old-shaped hello — including today's empty ``{}`` payload —
    still validates: absent fields take their declared default rather than failing validation.
    """

    device_pk: str | None = None
    hostname: str | None = None
    machine_id_hash: str | None = None
    os: str | None = None
    os_version: str | None = None
    arch: str | None = None
    agent_version: str | None = None
    primary_macs: list[str] = Field(default_factory=list)
    readiness: list[Readiness] = Field(default_factory=list)
    spool_depth: int = 0
    capability_schema: int = 1


class HelloAckPayload(BaseModel):
    """server -> agent `hello.ack` payload for the post-enrollment link-establishment handshake
    (specs/2026-07-26-cb-agent-design.md §4.2: the server "re-sends the authoritative set on
    every hello.ack"). The enrollment socket (WS /api/agents/enroll) also emits `hello.ack`
    frames for pairing-code/status messages with a different, untyped payload shape (see
    ws_agents.py's ``_ack_bytes``); this model only covers the link ack. All fields are optional
    with safe defaults when absent.
    """

    accepted: bool = False
    reason: str | None = None
    server_time: datetime | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    agent_id: int | None = None


class CapabilityReadinessPayload(BaseModel):
    readiness: list[Readiness] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    """agent -> server `heartbeat` payload (D-12), mirroring
    apps/agent/internal/frame/frame.go's HeartbeatPayload field-for-field.

    Carries the agent's live outbound-spool backlog so the server can watch a
    catch-up drain start *and finish* without waiting for a reconnect to
    refresh hello's at-connect snapshot.

    Both fields are optional-with-default — the same backward-compatibility
    convention ``HelloPayload`` documents above — so today's empty ``{}``
    heartbeat from an agent that predates this model still validates instead
    of tearing down the link.

    That default is why callers must gate persistence on
    ``"spool_depth" in payload.model_fields_set`` rather than on the value:
    the Go side deliberately carries no ``omitempty``, so a current agent
    emits ``{"spool_depth": 0, "spool_bytes": 0}`` once its backlog clears,
    while an agent that predates the field emits ``{}``. Presence is
    therefore an exact "this agent reports spool state" test, and it is what
    keeps ``agents.spool_depth`` NULL ("never reported") for an old agent
    instead of writing a fabricated 0 ("reported, empty").
    """

    spool_depth: int = 0
    spool_bytes: int = 0


class HostTelemetryPayload(BaseModel):
    """agent -> server `telemetry.host` payload, mirroring
    apps/agent/internal/frame/frame.go's HostTelemetryPayload field-for-field.

    ``populate_by_name`` is load-bearing, not cosmetic: ``schema_version`` is aliased to the
    wire key ``schema`` (``schema`` shadows pydantic's own BaseModel attribute), so
    ``model_dump()``/``model_dump_json()`` emit ``schema_version`` unless the caller passes
    ``by_alias=True``. Without ``populate_by_name`` the model cannot re-validate its own dump —
    pinned by test_corpus_typed_payloads_decode_and_round_trip.
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(alias="schema")
    sample_id: str
    status: str
    summary: dict[str, int | float]
    filesystems: list[dict[str, Any]] = Field(default_factory=list)
    disks: list[dict[str, Any]] = Field(default_factory=list)
    interfaces: list[dict[str, Any]] = Field(default_factory=list)
    temperatures: list[dict[str, Any]] = Field(default_factory=list)
    docker: dict[str, Any] | None = None


class TransportRekeyPayload(BaseModel):
    """Announces a Noise cipher rekey for one direction of the link. `direction` is relative to
    the sender: "outbound" is the sender's send cipher, "inbound" is its receive cipher.
    `generation` is a per-direction, per-session counter the sender increments each rekey,
    letting the receiver tell rekey announcements apart; generations are strictly sequential
    from 1 per direction per connection. app/api/ws_agents.py drives the 15-minute timing and
    the cipher swap for the server->agent direction; internal/link does the same on the agent.
    """

    direction: str  # "inbound" | "outbound"
    generation: int = 0


class UpdateStatusPayload(BaseModel):
    """agent -> server `update.status` payload (Task 24): one self-update
    transition the agent itself observed, reported over the live `/link`
    connection that originally delivered the `update` frame (or the next
    reconnect, for `rolled_back` — see internal/update/update.go's
    rollback-report marker, written by a process that decided to roll back
    before it has any live connection to report over, and read/sent by the
    next process that reconnects).

    `phase` is one of "started" (download beginning), "succeeded" (binary
    swapped, marker written, about to re-exec), "failed" (download/verify/
    swap error — `error` carries a short message), or "rolled_back" (the
    2-minute confirm window lapsed with no successful reconnect at the new
    version, so the previous binary was restored).
    """

    version: str
    phase: str  # "started" | "succeeded" | "failed" | "rolled_back"
    error: str | None = None


_HEX_PK_RE = re.compile(r"^[0-9a-f]{64}$")


class KeyRotatePayload(BaseModel):
    """A pending device-key or server-key rotation: the kind of key being rotated, the
    successor public key material, and when the rotation must complete by. Schema only —
    Tasks 27/28 wire the rotation state machine.
    """

    kind: str  # "device" | "server"
    successor_pk: str
    expiry: datetime

    @field_validator("successor_pk")
    @classmethod
    def _successor_pk_must_be_hex_pubkey(cls, v: str) -> str:
        """Reject at frame-decode time, before `successor_pk` ever reaches
        `agent_registry.start_device_key_rotation`'s `bytes.fromhex(...)` /
        `Agent.pending_device_pk` column: an X25519 public key is exactly 32
        bytes, i.e. exactly 64 lowercase hex characters. Anything else — odd
        length, uppercase, non-hex characters, or an unbounded-length string
        — both crashes `bytes.fromhex` downstream and would otherwise let an
        arbitrary-length value get stored in the indexed
        `pending_device_pk` column."""
        if not _HEX_PK_RE.fullmatch(v):
            raise ValueError("successor_pk must be exactly 64 lowercase hex characters")
        return v
