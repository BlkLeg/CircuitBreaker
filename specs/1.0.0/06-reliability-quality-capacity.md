# Reliability, Quality, and Capacity Specification

**Status:** Draft

## Outcome

Circuit Breaker behaves predictably under concurrency, duplicated or lost delivery, dependency
failure, and sustained load. Critical paths have risk-weighted test depth, and published limits are
derived from reproducible measurements.

## Data, concurrency, and network reliability

| ID | Requirement | Acceptance |
|---|---|---|
| REL-01 | Define transaction boundaries and idempotency keys for every background job and agent dispatch. | Duplicate invocation produces one logical effect and an observable disposition. |
| REL-02 | Prove advisory-lock and migration coordination across multiple API/worker processes. | Concurrent startup/migration tests cannot corrupt or race schema state. |
| REL-03 | Handle duplicate, reordered, delayed, replayed, malformed, and oversized NATS/agent frames. | Protocol corpus and integration tests prove reject/dedupe/order semantics without crash or amplification. |
| REL-04 | Define Redis/NATS outage behavior per feature as reject, queue, degrade, or retry. | Fault injection detects no silent drop and exposes operator-visible state. |
| REL-05 | Bound telemetry, audit, events, scans, uploads, logs, queues, and agent spool growth. | Retention/backpressure jobs work under load and after downtime; disk ceilings are enforced. |
| REL-06 | Serialize audit-chain writes and provide supported verification/repair. | Concurrent and tamper tests satisfy SEC-16. |
| REL-07 | Replace broad exception swallowing in listeners/streams with classified, rate-limited logs and metrics. | Injected failures are observable without log storms; streams recover or close explicitly. |
| REL-08 | Treat un-awaited coroutine warnings and deprecations as tracked defects. | RC run has no unexplained async/deprecation warnings; future-removal dates have owners. |
| REL-09 | Verify proxy headers, client IP, HTTPS, cookies, WebSocket URLs, and limits in every topology. | Results satisfy SEC-10 and SRV-10. |
| REL-10 | Prove SIGTERM, lease handoff, reconnect storms, rolling restart, and dependency recovery. | Results satisfy SRV-04 and ACC-18 with reconciled effect counts. |
| REL-11 | Define privacy and external-call behavior during partial connectivity. | No undisclosed data egress or retry amplification occurs. |
| REL-12 | Run long-duration API, worker, agent, telemetry, monitor, retention, and backup soak tests. | 24-hour and 7-day gates meet RC-05/RC-06 without unbounded growth or unreconciled loss. |

## Test strategy

| ID | Requirement | Acceptance |
|---|---|---|
| REL-13 | Reach 90%+ branch coverage for auth, RBAC, tenancy, migrations, backup/restore, agent protocol/update, audit, secrets, and destructive admin actions. | Coverage is measured with justified exclusions and cannot regress unnoticed. |
| REL-14 | Establish a repo-wide backend ratchet above the measured 55.42% baseline. | Threshold is based on a full supported suite and increases intentionally. |
| REL-15 | Publish frontend line/branch coverage and critical client/state thresholds. | CI retains reports and fails critical regressions. |
| REL-16 | Apply mutation tests to auth/tenant/protocol validators and property/fuzz tests to parsers, CIDRs, URLs, frame codecs, imports, and backup manifests. | Mutation score/corpus targets and triage rules are approved and repeatable. |
| REL-17 | Add Playwright E2E for routing, cookies/CSRF, WebSockets, responsive behavior, focus, and console/runtime health. | ACC-09 runs from production builds in all supported browsers. |
| REL-18 | Add visual regression for topology, discovery, agents, monitors, settings, auth/OOBE, and empty/error states. | Reviewed desktop/mobile baselines are versioned with deterministic fixtures. |
| REL-19 | Track every skip/xfail with issue, owner, reason, and expiry; fail unexpected warnings. | RC-08 register and test reports reconcile exactly. |
| REL-20 | Shard deterministically and retain JUnit, coverage, logs, traces, screenshots, seeds, and container diagnostics. | Any failed release job is diagnosable from retained artifacts alone. |

## Performance and supported limits

| ID | Requirement | Acceptance |
|---|---|---|
| REL-21 | Benchmark 1k, 10k, and target-maximum inventory entities/edges. | API and UI measurements include p50/p95/p99, graph render/interaction FPS, memory, and failure behavior. |
| REL-22 | Benchmark 10, 100, and target-maximum concurrent agents. | Measures reconnect, fan-out, ingest, queues, DB pools/locks, CPU/RAM, disk, and spool behavior. |
| REL-23 | Benchmark concurrent telemetry, discovery, monitoring, notifications, and integrations. | Workload is reproducible and includes queue lag, fairness, backpressure, and duplicate/loss reconciliation. |
| REL-24 | Measure frontend startup/bundle size, large tables, responsive topology, and reconnect. | Budgets are published and enforced on production bundles. |
| REL-25 | Run 24-hour and 7-day soaks with retention and backups enabled. | Trends remain within approved leak/growth/error budgets and backup RPO/RTO. |
| REL-26 | Publish limits and fail gracefully before exceeding them. | Configuration validation and runtime behavior prevent unbounded queues, scans, rendering, or disk use. |
