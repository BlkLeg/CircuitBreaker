# Release Execution — Sprint Implementation Slices

**Companion spec:** [09-release-execution.md](./09-release-execution.md)
**Status:** Ready for release-program scheduling

## Standalone slice plans

- [EXEC-1 — Program bootstrap](./slices/exec-1-program-bootstrap.md)
- [EXEC-2 — Trust milestone](./slices/exec-2-trust-milestone.md)
- [EXEC-3 — Agent milestone](./slices/exec-3-agent-milestone.md)
- [EXEC-4 — Server milestone](./slices/exec-4-server-milestone.md)
- [EXEC-5 — Whole-product acceptance](./slices/exec-5-whole-product-acceptance.md)
- [EXEC-6 — Public release hygiene](./slices/exec-6-public-release-hygiene.md)
- [EXEC-7 — RC assembly and audit](./slices/exec-7-rc-assembly-audit.md)
- [EXEC-8 — Soak and regression control](./slices/exec-8-soak-regression.md)
- [EXEC-9 — Sign-off, promotion, and rollback](./slices/exec-9-signoff-promotion-rollback.md)

## Slice EXEC-1 — Program bootstrap

**Requirements:** EXEC-01
**Depends on:** Release-contract slices

- [ ] Accept the specification set as the planning baseline and record amendments by requirement ID.
- [ ] Populate the evidence ledger, owners, reviewers, dependencies, estimates, milestones, and risks.
- [ ] Establish release dashboards for P0s, failing gates, stale evidence, exceptions, and blockers.
- [ ] Archive or supersede competing active readiness plans.

**Exit:** Scope/support/compatibility/objectives are approved and every requirement has an owner.

## Slice EXEC-2 — Trust milestone

**Requirements:** EXEC-02
**Depends on:** EXEC-1

- [ ] Schedule tenant decision/implementation, endpoint policy, auth/bootstrap, systemic security,
  destructive-action, and scan work in dependency order.
- [ ] Require security-owner review for migrations, data access, public routes, egress, secrets, and
  exceptions.
- [ ] Run the complete SEC gate and attach RC-equivalent evidence.

**Exit:** SEC-01 through SEC-18 pass; unsupported claims are removed and no P0 exception is implicit.

## Slice EXEC-3 — Agent milestone

**Requirements:** EXEC-03
**Depends on:** EXEC-1; security prerequisites for agent identity/authorization

- [ ] Complete composed gate, ARM64 defects, request correctness, monitor workflow, state/error UX,
  fleet safety/recovery, and resource bounds.
- [ ] Freeze an agent RC and execute two-site physical acceptance.
- [ ] Reconcile all AGT evidence and issue #101 records against exact artifact digests.

**Exit:** AGT-01 through AGT-18 pass with signed physical-site evidence.

## Slice EXEC-4 — Server milestone

**Requirements:** EXEC-04
**Depends on:** Release-contract architecture decisions

- [ ] Complete headless, worker ownership, lifecycle, configuration, administration, sizing/deployment,
  observability, and remote-operations slices.
- [ ] Publish compatibility and operator contracts and verify them from artifacts.

**Exit:** SRV-01 through SRV-10 pass and routine operation does not require a browser.

## Slice EXEC-5 — Whole-product acceptance milestone

**Requirements:** EXEC-05
**Depends on:** EXEC-2 through EXEC-4

- [ ] Freeze server, agent, package, container, and UI release candidates by digest.
- [ ] Execute installs, product journeys, browsers/accessibility, upgrades/migrations, recovery,
  historical issues, failures, portability, performance, and soak gates.
- [ ] Invalidate and rerun affected evidence after every candidate change.

**Exit:** ACC-01 through ACC-21 and REL-01 through REL-26 pass against the same compatible RC set.

## Slice EXEC-6 — Public release hygiene

**Requirements:** EXEC-06
**Depends on:** Stable UI and artifact contracts

- [ ] Complete documentation/media, version/license/contact, repository hygiene, governance, and
  reproducible supply-chain work.
- [ ] Complete npm slices only if npm remains in RC-01 scope.
- [ ] Verify public claims against the final support matrix and known limitations.

**Exit:** GOV-01 through GOV-20 and all in-scope NPM requirements pass.

## Slice EXEC-7 — RC assembly and audit

**Requirements:** EXEC-07
**Depends on:** EXEC-2 through EXEC-6

- [ ] Build signed artifacts once from the accepted commit and publish candidate checksums, SBOMs,
  provenance, verification, release notes, migration, rollback, and limitations.
- [ ] Audit the ledger for missing owner, stale digest, incomplete environment, mutable evidence,
  unexplained warning, issue without evidence, or expired exception.
- [ ] Run installation smoke from the publication staging location.

**Exit:** Candidate users receive exactly the artifact set that passed the ledger.

## Slice EXEC-8 — Soak and regression control

**Requirements:** EXEC-08
**Depends on:** EXEC-7

- [ ] Run the approved RC soak with retention, backups, integrations, monitoring, and representative agents.
- [ ] Triage every anomaly; allow only blocker/regression fixes and invalidate affected evidence.
- [ ] Restart the soak or obtain explicit policy-based disposition after material changes.

**Exit:** Soak duration and objectives pass with no unresolved regression or scope addition.

## Slice EXEC-9 — Sign-off, promotion, and rollback readiness

**Requirements:** EXEC-09
**Depends on:** EXEC-8

- [ ] Review every mandatory final-gate statement and exception with named owners.
- [ ] Have rollback authority execute or tabletop the exact rollback plan from published instructions.
- [ ] Record release-owner signature, accepted digests, promotion targets, and incident contacts.
- [ ] Tag and promote stable/latest channels only after authorization; monitor post-promotion checks.

**Exit:** Signed acceptance matrix and rollback plan exist; promotion identities match everywhere.

## Stop rule

Any failed P0, artifact/evidence mismatch, unsupported public claim, expired exception, or unexecutable
recovery plan returns the release to NO-GO. Schedule pressure does not alter this rule.
