# 1.0.0 Owner and Reviewer Map

**Status:** Assigned
**Requirements:** RC-07, RC-08

Circuit Breaker has one codeowner, **shawnji**, who is the accountable owner for every
requirement prefix below. The role names are retained as *functions* — they describe which hat is
being worn when a decision is made — but they all resolve to the same person.

| Requirement prefix | Accountable owner | Reviewer | Scope |
|---|---|---|---|
| `RC` | shawnji (release) | shawnji (product) | Release contract and product/architecture decisions |
| `SEC` | shawnji (security) | shawnji (release) | Security boundary, scans, auth, tenant, SSRF, secrets, destructive actions |
| `AGT` | shawnji (agent) | shawnji (release) | cb-agent artifact, enrollment, remote site, fleet, recovery |
| `SRV` | shawnji (operations) | shawnji (architecture) | Headless server, workers, lifecycle, config, observability, remote access |
| `ACC` | shawnji (qa) | shawnji (release) | Artifact acceptance, E2E matrix, upgrade, backup, restore, failure injection |
| `REL` | shawnji (reliability) | shawnji (architecture) | Reliability semantics, coverage, load, capacity, retention, soak |
| `GOV` | shawnji (governance) | shawnji (release) | Documentation, repository hygiene, versioning, supply chain governance |
| `NPM` | shawnji (distribution) | shawnji (security) | npm package purpose, publishing, registry security, installed package gates |
| `EXEC` | shawnji (release) | shawnji (operations) | Milestone execution, RC production, soak, final sign-off, rollback |

## Owner and reviewer are the same person — recorded deviation

A four-eyes review is the usual control behind a separate `reviewer` column, and this project
cannot provide it: there is exactly one codeowner. Recording a second placeholder name would
manufacture an independence that does not exist, which is worse than naming the constraint.

What actually stands in for the second reviewer:

- **Automated gates that no single reviewer can wave through.** The endpoint policy gate
  (`test_endpoint_policy_inventory.py`) fails on any route whose auth posture changes without the
  policy being updated to match; `validate_v1_release_control.py` recomputes evidence digests and
  rejects `working-tree@` pins; `validate_security_suppressions.py` requires an owner, reason,
  compensating control, and expiry for every scanner suppression. These are the reviewer for
  anything they cover.
- **Adversarial review by an independent agent.** The SEC 1–10 audit
  (`specs/1.0.0/evidence/sec-slices-audit-2026-08-13.md`) was produced by a reader that did not
  write the code, and its findings were tracked to closure rather than self-assessed.
- **Expiry on every exception.** Nothing is waived indefinitely; each entry in
  `exception-register.csv` has to be re-approved at its expiry date.

This deviation is tracked as `EXC-002`.

## Escalation route

With a single owner there is no escalation path between people, so the route below describes the
order in which the hats must be satisfied — a later step cannot be skipped because an earlier one
was performed by the same person.

1. Requirement owner resolves implementation/evidence issues inside the owning slice.
2. Reviewer rejects incomplete or mutable evidence — in practice, the automated gates above.
3. Release owner arbitrates cross-slice conflicts and evidence invalidation.
4. Security owner has veto authority over P0/P1 security exceptions and public-exposure decisions.
5. Product owner has veto authority over user-facing scope and support-promise expansion.
