# REL-7 — Supported Limits and Soak Gates

**Requirements:** REL-12, REL-25, REL-26
**Depends on:** REL-2, REL-6, backup/retention gates

## Build sequence

1. Convert measured knees and saturation behavior into conservative supported limits for inventory,
   edges, agents, scan concurrency, monitors, queues, uploads, retention, database connections, and disk.
2. Add configuration validation, warning thresholds, admission control, queue bounds, backpressure, and
   stable retry-after/error responses before resource exhaustion.
3. Define 24-hour pre-RC and 7-day RC workloads with representative agents, browsers, integrations,
   monitoring, notifications, retention, backups, reconnects, and scheduled controlled faults.
4. Track latency/errors, CPU/RAM/file descriptors/goroutines/tasks, DB connections/locks/WAL, queue lag,
   disk by category, duplicate/lost effects, cleanup, backup RPO/RTO, and recovery time as time series.
5. Set leak/growth/error/latency budgets and automatic abort conditions that preserve diagnostics.
6. Analyze trends rather than endpoints; any unexplained monotonic growth or warning is a failure.

## Verification and done

Overload one unit beyond each limit and prove graceful rejection plus recovery, then pass the full soak
on the final RC configuration. Publish limits and sizing from the same evidence. Done means no
unbounded queue/scan/render/disk path and no unexplained 24-hour or 7-day degradation remains.
