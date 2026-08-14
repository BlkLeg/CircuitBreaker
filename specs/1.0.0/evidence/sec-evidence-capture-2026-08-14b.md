# SEC Evidence Capture — commit 49b20ed1 (supersedes 72d9aaf5 bundle)

**Requirements covered:** SEC-01, SEC-07, SEC-08, SEC-09, SEC-10, SEC-15, SEC-16, SEC-17
**Date:** 2026-08-14
**Owner / reviewer:** shawnji (single codeowner; see `EXC-002`)
**Supersedes:** `sec-evidence-capture-2026-08-14.md` (pinned `72d9aaf5`)

## Why this bundle exists

The first bundle pinned `72d9aaf5`. The next commit, `49b20ed1`, modified
`apps/backend/src/app/security/endpoint_policy.json` — the reviewed public
endpoint allowlist, which is the artifact SEC-07 is *about*. Under
`release-control/evidence-and-invalidation.md` that is an `impact:runtime-code`
change to a covered path, so the SEC-07 evidence could not stay `current`.

Rather than record a narrow impact analysis for one row and leave eight rows
split across two commits, all eight are re-evidenced here at `49b20ed1`. The
superseded bundle is retained unmodified for auditability.

This bundle is also stronger than the one it replaces: the gates ran in CI at
this exact commit, not only in a local container.

## Evidence bundle

| Field | Value |
|---|---|
| Commit | `49b20ed1f62c3e8082487c02446a6921edec82e6` |
| Version | `0.3.5` |
| Working tree state | clean; commit pushed to `origin/dev` |
| Local environment | `python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65` (`python:3.12-slim`), CPython 3.12.14, FastAPI 0.136.3 |
| CI environment | GitHub-hosted `ubuntu-24.04` (backend tests) and `ubuntu-22.04` (scans), Python 3.12, Node 20, Go resolved from `apps/agent/go.mod` |
| Deployment mode | frontend built (`npm run build`) so the route surface matches a shipped deployment; PostgreSQL via testcontainers; `CB_AUTO_MIGRATE=false` |
| Completion time | 2026-08-14T17:00:00Z |
| Result | **pass** — green locally and in CI |

## CI evidence at this commit

| Workflow | Result | Run |
|---|---|---|
| Dev CI (6 jobs: lint, security gate, backend tests, test, build native, build docker) | success | https://github.com/BlkLeg/CircuitBreaker/actions/runs/31820982457 |
| Security Scan (10 jobs) | success | https://github.com/BlkLeg/CircuitBreaker/actions/runs/31820982468 |
| CodeQL | success | https://github.com/BlkLeg/CircuitBreaker/actions/runs/31820982451 |

Backend suite in CI: **2329 passed, 13 skipped** in 594.96s, coverage 58.09%.
Locally: **2326 passed, 16 skipped**, coverage 58.05%. Both collect the same
2342 tests; the three-test delta is skip distribution between the two
environments, not a difference in what was exercised.

Mutable CI URLs are recorded alongside the immutable commit SHA, as
`evidence-and-invalidation.md` requires.

## Local procedure and results

From `/w/apps/backend` with `PYTHONPATH=src`, in the `cb-verify-312` container
(the host runs Python 3.14.6 only, which the project does not support):

| Gate | Command | Result |
|---|---|---|
| Backend suite | `python -m pytest tests -q` | exit 0 — 2326 passed, 16 skipped, 0 failed |
| Lint | `python -m ruff check src/app` | exit 0 |
| Format | `python -m ruff format --check src/app` | exit 0 — 283 files |
| Types | `python -m mypy src/app` | exit 0 — 283 source files |
| Release control | `python3 scripts/validate_v1_release_control.py` | exit 0 |

The endpoint policy gate was additionally run in both configurations of the
`_frontend_dir` branch — with a frontend build present, and with `STATIC_DIR`
pointed at a nonexistent path — because `main.py` registers a different route
surface in each and CI previously exercised only the second.

## Retained logs

| File | SHA-256 |
|---|---|
| `logs/2026-08-14-sec-gate/pytest.log` | `991ba57af3edf99678ef806cef6c20bbe237233a6ef035082a0045935dce1b1c` |
| `logs/2026-08-14-sec-gate/security-scan-report.md` | `e4acddb1ee338be1b81c54849a5850f201274614a930c2150d3fd0fc51ce2d9d` |

Those two files were produced at `72d9aaf5` and are retained as the superseded
bundle's artifacts. The authoritative results for this bundle are the three CI
runs linked above, which are tied to `49b20ed1` by SHA.

## Scope — what this bundle does NOT evidence

Unchanged from the superseded bundle. These rows stay `in_progress` because
their acceptance needs a release artifact, which no gate here produces:

| Row | Still requires |
|---|---|
| SEC-05 | release-artifact upgrade rehearsal |
| SEC-06 | RC artifact rerun of the endpoint/static surface inventory |
| SEC-11 | packaged RC dependency scan |
| SEC-12 | packaged RC controllable-DNS rebinding exercise |
| SEC-13 | multi-instance rate-limit evidence |
| SEC-14 | packaged RC fail-closed startup evidence |
| SEC-18 | container **image** scan against a pushed digest — CodeQL is now green at this commit, closing half of what was outstanding; `release.yml` runs `trivy image` before cosign, but that path executes only on a release tag |

SEC-02, SEC-03, SEC-04 remain `excepted` under `EXC-001`.

## A correction this capture records

The superseded bundle reported the local security gate as zero HIGH/CRIT. That
result was an artifact of the host toolchain: `security.yml` resolves Go from
`go-version-file`, so CI used `go.mod`'s `go 1.25.0` and govulncheck found **25
called standard-library vulnerabilities**, while this machine's Go 1.26.5 had a
patched stdlib and reported none. The `go` directive now pins 1.25.13, the
highest fix version across all 25, and the Go Vulnerability Scan passes in CI.
A gate that only passes on the maintainer's machine is not evidence — that is
the same class of finding the audit raised, reached from the opposite direction.
