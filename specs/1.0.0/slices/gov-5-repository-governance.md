# GOV-5 — Repository Governance

**Requirements:** GOV-15, GOV-16, GOV-17
**Depends on:** RC ownership model

## Primary touchpoints

- `.github/branch-protection.md`, actual GitHub repository settings
- `.github/instructions/ISSUE_TEMPLATE/` and standard `.github/ISSUE_TEMPLATE/`
- New `.github/CODEOWNERS`, pull-request template, release/changelog/security policies

## Build sequence

1. Export/read actual default branch, protections, required reviews, dismissal, admin enforcement,
   required checks, merge methods, tag/environment protection, and compare with documentation.
2. Define stable required-check names and update workflows/docs together. Test on a temporary PR before
   making a renamed check mandatory to avoid deadlock.
3. Add CODEOWNERS for security/auth, migrations/database, packaging/release, agent protocol/update, and
   workflows; ensure at least two viable reviewers for critical areas.
4. Move/add issue and PR templates in GitHub-recognized locations with reproduction, security, migration,
   test/evidence, screenshots, rollout/rollback, and requirement-ID fields.
5. Publish semver, deprecation/support lifetime, security patch, changelog, release-captain checklist,
   rollback authority, emergency release, and access-review policies.
6. Tabletop normal RC, urgent security patch, maintainer unavailable, failed promotion, and rollback.

## Verification and done

Use GitHub settings evidence, test PR reviewer routing/templates/checks, and tabletop records. Done means
actual enforcement matches documentation and critical release authority is not a single undocumented person.
