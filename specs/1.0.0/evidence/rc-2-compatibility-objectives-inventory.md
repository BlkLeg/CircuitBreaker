# RC-2 Compatibility and Service Objectives Inventory

**Status:** Draft inventory from repository scan
**Generated:** 2026-08-10
**Verification command:** `rg -n "compat|compatible|deprecat|upgrade|migration|RPO|RTO|SLO|liveness|readiness|startup|degraded|backup|retention|scale|availability|health" README.md docs packaging deploy apps/backend/src apps/frontend/src .github specs/1.0.0`

| Contract topic | Current source | Current evidence | RC-2 disposition | Owner | Acceptance row |
|---|---|---|---|---|---|
| API version prefix | `apps/backend/src/app/main.py` routes under `/api/v1` | Product UI/API use `/api/v1`; no third-party contract tests | Product API only; stable public API deferred | Architecture owner | RC-04, GOV-07 |
| Health endpoint | `apps/backend/src/app/main.py` `/api/v1/health` | Returns server state, ready boolean, version, uptime, DB/Redis checks | Current liveness/readiness split is incomplete; SRV-03 owns runtime split | Operations owner | RC-05, SRV-03 |
| Server lifecycle state | `apps/backend/src/app/core/server_state.py` | `starting`, `ready`, `stopping` states exist | Use as current primitive for startup/stopping semantics | Operations owner | SRV-03 |
| Docker healthcheck | `docker-compose.yml` | Calls `/api/v1/health` | Must be reconciled with future liveness/readiness endpoints | Operations owner | SRV-03 |
| Native healthcheck timer | `deploy/scripts/healthcheck.sh` | Restarts backend if `/api/v1/health` fails | Liveness watchdog only; not user readiness | Operations owner | SRV-03 |
| Automatic migrations | `apps/backend/src/app/main.py`, Alembic migrations | Startup applies migrations; audit found upgrade gaps | Direct source floor is `0.3.5` until ACC-12 expands | Release owner | RC-04, ACC-12 |
| Upgrade docs | `docs/installation/upgrading.md` | Documents `cb update`, compose pull/up, and rollback warning | Link to RC-2 compatibility policy and backup requirement | Release owner | RC-04, ACC-12 |
| Backup export/import | `docs/backup-restore.md`, `apps/backend/src/app/api/admin.py` | User docs and API exist; RPO/RTO evidence pending | Candidate RPO 24h and RTO 4h until ACC evidence passes | Operations owner | RC-06, ACC-14, ACC-15 |
| Backup retention defaults | `apps/backend/src/app/api/admin_db.py` | Local default 7, S3 default 30 in settings response | Candidate defaults documented; prune evidence pending | Operations owner | RC-06, REL-2 |
| Metrics endpoint | `docs/metrics.md`, `apps/backend/src/app/api/metrics.py` | Prometheus text endpoint exists | Metrics schema beta; not stable public integration contract | Product owner | RC-04, SRV-07 |
| Agent compatibility | `apps/agent`, `apps/backend/src/app/api/ws_agents.py` | Agent protocol exists; upgrade matrix pending | Same-artifact 1.0 agent supported candidate; older agents upgrade-only/rejected | Agent owner | RC-04, AGT-1, AGT-7 |
| CLI compatibility | `deploy/cli/cb`, installer docs | CLI exists for local admin workflows | Same-artifact CLI supported candidate; older CLI degraded/rejected for mutations | Operations owner | RC-04, SRV-5 |
| Scale ceilings | `specs/1.0.0/06-reliability-quality-capacity.md` | REL work defines needed load/soak gates | Small/medium candidate ceilings only; fleet deferred | Architecture owner | RC-06, REL-21-REL-26 |

## Verification examples

- Allowed: fresh 1.0 install reaches ready and runs core journeys.
- Allowed candidate: `0.3.5` to 1.0 upgrade passes migrations and reconciliation.
- Rejected: older binary starts against a 1.0 schema.
- Rejected/degraded: older CLI attempts mutating command against 1.0 server.
- Rejected/upgrade-only: unproven older agent connects to 1.0 server.
