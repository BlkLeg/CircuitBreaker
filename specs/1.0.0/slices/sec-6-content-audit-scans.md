# SEC-6 — Content, Audit, Destructive Actions, and Scans

**Requirements:** SEC-15, SEC-16, SEC-17, SEC-18
**Priority:** P0
**Depends on:** SEC-3; may overlap SEC-5

## Objective

Prevent active upload execution, make the audit chain concurrency-safe and recoverable, safeguard
destructive operations, and bind the complete security scan set to release artifacts.

## Primary touchpoints

- Upload APIs/services and `apps/backend/tests/test_uploads.py`, `test_upload_root_isolation.py`
- `apps/backend/src/app/core/audit.py`, `audit_chain.py`, `worker_audit.py`
- `apps/backend/src/app/api/admin_audit.py` and destructive admin/service endpoints
- `scripts/security_scan.sh`, `.github/workflows/{security,codeql}.yml`
- Backup/restore, agent, tenant, and discovery bulk-operation surfaces

## Implementation sequence

1. Inventory upload types and serving paths. Choose SVG reject, robust sanitize, or rasterize policy;
   enforce magic-byte/type/size checks, safe filenames/storage roots, download disposition, CSP, and
   no same-origin active execution.
2. Define audit-chain serialization using a database lock/transaction strategy compatible with all
   writers. Make canonical serialization stable and document verification failure semantics.
3. Build a verification/repair command that never silently rewrites evidence. Repair requires
   explicit authorization, backup, report, and an audit event outside the repaired segment.
4. Classify clear-lab, restore-with-wipe, tenant deletion, agent revoke/uninstall, and bulk import by
   impact. Implement authorization, reauthentication/confirmation, preview, cancellation boundary,
   idempotency, backup prerequisite where required, and actor/target/outcome audit.
5. Standardize scanner and suppression metadata across CodeQL, Semgrep, Bandit, Trivy, Checkov,
   Gitleaks, npm audit, pip-audit, Go vulnerability, container, and secret scans.
6. Scan the exact source commit, built containers/packages, and dependency graphs; retain reports by
   digest and fail expired/unowned suppressions.

## Verification

```bash
cd apps/backend
PYTHONPATH=src pytest -q --no-cov tests/test_uploads.py tests/test_upload_root_isolation.py \
  tests/test_audit_actor.py tests/test_audit_actor_extra.py tests/test_worker_audit.py
```

Add malicious SVG/polyglot/path corpus tests, real concurrent PostgreSQL audit writers, tamper and
repair drills, and end-to-end destructive cancellation/recovery. Run the repository security workflow
against the RC artifact set.

## Rollout and rollback

Existing SVGs require inventory and quarantine/migration before serving policy changes. Audit-chain
migrations need backup and verification before/after. Destructive safeguards may break automation;
provide scoped noninteractive confirmation only when the caller supplies explicit authorization and
an idempotency key.

## Definition of done

Active uploads cannot execute, concurrent audit chains cannot fork, destructive operations are
authorized/recoverable/audited, and all scanners are green or carry current RC-08 exceptions.
