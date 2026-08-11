# SRV-2 — Worker Topology and Ownership

**Requirement:** SRV-02
**Depends on:** SRV-1

## Primary files

- `apps/backend/src/app/main.py` and `apps/backend/src/app/workers/`
- NATS/Redis clients and worker audit/health files
- `deploy/systemd/circuitbreaker-worker@.service`, target/setup scripts, Compose definitions

## Build sequence

1. Inventory every loop/job in `main.py` and `workers/`; classify API-owned, dedicated worker, cron,
   or obsolete. Include integrations, analytics, rollups, retention, and probe dispatch—not only the
   five installed worker units.
2. Define one production owner per function plus queue/durable, lease, idempotency, concurrency,
   retry/dead-letter, readiness, and drain contract.
3. Replace ambiguous `CB_RUN_INPROCESS_WORKERS` combinations with an explicit topology mode. Refuse or
   safely disable duplicate owners when mixed configuration occurs.
4. Align worker entrypoint type map, systemd units, installer, containers, and documentation.
5. Expose per-worker readiness, last success, lag, queue depth, current lease/work, and drain state
   without high-cardinality metrics.
6. Add multi-process tests that start duplicate/mixed owners, kill lease holders, replay messages, and
   reconcile logical side effects.

## Verification and migration

Run worker/service tests plus native and Compose topology acceptance. Upgrades must stop old owners
before enabling new ones and preserve durable queue identity. Done means every background function has
exactly one documented production owner and accidental mixed mode cannot duplicate effects.
