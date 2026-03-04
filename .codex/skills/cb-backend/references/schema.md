# Circuit Breaker — Full DB Schema Reference

All models live in `backend/app/db/models.py`. SQLite backend; JSON stored as `Text`.  
Timestamps default to `utcnow()` unless noted. FK = ForeignKey.

## Table of Contents

1. [Tag](#tag)
2. [Doc](#doc)
3. [EntityTag / EntityDoc](#entitytag--entitydoc)
4. [Rack](#rack)
5. [Hardware](#hardware)
6. [ComputeUnit](#computeunit)
7. [Category](#category)
8. [Environment](#environment)
9. [Service](#service)
10. [ServiceDependency](#servicedependency)
11. [Storage](#storage)
12. [ServiceStorage](#servicestorage)
13. [Network](#network)
14. [HardwareNetwork / ComputeNetwork](#hardwarenetwork--computenetwork)
15. [HardwareCluster / HardwareClusterMember](#hardwarecluster--hardwareclustermember)
16. [MiscItem / ServiceMisc](#miscitem--servicemisc)
17. [ExternalNode](#externalnode)
18. [ExternalNodeNetwork / ServiceExternalNode](#externalnodenetwork--serviceexternalnode)
19. [GraphLayout](#graphlayout)
20. [AppSettings](#appsettings)
21. [DiscoveryProfile](#discoveryprofile)
22. [ScanJob](#scanjob)
23. [ScanResult](#scanresult)
24. [User](#user)
25. [Log](#log)
26. [UserIcon](#usericon)
27. [LiveMetric](#livemetric)
28. [Relationships Overview](#relationships-overview)

---

## Tag

**Table:** `tags`

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK, autoincrement |
| name | String | unique, not null |

---

## Doc

**Table:** `docs`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| title | String | not null |
| body_md | Text | not null — raw Markdown |
| body_html | Text | nullable — rendered HTML |
| category | String | not null, default="" |
| pinned | Boolean | not null, default=False |
| icon | String | not null, default="" |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

---

## EntityTag / EntityDoc

**Table:** `entity_tags` — polymorphic tag association

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| entity_type | String | not null — e.g. "hardware", "service" |
| entity_id | Integer | not null |
| tag_id | Integer | FK → tags.id |

**Unique:** (entity_type, entity_id, tag_id)

**Table:** `entity_docs` — polymorphic doc association

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK |
| entity_type | String | not null |
| entity_id | Integer | not null |
| doc_id | Integer | FK → docs.id |

**Unique:** (entity_type, entity_id, doc_id)

---

## Rack

**Table:** `racks`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| height_u | Integer | not null, default=42 |
| location | String | nullable |
| notes | Text | nullable |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:** `hardware` → list[Hardware] (back_populates rack)

---

## Hardware

**Table:** `hardware`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| role | String | nullable |
| vendor | String | nullable |
| vendor_icon_slug | String | nullable |
| model | String | nullable |
| cpu | String | nullable |
| memory_gb | Integer | nullable |
| location | String | nullable |
| notes | Text | nullable |
| ip_address | String | nullable |
| wan_uplink | String | nullable |
| cpu_brand | String | nullable |
| vendor_catalog_key | String | nullable — links to vendor catalog |
| model_catalog_key | String | nullable — links to model catalog |
| u_height | Integer | nullable — rack units tall |
| rack_unit | Integer | nullable — starting U slot |
| telemetry_config | Text | nullable — JSON: `{protocol, host, username, …}` |
| telemetry_data | Text | nullable — JSON: last poll result |
| telemetry_status | String | nullable, default="unknown" |
| telemetry_last_polled | DateTime(tz) | nullable |
| environment_id | Integer | nullable, FK → environments.id |
| rack_id | Integer | nullable, FK → racks.id |
| source_scan_result_id | Integer | nullable, FK → scan_results.id |
| mac_address | String | nullable |
| status | String | nullable, default="unknown" |
| last_seen | String | nullable |
| discovered_at | String | nullable |
| source | String | nullable, default="manual" — "manual"\|"discovery" |
| os_version | String | nullable |
| wifi_standards | Text | nullable — JSON array |
| wifi_bands | Text | nullable — JSON array |
| max_tx_power_dbm | Integer | nullable |
| port_count | Integer | nullable |
| port_map_json | Text | nullable — JSON array |
| software_platform | String | nullable |
| download_speed_mbps | Integer | nullable |
| upload_speed_mbps | Integer | nullable |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:**
- `rack` → Rack | None
- `compute_units` → list[ComputeUnit]
- `environment_rel` → Environment | None
- `storage_items` → list[Storage]
- `network_memberships` → list[HardwareNetwork]
- `cluster_memberships` → list[HardwareClusterMember]

---

## ComputeUnit

**Table:** `compute_units`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| kind | String | not null — `"vm"` or `"container"` |
| hardware_id | Integer | not null, FK → hardware.id |
| os | String | nullable |
| icon_slug | String | nullable |
| cpu_cores | Integer | nullable — DB column name `CPU_cores` |
| cpu_brand | String | nullable |
| memory_mb | Integer | nullable |
| disk_gb | Integer | nullable |
| ip_address | String | nullable |
| environment | String | nullable — legacy free-text |
| environment_id | Integer | nullable, FK → environments.id |
| status | String | nullable, default="unknown" |
| notes | Text | nullable |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:**
- `hardware` → Hardware
- `environment_rel` → Environment | None
- `services` → list[Service]
- `network_memberships` → list[ComputeNetwork]

---

## Category

**Table:** `categories`

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK, autoincrement |
| name | String | unique, not null |
| color | String | nullable |
| created_at | String | not null |

**Relations:** `services` → list[Service]

---

## Environment

**Table:** `environments`

| Column | Type | Constraints |
|--------|------|-------------|
| id | Integer | PK, autoincrement |
| name | String | unique, not null |
| color | String | nullable |
| created_at | String | not null |

**Relations:** `hardware`, `compute_units`, `services` → respective lists

---

## Service

**Table:** `services`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| slug | String | unique, not null |
| compute_id | Integer | nullable, FK → compute_units.id |
| hardware_id | Integer | nullable, FK → hardware.id — bare-metal service |
| icon_slug | String | nullable |
| category | String | nullable — legacy free-text |
| category_id | Integer | nullable, FK → categories.id |
| url | String | nullable |
| ports | String | nullable — legacy free-text |
| ports_json | Text | nullable — JSON array |
| description | Text | nullable |
| environment | String | nullable — legacy free-text |
| environment_id | Integer | nullable, FK → environments.id |
| status | String | nullable — `"running"` \| `"stopped"` \| `"degraded"` \| `"maintenance"` |
| ip_address | String | nullable |
| ip_mode | Text | default="explicit" — `"explicit"` \| `"inherited"` |
| ip_conflict | Boolean | default=False |
| ip_conflict_json | Text | default="[]" — JSON array of conflict details |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:**
- `compute_unit` → ComputeUnit | None
- `hardware` → Hardware | None
- `category_rel` → Category | None
- `environment_rel` → Environment | None
- `dependencies` → list[ServiceDependency] (this service depends on others)
- `dependents` → list[ServiceDependency] (others depend on this service)
- `storage_links` → list[ServiceStorage]
- `misc_links` → list[ServiceMisc]

---

## ServiceDependency

**Table:** `service_dependencies`  
**Unique:** (service_id, depends_on_id)

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| service_id | Integer | not null, FK → services.id |
| depends_on_id | Integer | not null, FK → services.id |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

---

## Storage

**Table:** `storage`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| kind | String | not null — `"disk"` \| `"pool"` \| `"dataset"` \| `"share"` |
| icon_slug | String | nullable |
| hardware_id | Integer | nullable, FK → hardware.id |
| capacity_gb | Integer | nullable |
| used_gb | Integer | nullable |
| path | String | nullable |
| protocol | String | nullable — e.g. "nfs", "smb", "iscsi" |
| notes | Text | nullable |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:**
- `hardware` → Hardware | None
- `service_links` → list[ServiceStorage]

---

## ServiceStorage

**Table:** `service_storage`  
**Unique:** (service_id, storage_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| service_id | Integer | FK → services.id |
| storage_id | Integer | FK → storage.id |
| purpose | String | nullable |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

---

## Network

**Table:** `networks`

| Column | Type | Constraints / Notes |
|--------|------|---------------------|
| id | Integer | PK, autoincrement |
| name | String | not null |
| icon_slug | String | nullable |
| cidr | String | nullable |
| vlan_id | Integer | nullable |
| gateway | String | nullable |
| description | Text | nullable |
| gateway_hardware_id | Integer | nullable, FK → hardware.id |
| created_at | DateTime(tz) | default=utcnow |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

**Relations:**
- `gateway_hardware` → Hardware | None
- `compute_memberships` → list[ComputeNetwork]
- `hardware_memberships` → list[HardwareNetwork]

---

## HardwareNetwork / ComputeNetwork

**Table:** `hardware_networks`  
**Unique:** (hardware_id, network_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| hardware_id | Integer | FK → hardware.id |
| network_id | Integer | FK → networks.id |
| ip_address | String | nullable |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

**Table:** `compute_networks`  
**Unique:** (compute_id, network_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| compute_id | Integer | FK → compute_units.id |
| network_id | Integer | FK → networks.id |
| ip_address | String | nullable |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

---

## HardwareCluster / HardwareClusterMember

**Table:** `hardware_clusters`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| name | String | not null |
| description | Text | nullable |
| environment | String | nullable |
| location | String | nullable |
| created_at / updated_at | DateTime(tz) | |

**Table:** `hardware_cluster_members`  
**Unique:** (cluster_id, hardware_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| cluster_id | Integer | FK → hardware_clusters.id |
| hardware_id | Integer | FK → hardware.id |
| role | String | nullable — e.g. "primary", "worker" |

---

## MiscItem / ServiceMisc

**Table:** `misc_items`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| name | String | not null |
| kind | String | nullable — "dns", "vpn", "saas", etc. |
| icon_slug | String | nullable |
| url | String | nullable |
| description | Text | nullable |
| created_at / updated_at | DateTime(tz) | |

**Table:** `service_misc`  
**Unique:** (service_id, misc_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| service_id | Integer | FK → services.id |
| misc_id | Integer | FK → misc_items.id |
| purpose | String | nullable |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

---

## ExternalNode

**Table:** `external_nodes`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| name | String | not null |
| provider | String | nullable — "Hetzner", "AWS", "Cloudflare", etc. |
| kind | String | nullable — "vps", "managed_db", "saas", "vpn_gateway", etc. |
| region | String | nullable — "us-west-2", "nbg1", "global", etc. |
| ip_address | String | nullable — primary IP or hostname |
| icon_slug | String | nullable |
| notes | Text | nullable |
| environment | String | nullable — "prod", "lab", "shared" |
| created_at / updated_at | DateTime(tz) | |

**Relations:**
- `network_links` → list[ExternalNodeNetwork] (cascade delete)
- `service_links` → list[ServiceExternalNode] (cascade delete)

---

## ExternalNodeNetwork / ServiceExternalNode

**Table:** `external_node_networks`  
**Unique:** (external_node_id, network_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| external_node_id | Integer | FK → external_nodes.id (CASCADE) |
| network_id | Integer | FK → networks.id (CASCADE) |
| link_type | String | nullable — "vpn", "wan", "wireguard", "reverse_proxy", etc. |
| notes | Text | nullable |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

**Table:** `service_external_nodes`  
**Unique:** (service_id, external_node_id)

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| service_id | Integer | FK → services.id (CASCADE) |
| external_node_id | Integer | FK → external_nodes.id (CASCADE) |
| purpose | String | nullable — "db", "auth", "cache", "upstream_api", etc. |
| connection_type | String | default="ethernet" |
| bandwidth_mbps | Integer | nullable |

---

## GraphLayout

**Table:** `graph_layouts`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| name | String | unique — e.g. "default", "user-1-custom" |
| context | String | nullable — e.g. "topology" |
| layout_data | Text | not null — JSON: node positions + viewport |
| updated_at | DateTime(tz) | default=utcnow, onupdate |

---

## AppSettings

**Table:** `app_settings` (singleton row, id=1)

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| id | Integer | PK, default=1 | |
| theme | String | "dark" | |
| default_environment | String | nullable | |
| show_experimental_features | Boolean | False | |
| api_base_url | String | nullable | |
| map_default_filters | Text | nullable | JSON |
| vendor_icon_mode | String | "custom_files" | |
| environments | Text | `["prod","staging","dev"]` | JSON array |
| categories | Text | `[]` | JSON array |
| locations | Text | `[]` | JSON array |
| dock_order | Text | nullable | JSON array of path strings |
| dock_hidden_items | Text | nullable | JSON array |
| show_page_hints | Boolean | True | |
| auth_enabled | Boolean | False | |
| jwt_secret | Text | nullable | |
| session_timeout_hours | Integer | 24 | |
| app_name | String | "Circuit Breaker" | |
| favicon_path | Text | nullable | |
| login_logo_path | Text | nullable | |
| login_bg_path | Text | nullable | |
| primary_color | String | "#00d4ff" | |
| accent_colors | Text | `["#ff6b6b","#4ecdc4"]` | JSON |
| theme_preset | String | "cyberpunk-neon" | |
| custom_colors | Text | nullable | JSON: {primary,secondary,accent1,accent2,background,surface} |
| show_external_nodes_on_map | Boolean | True | |
| timezone | String | "UTC" | IANA name |
| discovery_enabled | Boolean | False | |
| discovery_auto_merge | Boolean | False | |
| discovery_default_cidr | String | "" | |
| discovery_nmap_args | String | "-sV -O --open -T4" | |
| discovery_snmp_community | String | "" | |
| discovery_schedule_cron | String | "" | |
| discovery_http_probe | Boolean | True | |
| discovery_retention_days | Integer | 30 | |
| scan_ack_accepted | Boolean | False | |
| ui_font | String | "inter" | |
| ui_font_size | String | "medium" | |
| created_at / updated_at | DateTime(tz) | | |

---

## DiscoveryProfile

**Table:** `discovery_profiles`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, index |
| name | String | not null |
| cidr | String | not null |
| scan_types | String | default='["nmap"]' — JSON array |
| nmap_arguments | String | nullable |
| snmp_community_encrypted | String | nullable — Fernet encrypted |
| snmp_version | String | default="2c" |
| snmp_port | Integer | default=161 |
| schedule_cron | String | nullable |
| enabled | Integer | default=1 |
| last_run | String | nullable |
| created_at / updated_at | String | not null |

**Relations:** `jobs` → list[ScanJob]

---

## ScanJob

**Table:** `scan_jobs`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| profile_id | Integer | nullable, FK → discovery_profiles.id |
| label | String | nullable |
| target_cidr | String | not null |
| scan_types_json | String | not null — JSON array |
| status | String | default="queued" — queued\|running\|completed\|failed |
| started_at / completed_at | String | nullable |
| hosts_found / hosts_new / hosts_updated / hosts_conflict | Integer | default=0 |
| error_text | String | nullable |
| triggered_by | String | default="api" |
| progress_phase | String | default="queued" |
| progress_message | String | default="" |
| created_at | String | not null |

**Relations:**
- `profile` → DiscoveryProfile | None
- `results` → list[ScanResult]

---

## ScanResult

**Table:** `scan_results`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| scan_job_id | Integer | FK → scan_jobs.id |
| ip_address | String | not null |
| mac_address | String | nullable |
| hostname | String | nullable |
| open_ports_json | String | nullable — JSON array of {port, protocol, service, version} |
| os_family / os_vendor | String | nullable |
| snmp_sys_name / snmp_sys_descr | String | nullable |
| snmp_interfaces_json / snmp_storage_json | String | nullable — JSON |
| raw_nmap_xml | String | nullable |
| state | String | default="new" — new\|accepted\|ignored\|conflict |
| conflicts_json | String | nullable — JSON |
| matched_entity_type | String | nullable — "hardware" |
| matched_entity_id | Integer | nullable |
| merge_status | String | default="pending" |
| reviewed_by / reviewed_at | String | nullable |
| created_at | String | not null |

---

## User

**Table:** `users`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK, autoincrement |
| email | Text | unique, not null |
| password_hash | Text | not null — bcrypt |
| gravatar_hash | Text | nullable |
| profile_photo | Text | nullable — relative upload path |
| display_name | Text | nullable |
| is_admin | Boolean | default=False |
| created_at | Text | not null |
| last_login | Text | nullable |

---

## Log

**Table:** `logs` — Audit log

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| timestamp | DateTime(tz) | indexed, default=utcnow |
| level | String | default="info" |
| category | String | not null — "crud"\|"settings"\|"relationships"\|"docs" |
| action | String | not null — e.g. "create_hardware", "update_service" |
| actor | String | default="anonymous" |
| actor_gravatar_hash | String | nullable |
| entity_type | String | nullable |
| entity_id | Integer | nullable |
| old_value / new_value | Text | nullable |
| user_agent | String | nullable |
| ip_address | String | nullable |
| details | Text | nullable |
| status_code | Integer | nullable — HTTP response code |
| created_at_utc | String | nullable — ISO 8601 UTC; canonical for frontend display |
| actor_id | Integer | nullable |
| actor_name | String | default="admin" |
| entity_name | String | nullable — denormalized at write time |
| diff | Text | nullable — JSON: `{"before": {...}, "after": {...}}` |
| severity | String | default="info" — "info"\|"warn"\|"error" |

---

## UserIcon

**Table:** `user_icons`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| slug | String | unique, indexed |
| name | String | nullable |
| category | String | nullable |
| created_at / updated_at | DateTime(tz) | |

---

## LiveMetric

**Table:** `live_metrics`

| Column | Type | Notes |
|--------|------|-------|
| ip | String | PK |
| node_id | String | nullable — e.g. "hw-123" |
| node_type | String | nullable — "hardware"\|"service" |
| last_seen | DateTime(tz) | nullable |
| status | String | nullable — "up"\|"down"\|"offline" |
| assigned_to | String | nullable — service slug |
| subnet | String | nullable — e.g. "10.10.10.0/24" |

---

## Relationships Overview

```
Rack
└── Hardware (many)
    ├── ComputeUnit (many)
    │   ├── Service (many)
    │   │   ├── ServiceDependency → Service (self-referential)
    │   │   ├── ServiceStorage → Storage
    │   │   ├── ServiceMisc → MiscItem
    │   │   └── ServiceExternalNode → ExternalNode
    │   └── ComputeNetwork → Network
    ├── Storage (many)
    ├── HardwareNetwork → Network
    ├── HardwareClusterMember → HardwareCluster
    └── Service (bare-metal, optional)

Network
├── gateway_hardware → Hardware (optional)
├── HardwareNetwork ← Hardware
├── ComputeNetwork ← ComputeUnit
└── ExternalNodeNetwork ← ExternalNode

Environment → Hardware, ComputeUnit, Service
Category → Service

Doc ←→ EntityDoc ←→ any entity (polymorphic by entity_type + entity_id)
Tag ←→ EntityTag ←→ any entity (polymorphic)

DiscoveryProfile → ScanJob → ScanResult
ScanResult → Hardware (via source_scan_result_id)

AppSettings (singleton)
GraphLayout (named slots, context="topology")
User, Log, UserIcon, LiveMetric (standalone)
```
