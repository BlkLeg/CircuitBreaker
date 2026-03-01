# Prometheus Metrics

Circuit Breaker exposes an inventory metrics endpoint in the [Prometheus text exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/).
You can scrape it directly from Prometheus, Grafana Alloy, the OpenTelemetry Collector, or any compatible agent.

## Endpoint

```
GET /api/v1/metrics
```

Returns `text/plain; version=0.0.4; charset=utf-8` — the standard Prometheus scrape format.

> **Note:** The endpoint is intentionally placed under `/api/v1/` (not at the root `/metrics`) to avoid conflicts with Circuit Breaker's frontend catch-all route.

---

## Authentication

The metrics endpoint follows the same authentication model as the rest of the API:

| Circuit Breaker auth setting | Endpoint access |
|---|---|
| Auth disabled (`auth_enabled = false`) and no `CB_API_TOKEN` set | Public — no token required |
| Auth enabled **or** `CB_API_TOKEN` env var set | Requires a valid `Authorization: Bearer <token>` header |

When auth is required and no token is provided, the endpoint returns HTTP `401`.

### Generating a token for Prometheus

1. Log in to Circuit Breaker and copy a JWT from the browser's local storage (`cb:token`), **or**
2. Set the `CB_API_TOKEN` environment variable on the backend to a static secret and use that value as the bearer token in Prometheus.

Using `CB_API_TOKEN` is recommended for scraping — it never expires and does not require an interactive login.

---

## Prometheus Scrape Configuration

### Without authentication (auth disabled)

```yaml
scrape_configs:
  - job_name: 'circuit-breaker'
    static_configs:
      - targets: ['your-server:8080']
    metrics_path: '/api/v1/metrics'
```

### With authentication (`CB_API_TOKEN` or JWT)

```yaml
scrape_configs:
  - job_name: 'circuit-breaker'
    static_configs:
      - targets: ['your-server:8080']
    metrics_path: '/api/v1/metrics'
    authorization:
      credentials: '<your-cb-api-token-or-jwt>'
```

### Docker Compose — setting `CB_API_TOKEN`

```yaml
services:
  backend:
    environment:
      - CB_API_TOKEN=your-static-secret-here
```

Then use `your-static-secret-here` as the bearer token in the Prometheus scrape config above.

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
| `circuitbreaker_services_by_status_total` | Gauge | `status` | Services grouped by operational status |
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
| `circuitbreaker_service_status` | Gauge | `name`, `slug`, `environment`, `status` | Current status of each service. Value is `1` for the active status, `0` for all others |
| `circuitbreaker_hardware_memory_configured_gb` | Gauge | `name`, `role` | Configured memory per hardware node in GB (omitted if not set) |
| `circuitbreaker_compute_unit_memory_configured_mb` | Gauge | `name`, `kind` | Configured memory per compute unit in MB (omitted if not set) |
| `circuitbreaker_compute_unit_cpu_cores_configured` | Gauge | `name`, `kind` | Configured CPU cores per compute unit (omitted if not set) |
| `circuitbreaker_storage_capacity_gb` | Gauge | `name`, `kind` | Configured capacity per storage item in GB (omitted if not set) |
| `circuitbreaker_storage_used_gb` | Gauge | `name`, `kind` | Reported used space per storage item in GB (omitted if not set) |

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
- **DB-backed, not push-based:** Metrics are queried on demand from the Circuit Breaker SQLite database. They represent point-in-time inventory values, not counters that accumulate over time.
- **Null safety:** Per-resource metrics (memory, CPU, capacity, usage) are only emitted for resources where the value is explicitly configured. Resources with null values are silently omitted to avoid misleading zero values.
- **OpenAPI schema:** The endpoint is excluded from the Circuit Breaker OpenAPI/Swagger UI (`include_in_schema=False`) because it returns plain text, not JSON.
