"""The agent protocol v1 frame envelope — defined once here and in
apps/agent/internal/frame/frame.go, nowhere else, per
specs/2026-07-26-cb-agent-design.md §1's `agent_link.py` boundary note."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

FRAME_VERSION = 1

# agent -> server
TYPE_HELLO = "hello"
TYPE_HEARTBEAT = "heartbeat"
TYPE_TELEMETRY_HOST = "telemetry.host"
TYPE_PROBE_RESULT = "probe.result"
TYPE_DISCOVERY_FINDING = "discovery.finding"
TYPE_CAPABILITY_VIOLATION = "capability.violation"
TYPE_LOG = "log"
TYPE_UNINSTALL = "uninstall"

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
    capabilities: dict[str, bool] = Field(default_factory=dict)
    agent_id: int | None = None


class TransportRekeyPayload(BaseModel):
    """Announces a Noise cipher rekey for one direction of the link. `direction` is relative to
    the sender: "outbound" is the sender's send cipher, "inbound" is its receive cipher.
    `generation` is a per-direction, per-session counter the sender increments each rekey,
    letting the receiver tell rekey announcements apart. Schema only — Task 5 wires the actual
    rekey mechanism and the 15-minute timing.
    """

    direction: str  # "inbound" | "outbound"
    generation: int = 0


class KeyRotatePayload(BaseModel):
    """A pending device-key or server-key rotation: the kind of key being rotated, the
    successor public key material, and when the rotation must complete by. Schema only —
    Tasks 27/28 wire the rotation state machine.
    """

    kind: str  # "device" | "server"
    successor_pk: str
    expiry: datetime
