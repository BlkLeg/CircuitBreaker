# Prometheus Metrics

Circuit Breaker exposes an inventory metrics endpoint in the [Prometheus text exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/).
You can scrape it directly from Prometheus, Grafana Alloy, the OpenTelemetry Collector, or any compatible agent.

For v1.0 release candidates, this metrics schema is beta unless a later contract promotes it. Do not
treat metric names, labels, or cardinality as a stable public API before the
[1.0 compatibility policy](release/1.0.0-compatibility-policy.md) says otherwise.

## Endpoint

```
GET /api/v1/metrics/metrics
```

Returns `text/plain; version=0.0.4; charset=utf-8` — the standard Prometheus scrape format.

> **Note:** The endpoint is intentionally placed under `/api/v1/` (not at the root `/metrics`) to avoid conflicts with Circuit Breaker's frontend catch-all route.
>
> The path really does end in `/metrics/metrics`: the metrics router is mounted at the
> `/api/v1/metrics` prefix and declares its route as `/metrics`. `GET /api/v1/metrics` answers
> `404`.

---

## Authentication

Authentication is always required — there is no unauthenticated mode for this endpoint. Provide a
valid `Authorization: Bearer <token>` header. Without a valid token the endpoint returns HTTP `401`.

### Generating a token for Prometheus

Create a service account token as an admin:

```bash
curl -X POST https://your-server/api/v1/auth/service-account \
  -H "Authorization: Bearer <your-admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"label": "prometheus", "scopes": ["read:*"]}'
```

The response contains the token. It defaults to a one-year lifetime (`expires_at` accepts an ISO
datetime to shorten it) and can be revoked later from the API token list. A session JWT copied from
the browser also works, but expires with the session.

`CB_API_TOKEN` is deprecated and is **not** a working scrape credential: a request presenting it as a
bearer token is rejected with `401` unless `CB_LEGACY_AUTH=true` is set on the backend. It is retained only for
backward compatibility and has no scheduled removal release — use a service account instead.

---

## Prometheus Scrape Configuration

```yaml
scrape_configs:
  - job_name: 'circuit-breaker'
    static_configs:
      - targets: ['your-server:80']
    metrics_path: '/api/v1/metrics/metrics'
    authorization:
      credentials: '<your-service-account-token>'
```

Use the port you published the app on: `CB_PORT` (default `80`) for HTTP or `CB_PORT_HTTPS`
(default `443`) for HTTPS. `8080` and `8443` are the container-internal ports and are not reachable
from outside the container.

---

## Full Metrics Reference

### App Metadata

| Metric | Type | Labels | Description |
|---|---|---|---|
| `circuitbreaker_info` | Info | `version` | Circuit Breaker application version |

### Inventory Counts

| Metric | Type | Labels | Description |
|---|---|---|---|
| `circuitbreaker_hardware_total` | Gauge | — | Total hardware nodes in inventory |
| `circuitbreaker_compute_units_total` | Gauge | `kind` | Compute units grouped by kind (`vm`, `container`) |
| `circuitbreaker_services_total` | Gauge | — | Total services in inventory |
| `circuitbreaker_services_by_status_total` | Gauge | `status` | Services grouped by operational status. One series per status: `running`, `stopped`, `degraded`, `maintenance` (zero-filled) |
| `circuitbreaker_storage_items_total` | Gauge | `kind` | Storage items grouped by kind (`disk`, `pool`, `dataset`, `share`) |
| `circuitbreaker_storage_capacity_gb_total` | Gauge | — | Sum of all configured storage capacity in GB |
| `circuitbreaker_storage_used_gb_total` | Gauge | — | Sum of all reported storage usage in GB |
| `circuitbreaker_networks_total` | Gauge | — | Total network segments |
| `circuitbreaker_hardware_clusters_total` | Gauge | — | Total hardware clusters defined |
| `circuitbreaker_external_nodes_total` | Gauge | `provider`, `kind` | External nodes grouped by provider and kind |
| `circuitbreaker_misc_items_total` | Gauge | — | Total miscellaneous items |
| `circuitbreaker_docs_total` | Gauge | — | Total documentation entries |
| `circuitbreaker_users_total` | Gauge | — | Total registered users |
| `circuitbreaker_tags_total` | Gauge | — | Total unique tags |
| `circuitbreaker_service_dependencies_total` | Gauge | — | Total service-to-service dependency edges |
| `circuitbreaker_audit_log_entries_total` | Gauge | `level`, `category` | Audit log entries grouped by level and category |

### Per-Resource State

