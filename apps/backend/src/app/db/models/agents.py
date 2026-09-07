"""The cb-agent fleet: enrolment, granted capabilities, host telemetry and its hourly rollup."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._shared import _FK_HARDWARE_ID, _now
from app.db.session import Base


class Agent(Base):
    """A cb-agent instance enrolled against this Circuit Breaker server."""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    device_pk: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    # pending|active|revoked|rejected
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    machine_id_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    os: Mapped[str | None] = mapped_column(String, nullable=True)
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    arch: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # The server_url this agent reported dialing at enrollment. The server has
    # no other way to know: it never connects to the agent, so an endpoint that
    # nothing can reach is otherwise invisible — the agent that would report the
    # failure is the one that cannot connect to report it.
    enrolled_via_endpoint: Mapped[str | None] = mapped_column(String, nullable=True)
    # Slice B: which enrollment token this agent came through, when it came
    # through one. Nullable and never back-filled — every agent enrolled before
    # this slice, and every attended enrollment after it, has none.
    enrollment_token_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_enrollment_tokens.id"), nullable=True
    )
    # Task 24: the version a queued self-update is expected to land the agent
    # on, set by POST /{agent_id}/update and cleared once that outcome is
    # resolved — either `version_changed` fires on a reconnect whose hello
    # reports this exact version (agent_registry.update_hello_metadata), or
    # an `update.status` frame with phase failed/rolled_back arrives for it
    # (agent_link._handle_update_status). Never set directly by a hello.
    pending_update_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Task 27: device-key rotation. Set together by
    # agent_registry.start_device_key_rotation once an authenticated `/link`
    # session's `key.rotate` (kind="device") frame is accepted; cleared
    # together either by agent_registry.settle_device_key_rotation (promotion
    # on the first successful link under the new key, or lazy cleanup once
    # the transition window has elapsed) — never set/cleared independently of
    # each other.
    pending_device_pk: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    pending_device_pk_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Task 28: which of the server's two overlapping identity keys (see
    # app.core.agent_crypto.ServerKeyRotationState) this agent's most recent
    # successful `/link` Noise handshake actually authenticated against.
    #
    # These two columns are rollout-*timing* only, not the pin itself — the
    # actual per-agent pin (the successor server public key this specific
    # device now durably trusts, alongside its config file's original one) is
    # persisted agent-side, in apps/agent/internal/config's
    # ServerKeyRotation/SaveServerKeyRotation (see internal/link.go's
    # handleKeyRotate), not here: the server has no visibility into whether a
    # given agent's local state directory actually holds the successor key,
    # only into which key its handshakes have used so far. Set by
    # agent_registry.record_server_key_pin, called from ws_agents.py right
    # after a handshake completes against whichever key it matched. Purely
    # observational (nothing about handshake acceptance depends on these),
    # but lets an admin's rotation status view answer "how much of the fleet
    # has already switched to authenticating with the successor key" rather
    # than only knowing the rotation's global timing.
    server_pk_current_pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    server_pk_successor_pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Slice 4.1: which TLS trust policy this agent's most recent successful
    # dial actually matched, reported by the agent as hello's `tls_pin_kind`.
    # Rollout *timing* only, exactly like server_pk_*_pinned_at above: the
    # server cannot see whether an agent's state directory holds the
    # successor policy, only which one its handshakes have used. Unlike those
    # columns, though, these are not purely observational —
    # api/certificates.py's activation gate reads them, because activating a
    # certificate no agent has converged on is what stranded the fleet.
    tls_pin_current_pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tls_pin_successor_pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # *Which* successor policy the agent says it holds, not merely that it holds
    # one (H5). A bare boolean let an agent carrying a stale successor — from a
    # rotation that was abandoned, and which nothing ever told it to drop — be
    # credited as converged on the next rotation, opening the gate on a cutover
    # that would strand it. NULL for agents predating the field, which counts as
    # unconverged: blocking a cutover is the recoverable direction.
    tls_pin_successor_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_macs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reported_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Live outbound-spool backlog as last reported by the agent (D-12): the
    # `hello` frame stamps the at-connect depth, and every 20s `heartbeat`
    # refreshes both numbers thereafter, which is what lets the Agent Detail
    # catch-up indicator clear mid-connection instead of waiting for a
    # reconnect.
    #
    # NULL means "never reported" — an agent whose build predates
    # HeartbeatPayload — and is deliberately distinct from 0, which means
    # "reported, and the spool is empty". Nothing may backfill these to 0:
    # the agent's heartbeat payload carries no `omitempty`, so an explicit
    # 0 is exactly what a current agent sends once its backlog drains, and
    # `agent_registry.record_spool_stats`'s callers gate on field *presence*
    # to keep the two apart.
    spool_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spool_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spool_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What the agent's spool has *permanently destroyed* to stay inside its
    # byte cap, cumulatively for the life of its state directory, reported on
    # `hello` and refreshed on every `heartbeat` (migration 0110).
    #
    # Distinct from the three columns above in the way that matters most: a
    # backlog drains and these do not. `spool_depth` merely stopping its rise
    # was the *only* symptom of eviction before these existed, and it reads
    # identically to a healthy drain — which is how a homelab could lose days
    # of history and never be told.
    #
    # `_oldest_at`/`_newest_at` bound the window of observations that is gone,
    # taken from the destroyed frames' own timestamps rather than from when
    # the eviction ran: "which history is missing" is the operator's question,
    # not "when did the buffer overflow".
    #
    # NULL means "never reported" — an agent predating the fields — and stays
    # distinct from 0 ("reported, and nothing has been destroyed"). Nothing
    # may backfill these; see `agent_registry.record_spool_evictions`, which
    # gates on wire-key presence, and treats a *decrease* as a state-directory
    # reset rather than quietly taking the max.
    spool_evicted_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spool_evicted_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spool_evicted_oldest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    spool_evicted_newest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    spool_evicted_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Data frames *this server* refused from this agent and dropped on the
    # floor — the capability gate in `agent_link.dispatch_frame`, and the
    # `Invalid*` catches in its telemetry/probe/discovery handlers.
    #
    # It exists because the matching audit rows are rate-limited to one a
    # minute through `agent_telemetry.recordable_violation`, so the event
    # trail undercounts by design. That throttle is correct — thousands of
    # identical rows bury the trail — but it means an operator reading events
    # cannot tell nine refusals from nine thousand. This counter is not
    # throttled, so they can. NULL = nothing has ever been refused.
    refused_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refused_frames_last_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refused_frames_last_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Reserved for the delivery-acknowledgement handshake a later phase adds:
    # whether this agent and this server negotiated per-frame data acks. It
    # ships with migration 0110 so these agent columns land in one upgrade
    # step for a self-hoster, and is deliberately unread until then.
    data_ack_negotiated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_agents_fingerprint", "fingerprint"),)


class AgentCapabilityGrant(Base):
    """Per-agent, per-capability enable/disable — default-deny beyond host_telemetry."""

    __tablename__ = "agent_capability_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # host_telemetry|remote_probe|local_discovery
    capability: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    granted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "capability",
            name="uq_agent_capability_grants_agent_capability",
        ),
    )


class AgentEnrollmentToken(Base):
    """A short-lived bearer credential that enrolls an agent with no human present.

    The plaintext is returned once at mint and never stored — `token_hash` is
    SHA-256 of it, mirroring `user_service._hash_token`. `max_uses` exists
    because a single-use token breaks the case that motivates the feature: one
    token baked into a launch template, N instances booting, only the first
    enrolling (design §3.2).

    Rows are revoked, never deleted, so `agents.enrollment_token_id` stays
    resolvable for the life of every agent that came through one.
    """

    __tablename__ = "agent_enrollment_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    # The address this token's agents are told to dial. Stored as the URL
    # rather than the endpoint id so deleting an endpoint does not orphan a
    # token that is still live — the same reasoning that keys
    # agent_endpoints.usage_counts by URL.
    endpoint_url: Mapped[str] = mapped_column(String, nullable=False)
    # The grant scope applied on auto-approval — the same shape
    # POST /{agent_id}/approve accepts for `capabilities`.
    capabilities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_agent_enrollment_tokens_token_hash", "token_hash"),)


class AgentEvent(Base):
    """Timeline entry for an agent — enrolled, approved, revoked, capability_violation, etc."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_agent_events_agent_time", "agent_id", "created_at"),)


