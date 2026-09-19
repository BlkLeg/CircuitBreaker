# GitHub Branch Protection Settings

This document outlines the required branch protection rules for `main` and `dev` branches.

## Configuration for `main` and `dev` branches

Apply the following settings via GitHub Settings > Branch protection rules:

### Pull Request Requirements
- **Require a pull request before merging**: ✓ Enabled
- **Required approving reviews: 0** — deliberately, and this is the one setting
  here that documents an absence rather than a control.

  GitHub does not let an author approve their own pull request. This project has
  exactly one codeowner (EXC-002), so any non-zero approval count, and any
  Code Owner review requirement, is unsatisfiable by the only person able to
  satisfy it: every pull request would sit unmergeable forever. The two ways out
  are to require the review and grant the sole maintainer a bypass, or to not
  require it. A bypass was rejected on 2026-09-17: it reports the branch as
  review-protected while the only merges that happen are bypass events, which is
  a setting that looks enforced and is not — the precise condition GOV-15 exists
  to detect.

  What stands in for the second pair of eyes is EXC-002's own compensating
  control, now actually enforced rather than merely described: 21 required status
  checks that a single reviewer cannot wave through, including the endpoint
  policy gate, the release-control ledger validator, and ten security scanners.

  Revisit this the moment a second maintainer joins — that is also the condition
  under which EXC-002 closes.
- **Dismiss stale pull request approvals when new commits are pushed**: not
  applicable while the approval count is 0.

### Status Checks
- **Require status checks to pass before merging**: ✓ Enabled
  - GitHub matches these on the check-run **name** — the string after `name:` in
    the job — not on the job id. The list below was verified on 2026-09-17 by
    enumerating every workflow with a `pull_request` trigger for `main` or `dev`
    and reading the `name:` of each job it defines. Three earlier revisions of
    this file named checks that no workflow reported (`test`, `lint`,
    `trivy-scan`, then `Browser E2E`), and a required check that is never
    reported leaves every pull request pending forever — including the one that
    would correct the list. Re-verify after adding, renaming or path-filtering
    any job.

  **From `ci.yml` (main) and `dev-ci.yml` (dev) — 9 checks**
    - `Lint` — Tier 0 static gates: repo-policy suite, ruff, mypy, eslint, and the
      release-control ledger validator
    - `Security Gate` — `scripts/security_scan.sh --gate`, fails on HIGH/CRIT
    - `Backend tests (shard 1/4)` … `(shard 4/4)` — the sharded backend suite
    - `Backend coverage gate` — the combined-shard coverage ratchet
    - `Fresh-install migrations`
    - `Test` — frontend vitest and the Go agent suite

  **From `security.yml` (both branches) — 10 checks**
    - `Security Suppression Metadata`
    - `Trivy Filesystem Scan`
    - `Trivy Config / IaC Scan`
    - `Semgrep (SAST)`
    - `Bandit (Python SAST)`
    - `Gitleaks (Secret Scanning)`
    - `Checkov (GitHub Actions / IaC)`
    - `Python Dependency Audit`
    - `Frontend Dependency Audit`
    - `Go Vulnerability Scan`

    None of the ten is `continue-on-error`, so each already fails its run — they
    were simply never required. Two of them are also SEC-18's named scanners, so
    requiring them is what makes that row's acceptance load-bearing rather than
    advisory.

  **From `codeql.yml` (both branches) — 2 checks**
    - `Analyze (Python)`
    - `Analyze (JavaScript / TypeScript)`

  **Deliberately NOT required**
    - `Browser E2E` — the aggregate job (`browser-e2e-gate`), **temporarily**
      excluded, and the only entry here that is expected to move. The check
      itself is correct: the Playwright job is a matrix reporting
      `Browser E2E (shard 1/2)` and `(shard 2/2)`, never the bare name, so
      `browser-e2e-gate` exists to provide one stable name, needs both shards,
      and runs `if: always()` because a skipped required check counts as
      satisfied and a failed shard would otherwise skip it away.

      It is excluded because it is genuinely red, on both branches and since
      before it was required anywhere: shard 2 fails a webkit focus test
      (`global-navigator … hands focus to the dialog`) and the `monitors-empty`
      visual baseline. Requiring a red check would block every merge including
      the pull request that fixes it. That work is REL-17 (Playwright E2E
      coverage) and REL-18 (visual regression); add this check to both rulesets
      the day shard 2 is green, which is a one-line edit and needs no change
      here beyond moving this bullet back up.
    - `Build docs (strict)` and `Link check` (`docs.yml`). These are blocking
      jobs and would otherwise belong above, but `docs.yml` is **path-filtered**
      to `docs/**`, `mkdocs.yml`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`,
      `.lycheeignore` and its own file. A required check is only satisfied by
      being reported, and a code-only pull request never triggers this workflow,
      so requiring either one would hang every backend or frontend change
      indefinitely. Path-filtered workflows cannot be required checks; this is
      the same failure mode as a misnamed check, reached by a different route.
    - `Build Native (amd64)` and `Build Docker (smoke test)` are `dev-ci.yml`
      only, so they cannot be required on `main`. The second builds the mono
      image and then starts it through `docker-compose.yml` — `/livez`,
      `/readyz`, the served frontend, every supervisord program, restart count
      and SIGTERM shutdown. `main`'s equivalent coverage is `release.yml` at tag
      time, which builds the image per-architecture and calls
      `artifact-smoke.yml` for the packages. They are **not** currently required
      on `dev` either: one identical required set on both branches is one list to
      re-verify instead of two that drift apart, which is the failure this file
      keeps having. Adding them to the `dev` ruleset alone is a safe follow-up.

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
- **This gate is not currently enforced by review, and SEC-07 should not be read
  as if it were.** Its stated mechanism is Code Owner approval, which a
  single-codeowner repository cannot produce (see Pull Request Requirements
  above). Until a second maintainer exists, a change to the public endpoint
  policy merges without a second person's approval.
- What does still gate it automatically: the endpoint policy / route-inventory
  check runs inside `Lint` (Tier 0), which is a required status check, so an
  unclassified or silently-changed public route fails the pull request even
  though no human is required to look at it. That is a materially weaker control
  than the one SEC-07 describes — it catches *undeclared* changes, not
  *ill-advised declared* ones — and the difference is the open half of SEC-07.

---

**Note**: These rules prevent direct pushes to `main` and `dev`. All changes must
go through pull requests with passing security/quality checks — and, while this
project has one maintainer, with no approving review (see above).

**This file is documentation, not configuration.** Nothing in the repository
applies or verifies it — the live settings are server-side, and the two were out
of step on every line above until 2026-09-03. Until `dev-ci.yml` gained a
`pull_request` trigger that same day, a pull request into `dev` ran no Tier 0
and no Tier 1 at all, which is only possible if direct pushes to `dev` were in
fact permitted. Treat a claim here as a claim to check against the branch's
settings, not as evidence about them.
