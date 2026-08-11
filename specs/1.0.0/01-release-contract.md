# 1.0.0 Release Contract

**Status:** Draft for product and architecture decision
**Owners:** Release owner, product owner, security owner, operations owner

## Outcome

Circuit Breaker 1.0.0 has one published, internally consistent support contract. Users can determine
what is stable, what is supported, how upgrades work, and what availability and recovery promises
apply without inferring them from implementation details.

## Requirements

| ID | Requirement | Acceptance |
|---|---|---|
| RC-01 | Freeze the 1.0 feature scope and identify every deferred feature and known limitation. | Versioned scope document approved before RC1; release changes require explicit scope review. |
| RC-02 | Publish supported server OS/distributions, architectures, PostgreSQL/Timescale versions, browsers, agent platforms, and deployment modes. | Every acceptance job maps to a support-matrix row; no untested row is called supported. |
| RC-03 | Decide and record single-node versus HA, Linux-only boundaries, IPv6 level, internet-exposed versus LAN/VPN operation, multi-tenancy, offline/air-gap behavior, and public API/SDK stability. | One or more accepted ADRs state each decision and its consequences. |
| RC-04 | Define API, database, server/agent, and CLI compatibility windows, upgrade order, deprecation policy, and minimum supported source version. | Compatibility table includes allowed, blocked, and degraded combinations and is exercised by ACC-12. |
| RC-05 | Define service SLOs and the meaning of liveness, readiness, startup health, and degraded operation. | Targets and measurement windows are published; SRV-03 and REL-21 tests produce the named metrics. |
| RC-06 | Define RPO, RTO, backup retention, data-retention defaults, and maximum supported scale. | Values are evidence-based and validated by ACC-09 through ACC-15 and REL-21 through REL-26. |
| RC-07 | Assign an accountable owner to every acceptance-matrix row and production risk. | Ledger contains owner, automated/manual mode, environment, evidence, and current disposition. |
| RC-08 | Maintain one risk and exception register. Every exception has owner, rationale, compensating control, expiry, and release approval. | No unexplained skip, xfail, warning, scan suppression, or unmet gate remains at sign-off. |

## Product decisions that cannot remain implicit

- Whether alerting without maintenance windows is acceptable for 1.0.
- Which discovery mechanisms are stable and which remain beta.
- Whether IPv4-only operation is the supported boundary.
- Which destructive actions require confirmation, reauthentication, typed acknowledgement, backup,
  or multiple-party approval.
- The export/import and data-ownership escape hatch promised to users.
- Privacy treatment for discovered devices, uploads, credentials, telemetry, and external
  threat/weather/geocoding requests.

Each decision must appear in the UI and documentation wherever a reasonable user could otherwise
form a broader expectation.

## Evidence format

Release evidence must identify the Git commit, artifact digest, environment image or host details,
configuration, command or manual procedure, start/end time, result, logs/screenshots/report, and
reviewer. Links that can be overwritten are insufficient unless the immutable artifact is retained.

## Non-goals

- Choosing ambitious support promises merely to match currently available build targets.
- Treating undocumented behavior as a compatibility commitment.
- Allowing an exception to silently redefine the product contract.
