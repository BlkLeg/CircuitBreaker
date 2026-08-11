# REL-4 — Coverage and Critical-Path Test Depth

**Requirements:** REL-13, REL-14, REL-15, REL-16

## Build sequence

1. Define coverage source roots and explicit generated/vendor/unreachable exclusions. Measure the full
   PostgreSQL backend suite and frontend suite before setting thresholds.
2. Tag auth, RBAC, tenancy, migrations, backup/restore, agent protocol/update, audit, secrets, and
   destructive admin modules; require 90%+ branch coverage per critical group, not only aggregate.
3. Set an honest backend repository ratchet above 55.42% and frontend line/branch thresholds for API
   clients and critical state. Subset tests must not publish or enforce misleading aggregate coverage.
4. Add selective mutation jobs for authorization/tenant/protocol validators. Seed known mutations to
   prove the harness and set a reviewed mutation score.
5. Add property/fuzz corpora for URL/CIDR/address validation, frame codecs, parsers, imports, archive
   paths, and backup manifests; retain minimized regressions.
6. Publish reports by commit and fail threshold regression, missing critical module, or collection gap.

## Verification and done

Run full suites with branch coverage, deliberately introduce a missed authorization branch and known
mutants, and confirm gates fail. Done means thresholds measure executed production code and risk—not
test count or excluded files—and fuzz/mutation failures are reproducible by seed/corpus.
