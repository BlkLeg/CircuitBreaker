# SRV-3 — Health and Graceful Lifecycle

**Requirements:** SRV-03, SRV-04
**Depends on:** SRV-2

## Primary files

- Health/readiness routes and lifespan in `apps/backend/src/app/main.py`
- `apps/backend/src/app/workers/`, NATS/Redis/database clients
- `deploy/scripts/healthcheck.sh`, systemd units, Compose health checks

## Build sequence

1. Specify startup, liveness, readiness, dependency, and degraded payload schemas plus cache/timeout
   rules. Readiness must reflect safe reads/writes, not mere process response.
2. Add bounded checks for PostgreSQL, migration/schema compatibility, Redis, NATS, storage, vault, and
   required worker state. Prevent health probes from causing load cascades.
3. Implement shutdown ordering: stop admission/scheduling, mark draining, finish or checkpoint work,
   transfer/release leases, flush durable state, close streams/connections, exit within grace.
4. Handle reconnect storms with jitter/backpressure and reject unsafe work during migration or
   dependency loss.
5. Fault test SIGTERM/SIGKILL, DB/Redis/NATS loss, disk, migration lock, rolling API/worker restarts,
   and mass agent reconnect; reconcile monitors, notifications, telemetry, audit, and jobs.

## Verification and done

Run integration faults through real systemd/Compose health mechanisms. Done means orchestrators route
traffic correctly, SIGTERM drains within the declared budget, and recovery has no unexplained loss or
duplicate effect.
