# v1.0.0 Remediation — Plan Index

**Date:** 2026-08-18
**Source audit:** `specs/1.0.0/gap-audit-2026-08-18.md`
**Plan spec:** `specs/1.0.0/` (9 normative specs, 145 requirement IDs)

The audit spans several independent subsystems. Per `superpowers:writing-plans`, this is split
into five plans, each of which produces working, independently testable software. They can be
executed in any order **except** that Plan 3 must precede closing `known_bugs` item 1.

| # | Plan | Closes | Tasks |
|---|---|---|---|
| 1 | [Release pipeline](./2026-08-18-v1-release-pipeline.md) | RC-02, GOV-09, GOV-18, GOV-19, GOV-20, ACC-17, EXEC-07 | 6 |
| 2 | [Live defects](./2026-08-18-v1-live-defects.md) | AGT-04, AGT-10, AGT-11, AGT-12, SEC-05 | 5 |
| 3 | [Browser test harness](./2026-08-18-v1-browser-harness.md) | ACC-09, ACC-10, REL-14, REL-15, REL-17, REL-18, REL-19, `known_bugs` #1 | 7 |
| 4 | [Server contract](./2026-08-18-v1-server-contract.md) | SRV-03, SRV-05, SRV-06, RC-05, GOV-05 | 4 |
| 5 | [Governance hygiene](./2026-08-18-v1-governance-hygiene.md) | GOV-01, GOV-08, GOV-10, GOV-11, GOV-12, GOV-16, NPM-01–15, GOV-06/07 (agent docs) | 8 |

## Out of scope for these plans

Deliberately excluded — these need environments, measurements, or product decisions rather than
code, and are tracked as open in `specs/1.0.0/release-control/requirement-ledger.csv`:

- **REL-21 – REL-26** (performance, capacity, 24h/7d soak) — needs a load environment.
- **AGT-05 – AGT-09** (physical remote-site UAT) — needs two physical sites and real hardware.
- **ACC-12 – ACC-15** (upgrade/backup/restore matrix) — needs prior-version artifacts to upgrade from.
- **SRV-09 support bundle / dashboards** — worth doing, but it is a feature, not a remediation.
- **RC-01 – RC-08 approval** — the documents exist; what is missing is sign-off, not code.

## A correction carried into these plans

The audit's finding **B4** claimed the `AGT-04` xfail named three unfixed production bugs. On
verification, all three were fixed in `4aab49d5` and `ad197961` — **two hours after** the xfail was
written in `6903d6db`, and nobody removed it. The xfail's reason text is stale, not accurate.
Plan 2 Task 5 handles it as "verify and delete", not "fix three bugs". The audit note has been
corrected in place.
