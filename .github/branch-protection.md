# GitHub Branch Protection Settings

This document outlines the required branch protection rules for `main` and `dev` branches.

## Configuration for `main` and `dev` branches

Apply the following settings via GitHub Settings > Branch protection rules:

### Pull Request Requirements
- **Require a pull request before merging**: ✓ Enabled
  - Minimum 1 approving review required
  - Require review from Code Owners: ✓ Enabled
  - Dismiss stale pull request approvals when new commits are pushed: ✓ Enabled

### Status Checks
- **Require status checks to pass before merging**: ✓ Enabled
  - Required status checks. GitHub matches these on the check-run **name** — the
    string after `name:` in the job — not on the job id. The previous list named
    `test`, `lint` and `trivy-scan`; the first two were lowercase job ids that
    match nothing, and no job called `trivy-scan` has ever existed.
    - `Lint` — Tier 0 static gates: repo-policy suite, ruff, mypy, eslint, and the
      release-control ledger validator (`ci.yml`, `dev-ci.yml`)
    - `Security Gate` — `scripts/security_scan.sh --gate`, fails on HIGH/CRIT
    - `Backend tests (shard 1/4)` … `(shard 4/4)` — the sharded backend suite
    - `Backend coverage gate` — the combined-shard coverage ratchet, which the
      previous list omitted entirely
    - `Trivy Filesystem Scan` and `Trivy Config / IaC Scan` (`security.yml`) — the
      two jobs `trivy-scan` was presumably meant to name
    - `Fresh-install migrations`
    - `Browser E2E` — the **aggregate** job (`browser-e2e-gate`), not the shards.
      The Playwright job is a matrix, so it reports `Browser E2E (shard 1/2)` and
      `(shard 2/2)` and never a check called `Browser E2E`: naming the bare string
      here required a check that is never reported, which matches nothing and
      enforces nothing. Naming the two shards instead would work until the shard
      count changes, at which point the new shard is unrequired and silently
      optional. `browser-e2e-gate` is `name: Browser E2E`, needs both shards, and
      runs under `if: always()` so that a failed shard cannot skip it — a skipped
      required check counts as satisfied, so the aggregate had to be written to
      fail rather than to vanish. Until 2026-09-17 this suite ran on `main` only;
      `dev-ci.yml` now runs the same matrix, so this check exists on both branches.
  - **Require branches to be up to date before merging**: ✓ Enabled
  - Checks that exist on **one** branch only, and so cannot be required on both:
    - `Build Native (amd64)` and `Build Docker (smoke test)` are `dev-ci.yml` only.
      The second builds the mono image and then actually starts it through
      `docker-compose.yml` — `/livez`, `/readyz`, the served frontend, every
      supervisord program, restart count and SIGTERM shutdown. `main`'s
      equivalent coverage is `release.yml` at tag time, which builds the image
      per-architecture and calls `artifact-smoke.yml` for the packages.

### Administration
- **Enforce all above rules for administrators**: ✓ Enabled
  - Administrators are subject to the same restrictions

### Optional Recommendations
- Enable auto-delete of head branches after merge
- Require conversation resolution before merging (if using PR comments)

### SEC-07 Public Route Review Gate
- `.github/CODEOWNERS` maps the checked-in public endpoint allowlist and route-inventory gate to
  `security-owner`.
- With Code Owner review required, any pull request that adds or changes a reviewed public endpoint
  policy entry requires explicit security-owner approval before merge.

---

**Note**: These rules prevent direct pushes to `main` and `dev`. All changes must go through pull requests with at least one approval and passing security/quality checks.

**This file is documentation, not configuration.** Nothing in the repository
applies or verifies it — the live settings are server-side, and the two were out
of step on every line above until 2026-09-03. Until `dev-ci.yml` gained a
`pull_request` trigger that same day, a pull request into `dev` ran no Tier 0
and no Tier 1 at all, which is only possible if direct pushes to `dev` were in
fact permitted. Treat a claim here as a claim to check against the branch's
settings, not as evidence about them.
