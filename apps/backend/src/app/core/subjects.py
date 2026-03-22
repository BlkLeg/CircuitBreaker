"""NATS subject constants and payload helpers for Phase 3 messaging.

All subjects follow the pattern: <domain>.<entity>.<event>

Subscribers and publishers should import from this module to avoid
hard-coded subject strings scattered across the codebase.
"""

# ── Discovery ───────────────────────────────────────────────────────────────

DISCOVERY_SCAN_STARTED = "discovery.scan.started"
DISCOVERY_SCAN_PROGRESS = "discovery.scan.progress"
DISCOVERY_SCAN_COMPLETED = "discovery.scan.completed"
DISCOVERY_SCAN_FAILED = "discovery.scan.failed"
DISCOVERY_DEVICE_FOUND = "discovery.device.found"
DISCOVERY_LISTENER_FOUND = "discovery.listener.found"
DISCOVERY_PROBER_STARTED = "discovery.prober.started"

# ── Telemetry ────────────────────────────────────────────────────────────────

TELEMETRY_UPDATE = "telemetry.update"
TELEMETRY_PROXMOX_NODE = "telemetry.proxmox.node"
TELEMETRY_PROXMOX_VM = "telemetry.proxmox.vm"

# JetStream ingestion pipeline (telemetry_collector → TELEMETRY stream → telemetry_ingest_worker)
TELEMETRY_INGEST = "telemetry.ingest.{hardware_id}"  # formatted at publish time
TELEMETRY_INGEST_ALL = "telemetry.ingest.>"  # stream subject filter

# ── Integrations ─────────────────────────────────────────────────────────────

INTEGRATION_SYNCED = "integrations.synced.{integration_id}"  # formatted at publish time
INTEGRATION_SYNCED_ALL = "integrations.synced.>"  # subscribe filter

PROXMOX_STORAGE_REMOVED = "integrations.proxmox.storage.removed"
PROXMOX_NODE_REMOVED = "integrations.proxmox.node.removed"
PROXMOX_VM_REMOVED = "integrations.proxmox.vm.removed"

BACKUP_SNAPSHOT_COMPLETED = "backup.snapshot.completed"

# ── Intelligence ──────────────────────────────────────────────────────────────

INTEL_ASSET_DOWN = "intel.asset.down"  # enriched DOWN event including blast radius payload

# ── Notifications / Alerts ───────────────────────────────────────────────────

NOTIFICATION_EVENT = "notifications.event"
ALERT_EVENT = "notifications.alert"

# ── Topology (map / rack live updates) ───────────────────────────────────────

TOPOLOGY_NODE_MOVED = "topology.node.moved"
TOPOLOGY_CABLE_ADDED = "topology.cable.added"
TOPOLOGY_CABLE_REMOVED = "topology.cable.removed"
TOPOLOGY_NODE_STATUS_CHANGED = "topology.node.status_changed"


# ── Payload helpers ──────────────────────────────────────────────────────────


def discovery_scan_started_payload(job_id: int, cidr: str, triggered_by: str = "api") -> dict:
    return {"job_id": job_id, "cidr": cidr, "triggered_by": triggered_by}


def discovery_listener_found_payload(
    source: str,
    ip: str | None,
    name: str | None,
    service_type: str | None,
    port: int | None = None,
) -> dict:
    return {"source": source, "ip": ip, "name": name, "service_type": service_type, "port": port}


def discovery_scan_progress_payload(
    job_id: int,
    phase: str,
    message: str = "",
    percent: int | None = None,
) -> dict:
    p: dict = {"job_id": job_id, "phase": phase, "message": message}
    if percent is not None:
        p["percent"] = max(0, min(100, percent))
    return p


def discovery_scan_completed_payload(
    job_id: int,
    hosts_found: int = 0,
    hosts_new: int = 0,
) -> dict:
    return {"job_id": job_id, "hosts_found": hosts_found, "hosts_new": hosts_new}


def topology_node_moved_payload(
    node_id: str,
    node_type: str,
    x: float,
    y: float,
) -> dict:
    return {"node_id": node_id, "node_type": node_type, "x": x, "y": y}


def topology_cable_payload(
    source_id: str,
    target_id: str,
    connection_type: str = "ethernet",
    bandwidth_mbps: int | None = None,
) -> dict:
    p: dict = {
        "source_id": source_id,
        "target_id": target_id,
        "connection_type": connection_type,
    }
    if bandwidth_mbps is not None:
        p["bandwidth_mbps"] = bandwidth_mbps
    return p


def topology_status_changed_payload(
    node_id: str,
    node_type: str,
    status: str,
) -> dict:
    return {"node_id": node_id, "node_type": node_type, "status": status}
