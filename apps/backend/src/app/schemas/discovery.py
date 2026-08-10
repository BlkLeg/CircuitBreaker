import ipaddress
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.discovery_scan_types import validate_scan_types


def _validate_cron_expression(v: str | None) -> str | None:
    """Validate cron expression using APScheduler's CronTrigger. Returns HTTP 422 on invalid."""
    if v is None or v == "":
        return v
    try:
        from apscheduler.triggers.cron import CronTrigger

        CronTrigger.from_crontab(v)
    except Exception as exc:
        raise ValueError(f"Invalid cron expression {v!r}: {exc}") from exc
    return v


class DiscoveryProfileCreate(BaseModel):
    name: str
    cidr: str | None = None
    vlan_ids: list[int] = []
    scan_types: list[str] = ["nmap"]
    # None means the existing server discovery engine — every profile that
    # predates Slice 4. An id dispatches the profile to that agent instead.
    scan_agent_id: int | None = None
    nmap_arguments: str | None = Field(None, max_length=256)
    snmp_community: str | None = None  # plaintext input only; never in output
    snmp_version: str = "2c"
    snmp_port: int = 161
    docker_network_types: list[str] = ["bridge"]
    docker_port_scan: bool = False
    docker_socket_path: str = "/var/run/docker.sock"
    schedule_cron: str | None = None
    enabled: bool = True

    @field_validator("schedule_cron")
    @classmethod
    def validate_schedule_cron(cls, v: str | None) -> str | None:
        return _validate_cron_expression(v)

    @model_validator(mode="after")
    def validate_scan_type_vocabulary(self) -> "DiscoveryProfileCreate":
        # Cross-field, because which types are legal depends entirely on where
        # the profile executes.
        self.scan_types = validate_scan_types(self.scan_types, scan_agent_id=self.scan_agent_id)
        return self


class DiscoveryProfileUpdate(BaseModel):
    name: str | None = None
    cidr: str | None = None
    vlan_ids: list[int] | None = None
    scan_types: list[str] | None = None
    scan_agent_id: int | None = None
    nmap_arguments: str | None = Field(None, max_length=256)
    snmp_community: str | None = None
    snmp_version: str | None = None
    snmp_port: int | None = None
    docker_network_types: list[str] | None = None
    docker_port_scan: bool | None = None
    docker_socket_path: str | None = None
    schedule_cron: str | None = None
    enabled: bool | None = None

    @field_validator("schedule_cron")
    @classmethod
    def validate_schedule_cron(cls, v: str | None) -> str | None:
        return _validate_cron_expression(v)

    # No `validate_scan_type_vocabulary` here, deliberately (§3, D-6). Which scan
    # types are legal depends on the execution location, and a PATCH names either
    # half of that pair on its own: an unset `scan_agent_id` on this model means
    # "leave the stored agent alone", not "the server". Judging the payload
    # against itself therefore got both directions wrong — it let
    # `{"scan_types": ["nmap"]}` land on an agent-executed profile (a server-only
    # type dispatched to an agent, which §3 forbids) and refused
    # `{"scan_types": ["agent_connect"]}` on a profile that already had an agent.
    # The check belongs where the stored row is in hand:
    # `discovery_profiles_service.update_profile` runs `validate_scan_types` over
    # the merged state and normalizes the list it stores. `DiscoveryProfileCreate`
    # keeps its validator because a create carries the whole profile.


