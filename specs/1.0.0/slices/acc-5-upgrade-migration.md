# ACC-5 — Upgrade, Interrupted Installation, and Migration

**Requirements:** ACC-12, ACC-13, ACC-21
**Depends on:** ACC-1, RC-04

## Primary touchpoints

- `apps/backend/migrations/`, `docker/20-migrate.sh`, migration startup coordination
- `deploy/setup.sh`, native package upgrade scripts, container release workflow
- `apps/backend/scripts/migrate_sqlite_to_pg.py`, upgrade documentation

## Build sequence

1. Create immutable source-version fixtures from every supported prior release with representative
   users, tenant data, inventory, topology, integrations/secrets, monitors/history, agents, uploads,
   audit, and queued work.
2. Measure the full Alembic chain on realistic 1k/10k/target datasets and explicitly inspect migration
   0100+ index locks, disk amplification, DB connections, downtime, and worker compatibility.
3. Upgrade in the documented server/database/agent order for native, mono, and split modes. Verify
   schema head, runtime version, durable data, secret usability, agents, and API compatibility.
4. Inject termination before/after package replacement, migration lock/acquire/commit, service restart,
   and agent update. Define whether each checkpoint resumes, rolls back, or requires restore.
5. Test concurrent API/worker startup and advisory migration locking. Exactly one migrator may act.
6. Reject incompatible downgrade/schema/binary combinations with actionable recovery instructions.

## Verification

Unit tests of migration SQL are insufficient. Run `alembic upgrade` from actual source schemas using
the production role and exact packaged entrypoint, then query data invariants and execute core journeys.
Retain migration logs, locks/timing, schema checksum, before/after counts, and artifact digests.

## Done

Every promised upgrade path and interruption checkpoint has a proven recovery outcome within declared
downtime/resources; no second in-process migration race or silent partial state remains.