class AgentHostSample(Base):
    __tablename__ = "agent_host_samples"
    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="SET NULL"), nullable=True
    )
    sample_id: Mapped[str] = mapped_column(String(32), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    root_disk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_rx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_tx_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    projected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        PrimaryKeyConstraint("id", "collected_at"),
        UniqueConstraint("agent_id", "sample_id", "collected_at", name="uq_agent_host_sample"),
        Index("ix_agent_host_samples_agent_time", "agent_id", "collected_at"),
    )


class AgentHostSampleHourly(Base):
    __tablename__ = "agent_host_sample_hourly"
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    bucket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AgentCapabilityReadiness(Base):
    __tablename__ = "agent_capability_readiness"
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    collector: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remediation: Mapped[str | None] = mapped_column(String(512), nullable=True)
    missing: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (Index("ix_agent_readiness_agent_time", "agent_id", "updated_at"),)


class AgentNetwork(Base):
    """The agent's current directly connected networks, as reported on `hello` (D-1).

    One row per agent — this is the *latest* report, not a history — holding the
    normalized `HelloPayload.networks` list (see
    `agent_registry.record_network_facts`). It is the sole input to the derived
    half of an agent's probe scope, so the scheduler, the UI and the audit trail
    can all point at one generation and agree on what produced that scope.

    `generation` advances only when the normalized facts actually differ, which
    is what makes "the agent's scope changed" a decidable question; `observed_at`
    is correspondingly when *these* facts were first seen, not when the agent
    last mentioned them (liveness is `agents.last_seen_at`).
    """

    __tablename__ = "agent_networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # [{"name": "eth0", "flags": ["broadcast", "up"], "addrs": ["10.0.0.5/24"]}, ...]
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (UniqueConstraint("agent_id", name="uq_agent_networks_agent_id"),)
