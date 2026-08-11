# EXEC-7 — Release Candidate Assembly and Audit

**Requirement:** EXEC-07
**Depends on:** EXEC-2 through EXEC-6

## Implementation sequence

1. Select the accepted commit and clean protected build environment. Derive `VERSION`; build each
   artifact once and record inputs, logs, digest, signature, SBOM, and provenance.
2. Stage—do not promote—native/container/agent/CLI/optional npm, docs, release manifest, checksums,
   verification, notes, limitations, migration, upgrade order, backup prerequisite, rollback, and posture.
3. Audit the ledger for missing/duplicate IDs, wrong/stale digest, unsupported environment, mutable or
   missing evidence, unreviewed result, expired exception, unexplained warning/skip/xfail, open issue,
   and invalidated evidence.
4. Run clean installation and signature/provenance/version smoke directly from staging.
5. Compare staged bytes with accepted evidence. Any rebuild requires new identity and affected acceptance.
6. Freeze scope; only governed release blockers/regressions may alter the candidate.

## Done

The staged candidate is byte-for-byte the accepted artifact set, user documentation is complete, and
the ledger audit has no unexplained defect. Staging is not stable/latest promotion.
