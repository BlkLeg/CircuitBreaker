# Security Reports and Patch Records — Index

**Historical records, with one exception — read the status column before acting on
anything here.**

This file indexes both `SECURITY_REPORTS/` (audits, triage and raw scanner
output) and `SECURITY_PATCHES/` (patch write-ups and the raw scan run they
were triaged from). Every document in either directory describes the codebase
as it stood on its own date. A finding is closed only if the requirement ledger,
or the finding's own row, names the commit that closed it.

**One exception to "historical".** [`bug-bounty-2026-08-26.md`](./bug-bounty-2026-08-26.md)
was run against 1.0.0-rc.4 and is being actively remediated — sixteen of its findings
carry a fix in the uncommitted working tree, thirteen are still open, and the remediation
introduced thirteen regressions of its own that the document lists. If you are picking
that work up mid-flight, start with
[`HANDOFF-2026-08-26.md`](./HANDOFF-2026-08-26.md), which is the operating order.
Everything else here predates the release candidate, between 2026-03-10
(v0.2.0-beta) and 2026-06-30, and none of it has been re-run against 0.4.0.

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
- **Historical** — accurate for its date, not re-verified against 0.4.0.
- **Active** — at least one finding was still open in the tree when this index
  was written. Confirm against the ledger before acting.

## `SECURITY_REPORTS/` — audits, triage and scanner output

| Report | Date | Version audited | Status |
|---|---|---|---|
| [`bug-bounty-2026-08-26.md`](./bug-bounty-2026-08-26.md) — 35 confirmed defects from a multi-agent hunt, with per-finding status | 2026-08-26 | 1.0.0-rc.4 (`dev` at `f483bcb3`) | **Active** — the only document here describing the current tree. **All 51 findings are now fixed and committed** (`10db56ee`, `d773d60d`), bar two recorded as partly fixed (R10 and B44), and the thirteen regressions the remediation introduced are closed bar R10. Read the report's *Wave 3* section before trusting that: every one of its fifteen clusters came back INCOMPLETE from adversarial review the first time — 7 blockers, 17 majors and 24 tests proven vacuous — and six clusters carry one review rather than two because a session limit killed their second reviewers. The table there marks which. Raw evidence in [`bug-bounty-2026-08-26-findings.json`](./bug-bounty-2026-08-26-findings.json). |
| [`bug-bounty-2026-08-26-findings.json`](./bug-bounty-2026-08-26-findings.json) — raw finding data behind the report above | 2026-08-26 | 1.0.0-rc.4 (`dev` at `f483bcb3`) | **Active** — machine output, kept as the evidence for the report. Each entry carries the refutation attempt that failed to kill it (`reasoning`) and the proposed remediation (`fix`) in full; the report quotes the latter and summarises the rest. |
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
