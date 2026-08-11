# RC-3 — Ownership, Evidence, and Exceptions

**Requirements:** RC-07, RC-08
**Type:** Release-control slice
**Depends on:** RC-1

## Objective

Create the auditable control plane for release evidence so a green claim always identifies an owner,
candidate artifact, environment, immutable result, and review decision.

## Deliverables

- Machine-readable requirement ledger plus a rendered human view
- Owner/reviewer map and escalation route
- Consolidated risk/exception register
- Evidence-bundle schema and invalidation rules
- CI validation for missing, duplicate, stale, or malformed entries

## Implementation tasks

1. Choose a checked-in, reviewable ledger format. Each row must contain requirement ID, owner,
   reviewer, status, commit, version, artifact digest, environment, procedure, evidence URL/digest,
   completion time, issues, exception, and invalidation state.
2. Seed exactly one row for all 145 requirement IDs in the spec set; do not pre-mark draft plans as
   passes.
3. Consolidate active risks, scanner suppressions, skips, xfails, warnings, and historical audit
   findings. Mark superseded sources without deleting useful evidence.
4. Define exception authority, rationale, compensating control, evidence, expiry, renewal, and
   forced-fail behavior after expiry. P0 exceptions require named security/release approval.
5. Define impact labels that invalidate evidence when code, migrations, build inputs, configuration,
   docs claims, or artifacts change.
6. Add a read-only validator and make it a required RC check after the ledger format stabilizes.

## Verification

```bash
rg -o '\b(RC|SEC|AGT|SRV|ACC|REL|GOV|NPM|EXEC)-[0-9]{2}\b' \
  specs/1.0.0/[0-9][0-9]-*.md | sort -u
```

- Compare the canonical ID set with ledger IDs; fail missing, unknown, or duplicate rows.
- Tabletop an expiring exception and a post-pass code change that invalidates evidence.
- Ensure mutable CI URLs are accompanied by retained artifact identity/digest.

## Definition of done

RC-07 and RC-08 pass, every requirement has accountable ownership, and the final release decision can
be reconstructed without relying on chat history or maintainer memory.
