# Business Intelligence

Circuit Breaker's intelligence layer provides automated blast-radius analysis, predictive capacity forecasting, right-sizing recommendations, flap detection, vulnerability assessment, and configurable telemetry retention — all derived from the same asset graph and live-metric data already collected by the platform.

## Where these appear

| Capability | Surface |
|---|---|
| Capacity forecasts | **Intel** page (`/intel`) |
| Resource efficiency | **Intel** page (`/intel`) |
| Blast radius | **Impact** panel on a hardware, compute unit, service, or storage detail view |
| Vulnerability assessment | **Vulnerability assessment** panel on a hardware, compute unit, or service detail view |

All of these are readable by any signed-in user; they carry no role restriction. Correcting an assessment identity and triggering a feed sync require editor access.

## When the data appears

Capacity forecasts and right-sizing recommendations are written by the
`analytics_job` scheduled job, which runs nightly at 02:30. Both tables are
empty until it has run at least once, and stay empty for anything it has no
recommendation about — a host without enough telemetry history has no forecast,
and an asset sitting comfortably within its allocation has no recommendation.
The page states both possibilities, because the stored data cannot distinguish
them: the job writes nothing when it finds nothing.

Blast radius is computed on demand when you expand the **Impact** panel, not on
a schedule, because it reflects the dependency graph as it stands right now.
It reports **potential dependency impact** from declared relationships — what
could lose its provider — never an observed outage. Every listed asset can
show the path of evidence that connects it. "Nothing depends on this" is a
real answer and is displayed as one; a traversal that stopped at a limit says
so instead, because an empty result from part of the graph is not proof that
nothing depends on the asset.

## Vulnerability assessment, honestly

The **Vulnerability assessment** panel matches an entity's product identity
against a locally cached NVD CVE feed. It separates readiness from findings:
the first thing it shows is what state the assessment is in, and only a
`completed` assessment with zero findings says **No matches in this
assessment** — never "safe". A missing, incomplete, stale, or failed feed
cannot produce an unqualified clean result.

The assessment states:

| State | Meaning |
|-------|---------|
| `unavailable` | No complete feed generation is active (never synced, incomplete, or failed). Findings are withheld. |
| `unassessed` | The entity has no usable identity — missing product, missing version, or a version format with no supported comparator. |
| `partial` | The assessment ran, but candidates or findings exceeded their limits, or some applicability could only evaluate to unknown. |
| `completed` | Every matching candidate in the active feed was evaluated. |
| `stale` | The findings come from a feed older than the freshness policy. They remain displayed, labelled stale, until a fresh sync completes. |

**Identity.** The matcher evaluates vendor/product/version. It reads them from
the entity's inventory fields first; an operator can correct them on the
panel, and the correction carries a revision so a stale edit cannot silently
overwrite a newer one. Editing the identity invalidates the previous
assessment immediately.

**Evidence and limits.** Each finding can show the CPE criteria that matched it,
including inclusive/exclusive version bounds. Version comparison supports
dotted-numeric versions only; any other scheme reports `unknown` rather than
guessing. Unsupported applicability coexists with confirmed matches, and the
result says which. Assessments are bounded (candidate and finding caps); when
a cap is hit the result is `partial` with the limitation stated, not a silent
truncation.

The feed sync itself is configured under **Settings → Security** (CVE feed
sync) and downloads the NVD feed to a local SQLite cache; no inventory data
leaves the host. See [Privacy](security/privacy.md).

---

## New Models (migration 0058)

| Table | Purpose |
|-------|---------|
| `capacity_forecasts` | Linear-regression disk/memory saturation forecasts per hardware node |
| `resource_efficiency_recommendations` | CPU/memory right-sizing classifications per asset |
| `flap_incidents` | Records of rapid UP/DOWN status transitions detected within a time window |

### AppSettings additions

| Column | Default | Description |
|--------|---------|-------------|
| `telemetry_hot_days` | 7 | Keep full-resolution telemetry rows |
| `telemetry_warm_days` | 30 | Keep hourly-downsampled rows; purge beyond this |

---

## API Endpoints

All endpoints require authentication and are prefixed `/api/v1/intel/`.

### `GET /api/v1/intel/blast-radius/{asset_type}/{asset_id}`

Returns the downstream impact of a given asset going offline. Performs a bounded breadth-first traversal of the operational dependency graph starting from the specified asset.

**Path parameters:**

