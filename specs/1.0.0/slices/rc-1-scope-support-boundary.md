# RC-1 — Scope and Support Boundary

**Requirements:** RC-01, RC-02, RC-03
**Type:** Product/architecture decision slice
**Entry:** 1.0 audit accepted as input
**Exit:** Approved scope, support matrix, ADRs, and known-limitations inventory

## Objective

Replace implicit support claims with one version-controlled 1.0 contract. This slice changes no
runtime behavior; any unsupported current claim becomes a later implementation or removal task.

## Repository touchpoints

- `README.md`, `docs/index.md`, `docs/roadmap.md`, `docs/installation/`, `docs/deployment-security.md`
- `docs/1.0.0-release-readiness-audit.md` and `specs/1.0.0/`
- `.github/workflows/{ci,build,release}.yml`, `packaging/`, `deploy/`
- `VERSION`, root/frontend package manifests, backend packaging metadata, agent build workflows

## Implementation tasks

1. Generate a claims inventory with columns: claim, source file/line, current evidence, proposed
   status, owner, and affected acceptance row. Search UI strings and packaging workflow matrices in
   addition to documentation.
2. Freeze features as supported, beta, deferred, or removed. Each deferred/removed item must name
   its UI/API/docs cleanup; “present in code” does not imply supported.
3. Define server and agent OS/architecture, browser engines/versions, PostgreSQL/Timescale versions,
   deployment modes, and network exposure assumptions.
4. Write ADRs deciding HA, Linux-only limits, IPv6, internet exposure, multi-tenancy, air-gap
   enrollment/update, and API/SDK stability. State rejected alternatives and upgrade impact.
5. Map every supported matrix row to an ACC/AGT job or manual UAT owner. Narrow the claim if no
   credible pre-release evidence environment exists.
6. Create a known-limitations section suitable for release notes and in-product help.

## Verification

```bash
rg -n "support|supported|Linux|Windows|macOS|arm64|x86_64|PostgreSQL|Timescale|IPv6|HA|multi-tenant" \
  README.md docs packaging .github apps/frontend/src
```

- Review every hit against the claims inventory.
- Confirm each supported matrix row has an evidence owner and environment.
- Confirm product, architecture, security, operations, and release owners approve the same revision.

## Rollout and rollback

Publish the contract before RC implementation freezes. Rollback is a version-control revert before
publication; after an RC is public, narrowing a promise requires release-note correction and user
impact review rather than silently editing the page.

## Definition of done

RC-01 through RC-03 have immutable approvals, every public claim is consistent, and downstream
work can decide behavior without guessing the product boundary.
