# SRV-6 — Resource Profiles and Deployment Modes

**Requirements:** SRV-07, SRV-08
**Depends on:** REL load baselines, RC HA decision

## Build sequence

1. Define small, medium, and fleet workloads in inventory, agents, telemetry rate, monitors, scans,
   notifications, users, retention, and backup size—not vague host labels.
2. Measure API/worker/database/Redis/NATS CPU, RAM, connections, locks, disk growth, and queue/spool
   demand on controlled hardware.
3. Convert measurements into minimum/recommended sizing and enforced limits for queues, retention,
   uploads, logs, concurrent scans, workers, connections, and agent spools.
4. Add validation, warning thresholds, backpressure, and predictable rejection before exhaustion.
5. Label mono as single-node appliance and split services as production/scalable in installers, docs,
   telemetry, and diagnostics. Implement tested HA behavior or reject unsupported multi-instance
   combinations that risk duplicate work.

## Verification and rollout

Reproduce REL datasets, overload each bound, and run 24-hour/7-day soaks with backups and retention.
Configuration upgrades preserve safe defaults and warn before stricter caps affect existing load.
Done means published sizing and deployment claims derive from retained measurements.
