# SEC Evidence Capture — immutable commit, Python 3.12

**Requirements covered:** SEC-01, SEC-07, SEC-08, SEC-09, SEC-10, SEC-15, SEC-16, SEC-17
**Date:** 2026-08-14
**Owner / reviewer:** shawnji (single codeowner; see `EXC-002`)

This bundle exists to satisfy one specific blocker. After the SEC 1–10 audit
(`sec-slices-audit-2026-08-13.md`), the rows above read:

> Implementation complete and gates green locally; prior 'passed' was pinned to a
> development tree, which the definition of done forbids as release evidence.
> Awaiting evidence capture at an immutable commit on Python 3.12.

The implementation work was already done and reviewed. What was missing was a gate
run against a committed, reproducible tree on the interpreter the project actually
supports. That run is recorded here.

## Evidence bundle

| Field | Value |
|---|---|
| Commit | `72d9aaf5e7dc0ffa4e18114a7f9bd0fcd0c7f440` |
| Source tree | `git-tree:133b7546aed2f764ebf097a4f1edcce67f95a595` |
| Version | `0.3.5` |
| Working tree state | clean (`git status --porcelain` empty at run time) |
| Environment image | `python@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65` (`python:3.12-slim`) |
| Interpreter | CPython 3.12.14 |
| Key libraries | FastAPI 0.136.3 · SQLAlchemy 2.0.52 · Pydantic 2.13.4 · ruff 0.16.3 · mypy 2.3.0 |
| Deployment mode | source tree under test; PostgreSQL provisioned per-session by testcontainers; `CB_AUTO_MIGRATE=false` (schema built from SQLAlchemy metadata by the `setup_db` fixture) |
| Completion time | 2026-08-14T15:52:25Z |
| Result | **pass** — all five gates green |

The host runs Python 3.14.6 only, which the project does not support
(`requires-python >=3.12,<4`). Every gate below therefore ran inside the
`cb-verify-312` container with the repository bind-mounted at `/w`. Running the
suite on the host interpreter is not valid evidence — the audit recorded 20
failures there, including the SEC-07 gate itself, as an interpreter artifact.

## Procedure and results

All commands run from `/w/apps/backend` with `PYTHONPATH=src` unless noted.

| Gate | Command | Result |
|---|---|---|
| Backend suite | `python -m pytest tests -q` | exit 0 — **2326 passed, 16 skipped, 0 failed, 0 errors** |
| Coverage floor | (same run, `--cov` via addopts) | 58.05% ≥ 55% required |
| Lint | `python -m ruff check src/app` | exit 0 — all checks passed |
| Format | `python -m ruff format --check src/app` | exit 0 — 283 files already formatted |
| Types | `python -m mypy src/app` | exit 0 — no issues in 283 source files |
| Security scanners | `bash scripts/security_scan.sh --gate` (host) | exit 0 — zero HIGH/CRIT across Bandit, Semgrep, Gitleaks, ESLint, Hadolint, Checkov, Trivy fs, Trivy config, npm audit, pip-audit, govulncheck |
| Release control | `python3 scripts/validate_v1_release_control.py` | exit 0 — 145 ledger rows, 145 canonical IDs |

The security gate initially failed closed on one genuine HIGH — CVE-2026-46600 in
`golang.org/x/net` v0.55.0, reachable via `golang.org/x/net/dns/dnsmessage`. That
is fixed in commit `72d9aaf5` (bump to v0.56.0); the gate result above is the
re-run after the fix, at the pinned commit.

## Retained logs

| File | SHA-256 |
|---|---|
| `logs/2026-08-14-sec-gate/pytest.log` | `991ba57af3edf99678ef806cef6c20bbe237233a6ef035082a0045935dce1b1c` |
| `logs/2026-08-14-sec-gate/security-scan-report.md` | `e4acddb1ee338be1b81c54849a5850f201274614a930c2150d3fd0fc51ce2d9d` |

## Scope — what this bundle does NOT evidence

This is a source-tree gate. It does not build, package, or deploy a release
artifact, so it cannot satisfy any row whose acceptance depends on one. The
following rows stay `in_progress` deliberately; their notes already name what is
outstanding, and nothing here changes it:

| Row | Still requires |
|---|---|
| SEC-05 | release-artifact upgrade rehearsal |
| SEC-06 | RC artifact rerun of the endpoint/static surface inventory |
| SEC-11 | packaged RC dependency scan |
| SEC-12 | packaged RC controllable-DNS rebinding exercise |
| SEC-13 | multi-instance rate-limit evidence (shared Redis across processes) |
| SEC-14 | packaged RC fail-closed startup evidence |
| SEC-18 | CodeQL run and a container **image** scan against a pushed digest — the local gate covers the other eleven scanners, and `release.yml` now runs `trivy image` before cosign, but that path has not executed yet |

SEC-02, SEC-03 and SEC-04 remain `excepted` under `EXC-001` (multi-tenancy
deferred per ADR-0003). A waiver is not a test result and this bundle does not
convert one into one.

## Invalidation

This evidence is `current` as of commit `72d9aaf5`. Per
`release-control/evidence-and-invalidation.md`, any later commit labelled
`impact:runtime-code`, `impact:dependency`, `impact:test-harness`, or
`impact:environment` touching the covered code paths invalidates it unless the
owner records a narrower impact analysis. Because the whole point of this bundle
is the commit pin, re-running the gates on a later tree does not extend it —
capture a new bundle and supersede this one.