These follow the [kube-state-metrics](https://github.com/kubernetes/kube-state-metrics) enum state pattern: one series is emitted per `{resource × possible_state}` combination. The active state receives value `1`, all inactive states receive `0`. This makes alerting on specific states straightforward.

| Metric | Type | Labels | Description |
|---|---|---|---|
| `circuitbreaker_service_status` | Gauge | `name`, `slug`, `environment`, `status` | Current status of each service. One series per service per status (`running`, `stopped`, `degraded`, `maintenance`); value is `1` for the active status, `0` for all others |
| `circuitbreaker_hardware_memory_configured_gb` | Gauge | `name`, `role` | Configured memory per hardware node in GB (omitted if not set) |
| `circuitbreaker_compute_unit_memory_configured_mb` | Gauge | `name`, `kind` | Configured memory per compute unit in MB (omitted if not set) |
| `circuitbreaker_compute_unit_cpu_cores_configured` | Gauge | `name`, `kind` | Configured CPU cores per compute unit (omitted if not set) |
| `circuitbreaker_storage_capacity_gb` | Gauge | `name`, `kind` | Configured capacity per storage item in GB (omitted if not set) |
| `circuitbreaker_storage_used_gb` | Gauge | `name`, `kind` | Reported used space per storage item in GB (omitted if not set) |

---

### Service-objective series

The tables above are point-in-time gauges rebuilt from the database on every scrape. These are
**process-lifetime** counters and gauges, held in a separate registry so a scrape does not reset
them, and appended to the same exposition. They are the measurement source behind the
[1.0.0 service objectives](release/1.0.0-service-objectives.md).

| Metric | Type | Labels | Description |
|---|---|---|---|
| `circuitbreaker_http_requests_total` | Counter | `method`, `route`, `status_class` | HTTP requests served. The availability indicator |
| `circuitbreaker_http_request_duration_seconds` | Histogram | `method`, `route` | Request duration. Buckets are `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0` — `0.5` is a bucket edge because the latency objective is stated at p95 < 500 ms |
| `circuitbreaker_health_state` | Gauge | `state` | One-hot: `1` for the current state, `0` for the others. Every state (`starting`, `ready`, `degraded`, `not_ready`, `stopping`) is always present, so an alert fires on a value rather than on a missing label |
| `circuitbreaker_write_admission_rejections_total` | Counter | `health` | Mutating requests refused because readiness could not serve them safely, by the state that refused |
| `circuitbreaker_background_job_runs_total` | Counter | `job`, `outcome` | Background job executions. The `skipped_not_owner` outcome makes single-owner execution observable rather than merely asserted |
| `circuitbreaker_process_uptime_seconds` | Gauge | — | Seconds since this process finished importing |

**Cardinality is bounded by construction.** `route` is the route *template* the request matched
(`/api/v1/hardware/{hardware_id}`), never the raw path — which would carry ids and grow without
limit. A request that matched no route collapses to the single value `unmatched`. Status is bucketed
into a class rather than exposed per code.

---

## Example PromQL Queries

```promql
# Services currently stopped or degraded
circuitbreaker_service_status{status=~"stopped|degraded"} == 1

# Count of running services
sum(circuitbreaker_service_status{status="running"} == 1)

# Service count by environment
sum by (environment) (circuitbreaker_service_status{status="running"} == 1)

# Storage utilization ratio per item (requires both capacity and usage to be set)
circuitbreaker_storage_used_gb / circuitbreaker_storage_capacity_gb

# Overall storage fill percentage
sum(circuitbreaker_storage_used_gb_total) / sum(circuitbreaker_storage_capacity_gb_total) * 100

# Total configured RAM across all hardware nodes (GB)
sum(circuitbreaker_hardware_memory_configured_gb)

# Total configured RAM across all compute units (GB, converted from MB)
sum(circuitbreaker_compute_unit_memory_configured_mb) / 1024

# Compute units per kind
circuitbreaker_compute_units_total

# Services without a "running" status (potentially unhealthy)
circuitbreaker_services_total - sum(circuitbreaker_service_status{status="running"} == 1)
```

---

## Grafana Panel Suggestions

| Panel | PromQL |
|---|---|
| **Service status overview** (stat panel) | `sum by (status) (circuitbreaker_service_status == 1)` |
| **Degraded/stopped services** (alert panel) | `sum(circuitbreaker_service_status{status=~"stopped\|degraded"} == 1)` |
| **Storage utilization** (gauge panel) | `sum(circuitbreaker_storage_used_gb_total) / sum(circuitbreaker_storage_capacity_gb_total) * 100` |
| **Inventory totals** (stat panels) | `circuitbreaker_hardware_total`, `circuitbreaker_services_total`, `circuitbreaker_compute_units_total` |
| **RAM by host** (bar chart) | `circuitbreaker_hardware_memory_configured_gb` |
| **Storage by item** (bar chart) | `circuitbreaker_storage_capacity_gb` |

---

## Implementation Notes

- **No global state:** A fresh `CollectorRegistry` is created per scrape request. There are no background threads or process-level metric accumulators. Every scrape reflects the current database state.
- **DB-backed, not push-based:** Metrics are queried on demand from the Circuit Breaker PostgreSQL database. They represent point-in-time inventory values, not counters that accumulate over time.
- **Null safety:** Per-resource metrics (memory, CPU, capacity, usage) are only emitted for resources where the value is explicitly configured. Resources with null values are silently omitted to avoid misleading zero values.
- **OpenAPI schema:** The endpoint is excluded from the Circuit Breaker OpenAPI/Swagger UI (`include_in_schema=False`) because it returns plain text, not JSON.