| Parameter | Values |
|-----------|--------|
| `asset_type` | `hardware`, `compute_unit`, `service`, `storage` |
| `asset_id` | integer primary key |

**Query parameters:**

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `include_inferred` | `false` | Also traverse edges whose provenance is inferred, not just confirmed ones. The response states whether any inferred edges exist (`inferred_available`). |
| `max_nodes` | `500` | Traversal node cap (1–1000). |
| `max_depth` | `12` | Traversal hop cap (1–24). |

**Response:**

```json
{
  "root_asset": { "asset_type": "hardware", "asset_id": 1, "name": "hypervisor-01", "status": "up" },
  "impacted_hardware": [],
  "impacted_compute_units": [
    { "asset_type": "compute_unit", "asset_id": 3, "name": "vm1", "status": "running" }
  ],
  "impacted_services": [
    { "asset_type": "service", "asset_id": 7, "name": "api-server", "status": null }
  ],
  "impacted_storage": [],
  "total_impact_count": 2,
  "summary": "hypervisor-01 is DOWN. Impact: 1 VM, 1 service affected.",
  "paths": [
    {
      "asset": { "asset_type": "service", "asset_id": 7, "name": "api-server", "status": null },
      "edges": [
        { "identity": "compute_units.hardware_id:3:hardware:1:compute_unit:3",
          "provider_type": "hardware", "provider_id": 1,
          "dependent_type": "compute_unit", "dependent_id": 3,
          "edge_type": "hosting", "provenance": "confirmed",
          "source_kind": "compute_units.hardware_id", "source_id": 3,
          "label": "hosted by" }
      ],
      "provenance": "confirmed"
    }
  ],
  "edges": [],
  "connectivity": [],
  "evaluated_at": "2026-09-15T12:00:00Z",
  "completeness": "complete",
  "truncation_reason": null,
  "limits": { "max_nodes": 500, "max_depth": 12, "max_edges": 5000 },
  "inferred_available": false
}
```

Every listed asset has an entry in `paths` (unless a cap was hit first) made
of typed, provenance-tagged edges. `edges` carries the deduplicated edges the
traversal used; `connectivity` carries ordinary connectivity (physical links
and network memberships) that is *not* counted as impact. `completeness` is
`"truncated"` with a `truncation_reason` of `node_limit`, `depth_limit` or
`edge_limit` when a cap stopped the traversal — a truncated result is partial,
never exhaustive.

**Dependency graph edges traversed (impact):**

- `ComputeUnit.hardware_id` — compute units hosted on a hardware node (**hosting**)
- `Service.hardware_id` / `Service.compute_id` — services running on hardware or compute (**hosting**)
- `ServiceDependency` — if service A depends on service B, B going down impacts A (**dependency**)
- `Storage.hardware_id` — storage attached to hardware (**hosting**)
- `ServiceStorage` — services that use a storage target (**dependency**)

**Edges reported as connectivity only (never traversed for impact):**

- `HardwareConnection` — direct hardware-to-hardware links
- `HardwareNetwork` / `ComputeNetwork` — network memberships

Shared subnet membership is connectivity, not an operational dependency: two
devices on the same network are not mutual dependents, and membership is never
expanded into device pairs.

### `GET /api/v1/intel/capacity-forecasts`

Returns all capacity forecasts ordered by projected saturation date (soonest first, null last).

```json
[
  {
    "id": 1,
    "hardware_id": 5,
    "metric": "disk_pct",
    "slope_per_day": 1.04,
    "current_value": 71.3,
    "projected_full_at": "2025-05-12T02:30:00Z",
    "warning_threshold_days": 7,
    "evaluated_at": "2025-04-19T02:30:00Z"
  }
]
```

### `GET /api/v1/intel/resource-efficiency`

Returns right-sizing recommendations ordered by most recently evaluated.

```json
[
  {
    "id": 2,
    "asset_type": "hardware",
    "asset_id": 3,
    "classification": "over_provisioned",
    "cpu_avg_pct": 2.1,
    "cpu_peak_pct": 8.4,
    "mem_avg_pct": 4.9,
    "recommendation": "Average CPU 2.1%, memory 4.9% over 30d. Resources appear over-allocated; consider consolidating workloads.",
    "evaluated_at": "2025-04-19T02:30:00Z"
  }
]
```

---

## Vulnerability assessment API

