# ACC-1 — Acceptance Matrix, Harness, and Evidence

**Supports:** ACC-01, ACC-02, ACC-03, ACC-04, ACC-05, ACC-06, ACC-07, ACC-08, ACC-09,
ACC-10, ACC-11, ACC-12, ACC-13, ACC-14, ACC-15, ACC-16, ACC-17, ACC-18, ACC-19, ACC-20, ACC-21
**Depends on:** RC-02, RC-04, RC-07

## Objective

Provide one reusable artifact-first harness and evidence contract for every release journey. The
harness must make it impossible to accidentally test a local source build while claiming acceptance
for a published candidate.

## Repository touchpoints

- `.github/workflows/{ci,build,release}.yml`, `scripts/test-mono-e2e.sh`
- Root and agent Compose E2E stacks, `deploy/`, `packaging/`, `install.sh`, `uninstall.sh`
- Existing pytest/vitest/Go suites and the future browser E2E project

## Implementation sequence

1. Store the support/journey matrix in a machine-readable format with case ID, requirements, owner,
   manual/automated mode, topology, OS/arch/browser/database, source version, and evidence retention.
2. Define candidate input as immutable version, commit, artifact URL, digest, signature, provenance,
   and SBOM. Verify before provisioning and record again from the installed runtime.
3. Build shared provisioning primitives for clean hosts/runners, unique ports/project names, secrets,
   clocks, networks, fixture data, teardown, and post-failure diagnostic capture.
4. Build assertions for version parity, services/process users, migrations, health/readiness, ports,
   logs, file ownership, durable state, audit, and unexpected warnings.
5. Define evidence-bundle manifest, redaction, timestamps, environment fingerprint, command/result,
   screenshots/traces/logs, checksums, reviewer, and upload retention.
6. Add fail-safe cleanup that targets only run-owned resources and preserves failed environments long
   enough to collect evidence.

## Verification and done

Run one deliberately passing and one deliberately failing sample candidate. An independent reviewer
must reconstruct artifact identity, environment, action, result, and failure cause from the bundle.
Done means matrix/ledger IDs reconcile exactly and no harness default can substitute a workspace build.