class DiscoveryProfileOut(BaseModel):
    id: int
    name: str
    cidr: str | None
    # Where this profile executes (Task 26). `None` is the server discovery
    # engine — every profile that predates Slice 4 — and an id is the agent the
    # "Scan from" selector has to read back to show what is already chosen.
    scan_agent_id: int | None = None
    # `"system"` for a profile `discovery_bootstrap` owns and may re-upsert,
    # `None` for one an operator wrote. Plan §6 asks the scope section to render
    # automatic and user-created subnets with *visibly different provenance*,
    # and this is the only field that tells them apart.
    managed_by: str | None = None
    # Per-subnet pause (plan §6, M14). Distinct from `enabled = false`, which
    # means the subnet is gone; a timestamp here means an operator held it.
    paused_at: datetime | None = None
    vlan_ids: list[int] = []
    scan_types: list[str]
    nmap_arguments: str | None
    # snmp_community_encrypted NEVER included
    snmp_version: str
    snmp_port: int
    docker_network_types: list[str]
    docker_port_scan: bool
    docker_socket_path: str
    schedule_cron: str | None
    enabled: bool
    last_run: str | None
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)

    @field_validator("scan_types", mode="before")
    @classmethod
    def parse_scan_types(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    @field_validator("docker_network_types", mode="before")
    @classmethod
    def parse_docker_network_types(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [v]
        return v

    @field_validator("vlan_ids", mode="before")
    @classmethod
    def parse_vlan_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v or []


class ScanJobOut(BaseModel):
    id: int
    profile_id: int | None
    # The execution location, copied onto the job at creation so historical
    # attribution cannot change when the profile is later repointed (Task 26).
    # Plan §6: the job card and the history row show where a scan ran, and link
    # the agent name to its detail page.
    scan_agent_id: int | None = None
    # `manual|prober|scheduled|listener_triggered|agent`. Carried alongside
    # `scan_agent_id` rather than folded into it: the agent id says *which*
    # vantage point, while this says what kind of run it was, and the four
    # server-side values are the ones the history filter already distinguishes.
    # A UI reading only `scan_agent_id != null` would render a scheduled server
    # sweep and a manual one identically.
    source_type: str = "manual"
    label: str | None
    target_cidr: str | None
    vlan_ids: list[int] = []
    network_ids: list[int] = []
    scan_types_json: str
    status: str
    started_at: str | None
    completed_at: str | None
    hosts_found: int
    hosts_new: int
    hosts_updated: int
    hosts_conflict: int
    error_text: str | None
    error_reason: str | None = None
    triggered_by: str
    progress_phase: str | None = None
    progress_message: str | None = None
    created_at: str
    model_config = ConfigDict(from_attributes=True)

    @field_validator("vlan_ids", "network_ids", mode="before")
    @classmethod
    def parse_json_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return []
        return v or []


class DiscoveryScopeEntry(BaseModel):
    """One CIDR in an agent's effective scope, with where it came from and
    whether the evaluator will actually permit it.

    `provenance` is what plan §6 means by "visibly different provenance", and the
    distinction is operational rather than cosmetic:

    * `automatic` — derived from the agent's own reported interfaces. It appears
      and disappears with the interface, and the control an operator gets over it
      is to *exclude* it.
    * `override` — an `additional_cidrs` entry an administrator typed. Routed,
      not directly connected; nothing but another edit removes it.
    * `excluded` — an `excluded_cidrs` entry. Listed in its own right because an
      exclusion narrower than any allow-list network (a /25 inside a reported
      /24) would otherwise be invisible while still refusing the enclosing /24.

    `effective` is `agent_scope.network_in_scope`'s verdict, not membership in
    the allow list. `EffectiveScope.networks` is what is permitted *before*
    exclusions and the static special-use blocklist are subtracted, so rendering
    it as reachability would claim access the evaluator refuses — which is
    exactly the difference plan §6 asks the section to show. `reason` is the
    evaluator's own (`excluded_cidr`, `prefix_too_wide`, `special_use`, …).
    """

    cidr: str
    provenance: str
    effective: bool
    reason: str


class DiscoveryLimits(BaseModel):
    """The `local_discovery` grant's bounds, as the detail page renders them.

    These are the numbers `port_not_granted` and `address_limit_exceeded` are
    measured against, so an operator reading either refusal finds what refused
    it on the same page.
    """

    scope_mode: str
    max_addresses_per_job: int
    max_concurrent_hosts: int
    host_timeout_ms: int
    job_timeout_seconds: int
    tcp_ports: list[int] = Field(default_factory=list)


class DiscoveryReadinessRow(BaseModel):
    """One D-8 collector's reported state.

    Rendered for every collector in the closed set, including those that have
    never reported — `state = None` is "no row", which is what makes a job refuse
    with `readiness_unknown`, and it is a different operator problem from a
    collector that reported `unavailable`.

    `stale` is `updated_at` older than `discovery_eligibility.READINESS_MAX_AGE_S`.
    Readiness rows have no TTL, so an old `ready` is evidence of nothing and the
    eligibility query already ignores it; without this flag the page would show a
    green collector next to a job refused for `readiness_unknown`.
    """

    collector: str
    state: str | None = None
    reason: str | None = None
    remediation: str | None = None
    updated_at: datetime | None = None
    stale: bool = False
    # Whether a job is gated on this one. Only the connect sweep is
    # (`discovery_eligibility.REQUIRED_READINESS_COLLECTORS`); the neighbor cache,
    # the ICMP sweep and reverse DNS make it faster or richer and are legitimately
    # unavailable on an unprivileged host that can still run the whole scan.
    required: bool = False


class AgentDiscoveryRead(BaseModel):
    """Everything §6's "Discovery scope" section on Agent Detail renders.

    `AgentProbesRead`'s counterpart, and loaded by the same page the same way, so
    Task 27's component can be cloned from `AssignedProbesSection`. It answers
    one question — *what is this vantage point discovering, and if nothing, why*
    — which is why the eligibility verdict, the three pause scopes and the
    readiness rows sit alongside the scope itself rather than being three more
    round trips.
    """

    agent_id: int
    online: bool
    granted: bool
    # The per-agent hold (`local_discovery.auto_discovery_paused`) and the
    # fleet-wide one. Kept as separate fields with no precedence between them,
    # exactly as `discovery_service`'s pause readers are: each holds on its own
    # and neither releases the other, so a single derived boolean would let an
    # operator resume the wrong one and see nothing change.
    paused: bool = False
    globally_paused: bool = False
    # `discovery_eligibility`'s closed vocabulary — the same string the scan
    # endpoints refuse with and the dispatch audit row carries.
    eligible: bool
    reason: str | None = None
    detail: str | None = None
    scope_version: str
    scope: list[DiscoveryScopeEntry] = Field(default_factory=list)
    limits: DiscoveryLimits
    readiness: list[DiscoveryReadinessRow] = Field(default_factory=list)
    # A list, not one job: nothing in the dispatch model limits an agent to a
    # single open discovery job, and rendering only the first would hide work
    # that is genuinely running.
    active_jobs: list["ScanJobOut"] = Field(default_factory=list)
    recent_jobs: list["ScanJobOut"] = Field(default_factory=list)
    # The subnets this agent is responsible for, automatic and user-created
    # alike, so the cadence and per-subnet pause controls have something to bind
    # to without a second request.
    profiles: list["DiscoveryProfileOut"] = Field(default_factory=list)


class EligibleDiscoveryAgent(BaseModel):
    """One candidate vantage for a discovery scan, as plan §6's "Scan from"
    selector renders it — including the ones it may not choose.

    `EligibleProbeAgent`'s twin, field for field where the question is the same,
    because the two selectors sit next to each other in the product and an
    operator should not have to learn that "granted" means one thing here and
    another there. What differs is what discovery is bounded by: prefixes rather
    than one destination, so the scope lists carry `direct_networks` as well
    (the agent additionally requires a target to be directly connected unless an
    override covers it), and the grant's per-job ceilings are surfaced because
    they are what refuses an otherwise-fine agent.

    `reason` and `detail` are `discovery_service.AgentExecutionLocationError`'s —
    the *same* pair `POST /discovery/scan` refuses with, produced by the same
    call — so the selector can never advertise an agent the next request rejects.
    """

    agent_id: int
    name: str | None = None
    # Carried *alongside* `name`, not folded into it. `agents.name` is nullable
    # and enrollment never writes it — `agent_registry.create_pending_agent`
    # records hostname/os/arch, and the only writer of `name` is an explicit
    # operator `PATCH /agents/{id}` — so `name is None` is the state of every
    # agent nobody has renamed, and a selector with only `name` to render labels
    # the common case "agent 7". Defaulting `name` to the hostname at enrollment
    # was rejected: it would leave every existing un-renamed row still nameless,
    # and it conflates "an operator named this" with "we guessed", so a later
    # hostname change could not track. Resolving at display time fixes old and
    # new rows alike and keeps `name` meaning what it means.
    hostname: str | None = None
    online: bool
    granted: bool
    # The per-agent hold (M14). Not an ineligibility: a paused agent still
    # accepts a scan an operator starts by hand; what is paused is the automatic
    # cadence. The selector renders it so "nothing is happening" has an answer.
    paused: bool = False
    readiness: str | None = None
    readiness_collector: str | None = None
    scope_version: str
    scope_networks: list[str] = Field(default_factory=list)
    direct_networks: list[str] = Field(default_factory=list)
    excluded_networks: list[str] = Field(default_factory=list)
    max_addresses_per_job: int
    max_concurrent_hosts: int
    tcp_ports: list[int] = Field(default_factory=list)
    active_jobs: int = 0
    assigned_profiles: int = 0
    # `None` when the caller named no CIDR: "not asked" is a different answer
    # from "no", and a selector that rendered them the same would show every
    # agent as out of scope until the operator finished typing.
    in_scope: bool | None = None
    eligible: bool
    reason: str | None = None
    detail: str | None = None


class ScanResultOut(BaseModel):
    id: int
    scan_job_id: int
    ip_address: str
    mac_address: str | None
    hostname: str | None
    open_ports_json: str | None
    os_family: str | None
    os_vendor: str | None
    os_accuracy: int | None = None
    snmp_sys_name: str | None
    snmp_sys_descr: str | None
    vlan_id: int | None = None
    network_id: int | None = None
    # raw_nmap_xml NEVER included
    device_type: str | None = None
    device_confidence: int | None = None
    state: str
    conflicts_json: str | None
    matched_entity_type: str | None
    matched_entity_id: int | None
    # Which agent's local-discovery scan produced this finding; None for a
    # server-executed scan. The column has existed since Slice 4 but was not
    # serialized, so no caller could attribute a finding to an agent — which
    # Slice 3 §7's "Create monitor from this agent" action needs in order to
    # list the devices one agent found.
    discovery_agent_id: int | None = None
    merge_status: str
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    model_config = ConfigDict(from_attributes=True)

    @field_validator("open_ports_json", mode="before")
    @classmethod
    def _coerce_open_ports_json(cls, v: Any) -> Any:
        """JSONB column returns a Python list; serialize it so the schema str | None holds."""
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return v


def _datetime_to_str(v: Any) -> str:
    """Coerce datetime to ISO string for API output."""
    if hasattr(v, "isoformat"):
        return str(v.isoformat())
    return str(v) if v is not None else ""


class ScanLogOut(BaseModel):
    id: int
    scan_job_id: int
    timestamp: str
    level: str
    phase: str | None
    message: str
    details: str | None
    created_at: str
    model_config = ConfigDict(from_attributes=True)

    @field_validator("timestamp", "created_at", mode="before")
    @classmethod
    def coerce_datetime_to_str(cls, v: Any) -> str:
        if isinstance(v, str):
            return v
        return _datetime_to_str(v)


class AdHocScanRequest(BaseModel):
    cidr: str | None = None
    cidrs: list[str] | None = None
    vlan_ids: list[int] = []
    scan_types: list[str] = ["nmap"]
    nmap_arguments: str | None = Field(None, max_length=256)
    snmp_community: str | None = None
    label: str | None = None
    scan_agent_id: int | None = None

    @field_validator("cidrs")
    @classmethod
    def validate_cidrs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 10:
            raise ValueError("Maximum 10 CIDR targets per scan")
        for entry in v:
            try:
                ipaddress.ip_network(entry.strip(), strict=False)
            except ValueError as err:
                raise ValueError(f"Invalid CIDR: {entry}") from err
        return [e.strip() for e in v if e.strip()]

    @model_validator(mode="after")
    def validate_scan_type_vocabulary(self) -> "AdHocScanRequest":
        self.scan_types = validate_scan_types(self.scan_types, scan_agent_id=self.scan_agent_id)
        return self


class MergeRequest(BaseModel):
    action: str  # 'accept' | 'reject'
    entity_type: str | None = None
    overrides: dict = Field(default_factory=dict)


class BulkMergeRequest(BaseModel):
    result_ids: list[int]
    action: str


class BulkAssignment(BaseModel):
    """Per-node overrides for enhanced bulk merge."""

    result_id: int
    vendor: str | None = None
    vendor_catalog_key: str | None = None
    model_catalog_key: str | None = None
    vendor_icon_slug: str | None = None
    role: str | None = None
    name: str | None = None


class EnhancedBulkMergeCluster(BaseModel):
    name: str
    description: str | None = None
    environment: str | None = None
    location: str | None = None


class EnhancedBulkMergeNetwork(BaseModel):
    name: str | None = None  # Optional when existing_id is provided
    cidr: str | None = None
    vlan_id: int | None = None
    gateway: str | None = None
    description: str | None = None
    existing_id: int | None = None  # Link to existing network instead of creating


class EnhancedBulkMergeRequest(BaseModel):
    """Full-featured bulk merge with cluster, network, rack, and per-node assignments."""

    result_ids: list[int]
    cluster: EnhancedBulkMergeCluster | None = None
    network: EnhancedBulkMergeNetwork | None = None

    assignments: list[BulkAssignment] = []
    create_services: bool = False


class BulkSuggestRequest(BaseModel):
    result_ids: list[int]


class DiscoveryStatusOut(BaseModel):
    discovery_enabled: bool
    scan_ack_accepted: bool
    pending_results: int
    active_jobs: list[ScanJobOut]
    last_scan: str | None
    next_scheduled: str | None  # ISO string of next APScheduler fire time
    # Safe-mode capability info
    discovery_mode: str = "safe"
    effective_mode: str = "safe"  # actual mode after privilege check
    net_raw_capable: bool = False
    docker_available: bool = False
    docker_container_count: int = 0


# ── Scan-to-Map pipeline schemas ─────────────────────────────────────────────


class InferredScanResultOut(ScanResultOut):
    """ScanResultOut extended with inference annotations for the import modal."""

    inferred_vendor: str | None = None
    inferred_role: str | None = None
    inferred_icon_slug: str | None = None
    confidence: float = 0.0
    signals_used: list[str] = []
    exists_in_hardware: bool = False
    existing_hardware_id: int | None = None
    existing_role: str | None = None
    is_new: bool = True


class BatchImportItem(BaseModel):
    scan_result_id: int
    overrides: dict = {}


class BatchImportRequest(BaseModel):
    items: list[BatchImportItem]


class BatchImportCreated(BaseModel):
    id: int
    ip: str | None = None
    position: dict | None = None
    scan_result_id: int | None = None


class BatchImportConflict(BaseModel):
    scan_result_id: int
    ip: str | None = None
    mac: str | None = None
    reason: str


class BatchImportResponse(BaseModel):
    created: list[BatchImportCreated] = []
    updated: list[BatchImportCreated] = []
    conflicts: list[BatchImportConflict] = []
    skipped: list[int] = []


class ImportAsNetworkRequest(BaseModel):
    items: list[BatchImportItem]
    map_id: int | None = None  # None = auto-select main map (lowest topology id)
    environment_id: int | None = None


class ImportAsNetworkPlaceholder(BaseModel):
    id: int
    subnet: str


class ImportAsNetworkResponse(BaseModel):
    created: list[BatchImportCreated] = []
    updated: list[BatchImportCreated] = []
    placeholders: list[ImportAsNetworkPlaceholder] = []
    edges_created: int = 0
    conflicts: list[BatchImportConflict] = []


class LLDPEnrichRequest(BaseModel):
    hardware_ids: list[int]
    snmp_community: str = "public"
    snmp_port: int = 161


class LLDPConnectionSelection(BaseModel):
    source_scan_result_id: int
    neighbor_index: int


class LLDPApplyRequest(BaseModel):
    connections: list[LLDPConnectionSelection]


class LLDPApplyResponse(BaseModel):
    edges_created: int = 0
    stubs_created: int = 0


class LLDPNeighborOut(BaseModel):
    source_scan_result_id: int
    neighbor_index: int
    source_hardware_id: int | None
    source_hardware_name: str | None
    local_port_desc: str | None
    remote_chassis_id: str | None
    remote_port_desc: str | None
    remote_sys_name: str | None
    remote_mgmt_ip: str | None
    remote_hardware_id: int | None
    remote_hardware_name: str | None
    is_new_stub: bool


class LLDPJobResultsOut(BaseModel):
    job_id: int
    neighbors: list[LLDPNeighborOut]
