# SRV-5 — Headless Administration and Identity

**Requirement:** SRV-06
**Depends on:** SRV-1, SEC endpoint/auth slices

## Primary files

- API-token/auth models, migration `0028_api_tokens.py`, auth/admin APIs
- `deploy/cli/cb`, backup/migration/config/agent services
- Audit infrastructure and headless deployment tests

## Build sequence

1. Define service-account/token model: named owner, hashed secret, scopes, optional tenant, expiry,
   last use, rotation overlap, revocation, rate policy, and audit. Never store retrievable raw tokens.
2. Add forward migration and API/CLI create/list/rotate/revoke flows with one-time secret display.
3. Implement `cb` commands for health, config validation, migration status/apply, backup/restore,
   users/tokens, agent status, and diagnostics. Use stable exit codes and optional JSON.
4. Separate local privileged operations from remote API operations; validate target TLS and avoid
   putting secrets in argv, shell history, logs, or process listings.
5. Add role/tenant, expired/revoked/rotated, concurrent rotation, audit, output-redaction, network
   failure, and fully headless journeys.

## Verification and done

Test migrations on fresh/upgrade databases, backend auth matrices, CLI unit/integration, and installed
headless artifact journeys. Done means routine and recovery administration works without browser
sessions and every credential operation is least-privilege and audited.
