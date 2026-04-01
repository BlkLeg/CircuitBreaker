import ipaddress
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class DiscoveryProfileUpdate(BaseModel):
    name: str | None = None
    cidr: str | None = None
    vlan_ids: list[int] | None = None
    scan_types: list[str] | None = None
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


class DiscoveryProfileOut(BaseModel):
    id: int
    name: str
    cidr: str | None
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
    merge_status: str
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    model_config = ConfigDict(from_attributes=True)


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
    rack_unit: int | None = None
    u_height: int | None = None


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
    rack_id: int | None = None
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
