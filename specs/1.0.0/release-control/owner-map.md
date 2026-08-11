# 1.0.0 Owner and Reviewer Map

**Status:** Draft pending named-person assignment
**Requirements:** RC-07, RC-08

The ledger uses role placeholders until sprint planning assigns named directly responsible
individuals. Replacing a placeholder with a person or team handle is an RC-3 follow-up and does not
change the validation schema.

| Requirement prefix | Accountable owner | Default reviewer | Scope |
|---|---|---|---|
| `RC` | release-owner | product-owner | Release contract and product/architecture decisions |
| `SEC` | security-owner | release-owner | Security boundary, scans, auth, tenant, SSRF, secrets, destructive actions |
| `AGT` | agent-owner | release-owner | cb-agent artifact, enrollment, remote site, fleet, recovery |
| `SRV` | operations-owner | architecture-owner | Headless server, workers, lifecycle, config, observability, remote access |
| `ACC` | qa-owner | release-owner | Artifact acceptance, E2E matrix, upgrade, backup, restore, failure injection |
| `REL` | reliability-owner | architecture-owner | Reliability semantics, coverage, load, capacity, retention, soak |
| `GOV` | governance-owner | release-owner | Documentation, repository hygiene, versioning, supply chain governance |
| `NPM` | distribution-owner | security-owner | npm package purpose, publishing, registry security, installed package gates |
| `EXEC` | release-owner | operations-owner | Milestone execution, RC production, soak, final sign-off, rollback |

## Escalation route

1. Requirement owner resolves implementation/evidence issues inside the owning slice.
2. Reviewer rejects incomplete or mutable evidence.
3. Release owner arbitrates cross-slice conflicts and evidence invalidation.
4. Security owner has veto authority over P0/P1 security exceptions and public-exposure decisions.
5. Product owner has veto authority over user-facing scope and support-promise expansion.
