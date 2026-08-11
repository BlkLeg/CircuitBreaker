# ACC-7 — Historical Issue Artifact Verification

**Requirement:** ACC-16; integrates AGT-10, AGT-11, AGT-12
**Priority:** Release-blocking issue closure

## Case matrix

| Issue | Required artifact evidence |
|---|---|
| #66 | Fresh PostgreSQL install completes migration 0071 without duplicate column. |
| #68 | True Alembic chain and affected-version upgrades tolerate 0060/0071/0078 and revision width. |
| #74 | UI/API save and reload hardware with non-empty `port_map`; topology edge remains correct. |
| #75 | Installed package discovers reported replacement/non-ASCII bytes under minimal ASCII locale. |
| #81 | ARM64 package starts, reaches health, restarts, and has clean logs after migrations. |
| #87 | x86_64/ARM64 install and upgrade through 0080 start once with correct app-role grants. |
| #101 | ARM64 AVIF, bounded PyInstaller extraction, and numeric environment filter all pass. |

## Implementation sequence

1. Capture issue body, original version/environment, reproduction, expected behavior, and patch commit.
2. Create an automated case using the closest reproducible clean host and exact signed candidate. If
   hardware/manual reproduction is required, use the ACC-1 evidence schema.
3. Prove the test fails on the affected artifact when safely obtainable; otherwise explain why the
   reproduction still distinguishes the defect from a generic smoke test.
4. Run fresh install and affected-version upgrade where relevant. Attach logs/screenshots/data checks
   to the issue before closure; “code patch present” remains incomplete.
5. Run neighboring regressions and full platform smoke after all cases share the final candidate.

## Done

Every listed issue has clean-host evidence for the exact RC and is closed, or has an explicit RC-08
exception with owner, compensating control, user-visible limitation, and expiry.
