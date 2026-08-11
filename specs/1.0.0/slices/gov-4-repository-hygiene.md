# GOV-4 — Repository Hygiene and Historical Records

**Requirements:** GOV-12, GOV-13
**Safety:** Review history and ownership before deletion

## Scope

Review suspicious root `-H`, `-d`, `=1.9.0`; `.idea/`; `apps/agent/e2e/.env`; tracked profile uploads;
`apps/frontend/eslint_output.json`; generated `site/`; caches/build output; and accumulated reports/plans.

## Build sequence

1. Produce a tracked-file inventory with path, origin/commit, owner, content class, secret/PII scan,
   referenced-by results, required-at-runtime/build, and retain/relocate/redact/remove decision.
2. Inspect git history before removing a credential-like file. If a real secret existed, rotate/revoke
   first and follow the incident process; deleting HEAD is not remediation.
3. Replace useful environment fixtures with `.env.example` and test-only generated secrets. Move sample
   uploads to clearly synthetic fixtures or generate them during tests.
4. Remove/ignore reproducible generated outputs and IDE state. Add allowlist-based tracked-artifact CI
   checks rather than broad destructive cleanup scripts.
5. Create an index for security reports/plans with date, status, superseded-by, relevant version, and
   retained decisions. Move durable decisions to ADR/release records without rewriting history.
6. Verify no docs/build/test/runtime path depended on removed content.

## Verification and done

Run secret scan, tracked-policy check, docs build, application builds, and targeted fixtures/E2E. Done
means every reviewed file has a recorded disposition, current sources of truth are obvious, and no
user/generated/private data is tracked accidentally.
