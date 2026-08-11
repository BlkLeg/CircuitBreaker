# 1.0.0 Release Execution Specification

**Status:** Draft
**Entry condition:** The release owner accepts this specification set as the planning baseline.

## Outcome

Production readiness is executed in dependency order, evidence remains current, and 1.0.0 is not
tagged or promoted until every mandatory gate is satisfied or governed by an approved exception.

## Delivery sequence

| ID | Phase | Exit criteria |
|---|---|---|
| EXEC-01 | Release definition | RC-01 through RC-08 decided; acceptance owners assigned; one risk register active. |
| EXEC-02 | Trust blockers | SEC-01 through SEC-18 pass; tenant promise is enforced or removed; route inventory is complete. |
| EXEC-03 | Agent readiness | AGT-01 through AGT-18 pass, including physical remote-site sign-off and ARM64 artifact tests. |
| EXEC-04 | Server productization | SRV-01 through SRV-10 pass; headless/admin/lifecycle/compatibility contracts are published. |
| EXEC-05 | Whole-product acceptance | ACC-01 through ACC-21 and REL-01 through REL-26 pass against RC artifacts. |
| EXEC-06 | Release hygiene | GOV-01 through GOV-20 pass; if npm is in scope, NPM-01 through NPM-15 pass. |
| EXEC-07 | RC production | Signed artifacts, checksums, SBOM/provenance, release notes, migration/rollback instructions, and known limitations are complete. |
| EXEC-08 | RC soak | Approved soak period completes without unresolved regression or scope addition. |
| EXEC-09 | Final sign-off | Release owner signs acceptance matrix and rollback plan; stable/latest promotion is authorized. |

Security and data-integrity work precedes feature expansion. Work inside a later phase may be
prepared earlier, but it cannot supply evidence for an unmet prerequisite.

## Evidence ledger

The release ledger must contain one row per requirement ID with:

- accountable owner and reviewer;
- status: not started, in progress, pass, fail, blocked, or excepted;
- exact commit, version, artifact digest, and environment;
- automated/manual classification and reproducible procedure;
- immutable evidence links and completion date;
- related issue/PR and documentation links;
- exception ID and expiry where applicable; and
- invalidation status if a later change touches the tested surface.

## Mandatory final gate

Before tagging 1.0.0, the ledger must demonstrate:

- tenant and route security boundaries, scans, and supply-chain controls are complete;
- composed and physical-site cb-agent acceptance is signed, including update/rollback and #101;
- all supported fresh-install and upgrade paths pass from signed artifacts;
- backup/restore meets RPO/RTO with encrypted, upload, audit, telemetry, tenant, and agent data;
- browser, accessibility, responsive, console, failure, lifecycle, performance, retention, and soak
  gates pass;
- compatibility/deprecation, support, security, privacy, operations, migration, rollback, and known
  limitations are published;
- version and artifact identity match everywhere;
- docs/media/contact/license/repository hygiene are approved;
- issues #66 through #101 in scope have clean-host evidence or an RC-08 exception;
- npm acceptance passes if npm is part of 1.0;
- no unexplained skip, xfail, async/deprecation/lint warning, or release exception remains; and
- the named rollback authority has verified the rollback plan.

## Change control

Any change after a requirement passes must identify affected requirement IDs. The owner either
re-runs the evidence or records why it remains valid. RC changes fix release blockers and
regressions; they do not add unapproved scope.

## Stop conditions

The release remains NO-GO if any P0 requirement fails, if acceptance evidence does not identify the
artifact users receive, if the support contract exceeds the tested matrix, or if rollback/recovery
cannot be executed by the named operator.
