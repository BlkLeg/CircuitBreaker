"""Network discovery: scan profiles, jobs, results, and the always-on listener's observations."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.credentials import IntegrationConfig


class ProxmoxDiscoverRun(Base):
    """One run of Proxmox cluster discovery (nodes, VMs, CTs, storage)."""

    __tablename__ = "proxmox_discover_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    integration_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running"
    )  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nodes_imported: Mapped[int] = mapped_column(Integer, default=0)
    vms_imported: Mapped[int] = mapped_column(Integer, default=0)
    cts_imported: Mapped[int] = mapped_column(Integer, default=0)
    storage_imported: Mapped[int] = mapped_column(Integer, default=0)
    networks_imported: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # list of error strings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    integration: Mapped["IntegrationConfig"] = relationship(
        "IntegrationConfig", foreign_keys=[integration_id]
    )


# ── Auto Discovery ────────────────────────────────────────────────────────────


class DiscoveryProfile(Base):
    __tablename__ = "discovery_profiles"
    __table_args__ = (
        # Slice 4: one system-managed profile per (agent, subnet). Partial, so a
        # user-created profile may target the same CIDR without colliding —
        # plan §3's "user-created profiles remain separate and are never
        # overwritten". Declared here *and* in migration 0100 so `create_all`
        # (the test schema) and the migrated schema agree.
        Index(
            "uq_discovery_profiles_system_agent_cidr",
            "scan_agent_id",
            "normalized_cidr",
            unique=True,
            postgresql_where=text("managed_by = 'system'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cidr: Mapped[str | None] = mapped_column(String, nullable=True)
    # Slice 4 execution location. NULL means the existing server scanner, which
    # is every profile that predates this column. RESTRICT because this is a
    # *live assignment*, mirroring `MonitorItem.probe_agent_id`: deleting an
    # agent a profile still names is refused with a 409 rather than silently
    # repointing the profile at the server.
    scan_agent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agents.id", ondelete="RESTRICT", name="fk_discovery_profiles_scan_agent_id_agents"
        ),
        nullable=True,
        index=True,
    )
    # The canonical form of `cidr`, so the uniqueness rule above has a stable
    # key: "10.0.0.5/24" and "10.0.0.0/24" name the same segment.
    normalized_cidr: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL for a user-created profile; "system" for one the discovery bootstrap
    # owns and may idempotently re-upsert.
    managed_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Per-subnet pause (plan §6). Distinct from `enabled = 0`, which means the
    # subnet is gone; a paused profile is one an operator chose to hold.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vlan_ids: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON array of VLAN IDs
    scan_types: Mapped[str] = mapped_column(String, default='["nmap"]')
    nmap_arguments: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_community_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_version: Mapped[str] = mapped_column(String, default="2c")
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    docker_network_types: Mapped[str] = mapped_column(String, default='["bridge"]')
    docker_port_scan: Mapped[int] = mapped_column(Integer, default=0)
    docker_socket_path: Mapped[str] = mapped_column(String, default="/var/run/docker.sock")
    schedule_cron: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    jobs: Mapped[list["ScanJob"]] = relationship("ScanJob", back_populates="profile")


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        Index("ix_scan_jobs_agent_status_created", "scan_agent_id", "status", "created_at"),
        # Partial: every job the server scanner has ever written has a NULL
        # dispatch_id, and PostgreSQL NULLs do not collide — but stating the
        # predicate keeps the index small and says what it is for.
        Index(
            "uq_scan_jobs_dispatch_id",
            "dispatch_id",
            unique=True,
            postgresql_where=text("dispatch_id IS NOT NULL"),
        ),
    )
    # There is deliberately no `uq_..._active_dispatch` partial unique index
    # here, unlike `uq_monitor_probe_runs_active`. That index works for monitors
    # because a probe lease is its *own row* and two workers racing would insert
    # two of them. A discovery lease lives on the job row itself, so there is
    # only ever one row and a unique index over it enforces nothing — the race
    # is two workers both reading `dispatch_status IS NULL` and both writing
    # `dispatched`, which only a conditional UPDATE can stop. The backstop is
    # therefore a compare-and-set — a single conditional UPDATE predicated on the
    # lease state it expects to find, with a rowcount check — and
    # `uq_scan_jobs_dispatch_id`,
    # which does carry real weight: it makes a replayed or duplicated
    # `dispatch_id` an integrity error rather than two jobs sharing a token.

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("discovery_profiles.id"), nullable=True, index=True
    )
    # Slice 4: the execution location, copied from the profile at creation so
    # historical attribution cannot change when the profile is later edited.
    # CASCADE, unlike the profile's RESTRICT: a job is finished history, and
    # `MonitorProbeRun.agent_id` settled the same question the same way.
    scan_agent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("agents.id", ondelete="CASCADE", name="fk_scan_jobs_scan_agent_id_agents"),
        nullable=True,
    )
    # The agent-dispatch lease. `dispatch_id` is a server-minted opaque 128-bit
    # token and is the only identifier that ever reaches the agent, so a guessed
    # or leaked `scan_job_id` buys nothing.
    dispatch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # queued|dispatched|running|completed|execution_error|expired|cancelled
    dispatch_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    dispatch_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_finding_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The `EffectiveScope.version` in force at dispatch. Plan §2 requires an
    # active request to be cancelled when scope changes incompatibly, and
    # comparing a digest is what makes that possible without diffing CIDR lists
    # on every readiness frame.
    scope_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    target_cidr: Mapped[str | None] = mapped_column(String, nullable=True)
    vlan_ids: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON array of VLAN IDs
    network_ids: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # JSON array of network IDs
    scan_types_json: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    hosts_found: Mapped[int] = mapped_column(Integer, default=0)
    hosts_new: Mapped[int] = mapped_column(Integer, default=0)
    hosts_updated: Mapped[int] = mapped_column(Integer, default=0)
    hosts_conflict: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, default="api")
    source_type: Mapped[str] = mapped_column(
        String, default="manual"
    )  # manual|prober|scheduled|listener_triggered|agent
    progress_phase: Mapped[str] = mapped_column(String, default="queued")
    progress_message: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )

    profile: Mapped["DiscoveryProfile | None"] = relationship(
        "DiscoveryProfile", back_populates="jobs"
    )
    results: Mapped[list["ScanResult"]] = relationship("ScanResult", back_populates="job")
    logs: Mapped[list["ScanLog"]] = relationship("ScanLog", back_populates="job")


class ScanResult(Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        # Slice 4's idempotent-replay key. A finding spooled across an agent
        # outage arrives again on reconnect; inserting it twice would double the
        # review queue and the job counters. Partial because every row the
        # server scanner writes has a NULL `finding_id`, and a full unique index
        # would permit exactly one of them per job.
        Index(
            "uq_scan_results_job_finding",
            "scan_job_id",
            "finding_id",
            unique=True,
            postgresql_where=text("finding_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scan_jobs.id"), nullable=False, index=True
    )
    # Slice 4 provenance. CASCADE for the same reason `ScanJob.scan_agent_id`
    # is: a result is finished history, and revocation — which retains
    # provenance — does not delete the agent row.
    discovery_agent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "agents.id", ondelete="CASCADE", name="fk_scan_results_discovery_agent_id_agents"
        ),
        nullable=True,
        index=True,
    )
    # Opaque, agent-chosen, unique within one dispatch. Replay-stable by
    # construction on the agent side (a digest of dispatch/kind/address), which
    # is what makes the partial unique index above an idempotency key rather
    # than a race.
    finding_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Derived from the owning job, never from the finding payload. `scan_jobs`
    # already carried a tenant and this table did not, so there was nothing at
    # result level for plan §8's tenant rule to assert against.
    tenant_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("tenants.id", ondelete="SET NULL", name="fk_scan_results_tenant_id_tenants"),
        nullable=True,
        index=True,
    )
    ip_address: Mapped[str] = mapped_column(String, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    open_ports_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    os_family: Mapped[str | None] = mapped_column(String, nullable=True)
    os_vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_name: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_descr: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_interfaces_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # JSONB as of v0.2.0
    snmp_storage_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # JSONB as of v0.2.0
    lldp_neighbors_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    network_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("networks.id"), nullable=True
    )
    raw_nmap_xml: Mapped[str | None] = mapped_column(String, nullable=True)
    banner: Mapped[str | None] = mapped_column(Text, nullable=True)  # service banner from TCP probe
    os_accuracy: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0–100 nmap OS confidence
    device_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # ios_device|android_device|fire_tv|router|printer|nas|smart_tv|ip_camera|windows_pc|…
    device_confidence: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )  # 0–100 classification confidence
    role_suggestion: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # suggested role slug when confidence < auto-assign threshold
    source_type: Mapped[str] = mapped_column(
        String, default="nmap"
    )  # nmap|arp|listener|prober|deep_dive|docker|agent
    state: Mapped[str] = mapped_column(String, default="new", index=True)
    conflicts_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    matched_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Indexed as of migration 0109: `state` always was, but `merge_status` is
    # what the review badge, the queue fetch and the enrichment backfill's
    # selector all actually filter on.
    merge_status: Mapped[str] = mapped_column(String, default="pending", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # What `discovery_enrich` filled in on the matched device, and when. Three
    # distinguishable states, and the UI renders each differently:
    #   NULL -> never enriched (or written by a build older than 0109)
    #   []   -> enriched, but there was nothing empty to fill; only liveness moved
    #   [{"field": ..., "value": ...}] -> these fields were backfilled
    # `reviewed_by`/`reviewed_at` are deliberately NOT set alongside these: they
    # mean a human reviewed the row, and an enriched row had no human.
    enriched_fields_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enriched_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, index=True)

    job: Mapped["ScanJob"] = relationship("ScanJob", back_populates="results")


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_jobs.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False)  # INFO, SUCCESS, WARN, ERROR
    phase: Mapped[str | None] = mapped_column(String, nullable=True)  # ping, arp, nmap, snmp, http
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Raw command output, error traces
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    job: Mapped["ScanJob"] = relationship("ScanJob", back_populates="logs")


# ── Phase 4: Listener Events ──────────────────────────────────────────────────


class ListenerEvent(Base):
    """mDNS / SSDP advertisements captured by the always-on listener."""

    __tablename__ = "listener_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "mdns" | "ssdp"
    service_type: Mapped[str | None] = mapped_column(String, nullable=True)  # "_http._tcp.local."
    name: Mapped[str | None] = mapped_column(String, nullable=True)  # advertised service name
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    properties_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # TXT records / SSDP headers — JSONB as of v0.2.0
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    # The dedup probe in services/listener_service._persist_event filters on
    # exactly these three columns, once per multicast packet that clears the
    # rate gate. Without a composite index that is a scan of every retained
    # event per advertisement, on a table fed by unauthenticated LAN traffic.
    # Declared here as well as in the Alembic revision so a schema built by
    # `Base.metadata.create_all` — which is how the backend test suite builds
    # it — matches the one an upgrade produces. They drifted before.
    __table_args__ = (
        Index(
            "ix_listener_events_dedup",
            "ip_address",
            "service_type",
            "seen_at",
        ),
    )
