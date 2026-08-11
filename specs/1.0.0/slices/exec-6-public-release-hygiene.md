# EXEC-6 — Public Release Hygiene

**Requirement:** EXEC-06
**Depends on:** Stable UI/artifact contracts; preparation may start earlier

## Implementation sequence

1. Complete canonical docs/navigation, current anonymized media, support/operations/security/privacy/API/
   CLI/migration/compatibility content, and strict docs builds.
2. Unify version/license/contact/contributor truth and standard root commands.
3. Complete reviewed repository cleanup, tracked-file policy, and historical report/ADR index.
4. Verify actual branch protection, CODEOWNERS, templates, semantic/support/security/release/rollback
   policies, and emergency authority.
5. Pin build inputs; generate/verify checksums, signatures, SBOMs, provenance, and promotion controls.
6. If npm is in scope, complete selected package, tarball/platform/registry security, docs, and gate. If
   excluded, remove 1.0 npm promises and record deferral.
7. Review every public claim and asset against the final support matrix and exact RC.

## Done

GOV-01 through GOV-20 and all in-scope NPM requirements pass; the public repository describes exactly
what the candidate delivers and exposes no placeholder, stale, private, or unverified material.
