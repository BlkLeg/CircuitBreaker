# REL-2 — Bounds, Retention, and Failure Observability

**Requirements:** REL-05, REL-07, REL-08, REL-11
**Depends on:** REL-1 for queue semantics

## Build sequence

1. Inventory telemetry, audit, events, monitor history, scans/findings, uploads, logs, queues, caches,
   backups, and agent spools with producer rate, retention, maximum size, and cleanup owner.
2. Define hard/soft limits and backpressure/rejection behavior. Reserve disk headroom for recovery,
   database WAL, migrations, and a final diagnostic bundle.
3. Make retention jobs incremental, indexed, resumable, tenant-aware if applicable, observable, and
   protected from deleting legal/audit or last-valid-backup data.
4. Replace broad listener/stream exception swallowing with stable error class, bounded retry, sampled
   or rate-limited log, metric, correlation, and terminal/degraded state.
5. Fail new un-awaited coroutine warnings; inventory deprecations with upstream removal, owner, and
   expiry. Remove warnings that invalidate intended async execution.
6. Map outbound privacy/egress and retry behavior during partial connectivity; prevent request storms
   and undisclosed fallback providers.

## Verification and done

Saturate each bounded store, stop cleanup, recover after downtime, inject repeated exceptions, and
inspect disk/memory/log growth. Run retention suites against PostgreSQL-sized data. Done means growth
is bounded, cleanup is safe/resumable, and every failure is visible without a log storm.
