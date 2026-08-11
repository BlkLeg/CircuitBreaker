# Documentation, Repository, and Governance — Sprint Implementation Slices

**Companion spec:** [07-documentation-repository-governance.md](./07-documentation-repository-governance.md)
**Status:** Ready for content and repository planning

## Standalone slice plans

- [GOV-1 — Documentation architecture](./slices/gov-1-documentation-architecture.md)
- [GOV-2 — Screenshot and media refresh](./slices/gov-2-media-refresh.md)
- [GOV-3 — Version, license, and contributor truth](./slices/gov-3-version-license-contributor.md)
- [GOV-4 — Repository hygiene and records](./slices/gov-4-repository-hygiene.md)
- [GOV-5 — Repository governance](./slices/gov-5-repository-governance.md)
- [GOV-6 — Reproducible supply chain](./slices/gov-6-reproducible-supply-chain.md)

## Slice GOV-1 — Documentation information architecture

**Requirements:** GOV-05, GOV-06, GOV-07, GOV-08
**Depends on:** RC support and deployment decisions

- [ ] Inventory pages, duplicate installation names, missing navigation, stale claims, and generated site state.
- [ ] Define authoritative pages for deployment comparison, support, operations, configuration, API/CLI,
  security/privacy, troubleshooting, migration, compatibility, and release notes.
- [ ] Consolidate installation recommendations and update MkDocs navigation.
- [ ] Generate API/CLI/config references where possible and run examples in docs CI.
- [ ] Remove tracked generated site output or document and automate its required publication workflow.

**Verification:** Link/nav/build checks pass and sampled user journeys reach one current answer.

## Slice GOV-2 — Screenshot and media refresh

**Requirements:** GOV-01, GOV-02, GOV-03, GOV-04
**Depends on:** Stable RC UI for final capture; automation can start earlier

- [ ] Add Markdown/media link validation and preserve `docs/assets/screenshots/` as canonical.
- [ ] Inventory all 16 restored assets for UI freshness, secrets, names, addresses, and personal data.
- [ ] Build deterministic anonymized fixtures and screenshot capture where practical.
- [ ] Refresh/approve required install, OOBE, agent, discovery, monitor, backup, mobile, empty/error,
  and accessibility media with source version metadata.
- [ ] Produce architecture/deployment visuals and the physical remote-site agent demo.

**Verification:** Media review checklist and link scan pass against the RC documentation build.

## Slice GOV-3 — Version, license, and contributor truth

**Requirements:** GOV-09, GOV-10, GOV-11, GOV-14
**Depends on:** RC versioning policy

- [ ] Inventory all version/license/contact/branch references and root developer commands.
- [ ] Make `VERSION` the hand-edited source and generate or verify every dependent display/artifact.
- [ ] Align/remove Poetry and duplicate Node metadata; ensure build scripts leave tracked files clean.
- [ ] Correct contribution branch/check names, license, security contact, and add root `SECURITY.md`.
- [ ] Make root test commands meaningful or replace them with documented workspace commands.

**Verification:** Automated parity/license/contact checks pass and a release build leaves no manifest diff.

## Slice GOV-4 — Repository hygiene and historical records

**Requirements:** GOV-12, GOV-13
**Depends on:** Read-only secret/history review before removal

- [ ] Classify suspicious root files, IDE state, E2E env, uploads, lint output, generated site, reports,
  plans, and user/generated artifacts as retain, ignore, relocate, redact, or remove.
- [ ] Check git history and current files for credentials or personal data before changing them.
- [ ] Add examples/fixtures where required and tracked-file policy checks to prevent recurrence.
- [ ] Index reports/plans by date/status/supersession and promote durable decisions into ADRs.

**Verification:** Repository policy scan passes and no historical source of truth remains ambiguously current.

## Slice GOV-5 — Repository governance

**Requirements:** GOV-15, GOV-16, GOV-17
**Depends on:** RC owner model

- [ ] Reconcile documented branches/checks with actual GitHub protection settings.
- [ ] Add CODEOWNERS for security, migrations, packaging, agent protocol, and release workflows.
- [ ] Place issue and PR templates in GitHub-recognized standard locations.
- [ ] Publish semver, deprecation, supported lifetime, security patch, changelog, release captain,
  rollback authority, and emergency procedures.
- [ ] Exercise reviewer routing, templates, release sign-off, and rollback authority in a tabletop.

**Verification:** GitHub settings evidence and tabletop record are stored in the release ledger.

## Slice GOV-6 — Reproducible supply chain

**Requirements:** GOV-18, GOV-19, GOV-20
**Depends on:** Supported artifact matrix

- [ ] Pin or govern all downloaded build tools, including nfpm, with update ownership.
- [ ] Produce checksums, signatures, SBOMs, and provenance bound to commit/version/artifact digest.
- [ ] Publish user verification steps and test them on clean systems.
- [ ] Gate promotion on artifact installation acceptance; define stable-channel deprecation/rollback.

**Verification:** A clean verifier authenticates every artifact and promotion cannot precede acceptance.
