# Release Contract — Sprint Implementation Slices

**Companion spec:** [01-release-contract.md](./01-release-contract.md)
**Status:** Ready for estimation
**Change type:** Decisions, ADRs, release metadata, and documentation

## Working rules

- Complete Slice RC-1 before implementation teams rely on a support promise.
- Assign one directly responsible individual to each deliverable during sprint planning.
- Decision documents must state the chosen option, rejected options, migration impact, and the
  requirement IDs they satisfy.

## Standalone slice plans

- [RC-1 — Scope and support boundary](./slices/rc-1-scope-support-boundary.md)
- [RC-2 — Compatibility and service objectives](./slices/rc-2-compatibility-service-objectives.md)
- [RC-3 — Ownership, evidence, and exceptions](./slices/rc-3-ownership-evidence-exceptions.md)

## Slice RC-1 — Scope and support boundary

**Requirements:** RC-01, RC-02, RC-03
**Depends on:** None

- [ ] Inventory current feature, deployment, platform, architecture, browser, database, agent, and
  network claims from README, docs, packaging workflows, UI text, and release metadata.
- [ ] Hold the 1.0 scope review and classify each claim as supported, beta, deferred, or removed.
- [ ] Decide HA, Linux-only boundaries, PostgreSQL/Timescale versions, IPv6, exposure model,
  multi-tenancy, air-gap behavior, and public API/SDK stability.
- [ ] Write the support matrix and ADRs; identify acceptance jobs required for every supported row.
- [ ] Create explicit known-limitations entries for every beta or unsupported boundary.

**Verification:** Product, architecture, security, and operations owners approve the same versioned
matrix; every supported row has an ACC/AGT test owner and no public page makes a broader claim.

## Slice RC-2 — Compatibility and service objectives

**Requirements:** RC-04, RC-05, RC-06
**Depends on:** RC-1; initial capacity and recovery baselines may run in parallel

- [ ] Define API, database, CLI/server, and agent/server compatibility windows and upgrade order.
- [ ] Define semantic deprecation stages, notices, duration, and removal criteria.
- [ ] Define liveness, startup, readiness, degraded service, and user-visible availability.
- [ ] Propose measurable SLOs plus RPO, RTO, backup retention, data retention, and scale limits.
- [ ] Reconcile proposed promises with existing measurement capability; open implementation tasks
  where metrics or evidence are missing.

**Verification:** Compatibility examples cover safe, degraded, and blocked combinations; every
objective names its metric, window, evidence source, and responsible owner.

## Slice RC-3 — Ownership, evidence, and exceptions

**Requirements:** RC-07, RC-08
**Depends on:** RC-1

- [ ] Create the release evidence ledger schema and populate one row per requirement ID.
- [ ] Assign accountable owner and reviewer for every requirement and production risk.
- [ ] Consolidate active risks, suppressions, skips, xfails, and warnings into one register.
- [ ] Define exception creation, security review, compensating control, expiry, renewal, and closure.
- [ ] Define evidence invalidation when later code, configuration, artifact, or support claims change.

**Verification:** Automated completeness check finds every RC/SEC/AGT/SRV/ACC/REL/GOV/NPM/EXEC ID
exactly once in the ledger; a tabletop exception and evidence-invalidation exercise succeeds.

## Sprint handoff

Deliver the approved scope/support matrix, ADR set, compatibility policy, objectives, evidence
ledger, ownership map, and risk/exception register. Do not mark RC-* complete from draft decisions.
