# Security Reports and Patch Records — Index

**These are historical records, not the current source of truth.**

This file indexes both `SECURITY_REPORTS/` (audits, triage and raw scanner
output) and `SECURITY_PATCHES/` (patch write-ups and the raw scan run they
were triaged from). Every document in either directory describes the codebase
as it stood on its own date, between 2026-03-10 (v0.2.0-beta) and 2026-06-30.
None of them has been re-run against 1.0.0-rc.3. A finding is closed only if
the requirement ledger says so.

The current security posture is defined by:

- [`specs/1.0.0/02-security-and-trust.md`](../specs/1.0.0/02-security-and-trust.md) — the normative requirements (SEC-01 … SEC-18)
- [`specs/1.0.0/release-control/requirement-ledger.csv`](../specs/1.0.0/release-control/requirement-ledger.csv) — current status per requirement
- [`specs/1.0.0/release-control/security-suppressions.json`](../specs/1.0.0/release-control/security-suppressions.json) — accepted scanner findings, with owner and expiry
- [`SECURITY.md`](../SECURITY.md) — reporting policy

SEC-18 requires scanner reports to be retained **against the RC digest**. The two
Trivy dumps in `SECURITY_REPORTS/`, and `SECURITY_PATCHES/security_scan_report.md`,
predate the release candidate by five months and satisfy nothing; they are kept
as history only. GOV-13 is the requirement this index exists to close.

## Status vocabulary

- **Superseded** — a later document, or a live control in the tree, covers the
  same ground. The row names what replaced it.
- **Historical** — accurate for its date, not re-verified against 1.0.0-rc.3.
- **Active** — at least one finding was still open in the tree when this index
  was written. Confirm against the ledger before acting.

## `SECURITY_REPORTS/` — audits, triage and scanner output

| Report | Date | Version audited | Status |
|---|---|---|---|
| [`SECURITY_TRIAGE_ACTIONABLE_2026-06-30.md`](./SECURITY_TRIAGE_ACTIONABLE_2026-06-30.md) — actionable triage of the June scan run | 2026-06-30 | pre-1.0 `dev` | **Active** — the two top findings are closed in the tree (no `verify_signature` bypass remains anywhere in `apps/backend/src/app`; `docker/nginx.mono.conf` clears `Upgrade`/`Connection` on the general proxy and forwards them only in explicit WebSocket locations). The Medium "JWT secret fallback is logged" still stands: `apps/backend/src/app/core/users.py:197-201` logs the fallback path. Dependency-CVE rows are stale — re-run the scanners. |
| [`SEC_ANALYSIS-3-12-26.md`](./SEC_ANALYSIS-3-12-26.md) — narrative overview of shipped security features | 2026-03-13 | v0.2.2 | Historical. A feature description, not a finding list; nothing here is actionable. |
| [`trivy_scan-3-13-26.txt`](./trivy_scan-3-13-26.txt) — raw Trivy output | 2026-03-13 | v0.2.2 | Superseded by the Trivy stages that run continuously: filesystem and IaC in [`security.yml`](../.github/workflows/security.yml), and an image scan of the pushed digest in [`release.yml`](../.github/workflows/release.yml) that blocks signing on *fixable* HIGH/CRITICAL — it sets `ignore-unfixed: true`, so the 105 unfixable HIGH/CRIT findings the base image carries are deliberately non-blocking. |
| [`trivy_report-3-12-26.txt`](./trivy_report-3-12-26.txt) — raw Trivy output | 2026-03-13 | v0.2.2 | Superseded, as above. |
| [`SECURITY_AUDIT_2026-03-12.md`](./SECURITY_AUDIT_2026-03-12.md) — manual review plus automated scan triage | 2026-03-12 | v0.2.2 | Historical. Its headline finding (secrets in tracked runtime artifacts) is tracked as repository hygiene, not as an open code defect. |
| [`SECURITY_PATCH-3_FINDING_MATRIX.md`](./SECURITY_PATCH-3_FINDING_MATRIX.md) — C/H/M classification of the SECURITY_PATCH-3 findings | 2026-03-12 | v0.2.2 | Historical. Companion to the audit above; classifies each scanner hit as current-code, history-only or false-positive. Its stated source is [`SECURITY_PATCHES/SECURITY_PATCH-3.md`](../SECURITY_PATCHES/SECURITY_PATCH-3.md), indexed below. |
| [`GEMINI_SEC_AUDIT.md`](./GEMINI_SEC_AUDIT.md) — third-party static analysis pass | 2026-03-12 | v0.2.2 | Historical. Reported no Critical or High findings and one Low (SVG upload handling). |
| [`data_flow.md`](./data_flow.md) — backend → frontend data-flow analysis | 2026-03-12 | v0.2.2 | Historical reference, not a finding list. Predates the agent, monitors and discovery-dispatch work, so its flow diagrams are incomplete for 1.0.0. |
| [`SECURITY_STANDING-2.md`](./SECURITY_STANDING-2.md) — post-remediation standing | 2026-03-11 | v0.2.0 → v0.2.2 | Historical. Supersedes `SECURITY_STANDING-1.md`. |
| [`SECURITY_STANDING-1.md`](./SECURITY_STANDING-1.md) — pre-remediation standing | 2026-03-11 | v0.2.0 | **Superseded** by `SECURITY_STANDING-2.md`, published the same day after its ten High/Medium findings were remediated. Read only for the history. |


