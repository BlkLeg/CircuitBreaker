# EXEC-9 — Final Sign-off, Promotion, and Rollback Readiness

**Requirement:** EXEC-09
**Depends on:** EXEC-8

## Final sequence

1. Re-run ledger validation and review every P0, gate, exception, platform, #66–#101 case, RPO/RTO,
   supported limit, compatibility row, and known limitation.
2. Security, operations, product, agent, server, packaging, docs, and release owners sign their scopes;
   absence is NO-GO, not implied consent.
3. Rollback authority executes a staging rollback using published commands/backups and verifies
   data/schema/binary/agent compatibility plus communication steps.
4. Record commit/version, all artifact/docs digests, tag, manifest, targets, timestamps, approvers,
   contacts, and rollback thresholds.
5. Create signed tag/release without rebuilding. Promote existing accepted container/npm references
   only after authorization; verify public checksums, provenance, SBOM, and downloads.
6. Run public-endpoint install/version/health smoke and begin heightened monitoring.
7. On failure, stop promotion, invoke rollback/deprecation, preserve evidence, and never overwrite a release.

## Stop conditions and done

Failed P0, identity mismatch, unsupported claim, expired exception, missing signature, unexecutable
restore/rollback, or missing signature keeps NO-GO. Done requires accepted bytes publicly promoted,
post-promotion smoke green, signed matrix/rollback retained, and incident monitoring active.
