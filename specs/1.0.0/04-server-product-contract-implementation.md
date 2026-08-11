# Server Product Contract — Sprint Implementation Slices

**Companion spec:** [04-server-product-contract.md](./04-server-product-contract.md)
**Status:** Ready for architecture decomposition

## Standalone slice plans

- [SRV-1 — Headless process boundary](./slices/srv-1-headless-process.md)
- [SRV-2 — Worker topology](./slices/srv-2-worker-topology.md)
- [SRV-3 — Health and lifecycle](./slices/srv-3-health-lifecycle.md)
- [SRV-4 — Configuration contract](./slices/srv-4-configuration-contract.md)
- [SRV-5 — Headless administration](./slices/srv-5-headless-administration.md)
- [SRV-6 — Resources and deployment](./slices/srv-6-resources-deployment.md)
- [SRV-7 — Observability and remote operation](./slices/srv-7-observability-remote.md)

## Slice SRV-1 — Headless process boundary

**Requirements:** SRV-01
**Depends on:** RC-03 and RC-04 decisions

- [ ] Inventory UI-only imports, startup calls, routes, static assets, weather/geocoding, and bundled
  reverse-proxy assumptions in API and workers.
- [ ] Define supported process commands for API and each worker role.
- [ ] Make frontend serving optional without weakening API authentication or health behavior.
- [ ] Publish OpenAPI and a stable machine-readable error envelope.
- [ ] Add headless startup and administration acceptance using the production artifact.

**Verification:** API/workers and required admin journeys operate with frontend and UI-only outbound
calls disabled.

## Slice SRV-2 — Worker topology and ownership

**Requirements:** SRV-02
**Depends on:** SRV-1 process model

- [ ] Map discovery, notifications, telemetry, integrations, monitoring, cleanup/rollups, and agent
  dispatch to named process owners.
- [ ] Define lease, transaction, idempotency, retry, and dead-letter behavior per worker.
- [ ] Detect or prevent simultaneous in-process and dedicated ownership.
- [ ] Expose worker readiness, lag, last success, queue depth, and drain state.
- [ ] Add multi-process duplicate-execution and lease-handoff tests.

**Verification:** Starting redundant/mixed workers either fails clearly or preserves exactly-once
logical effects according to the documented contract.

## Slice SRV-3 — Health and graceful lifecycle

**Requirements:** SRV-03, SRV-04
**Depends on:** SRV-2

- [ ] Define separate startup, liveness, readiness, dependency, and degraded states.
- [ ] Map database, Redis, NATS, storage, and downstream failures to safe read/write behavior.
- [ ] Implement SIGTERM drain ordering, job lease handoff, and connection shutdown deadlines.
- [ ] Add rolling restart, process kill, reconnect storm, migration coordination, and duplicate/loss
  reconciliation tests.

**Verification:** Orchestrators stop routing unsafe writes, termination stays within grace periods,
and effect counts reconcile after recovery.

## Slice SRV-4 — Configuration contract

**Requirements:** SRV-05
**Depends on:** SRV-1

- [ ] Inventory settings from file, environment, database, CLI, and defaults.
- [ ] Define one precedence order, type/constraint schema, secret handling, and restart requirements.
- [ ] Implement `cb config validate` and redacted effective-configuration diagnostics.
- [ ] Validate repository examples and conflict/error cases in CI.

**Verification:** Every setting has one canonical name/type/source rule; diagnostics reveal no secret.

## Slice SRV-5 — Headless administration and identity

**Requirements:** SRV-06
**Depends on:** SRV-1, SEC-3, SEC-4

- [ ] Design scoped service accounts/API tokens with expiry, rotation, revocation, and audit.
- [ ] Implement CLI workflows for health, config, migrations, backup/restore, users/tokens, agent
  status, and diagnostics.
- [ ] Ensure noninteractive output has stable exit codes and machine-readable mode.
- [ ] Add least-privilege role and revoked/expired token journeys without browser sessions.

**Verification:** A clean headless deployment can be routinely operated and recovered through `cb`.

## Slice SRV-6 — Resource profiles and deployment modes

**Requirements:** SRV-07, SRV-08
**Depends on:** REL performance baselines, RC-03 HA decision

- [ ] Define small, medium, and fleet workload profiles and translate results into sizing guidance.
- [ ] Add configuration limits/backpressure for queues, retention, uploads, logs, and spools.
- [ ] Label mono as single-node appliance and split services as production/scalable mode.
- [ ] Implement HA validation or explicit unsupported-topology detection and documentation.

**Verification:** Documentation, installers, runtime diagnostics, and observed limits describe the
same supported deployment boundary.

## Slice SRV-7 — Observability and remote operations

**Requirements:** SRV-09, SRV-10
**Depends on:** SRV-2, SRV-3

- [ ] Define stable metrics and structured log fields with request/job/agent correlation IDs.
- [ ] Bound metric cardinality and add secret/PII redaction tests.
- [ ] Provide example dashboards, actionable alerts, and support-bundle generation.
- [ ] Document and test reverse proxies, trusted headers, TLS/renewal, firewall ports, outbound agent
  endpoints, WebSockets, cookies, rate limits, and air-gap limitations.

**Verification:** An injected failure is detected, correlated, bundled, and diagnosed using only the
published operations surface in every supported topology.
