# CORTEX.md — Circuit Breaker Backend Intelligence Audit
**Version audited**: v0.1.4-beta
**Rack simulator scope**: v1.1 (pre-foundation)
**Produced by**: Senior Backend Architect Agent
**Total findings**: 32

## Finding Index

| ID | Title | Priority | Rack Impact |
|---|---|---|---|
| CB-REL-001 | Missing Hard Link from Created Entity to Scan Source | P2 | No |
| CB-REL-002 | Services on Compute lack direct Hardware Edge | P2 | Yes |
| CB-REL-003 | Network Entity lacks Utilization Metric | P3 | No |
| CB-REL-004 | External Node to Service Typed Relationship | P3 | No |
| CB-REL-005 | Cluster to Service Relationship | P3 | No |
| CB-STATE-001 | Hardware Status Derived from Telemetry/Children | P2 | Yes |
| CB-STATE-002 | Compute Unit Composite Health Status | P2 | No |
| CB-STATE-003 | Service IP Conflict Real-time Re-evaluation | P1 | No |
| CB-STATE-004 | Network Address Utilization State | P3 | No |
| CB-STATE-005 | Hardware Last Seen Hybridization | P2 | No |
| CB-STATE-006 | Service Port Conflict Detection (Local) | P1 | No |
| CB-CASCADE-001 | Hardware Deletion Orphaned Telemetry Configs | P3 | No |
| CB-CASCADE-002 | Service Deletion Log Orphanage | P3 | No |
| CB-CASCADE-003 | Network Gateway Nullification Cascade | P2 | No |
| CB-CASCADE-004 | Environment Deletion Cascade | P2 | No |
| CB-CASCADE-005 | Scan Result Merge Atomicity | P1 | No |
| CB-PATTERN-001 | Duplicate Serial Number / MAC Detection | P1 | Yes |
| CB-PATTERN-002 | Service Port-Protocol Standardization | P3 | No |
| CB-PATTERN-003 | Orphaned Hardware Detection | P2 | Yes |
| CB-PATTERN-004 | Fleet Identification (Vendor/Model Grouping) | P2 | Yes |
| CB-PATTERN-005 | Subnet Nesting Detection | P3 | No |
| CB-PATTERN-006 | Degenerate Cluster Detection | P3 | No |
| CB-LEARN-001 | Service Category Learning from Ports | P2 | No |
| CB-LEARN-002 | Hardware U-Height Learning from Catalog | P2 | Yes |
| CB-LEARN-003 | MAC OUI Vendor Correction | P3 | No |
| CB-LEARN-004 | Naming Convention Suggestion | P3 | No |
| CB-LEARN-005 | Network VLAN/CIDR Correlation | P3 | No |
| CB-RACK-001 | Missing Rack Entity | P1 | Yes |
| CB-RACK-002 | Rack Unit Overlap Validation | P1 | Yes |
| CB-RACK-003 | Hardware Rear/Front Facing Orientation | P3 | Yes |
| CB-RACK-004 | Power Chain Modeling | P3 | Yes |
| CB-RACK-005 | Rail/Mounting Kit Compatibility | P3 | Yes |

***

### CB-REL-001 — Missing Hard Link from Created Entity to Scan Source

**Where**: `backend/app/services/discovery_service.py` → `_auto_merge_result` / `merge_scan_result`
**Entities involved**: Hardware, ScanResult, ScanJob
**Current behaviour**: When a `ScanResult` is merged (accepted), a `Hardware` entity is created with `source='discovery'`, but no specific FK links it back to the `ScanResult` or `ScanJob` that originated it.
**Gap / opportunity**: We lose the "provenance" of the data. We cannot answer "Which scan job found this server?" or "Show me the raw Nmap XML that generated this entity."
**Suggested fix / hook**: Add a nullable `source_scan_result_id` FK to `hardware` (and potentially `services`). Populate it upon merge.
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-REL-002 — Services on Compute lack direct Hardware Edge

