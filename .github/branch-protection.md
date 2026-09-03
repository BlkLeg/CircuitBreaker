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
    - `Browser E2E`
  - **Require branches to be up to date before merging**: ✓ Enabled

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
