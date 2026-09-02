"""The agent protocol v1 frame envelope — defined once here and in
apps/agent/internal/frame/frame.go, nowhere else, per
specs/2026-07-26-cb-agent-design.md §1's `agent_link.py` boundary note."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.agent_scope import (
    REASON_EMPTY_SCOPE,
    REASON_EXCLUDED,
    REASON_INVALID_DESTINATION,
    REASON_OUT_OF_SCOPE,
    REASON_PREFIX_TOO_WIDE,
    REASON_SPECIAL_USE,
)

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
TYPE_PROBE_CANCEL = "probe.cancel"
TYPE_DISCOVERY_REQUEST = "discovery.request"
TYPE_DISCOVERY_CANCEL = "discovery.cancel"
TYPE_KEY_ROTATE = "key.rotate"
TYPE_TLS_PIN_ROTATE = "tls.pin.rotate"
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


class NetworkFacts(BaseModel):
    """One of the agent host's directly connected networks, carried in HelloPayload.networks
    (D-1), mirroring apps/agent/internal/frame/frame.go's NetworkFacts.

    ``addrs`` are CIDR strings holding the interface's own address *with* its prefix length
    ("10.0.0.5/24", "fd00::1/64") — the prefix is what makes the network directly connected and
    is the whole input to the slice-3 scope evaluator. ``flags`` uses Go's net.Flags vocabulary
    ("up", "broadcast", "pointtopoint", ...). These are reported facts, not policy: the agent
    reports every usable address it has and the server decides which fall inside scope.
    """

    name: str
    flags: list[str] = Field(default_factory=list)
    addrs: list[str] = Field(default_factory=list)


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
    networks: list[NetworkFacts] = Field(default_factory=list)
    spool_depth: int = 0
    capability_schema: int = 1
    tls_pin_kind: str | None = None


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
    """agent -> server `capability.readiness` payload.

    ``networks`` is the same shape as ``HelloPayload.networks`` and exists so an
    agent can refresh its directly connected networks *mid-session* (Slice 4
    D-8). Hello carries them only at connect, so without this a subnet that
    appeared on the agent host would not become discoverable until the next
    reconnect — which may be days.

    It is optional and callers must gate persistence on presence in
    ``model_fields_set``, never on truthiness: an agent that predates the field
    omits the key entirely and must leave the last known report standing, while
    an explicit ``[]`` is a real report of "nothing directly connected" and must
    replace it. That is why the Go side carries no ``omitempty`` for it — an
    agent that has lost every interface must be able to say so, or a stale,
    wider-than-reality scope stands forever.
    """

    readiness: list[Readiness] = Field(default_factory=list)
    networks: list[NetworkFacts] = Field(default_factory=list)


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


class ProbeAssignPayload(BaseModel):
    """server -> agent `probe.assign` payload (§4), mirroring
    apps/agent/internal/frame/frame.go's ProbeAssignPayload field-for-field: exactly one remote
    check, fully specified, with no schedule for the agent to keep.

    ``run_id`` is the server-minted 32-hex token that is the only identifier a result may be
    posted against, so a leaked or guessed ``monitor_id`` buys nothing. ``config`` is the
    monitor's complete validated configuration and therefore carries HTTP credentials when the
    monitor has them (D-10): the agent holds it in memory for the life of the run and it must
    never reach ``status.json``, ``grants.json``, a log line, or ``probe.result``.

    ``scheduled_at``/``deadline_at`` must be serialized with ``.isoformat()``, never left as raw
    ``datetime`` objects: ``agent_registry.publish_agent_control_frame`` dumps with
    ``default=str``, which renders a space separator that Go's ``time.Time`` rejects.
    """

    run_id: str
    monitor_id: int
    check_type: str  # icmp | tcp | http | dns
    host: str
    config: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime
    deadline_at: datetime


class ProbeCancelPayload(BaseModel):
    """server -> agent `probe.cancel` payload (§4), sent when a monitor is paused, deleted,
    reassigned, has its capability disabled, or the agent is revoked.

    ``reason`` is advisory. Cancellation is best-effort and the backend stays authoritative: a
    result for a run it has already closed is rejected on arrival regardless of whether the
    cancel was ever delivered.
    """

    run_id: str
    reason: str | None = None


class ProbeSample(BaseModel):
    """One observation from a completed check, mirroring
    ``app.services.monitoring.collectors.Sample`` so a remote result reaches the shared result
    service in the same shape a server-executed one does.

    ``error_reason`` is the collectors' own per-sample annotation ("http_error", "dns_error").
    It is audit metadata: it lands in ``monitor_probe_runs.result_metadata`` and nowhere else,
    exactly as it is dropped for server-executed checks today (D-8).
    """

    metric: str
    value: float
    error_reason: str | None = None


class ProbeResultPayload(BaseModel):
    """agent -> server `probe.result` payload (§4), mirroring
    apps/agent/internal/frame/frame.go's ProbeResultPayload field-for-field.

    ``outcome`` is closed: "completed" (a real target result, feed the monitor state machine),
    "execution_error" (the agent could not perform the probe), "cancelled", or "rejected"
    (invalid, unauthorized, out-of-scope or capacity-limited assignment). Only "completed" says
    anything about the target — the other three preserve its last known state, which is why
    ``up`` is meaningless outside "completed" rather than a fallback DOWN.

    ``up`` is required rather than defaulted, and the Go side deliberately carries no
    ``omitempty`` for it: false is what a DOWN target reports, so an absent key must be a
    protocol error and never silently read as "no opinion".

    The 64 KiB ``details`` and 2000-character ``msg`` limits are enforced by the ingest handler
    on the raw frame before this model ever runs — nothing upstream bounds inbound frame size.
    """

    run_id: str
    monitor_id: int
    outcome: str  # completed | execution_error | cancelled | rejected
    up: bool
    started_at: datetime
    finished_at: datetime
    samples: list[ProbeSample] = Field(default_factory=list)
    msg: str = ""
    details: dict[str, Any] | None = None


_DISPATCH_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FINDING_ID_RE = re.compile(r"^[0-9a-f]{1,64}$")

# Slice 4 plan §4's bounds. They are declared here, on the model, rather than
# left to the ingest handler, because a bound the *schema* does not carry is one
# the agent's own encoder has no reason to respect — and `discovery.finding` is
# a spooled data frame, so a single oversized batch replayed after an outage is
# the shape this has to survive.
MAX_DISCOVERY_TARGETS = 16
MAX_DISCOVERY_PORTS = 32
MAX_DISCOVERY_EVIDENCE = 16
MAX_DISCOVERY_OPEN_PORTS = 64
MAX_DISCOVERY_BANNER_CHARS = 512
MAX_DISCOVERY_MSG_CHARS = 2000

# The closed `kind` vocabulary. A `host` finding describes one address; a
# `summary` is the dispatch's single terminal frame. Both travel as the same
# frame type so the summary rides the spool with the findings it closes, which
# is what makes replay after an outage idempotent rather than a job that never
# finishes.
DISCOVERY_KIND_HOST = "host"
DISCOVERY_KIND_SUMMARY = "summary"
DISCOVERY_KINDS = frozenset({DISCOVERY_KIND_HOST, DISCOVERY_KIND_SUMMARY})


class DiscoveryRequestPayload(BaseModel):
    """server -> agent `discovery.request` payload (plan §4).

    One bounded, one-shot scan. Every limit here is *also* enforced by the agent
    against its own grant before it opens a socket — the backend deriving a
    target and the agent accepting one are independent checks on purpose, so a
    backend bug cannot widen what an agent will actually scan.

    ``scope_version`` is the ``EffectiveScope.version`` in force when the
    request was built. The agent re-derives its own and refuses a mismatch: plan
    §2 requires an active request to be cancelled when scope changes
    incompatibly, and a version is what makes that decidable without shipping
    the whole CIDR list on every dispatch.

    Datetimes are ``datetime`` and must be serialized with ``.isoformat()`` —
    ``agent_registry.publish_agent_control_frame`` dumps with ``default=str``,
    which renders a space separator that Go's ``time.Time`` rejects.
    """

    dispatch_id: str
    scan_job_id: int
    targets: list[str] = Field(default_factory=list, max_length=MAX_DISCOVERY_TARGETS)
    methods: list[str] = Field(default_factory=list, max_length=8)
    tcp_ports: list[int] = Field(default_factory=list, max_length=MAX_DISCOVERY_PORTS)
    host_timeout_ms: int
    max_concurrent_hosts: int
    scope_version: str = Field(max_length=64)
    deadline_at: datetime

    @field_validator("dispatch_id")
    @classmethod
    def _dispatch_id_is_a_128_bit_hex_token(cls, v: str) -> str:
        if not _DISPATCH_ID_RE.fullmatch(v):
            raise ValueError("dispatch_id must be exactly 32 lowercase hex characters")
        return v


class DiscoveryCancelPayload(BaseModel):
    """server -> agent `discovery.cancel` payload (plan §4), sent when the job is
    cancelled, its profile disabled, scope changed incompatibly, the capability
    disabled, or the agent revoked.

    ``reason`` is advisory. Cancellation is best-effort and the backend stays
    authoritative: a finding for a dispatch it has already closed is rejected on
    arrival regardless of whether the cancel was ever delivered.
    """

    dispatch_id: str
    reason: str | None = Field(default=None, max_length=64)


class DiscoveryOpenPort(BaseModel):
    """One reachable TCP port on a discovered host.

    ``banner`` is an untrusted observation: whatever bytes the service sent
    first, control characters stripped and truncated agent-side. It is bounded
    again here because ``ScanResult.banner`` is an unbounded ``Text`` column, so
    this cap is the only one there is.
    """

    port: int = Field(ge=1, le=65535)
    protocol: str = Field(default="tcp", max_length=8)
    banner: str | None = Field(default=None, max_length=MAX_DISCOVERY_BANNER_CHARS)


class DiscoveryFindingPayload(BaseModel):
    """agent -> server `discovery.finding` payload (plan §4), mirroring
    apps/agent/internal/frame/frame.go's DiscoveryFindingPayload field-for-field.

    ``kind`` is closed: ``host`` describes one discovered address, ``summary``
    is the dispatch's single terminal frame carrying counts and outcome. A
    summary has its own ``finding_id`` for the same reason every host finding
    does — spool replay must be idempotent, and the frame that *closes* a job is
    exactly the one an outage is most likely to duplicate.

    ``finding_id`` is agent-chosen but replay-stable by construction (a digest
    of dispatch/kind/address), which is what turns
    ``uq_scan_results_job_finding`` into an idempotency key rather than a race.
    It is bounded to the width of its ``String(64)`` column: an over-length
    value would otherwise become a psycopg ``DataError`` inside the ``/link``
    read loop.

    Every string here is an untrusted observation. ``hostname`` is a PTR answer
    from a resolver the agent does not control, ``banner`` is whatever bytes a
    service chose to send, and ``mac_address`` is whatever the neighbor cache
    held. None of them may reach ``Hardware`` without review, and none may be
    embedded in a log line or an audit detail.
    """

    dispatch_id: str
    scan_job_id: int
    finding_id: str
    kind: str = DISCOVERY_KIND_HOST
    observed_at: datetime
    ip_address: str | None = Field(default=None, max_length=45)
    mac_address: str | None = Field(default=None, max_length=17)
    hostname: str | None = Field(default=None, max_length=253)
    open_ports: list[DiscoveryOpenPort] = Field(
        default_factory=list, max_length=MAX_DISCOVERY_OPEN_PORTS
    )
    evidence: list[str] = Field(default_factory=list, max_length=MAX_DISCOVERY_EVIDENCE)
    terminal: bool = False
    # `summary` fields. Absent on a `host` finding; a `host` finding that
    # carried them would simply be ignored by the ingest handler rather than
    # rejected, since they say nothing about the address.
    outcome: str | None = Field(default=None, max_length=24)
    hosts_found: int | None = Field(default=None, ge=0)
    addresses_scanned: int | None = Field(default=None, ge=0)
    msg: str | None = Field(default=None, max_length=MAX_DISCOVERY_MSG_CHARS)
    error_code: str | None = Field(default=None, max_length=64)

    @field_validator("dispatch_id")
    @classmethod
    def _dispatch_id_is_a_128_bit_hex_token(cls, v: str) -> str:
        if not _DISPATCH_ID_RE.fullmatch(v):
            raise ValueError("dispatch_id must be exactly 32 lowercase hex characters")
        return v

    @field_validator("finding_id")
    @classmethod
    def _finding_id_fits_its_column(cls, v: str) -> str:
        if not _FINDING_ID_RE.fullmatch(v):
            raise ValueError("finding_id must be 1-64 lowercase hex characters")
        return v

    @field_validator("evidence")
    @classmethod
    def _evidence_entries_are_short_labels(cls, v: list[str]) -> list[str]:
        """Evidence names *how* the agent saw the host ("neighbor_cache",
        "tcp_connect"), never what it saw. Bounding each entry keeps an
        attacker from smuggling banner bytes through a field nothing else
        truncates."""
        if any(len(entry) > 32 for entry in v):
            raise ValueError("evidence entries must be at most 32 characters")
        return v


# Slice 4 plan §7's bounds on the agent's own outbound refusal report. Unlike
# every other agent -> server frame, `capability.violation` is deliberately
# absent from `agent_link.CAPABILITY_FOR_TYPE`, so `dispatch_frame`'s grant gate
# never runs for it: an agent with every capability disabled can still send one,
# and it lands in `agent_events.detail` — an unbounded JSONB column with no
# retention job. The bounds therefore have to live on the model, because the
# handler is the only thing between the wire and that column.

# `not_directly_connected` has no `core/agent_scope.py` counterpart on purpose —
# it is internal/netscope's agent-side-only rule (netscope.go:48-52), since only
# the agent knows which of the networks it was authorized for it is attached to
# right now. It is quoted here rather than imported because there is nothing to
# import it from.
REASON_NOT_DIRECTLY_CONNECTED = "not_directly_connected"

# The closed `capability.violation` reason vocabulary: the scope evaluator's own
# machine-readable refusals, which is exactly what
# `probe.Runtime.emitCapabilityViolation` sends (probe/runtime.go:606-619).
#
# Two of the evaluator's reasons are deliberately absent. `in_scope` is an
# acceptance and can never describe a refusal. `unresolved_hostname` is a name
# that resolved to nothing: the destination was never judged, so the agent
# reports it as an execution error and explicitly does *not* emit a capability
# violation for it (probe/runtime.go:511-518) — accepting it here would let the
# misleading row that comment exists to prevent be written by some other sender.
CAPABILITY_VIOLATION_REASONS = frozenset(
    {
        REASON_SPECIAL_USE,
        REASON_EXCLUDED,
        REASON_EMPTY_SCOPE,
        REASON_OUT_OF_SCOPE,
        REASON_INVALID_DESTINATION,
        REASON_PREFIX_TOO_WIDE,
        REASON_NOT_DIRECTLY_CONNECTED,
    }
)

# `frame_type` is one of this module's own TYPE_* strings; 32 characters is
# comfortably wider than the longest of them and leaves no room for a smuggled
# payload.
MAX_VIOLATION_FRAME_TYPE_CHARS = 32
# `reason` is closed, so its widest member *is* its bound — derived rather than
# written down so the two can never drift. It matters despite the membership
# check below: pydantic applies `max_length` first, so a hostile 40 KiB reason is
# refused on width and never reaches a set lookup or an error string.
MAX_VIOLATION_REASON_CHARS = max(len(reason) for reason in CAPABILITY_VIOLATION_REASONS)
# An address is the widest untrusted value the event is allowed to carry, and 45
# characters is a full IPv6 literal. Byte-identical to
# `agent_discovery._MAX_REASON_ADDRESS_CHARS`, for the same reason: anything
# longer is not an address.
MAX_VIOLATION_ADDRESS_CHARS = 45
# The one free-text field, capped at the same 200 characters
# `core.log_sanitize.safe_log_fragment` defaults to and `update.status`'s `error`
# is truncated to.
MAX_VIOLATION_DETAIL_CHARS = 200


class CapabilityViolationPayload(BaseModel):
    """agent -> server `capability.violation` payload (plan §7): the agent
    refused something this server asked it to do, and the two ends therefore
    disagree about this agent's authorization.

    Mirrors the anonymous struct `probe.Runtime.emitCapabilityViolation` encodes
    (`frame_type` plus the evaluator's own reason) and adds two optional fields
    the same shape allows for: `address`, the destination that was refused, and
    `detail`, short prose for an operator.

    Every field is bounded and `reason` is a closed vocabulary, because this is
    the only inbound frame no capability grant gates — see
    `CAPABILITY_VIOLATION_REASONS` above. Unknown keys are ignored rather than
    rejected, which is both this module's additive-compatibility convention and
    the property that keeps a banner or an evidence value out of the audit row:
    the handler builds its detail from these named fields alone, so a field that
    does not exist here cannot be persisted.

    `frame_type` is optional-with-default for the same backward-compatibility
    reason `HelloPayload` documents: the reason *is* the security signal, and a
    report that names no frame must still be auditable rather than dropped.
    """

    frame_type: str = Field(default="", max_length=MAX_VIOLATION_FRAME_TYPE_CHARS)
    reason: str = Field(max_length=MAX_VIOLATION_REASON_CHARS)
    address: str | None = Field(default=None, max_length=MAX_VIOLATION_ADDRESS_CHARS)
    detail: str | None = Field(default=None, max_length=MAX_VIOLATION_DETAIL_CHARS)

    @field_validator("reason")
    @classmethod
    def _reason_is_in_the_closed_vocabulary(cls, v: str) -> str:
        """Rejected here rather than filtered by the handler so the bound is
        visible on the wire contract itself. The message deliberately does not
        echo the offending value: it is attacker-authored text, and pydantic's
        own error string is what a caller would otherwise log."""
        if v not in CAPABILITY_VIOLATION_REASONS:
            raise ValueError("reason is outside the capability.violation vocabulary")
        return v


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


class TLSPinRotatePayload(BaseModel):
    """server -> agent `tls.pin.rotate` payload: the TLS trust policy this
    install is about to start serving, advertised over the authenticated
    Noise link ahead of the certificate actually changing.

    The rotated unit is a policy, not a digest. `mode="public"` carries an
    empty `successor_pin` and means "stop pinning; verify against the system
    CA store" — the transition a Let's Encrypt cutover makes, which a
    pin-only advertisement could not express. `mode="self_signed"` carries
    the base64 SHA-256 SPKI digest of the successor leaf, the same value
    `agent_install._spki_pin` computes.
    """

    mode: str
    successor_pin: str = ""
    expiry: datetime
