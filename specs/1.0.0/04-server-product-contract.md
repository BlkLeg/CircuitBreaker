# Server Product Contract Specification

**Status:** Draft; architecture decisions required

## Outcome

Circuit Breaker is a headless-capable control-plane server with an explicit service topology, safe
lifecycle behavior, stable administration surface, and observable failure modes. The web UI is its
first client, not an undocumented prerequisite.

## Logical contract

```text
Web UI / cb CLI / documented clients
                 |
      versioned control-plane API
                 |
 API services + dedicated worker services
                 |
PostgreSQL | Redis | NATS | file/object storage
                 |
      outbound cb-agent fleet
```

PostgreSQL is the source of truth. Redis and NATS are disposable coordination layers unless a
separately documented feature promises durable delivery. Uploads and object storage are part of the
backup contract.

## Requirements

| ID | Requirement | Acceptance |
|---|---|---|
| SRV-01 | API and workers start without the bundled frontend, weather/geocoding calls, or UI-only assumptions; OpenAPI and machine-readable error contracts are published. | Headless artifact acceptance completes all admin and health tasks without a browser or frontend service. |
| SRV-02 | Worker ownership is unambiguous across discovery, notifications, telemetry, integrations, monitor scheduling, cleanup/rollups, and agent dispatch. Mixed in-process/dedicated modes cannot duplicate work. | Multi-process tests prove single logical execution, ownership, leases, and idempotency. |
| SRV-03 | Liveness, startup, readiness, dependency, and degraded health are distinct; readiness rejects writes when they cannot be served safely. | Dependency fault matrix asserts endpoint state and orchestrator behavior for each failure. |
| SRV-04 | SIGTERM drains safely; leases hand off; rolling restart and reconnect storms do not duplicate notifications, monitor executions, ingest, or jobs. | Fault-injection tests reconcile counts and durable state before and after termination. |
| SRV-05 | Configuration has one precedence order across file, environment, database, and CLI; `cb config validate` detects invalid combinations and diagnostics redact secrets. | Contract tests cover every source and conflict; sample configs validate in CI. |
| SRV-06 | Scoped API tokens/service accounts support creation, least privilege, rotation, revocation, expiry, and audit. Routine health, migrations, backup/restore, user/token, agent, and diagnostics work through `cb` without browser sessions. | Role matrix and CLI journeys pass in headless mode. |
| SRV-07 | Small, medium, and fleet profiles publish minimum/recommended CPU, RAM, disk, database sizing, and bounded queues/retention/uploads/logs/spools. | Values derive from REL-21 through REL-26 and enforce safe rejection/backpressure. |
| SRV-08 | Mono container is labeled single-node appliance; split services are production/scalable mode. HA is either explicitly unsupported or proven under RC-03. | Installation docs and runtime warnings cannot imply unsupported topology. |
| SRV-09 | Stable Prometheus metrics, structured logs, correlation/request/job IDs, redaction, example dashboards/alerts, and support bundles are provided. | Schema/label tests prevent accidental cardinality or secret leakage; a support bundle is generated during failure injection. |
| SRV-10 | Secure remote access is documented for proxies, trusted headers, TLS ownership/renewal, firewall ports, agent outbound endpoints, and air-gap limitations. | Every documented topology passes proxy/auth/cookie/WebSocket/rate-limit tests. |

## Compatibility

The API version, migration policy, server/agent window, CLI/server window, deprecation process, and
upgrade order are governed by RC-04. A component must reject an unsafe combination with a stable,
actionable error; silent partial compatibility is not permitted.

## Non-goals

- A second parallel “server edition.”
- Making Redis or NATS authoritative by accident.
- Calling a process ready merely because it answers HTTP.
