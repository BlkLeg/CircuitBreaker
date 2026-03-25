# Business Intelligence

Circuit Breaker's intelligence layer provides automated blast-radius analysis, predictive capacity forecasting, right-sizing recommendations, flap detection, and configurable telemetry retention — all derived from the same asset graph and live-metric data already collected by the platform.

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

Returns the downstream impact of a given asset going offline. Performs a BFS traversal of the dependency graph starting from the specified asset.

**Path parameters:**

| Parameter | Values |
|-----------|--------|
| `asset_type` | `hardware`, `compute_unit`, `service`, `storage` |
| `asset_id` | integer primary key |

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
  "summary": "hypervisor-01 is DOWN. Impact: 1 VM, 1 service affected."
}
```

**Dependency graph edges traversed:**

- `HardwareConnection` — direct hardware-to-hardware links
- `HardwareNetwork` — hardware nodes sharing a network (bidirectional)
- `ComputeUnit.hardware_id` — compute units hosted on a hardware node
- `Service.hardware_id` / `Service.compute_id` — services running on hardware or compute
- `ServiceDependency` — if service A depends on service B, B going down impacts A
- `Storage.hardware_id` — storage attached to hardware

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

Enforces a two-tier data lifecycle on `hardware_live_metrics`:

| Window | Behaviour |
|--------|-----------|
| 0 → `telemetry_hot_days` ago | Untouched (full resolution) |
| `telemetry_hot_days` → `telemetry_warm_days` ago | Raw rows replaced with hourly averages (`source="hourly_agg"`) |
| Beyond `telemetry_warm_days` | Deleted entirely |

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

`HardwareLiveMetric` rows carry a `source` field that identifies their origin. Future Uptime Kuma integration will write rows with `source="uptime_kuma"`, allowing the same capacity and flap-detection analytics to operate on externally-monitored assets without schema changes.

Asset identity uses stable `(asset_type, asset_id)` tuples throughout, so external monitor data can be linked to existing hardware/service records by ID.

---

## Extending Blast Radius

To add a new asset type to the blast-radius graph, add edges in `_build_adjacency()` inside `src/app/services/intelligence/dependency_graph.py`. Each edge is a `(asset_type, id) → (asset_type, id)` entry in the adjacency dict. The BFS traversal and result classification handle the rest automatically.