Assessment endpoints are prefixed `/api/v1/cve/`. Reads are available to any
signed-in user; identity correction and feed sync require editor access.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/cve/entity/{entity_type}/{entity_id}` | GET | The full `AssessmentResult` for one entity: state, reason code, identity and its revision, feed generation/age, findings with applicability evidence, completeness, and limitations. |
| `/api/v1/cve/entity/{entity_type}/{entity_id}/identity` | PUT | Correct the identity. The request must carry the identity revision currently shown; a stale revision is rejected with `stale_identity`. |
| `/api/v1/cve/status` | GET | Feed configuration and state: sync enabled, interval, entry count, and the active generation's state/freshness. |
| `/api/v1/cve/sync` | POST | Trigger an immediate feed sync (also scheduled). |
| `/api/v1/cve/search` | GET | Search the cached CVE catalog directly. |

The identity revision makes out-of-order corrections rejectable on the client:
a response for revision *n* cannot overwrite a state already advanced to *n+1*.

---

## Analytics Jobs

Jobs run via APScheduler. Both are guarded by a PostgreSQL advisory lock so concurrent runs are safe.

| Job | Schedule (UTC) | Lock key | Function |
|-----|---------------|----------|---------|
| Analytics | Daily 02:30 | `analytics_job` | `run_analytics_job()` |
| Retention | Daily 03:30 | `retention_job` | `run_retention_job()` |

### Analytics job (`run_analytics_job`)

Runs three passes in order:

1. **Capacity forecast** (`run_capacity_forecast`) — OLS linear regression over the last 14 days of `disk_pct` and `mem_pct` per hardware node. Upserts `CapacityForecast` rows. Projects saturation date when slope > 0.

2. **Right-sizing** (`run_right_sizing`) — Aggregates 30-day CPU/memory averages and classifies each hardware node:
   - `under_provisioned` — CPU avg > 75% or (CPU avg > 60% and CPU peak > 90%)
   - `over_provisioned` — CPU avg < 10% and memory avg < 15%
   - `balanced` — everything else

3. **Flap detection** (`run_flap_detection`) — Counts UP/DOWN status transitions within a 30-minute window. Nodes with ≥ 5 transitions get an active `FlapIncident`. Incidents are resolved automatically when transitions drop below threshold.

### Retention job (`run_retention_job`)

Enforces the same two-tier data lifecycle on `hardware_live_metrics` and `agent_host_samples`:

| Window | Behaviour |
|--------|-----------|
| 0 → `telemetry_hot_days` ago | Untouched (full resolution) |
| `telemetry_hot_days` → `telemetry_warm_days` ago | Raw rows replaced with hourly averages (`source="hourly_agg"`) |
| Beyond `telemetry_warm_days` | Deleted entirely |

`hardware_live_metrics` warm rows are collapsed in place; `agent_host_samples` warm rows are collapsed into
`agent_host_sample_hourly`, so the window behaves identically with and without TimescaleDB jobs.

Thresholds default to 7 and 30 days and can be overridden per-instance via `AppSettings.telemetry_hot_days` / `telemetry_warm_days`.

---

## Blast Radius in Status Alerts

When the status worker detects a **critical** DOWN event (group offline for > 5 minutes), it automatically enriches the stored `StatusHistory.metrics` payload with a `blast_radius` summary:

```json
"blast_radius": {
  "summary": "hypervisor-01 is DOWN. Impact: 2 VMs, 1 service affected.",
  "total_impact_count": 3,
  "impacted_compute_units": 2,
  "impacted_services": 1,
  "impacted_hardware": 0
}
```

The blast radius call is best-effort — a failure never blocks the status update.

---

## Uptime Kuma / External Monitor Integration

`HardwareLiveMetric` rows carry a `source` field that identifies their origin. The Uptime Kuma integration is
configured under **Settings → Integrations → Service Integrations** and writes rows with `source="uptime_kuma"`,
so the capacity and flap-detection analytics already operate on externally-monitored assets without schema changes.

Asset identity uses stable `(asset_type, asset_id)` tuples throughout, so external monitor data can be linked to existing hardware/service records by ID.

---

## Extending Blast Radius

To add a new relationship to the blast-radius graph, add it in
`load_dependency_edges()` inside `src/app/services/intelligence/dependency_edges.py`.
Operational relationships go in `dependencies` with an edge type (`hosting`,
`dependency`) and provenance; physical links and memberships go in
`connectivity`, which is reported but never traversed for impact. The
traversal, path assembly and completeness handling in
`dependency_graph.py` pick edges up from there automatically.