## `SECURITY_PATCHES/` — patch records and the raw scan run

Remediation write-ups, not findings lists. They describe fixes in the present
tense as of their own date; several of the files and line numbers they cite have
since moved or been deleted. Treat them as history, and check the tree.

| Document | Date | Version audited | Status |
|---|---|---|---|
| [`SECURITY_PATCH-3.md`](../SECURITY_PATCHES/SECURITY_PATCH-3.md) — end-to-end hardening write-up (JWT, CSRF, API tokens, WebSocket auth, container runtime) | 2026-03-13 | v0.2.2 | Historical. Its JWT startup validation is still in the tree (`docker/entrypoint-mono.sh` hard-fails on an unset, short, `CHANGE_ME`, or vault-key-equal `CB_JWT_SECRET`), but two artefacts it cites are gone: `docker/docker-compose.prod.yml` and `PROMPT.md` are not in this repository, so its Compose and regression-suite sections cannot be followed as written. Classified finding-by-finding in [`SECURITY_PATCH-3_FINDING_MATRIX.md`](./SECURITY_PATCH-3_FINDING_MATRIX.md). |
| [`security_patch.md`](../SECURITY_PATCHES/security_patch.md) — C/H/M fix summary for the 2026-03-10 audit | 2026-03-10 | v0.2.0-beta | Historical, and the oldest document indexed here. Its named critical fixes are present in the tree today (`app/core/nmap_args.py`, `validate_snmp_community()` in `app/core/validation.py`, `reject_ssrf_url()`/`reject_ssrf_url_proxmox()` in `app/core/url_validation.py`, and no `verify_aud=False` anywhere in `apps/backend/src/app`). Its stated audit source, `Security Report.md`, is **not** in this repository, so its findings cannot be traced back past this summary. |
| [`scanner_false_positives_2026-03-12.md`](../SECURITY_PATCHES/scanner_false_positives_2026-03-12.md) — rationale for four suppressed scanner hits (FP-01, FP-02, RA-01, RA-02) | 2026-03-12 | v0.2.2 | **Superseded** as an operational control. The same four selectors now live in [`.trivyignore`](../.trivyignore) and, with owner, reviewer and expiry, in [`security-suppressions.json`](../specs/1.0.0/release-control/security-suppressions.json) as TRIVY-001 … TRIVY-004. Read this file only for the reasoning; the suppression list the release gate honours is the JSON. |
| [`security_scan_report.md`](../SECURITY_PATCHES/security_scan_report.md) — raw output of `scripts/security_scan.sh` (Bandit, Semgrep, Gitleaks, ESLint + security, Hadolint, Checkov, Trivy filesystem and config, npm audit); today the same script is `make security-report` | 2026-03-12 | v0.2.2 | Historical raw output, kept as the source both [`SECURITY_AUDIT_2026-03-12.md`](./SECURITY_AUDIT_2026-03-12.md) and [`SECURITY_TRIAGE_ACTIONABLE_2026-06-30.md`](./SECURITY_TRIAGE_ACTIONABLE_2026-06-30.md) triage. Five months stale and superseded for SEC-18 purposes by the CI scan stages named in the Trivy rows above. |

## Reading these safely

1. Nothing in this directory grants a requirement a pass. The ledger does.
2. Where a report and the tree disagree, the tree wins — several of these
   documents describe fixes in the present tense that had not landed at the
   time, and several describe defects that have since been fixed.
3. Do not add a document to `SECURITY_REPORTS/` or `SECURITY_PATCHES/` without
   also adding a row above. An unindexed report reopens the exact GOV-13 gap
   this file closes.
