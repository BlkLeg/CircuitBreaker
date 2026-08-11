# Reliability, Quality, and Capacity — Sprint Implementation Slices

**Companion spec:** [06-reliability-quality-capacity.md](./06-reliability-quality-capacity.md)
**Status:** Ready for test and platform planning

## Standalone slice plans

- [REL-1 — Delivery and transactions](./slices/rel-1-delivery-transactions.md)
- [REL-2 — Bounds, retention, and observability](./slices/rel-2-bounds-retention-observability.md)
- [REL-3 — Process, proxy, and recovery faults](./slices/rel-3-process-proxy-recovery.md)
- [REL-4 — Coverage and critical-path depth](./slices/rel-4-coverage-critical-path.md)
- [REL-5 — Browser and test infrastructure](./slices/rel-5-browser-test-infrastructure.md)
- [REL-6 — Load datasets and baselines](./slices/rel-6-load-datasets-baselines.md)
- [REL-7 — Limits and soak gates](./slices/rel-7-limits-soak.md)

## Slice REL-1 — Delivery and transaction contracts

**Requirements:** REL-01, REL-02, REL-03, REL-04, REL-06
**Depends on:** SRV worker inventory

- [ ] Inventory jobs, agent commands, NATS subjects, database writes, leases, and audit writes.
- [ ] Define transaction boundary, idempotency key, retry, ordering, replay, and dead-letter semantics.
- [ ] Add multi-process advisory-lock/migration tests and duplicate/reordered/delayed/replayed frame tests.
- [ ] Define and instrument reject/queue/degrade/retry behavior for Redis/NATS loss.
- [ ] Serialize audit writes and test verification/repair under concurrent load.

**Verification:** Fault matrix reconciles logical effects and exposes every rejected, queued, retried,
deduplicated, or dead-lettered item.

## Slice REL-2 — Bounds, retention, and observability

**Requirements:** REL-05, REL-07, REL-08, REL-11
**Depends on:** REL-1 where delivery queues are involved

- [ ] Define limits and retention for telemetry, audit, events, scans, uploads, logs, queues, and spools.
- [ ] Implement backpressure/rejection before disk or memory becomes unsafe.
- [ ] Replace broad swallowed exceptions with classified, rate-limited logs and metrics.
- [ ] Eliminate or register un-awaited coroutine, deprecation, and retry-amplification warnings.
- [ ] Document privacy/egress behavior during partial connectivity and test it.

**Verification:** Saturation and dependency faults remain bounded, observable, and privacy compliant.

## Slice REL-3 — Process, proxy, and recovery faults

**Requirements:** REL-09, REL-10
**Depends on:** SRV-3 and SRV-7 designs

- [ ] Build proxy topology fixtures covering trusted/untrusted forwarding, HTTPS, cookies, WebSockets,
  URLs, and rate-limit identity.
- [ ] Add SIGTERM, lease handoff, rolling restart, reconnect storm, and dependency recovery faults.
- [ ] Reconcile notifications, monitors, ingest, audit, and jobs before and after each fault.

**Verification:** All documented topologies and grace-period behaviors match SRV/SEC contracts.

## Slice REL-4 — Coverage and critical-path depth

**Requirements:** REL-13, REL-14, REL-15, REL-16
**Depends on:** Stable suite inventory

- [ ] Measure backend/frontend line and branch coverage with documented exclusions.
- [ ] Define 90%+ branch gates for named critical paths and an honest repo-wide backend ratchet.
- [ ] Add frontend critical client/state thresholds.
- [ ] Pilot mutation tests for auth/tenant/protocol and property/fuzz suites for parsers, CIDRs, URLs,
  frames, imports, and backup manifests.
- [ ] Establish score/corpus budgets, deterministic seeds, and failure triage.

**Verification:** Known representative mutants and malformed inputs are caught; thresholds cannot be
bypassed by subset runs.

## Slice REL-5 — Browser and test infrastructure

**Requirements:** REL-17, REL-18, REL-19, REL-20
**Depends on:** ACC-1 harness

- [ ] Add production-build Playwright projects for supported browsers and viewports.
- [ ] Add deterministic visual fixtures/baselines for critical pages and states.
- [ ] Enforce issue/owner/reason/expiry metadata for skips/xfails and fail unexpected warnings.
- [ ] Shard with stable seed/reporting and retain JUnit, coverage, logs, traces, screenshots, and
  container diagnostics.

**Verification:** A seeded failure can be reproduced locally and diagnosed from CI artifacts alone.

## Slice REL-6 — Baseline datasets and load models

**Requirements:** REL-21, REL-22, REL-23, REL-24
**Depends on:** RC target profiles

- [ ] Build reproducible 1k, 10k, and target-max inventory/edge datasets.
- [ ] Build 10, 100, and target-max agent simulators with reconnect and spool behavior.
- [ ] Define mixed telemetry/discovery/monitor/notification/integration workloads.
- [ ] Instrument API p50/p95/p99, fan-out, queue lag, DB pools/locks, CPU/RAM/disk, frontend startup,
  bundle, large tables, topology FPS, and reconnect.
- [ ] Run baselines on controlled hardware and publish raw inputs plus results.

**Verification:** An independent runner can reproduce results within the approved variance band.

## Slice REL-7 — Limits and soak gates

**Requirements:** REL-12, REL-25, REL-26
**Depends on:** REL-2 and REL-6

- [ ] Convert baselines into supported limits, warnings, backpressure, and rejection behavior.
- [ ] Run 24-hour pre-RC and 7-day RC soaks with retention and backup jobs enabled.
- [ ] Track memory/disk growth, queue lag, locks, latency, errors, reconnects, and recovery time.
- [ ] Publish limits and validate configuration/runtime enforcement before overload.

**Verification:** Soaks meet RC objectives with no unexplained trend, leak, silent loss, or unbounded work.
