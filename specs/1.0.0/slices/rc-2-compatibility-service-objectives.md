# RC-2 — Compatibility and Service Objectives

**Requirements:** RC-04, RC-05, RC-06
**Type:** Product/operations contract slice
**Depends on:** RC-1

## Objective

Define testable compatibility, availability, recovery, retention, and capacity promises before the
release test program treats them as gates.

## Repository touchpoints

- API version prefix and health behavior in `apps/backend/src/app/main.py`
- Migrations in `apps/backend/migrations/versions/` and agent protocol in `apps/agent/internal/`
- Backup/restore commands and `docs/backup-restore.md`
- Deployment health checks under `deploy/`, Compose files, and packaging service definitions
- Metrics/telemetry docs and performance specifications

## Implementation tasks

1. Build compatibility tables for API clients, database schema/source release, server/agent, and
   CLI/server. Include supported, temporarily degraded, rejected, and upgrade-only combinations.
2. Define upgrade ordering, minimum source version, downgrade policy, and user-visible response to an
   incompatible agent or client. Unsafe combinations must fail explicitly.
3. Define deprecation stages: announcement, telemetry/warning, minimum window, removal, and emergency
   security exception.
4. Define startup, liveness, readiness, dependency health, and degraded service in user terms. Name
   which operations remain safe in each state.
5. Define SLO indicators and windows for API, monitoring execution, notification delivery, agent
   presence, and background processing. Avoid targets that current instrumentation cannot measure.
6. Propose RPO/RTO, backup retention, application data retention, and scale ceilings; link each value
   to ACC/REL evidence needed for approval.

## Verification

- Walk at least one allowed and one rejected example through every compatibility table.
- Trace each SLO to a stable metric and alert; trace RPO/RTO to a recovery procedure.
- Confirm the acceptance matrix contains every source-version and deployment-mode combination.
- Reject circular definitions such as “ready when the readiness endpoint is green.”

## Migration and rollback

No database migration belongs in this slice. If an existing release violates the chosen compatibility
window, create explicit implementation work and preserve the current behavior until its migration and
user communication are approved.

## Definition of done

RC-04 through RC-06 are approved, measurable, and fully linked to acceptance evidence rather than
aspirational prose.
