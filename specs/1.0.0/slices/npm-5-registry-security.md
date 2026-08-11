# NPM-5 — Registry Security and Publication

**Requirements:** NPM-12, NPM-13, NPM-14, NPM-15
**Depends on:** NPM-4, GOV-6

## Build sequence

1. Configure organization/package ownership with enforced MFA, at least two maintainers, recovery
   owners, minimal teams, notification contacts, quarterly review, and offboarding procedure.
2. Configure npm trusted publishing/OIDC from a protected GitHub environment restricted to the release
   workflow and accepted commit/digest. Avoid long-lived automation tokens; scope any unavoidable token.
3. Require checks, human approval, immutable environment, package content scan, installed dependency
   scan, SBOM, provenance, and exact-tarball acceptance before publish.
4. Publish prereleases to `next`; verify registry provenance/content/install, then promote the same
   version to `latest` only after EXEC authorization. Never rebuild for promotion.
5. Enable integrity/name monitoring and define compromise response: freeze publish, revoke credentials,
   notify users, deprecate affected versions, rotate trust, and publish corrected patch. Avoid normal
   unpublish/overwrite rollback.
6. Tabletop compromised maintainer, workflow injection, bad RC, bad stable, and registry outage.

## Verification and done

Registry settings screenshots/export, provenance verification, denied unauthorized workflow attempt,
access review, and tabletop records enter the ledger. Done means only the accepted release path can
publish/promote and compromise recovery has named authority.