**Where**: `backend/app/api/graph.py` → `get_topology`
**Entities involved**: Service, ComputeUnit, Hardware
**Current behaviour**: `Service` links to `ComputeUnit`. `ComputeUnit` links to `Hardware`. The topology graph manually constructs the path, but no direct DB relationship exists.
**Gap / opportunity**: Fast queries like "Show all services running on Rack A" require a two-hop join. Rack simulator visualisation will need efficient access to all services physically present in a rack unit.
**Suggested fix / hook**: Add a derived/cached `hardware_id` on the `Service` model that is automatically kept in sync when `compute_id` changes, or rely on a view. (Note: `Service` already has a nullable `hardware_id`, but it's mutually exclusive with `compute_id` in current logic; it should potentially be populated as a denormalised field for compute-bound services too).
**Priority**: P2 (intelligence)
**Rack impact**: Yes — critical for visualizing heat/power/services per rack U.

### CB-REL-003 — Network Entity lacks Utilization Metric

**Where**: `backend/app/services/networks_service.py`
**Entities involved**: Network, Hardware, ComputeUnit
**Current behaviour**: Networks exist as definitions (CIDR/VLAN). Membership is tracked via `HardwareNetwork` / `ComputeNetwork`.
**Gap / opportunity**: No instant way to see "Network 90% full" or "Empty Network". Requires counting join rows every time.
**Suggested fix / hook**: Add a calculated property or cached `device_count` on the Network entity, updated via signal/hook on membership change.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-REL-004 — External Node to Service Typed Relationship

**Where**: `backend/app/db/models.py` → `ServiceExternalNode`
**Entities involved**: ExternalNode, Service
**Current behaviour**: `ServiceExternalNode` links them with a generic `purpose` string.
**Gap / opportunity**: This relation is vague. Is it an upstream dependency (API) or a downstream consumer?
**Suggested fix / hook**: Formalize `purpose` or `direction` (upstream/downstream) in the relationship to allow directed graph edges in topology.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-REL-005 — Cluster to Service Relationship

**Where**: `backend/app/db/models.py`
**Entities involved**: HardwareCluster, Hardware, Service
**Current behaviour**: Clusters group Hardware. Services run on Hardware. No link between Cluster and Service.
**Gap / opportunity**: "Cluster health" depends on the services running on its members. We cannot easily query "Services belonging to Cluster X".
**Suggested fix / hook**: A read-only property or view on `HardwareCluster` that aggregates all `services` from its `members`.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-STATE-001 — Hardware Status Derived from Telemetry/Children

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware, Telemetry, ComputeUnit
**Current behaviour**: `Hardware.status` is manual or set to "online" by discovery. `telemetry_status` is separate.
**Gap / opportunity**: Hardware status should reflect reality. If telemetry fails or all compute units are "stopped", hardware status should degrade.
**Suggested fix / hook**: Implement a `recalculate_status(hardware_id)` hook called on telemetry updates or compute unit state changes.
**Priority**: P2 (intelligence)
**Rack impact**: Yes — Rack view needs to show red/green indicators based on real status.

### CB-STATE-002 — Compute Unit Composite Health Status

**Where**: `backend/app/services/compute_units_service.py`
**Entities involved**: ComputeUnit, Service
**Current behaviour**: Compute Unit has no status field, only `kind`.
**Gap / opportunity**: A VM is "unhealthy" if its critical services are stopped.
**Suggested fix / hook**: Add `status` to ComputeUnit. Derive it from the worst-case status of its generic services.
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-STATE-003 — Service IP Conflict Real-time Re-evaluation

**Where**: `backend/app/services/services_service.py` → `update_service`
**Entities involved**: Service, Hardware, ComputeUnit
**Current behaviour**: IP conflict is checked on save. `ip_mode` captures explicit vs inherited.
**Gap / opportunity**: If the parent Hardware IP changes, the Service (inheriting IP) might now conflict with something else. This cascade exists in `hardware_service.update_hardware` but relies on explicit looping.
**Suggested fix / hook**: Centralize the "IP changed" event. When any entity IP changes, queue a background job to re-check conflicts for all entities sharing that IP or subnet.
**Priority**: P1 (correctness)
**Rack impact**: No

### CB-STATE-004 — Network Address Utilization State

**Where**: `backend/app/services/networks_service.py`
**Entities involved**: Network
**Current behaviour**: CIDR is stored string.
**Gap / opportunity**: We don't know how many IPs are free in the subnet without iterating all hardware/compute.
**Suggested fix / hook**: Compute `utilized_ips` count on network membership changes. Store `utilization_percentage`.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-STATE-005 — Hardware Last Seen Hybridization

**Where**: `backend/app/services/discovery_service.py`
**Entities involved**: Hardware
**Current behaviour**: `last_seen` is updated by discovery scans.
**Gap / opportunity**: Telemetry polls also confirm presence. Manual edits confirm presence.
**Suggested fix / hook**: Update `last_seen` on *any* successful interaction (telemetry success, API update, scan match).
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-STATE-006 — Service Port Conflict Detection (Local)

**Where**: `backend/app/services/services_service.py`
**Entities involved**: Service
**Current behaviour**: Only IP conflicts are checked.
**Gap / opportunity**: Two services on the same ComputeUnit cannot listen on port 80. This is a hard physical constraint often missed.
**Suggested fix / hook**: Add `check_port_conflict` logic: `SELECT * FROM services WHERE compute_id = X AND ports_json LIKE '%:80,%'`.
**Priority**: P1 (correctness)
**Rack impact**: No

### CB-CASCADE-001 — Hardware Deletion Orphaned Telemetry Configs

**Where**: `backend/app/services/hardware_service.py` → `delete_hardware`
**Entities involved**: Hardware
**Current behaviour**: Telemetry config is a JSON column on Hardware, so it deletes with it.
**Gap / opportunity**: If we move to a `IntegrationConfig` table (implied by `AGENTS.md` context but not seen in models), this needs explicit cleanup.
**Suggested fix / hook**: Verify if `telemetry_config` remains a column or becomes a relation. If column, no action. If relation, needs cascade. (Currently column, so low priority).
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-CASCADE-002 — Service Deletion Log Orphanage

**Where**: `backend/app/services/services_service.py` → `delete_service`
**Entities involved**: Service, Logs
**Current behaviour**: Logs reference `entity_id`. If Service is deleted, logs point to nowhere.
**Gap / opportunity**: We want to keep audit logs.
**Suggested fix / hook**: Ensure `Logs` UI handles missing entities gracefully (displays "Deleted Service (ID 55)" instead of crashing).
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-CASCADE-003 — Network Gateway Nullification Cascade

**Where**: `backend/app/services/hardware_service.py` → `delete_hardware`
**Entities involved**: Hardware, Network
**Current behaviour**: `delete_hardware` explicitly nullifies `Network.gateway_hardware_id`.
**Gap / opportunity**: Good, but if we delete the *Network*, does the Hardware know? (Hardware doesn't store network ID directly, only via `HardwareNetwork`, which is cascaded).
**Suggested fix / hook**: Current behavior is correct, but verify `HardwareNetwork` cleanup is transactional.
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-CASCADE-004 — Environment Deletion Cascade

**Where**: `backend/app/api/environments.py` (not read, but inferred from models)
**Entities involved**: Environment, Hardware, Service
**Current behaviour**: `environment_id` FK is `ON DELETE SET NULL`.
**Gap / opportunity**: Entities become "environment-less".
**Suggested fix / hook**: Frontend should warn "Deleting this environment will move 50 items to 'Unassigned'".
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-CASCADE-005 — Scan Result Merge Atomicity

**Where**: `backend/app/services/discovery_service.py` → `merge_scan_result`
**Entities involved**: ScanResult, Hardware, Service
**Current behaviour**: Creates Hardware, then adds Services.
**Gap / opportunity**: If Service creation fails (e.g. slug collision), Hardware remains but is empty.
**Suggested fix / hook**: Wrap `merge_scan_result` logic in a single `db.begin_nested()` transaction.
**Priority**: P1 (correctness)
**Rack impact**: No

### CB-PATTERN-001 — Duplicate Serial Number / MAC Detection

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware
**Current behaviour**: No constraint on MAC address or Serial (not in model).
**Gap / opportunity**: Two hardware nodes with same MAC = data error or physical spoofing.
**Suggested fix / hook**: Add unique index or soft check on `mac_address`. Alert if duplicate detected during CRUD.
**Priority**: P1 (correctness)
**Rack impact**: Yes — ensures unique asset tracking in rack.

### CB-PATTERN-002 — Service Port-Protocol Standardization

**Where**: `backend/app/services/services_service.py`
**Entities involved**: Service
**Current behaviour**: User can type any protocol string.
**Gap / opportunity**: "TCP", "tcp", "Tcp" create mess.
**Suggested fix / hook**: Normalize protocol to lowercase in Pydantic validator or Service logic.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-PATTERN-003 — Orphaned Hardware Detection

**Where**: `backend/app/api/hardware.py`
**Entities involved**: Hardware
**Current behaviour**: Hardware exists.
**Gap / opportunity**: Hardware with no services, no compute, no storage, no location = probably stale data.
**Suggested fix / hook**: `find_orphans()` query to suggest cleanup candidates.
**Priority**: P2 (intelligence)
**Rack impact**: Yes — don't want to place ghost servers in a rack.

### CB-PATTERN-004 — Fleet Identification (Vendor/Model Grouping)

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware
**Current behaviour**: `vendor` / `model` are free text (coerced slightly).
**Gap / opportunity**: If I have 50 "Dell R730", I want to edit them in bulk or see them as a group.
**Suggested fix / hook**: API endpoint `GET /hardware/groups` grouping by vendor+model count.
**Priority**: P2 (intelligence)
**Rack impact**: Yes — essential for batch-applying U-height/images.

### CB-PATTERN-005 — Subnet Nesting Detection

**Where**: `backend/app/services/networks_service.py`
**Entities involved**: Network
**Current behaviour**: Independent CIDRs.
**Gap / opportunity**: `192.168.1.0/24` is inside `192.168.0.0/16`.
**Suggested fix / hook**: `check_subnet_overlap` on save. Warn if nesting detected (it might be intentional, but usually isn't in homelabs).
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-PATTERN-006 — Degenerate Cluster Detection

**Where**: `backend/app/services/clusters_service.py`
**Entities involved**: Cluster
**Current behaviour**: Clusters can be empty or have 1 member.
**Gap / opportunity**: A cluster with 1 member is rarely useful.
**Suggested fix / hook**: UI hint or dashboard alert for "Empty Clusters".
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-LEARN-001 — Service Category Learning from Ports

**Where**: `backend/app/services/discovery_service.py` → `PORT_SERVICE_MAP`
**Entities involved**: Service, Category
**Current behaviour**: Hardcoded map.
**Gap / opportunity**: Users create "Plex" on 32400. System should learn 32400 = "Media".
**Suggested fix / hook**: Periodically analyse existing Services. If Port X is 90% associated with Category Y, update the suggestion map.
**Priority**: P2 (intelligence)
**Rack impact**: No

### CB-LEARN-002 — Hardware U-Height Learning from Catalog

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware, VendorCatalog
**Current behaviour**: `vendor_catalog.json` exists but isn't aggressively used to backfill.
**Gap / opportunity**: If I type "R720", system should know it's 2U.
**Suggested fix / hook**: On Hardware create/update, if `u_height` is null, try to look up `model` in `vendor_catalog.json` and auto-fill.
**Priority**: P2 (intelligence)
**Rack impact**: Yes — Reduces manual entry for rack layout.

### CB-LEARN-003 — MAC OUI Vendor Correction

**Where**: `backend/app/services/discovery_service.py`
**Entities involved**: ScanResult
**Current behaviour**: Nmap guesses OS vendor.
**Gap / opportunity**: MAC OUI is more authoritative for hardware vendor (e.g. Dell OUI vs Windows OS).
**Suggested fix / hook**: Use a python `mac-vendor-lookup` lib or static OUI list to refine `vendor` field if Nmap is ambiguous.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-LEARN-004 — Naming Convention Suggestion

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware
**Current behaviour**: Free text name.
**Gap / opportunity**: If user names 10 hosts `pve-01`, `pve-02`... next suggestion should be `pve-11`.
**Suggested fix / hook**: Regex pattern match on existing names to suggest next increment.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-LEARN-005 — Network VLAN/CIDR Correlation

**Where**: `backend/app/services/networks_service.py`
**Entities involved**: Network
**Current behaviour**: VLAN and CIDR are independent.
**Gap / opportunity**: Often VLAN 10 = 10.0.10.x.
**Suggested fix / hook**: If user types VLAN 20, suggest `10.0.20.0/24` based on observed pattern in other networks.
**Priority**: P3 (future-proofing)
**Rack impact**: No

### CB-RACK-001 — Missing Rack Entity

**Where**: `backend/app/db/models.py`
**Entities involved**: Rack (New)
**Current behaviour**: Hardware has `u_height`, `rack_unit`. No `Rack` entity.
**Gap / opportunity**: Cannot model "Rack A" vs "Rack B". `location` string is insufficient.
**Suggested fix / hook**: Create `Rack` model (`id`, `name`, `height_u`, `location`). Add `Hardware.rack_id` FK.
**Priority**: P1 (correctness)
**Rack impact**: Yes — Foundation.

### CB-RACK-002 — Rack Unit Overlap Validation

**Where**: `backend/app/services/hardware_service.py`
**Entities involved**: Hardware
**Current behaviour**: No validation. Two servers can occupy U1.
**Gap / opportunity**: Physical impossibility.
**Suggested fix / hook**: On save, check `SELECT * FROM hardware WHERE rack_id = :rid AND (:start < (rack_unit + u_height) AND (rack_unit + u_height) > :start)`.
**Priority**: P1 (correctness)
**Rack impact**: Yes — Prevents invalid data.

### CB-RACK-003 — Hardware Rear/Front Facing Orientation

**Where**: `backend/app/db/models.py`
**Entities involved**: Hardware
**Current behaviour**: Assumes front-mounting.
**Gap / opportunity**: Switches are often rear-mounted (ToR).
**Suggested fix / hook**: Add `rack_orientation` enum (front/rear).
**Priority**: P3 (future-proofing)
**Rack impact**: Yes — Visual accuracy.

### CB-RACK-004 — Power Chain Modeling

**Where**: `backend/app/db/models.py`
**Entities involved**: Hardware (PDU/UPS)
**Current behaviour**: No power linkage.
**Gap / opportunity**: Cannot visualize "If UPS A fails, Rack B goes down".
**Suggested fix / hook**: `Hardware.power_source_id` FK pointing to another Hardware (PDU).
**Priority**: P3 (future-proofing)
**Rack impact**: Yes.

### CB-RACK-005 — Rail/Mounting Kit Compatibility

**Where**: `backend/app/db/models.py`
**Entities involved**: Hardware
**Current behaviour**: None.
**Gap / opportunity**: 4-post vs 2-post racks. Rail depth.
**Suggested fix / hook**: Add `mounting_type` (rails, shelf, ears) to Hardware/Catalog.
**Priority**: P3 (future-proofing)
**Rack impact**: Yes.