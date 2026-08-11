# EXEC-5 — Whole-Product Acceptance Milestone

**Requirement:** EXEC-05
**Depends on:** EXEC-2, EXEC-3, EXEC-4

## Implementation sequence

1. Freeze compatible server, agent, native package, container, UI, CLI, and optional npm RC artifacts
   by digest. Acceptance retrieves these artifacts; it does not rebuild them.
2. Execute fresh installs, core journeys, browser/accessibility/visual, operations, upgrades/migrations,
   backup/restore, historical issues, failure/destructive/portability/package/export gates.
3. Execute delivery/concurrency, bounds/retention, proxy/lifecycle, critical coverage, browser infra,
   load baselines, overload limits, and 24-hour pre-RC soak.
4. Reject evidence with wrong digest, unsupported environment, incomplete journey, source-only substitute,
   mutable link, missing diagnostics, or indirect proof.
5. Label impacted requirements and invalidate/rerun evidence after every candidate change.
6. Produce supported-limit, RPO/RTO, compatibility, warning, and issue-closure reports.

## Done

ACC-01 through ACC-21 and REL-01 through REL-26 pass against one compatible RC set with no unexplained
loss/duplicate, missing platform, unproven restore, stale evidence, or unsupported claim.
