# SEC-6 Evidence — Content, Audit, Destructive Actions, and Scans

**Requirements:** SEC-15, SEC-16, SEC-17, SEC-18  
**Evidence date:** 2026-08-11  
**Source state:** working tree based on `17fe41d3`

## Summary

SEC-6 implementation is complete for the current source state:

- Active upload policy is reject-by-default for SVG/active markup on user icons, branding logos,
  document images, and profile avatars. Static upload serving also applies `nosniff`, restrictive
  CSP, and attachment disposition for legacy active-content filenames.
- Audit-chain writes share one canonical hash payload, serialize with a process lock plus PostgreSQL
  advisory lock where available, and expose explicit verify/repair behavior. Repair requires
  `REPAIR_AUDIT_CHAIN`, records before/after changes, and appends a separate repair audit event.
- High-impact destructive routes now require explicit confirmation/idempotency/backup headers for
  `clear-lab` and restore-with-wipe. Agent revoke/delete produce explicit warning audit events.
- Scanner suppressions are represented in
  `specs/1.0.0/release-control/security-suppressions.json` with owner, reviewer, reason,
  compensating control, expiry, and SEC-18/RC-08 linkage. The security gate validates the manifest.

## Verification

Targeted SEC-6 regression suite:

```bash
pytest -q --no-cov apps/backend/tests/test_uploads.py apps/backend/tests/test_logs.py \
  apps/backend/tests/test_worker_audit.py apps/backend/tests/test_destructive_actions.py \
  tests/build/test_security_suppressions.py
```

Result: **PASS**, 27 tests.

Release-control validation:

```bash
python3 scripts/validate_security_suppressions.py --today 2026-08-11
python3 scripts/validate_v1_release_control.py
```

Result: **PASS**.

Security gate:

```bash
./scripts/security_scan.sh --gate
```

Result: **PASS**, zero HIGH/CRIT findings. Final local report digest:

```text
dff70610eb03d53466d2297e7466bbcefac1c14da6d9f0e3d44f9fc150d0a612  security_scan_report.md
```

The gate covered Bandit, Semgrep, Gitleaks, ESLint security lint, Hadolint, Checkov, Trivy
filesystem, Trivy config, npm audit, and govulncheck. The GitHub workflow also includes CodeQL
Python and JavaScript/TypeScript jobs.

## Rollback Notes

- Upload policy rollback can re-allow SVG only by reverting both upload validation and static
  serving defenses. Existing SVG files remain inertly served as attachments under the new policy.
- Audit-chain repair does not restore original row content; it only relinks hashes after explicit
  authorization. Operators must preserve the repair report and any external backup before repair.
- Destructive action automation must provide confirmation, idempotency, and backup headers for
  wipe-capable operations.

## Remaining Release Assembly Work

This evidence is local source evidence. RC assembly must rerun the same security gate against the
tagged commit and retained release artifacts, then replace the working-tree source marker with the
final immutable commit and artifact digests.
