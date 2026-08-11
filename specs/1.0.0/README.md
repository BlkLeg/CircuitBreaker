# Circuit Breaker 1.0.0 Production-Readiness Specifications

**Date:** 2026-08-10
**Status:** Draft for review
**Source:** `docs/1.0.0-release-readiness-audit.md` at audited revision `49c5b775`

## Purpose

This directory turns every actionable requirement in the 1.0.0 release-readiness audit into a
testable product or release specification. These documents define outcomes and evidence; they do
not authorize implementation or change the current **NO-GO** recommendation.

## Specification set

| Spec | Implementation slices | Requirement IDs | Scope |
|---|---|---|---|
| [Release contract](./01-release-contract.md) | [Implementation](./01-release-contract-implementation.md) | RC-* | Scope, support, compatibility, SLOs, ownership, exceptions |
| [Security and trust](./02-security-and-trust.md) | [Implementation](./02-security-and-trust-implementation.md) | SEC-* | Tenancy, authorization, bootstrap, dependencies, SSRF, rate limits, secrets, uploads, audit |
| [cb-agent production readiness](./03-cb-agent-production-readiness.md) | [Implementation](./03-cb-agent-production-readiness-implementation.md) | AGT-* | Composed gate, remote-site UAT, ARM64 defects, UX, safety, recovery |
| [Server product contract](./04-server-product-contract.md) | [Implementation](./04-server-product-contract-implementation.md) | SRV-* | Headless mode, workers, lifecycle, configuration, admin, observability, remote access |
| [Artifact acceptance and recovery](./05-artifact-acceptance-and-recovery.md) | [Implementation](./05-artifact-acceptance-and-recovery-implementation.md) | ACC-* | E2E matrix, installs, upgrades, backup/restore, browser, packaging, failure injection |
| [Reliability, quality, and capacity](./06-reliability-quality-capacity.md) | [Implementation](./06-reliability-quality-capacity-implementation.md) | REL-* | Concurrency, delivery semantics, retention, coverage, soak and performance gates |
| [Documentation, repository, and governance](./07-documentation-repository-governance.md) | [Implementation](./07-documentation-repository-governance-implementation.md) | GOV-* | Docs/media, repository hygiene, versions, governance, supply chain |
| [npm distribution](./08-npm-distribution.md) | [Implementation](./08-npm-distribution-implementation.md) | NPM-* | Package purpose, contents, security, publishing, platform acceptance |
| [Release execution](./09-release-execution.md) | [Implementation](./09-release-execution-implementation.md) | EXEC-* | Phases, evidence ledger, final gate, sign-off and rollback authority |

## Audit-to-spec traceability

| Audit section | Owning requirements |
|---|---|
| R1 tenant isolation | SEC-01 through SEC-05 |
| R2 route authorization | SEC-06 through SEC-10 |
| R3 systemic security debt | SEC-11 through SEC-18 |
| R4 backup, restore, migration, upgrade | ACC-09 through ACC-15 |
| R5 issues #66-#101 | AGT-10 through AGT-12, ACC-16 |
| A1 composed agent journey | AGT-01 through AGT-04 |
| A2 remote-site acceptance | AGT-05 through AGT-09 |
| A3 agent UX and safety | AGT-13 through AGT-18 |
| Server architecture and non-goals | RC-01 through RC-08, SRV-01 through SRV-10 |
| Complete E2E matrix | ACC-01 through ACC-21 |
| Reliability and implementation gaps | REL-01 through REL-12 |
| Test strategy and coverage | REL-13 through REL-20 |
| Documentation and media | GOV-01 through GOV-08 |
| Version/repository/governance | GOV-09 through GOV-20 |
| npmjs packaging | NPM-01 through NPM-15 |
| Performance and capacity | REL-21 through REL-26 |
| Delivery phases and final checklist | EXEC-01 through EXEC-09 |

Every release-checklist item in the audit is represented by one or more rows above. If the audit is
amended, this table and the affected spec must change together.

The implementation companions divide each workstream into sprint-sized slices. They are planning
documents, not evidence that a requirement has passed. Slice checkboxes remain open until the work
is implemented and its named verification has run against the required environment or artifact.

## Shared definition of done

A requirement is complete only when:

1. its normative acceptance criteria pass against the exact release-candidate commit;
2. artifact-facing behavior is tested from the signed artifact rather than only a source checkout;
3. the evidence location, environment, owner, date, and result are recorded in the release ledger;
4. failures, skips, warnings, and exceptions are either resolved or approved under RC-08;
5. user-facing contracts and operational documentation are updated; and
6. the release owner confirms that no superseding change invalidated the evidence.

## Normative language

“Must” and “must not” are release requirements. “Should” records a preferred design that may be
changed through an ADR. “May” is optional. A test passing in a development tree is supporting
evidence, not release evidence, unless the requirement explicitly says otherwise.
