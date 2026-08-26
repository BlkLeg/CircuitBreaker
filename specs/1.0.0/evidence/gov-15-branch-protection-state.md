# GOV-15 — branch protection: documented versus actually enabled

**Requirement:** GOV-15 — verify branch protection and required checks; document the actual branch
names and check names.
**Reviewer:** shawnji (governance)
**Review date:** 2026-08-26
**Repository:** `BlkLeg/CircuitBreaker`
**Result:** **NOT MET.** Nothing documented is enforced, and the documented configuration could not
be enforced as written.

GOV-15's wording is deliberate — *verify settings are actually enabled in GitHub, not merely
documented*. This is that verification, and it is the case the wording anticipated.

## Method

```
gh api repos/BlkLeg/CircuitBreaker/branches/main/protection
gh api repos/BlkLeg/CircuitBreaker/branches/dev/protection
gh api repos/BlkLeg/CircuitBreaker/rulesets
```

Both branch-protection queries and the ruleset list, read against the live repository rather than
against `.github/branch-protection.md`.

## Findings

### 1. Neither branch is protected

```
$ gh api .../branches/main/protection
{"message":"Branch not protected","status":"404"}

$ gh api .../branches/dev/protection
{"message":"Branch not protected","status":"404"}
```

`main` and `dev` both accept direct pushes. `.github/branch-protection.md` closes with "These rules
prevent direct pushes to `main` and `dev`. All changes must go through pull requests with at least
one approval." No part of that sentence is currently true.

### 2. The one ruleset that exists is disabled

```
$ gh api .../rulesets
[{"id":13901513,"name":"Main-Branch","target":"branch","enforcement":"disabled",
  "created_at":"2026-03-14T01:17:36-04:00","updated_at":"2026-03-14T01:17:46-04:00"}]
```

Created and last touched within eleven seconds of each other on 2026-03-14, and left at
`enforcement: disabled` for five months. This is the closest thing to protection the repository
has, and it enforces nothing.

### 3. One of the three documented required checks does not exist

`.github/branch-protection.md` requires `test`, `lint` and `trivy-scan`. GitHub matches a required
check by the name the check run reports, which is the job's `name:` when it has one. Measured
against the workflows in the tree:

| Documented check | Actual status |
|---|---|
| `test` | Exists — `ci.yml` job `test`, display name **Test**. |
| `lint` | Exists — `ci.yml` job `lint`, display name **Lint**. |
| `trivy-scan` | **Does not exist.** `security.yml` reports **Trivy Filesystem Scan** (`trivy-fs`) and **Trivy Config / IaC Scan** (`trivy-config`). No check run is ever named `trivy-scan`. |

This matters more than a typo. A required check that no workflow reports never becomes green — it
sits pending indefinitely — so enabling the documented configuration verbatim would block **every**
pull request permanently, including the one that tried to correct it. The documentation is not
merely unenforced; it is not safely enforceable as written.

### 4. The documented list omits most of the gates that matter

Required checks name three jobs. The workflows actually run, among others: **Backend tests**,
**Security Gate**, **Browser E2E** (`ci.yml`), the ten scanners in `security.yml`, **Analyze
(Python)** and **Analyze (JavaScript / TypeScript)** (`codeql.yml`), and **Build docs (strict)** and
**Link check** (`docs.yml`). A protection rule built from the current document would gate on lint
and unit tests while letting a CodeQL or scanner failure merge.

### 5. SEC-07's review gate is not enforced

`.github/branch-protection.md` states that the SEC-07 public-route review gate works because
`.github/CODEOWNERS` maps the endpoint allowlist to `security-owner` and Code Owner review is
required. The CODEOWNERS mapping exists and is asserted by `tests/build/test_repo_governance.py`.
The requirement that makes it a gate does not: with no protection enabled, a change to the public
endpoint policy merges with no security-owner approval.

This is the one finding here with a security consequence rather than a process one, and it should
be read alongside SEC-06/SEC-07 rather than only as governance hygiene.

## What GOV-15 needs, and who must do it

Enabling branch protection is a change to repository settings, not to this tree. It is recorded here
rather than performed:

1. **Correct the document first.** Replace `trivy-scan` with the check names workflows actually
   report, and decide the full required set — at minimum Lint, Test, Backend tests, Security Gate,
   and the CodeQL analyses.
2. **Then enable it**, as a ruleset on `main` and `dev` with `enforcement: active`, or by deleting
   the dormant `Main-Branch` ruleset and configuring classic protection. Enabling before step 1
   deadlocks the repository.
3. **Re-run the three commands above** and attach the output, so the row is evidenced against the
   live repository rather than against the document.

Note the ordering constraint the single-maintainer waiver creates: EXC-002 records that this project
has one codeowner, so "require 1 approving review from a Code Owner" cannot be satisfied by the only
person able to merge. Either the review requirement is configured in a form a sole maintainer can
satisfy, or EXC-002 must be extended to cover this rule explicitly. Enabling a review requirement
nobody can satisfy is the same deadlock as `trivy-scan`, arrived at differently.
