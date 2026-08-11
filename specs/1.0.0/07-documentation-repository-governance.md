# Documentation, Repository, and Governance Specification

**Status:** Draft

## Outcome

The public repository and documentation accurately describe the supported 1.0 product, contain no
placeholder or user-generated material, and provide a reproducible, governed release process.

## Documentation and media

| ID | Requirement | Acceptance |
|---|---|---|
| GOV-01 | Keep `docs/assets/screenshots/` canonical and protect every Markdown/media target with link checking. | README and docs builds have no broken links or missing local media. |
| GOV-02 | Review, anonymize, and refresh or explicitly approve all 16 restored historical screenshots against the RC UI. | Each asset records source version/date and reviewer; no environment secrets or personal data remain. |
| GOV-03 | Add current media for install/OOBE, agent enrollment/fleet, discovery/import, agent monitor, backup/restore, mobile, empty/error, and accessibility states. | Required journeys have approved captures; screenshot automation is used where practical. |
| GOV-04 | Add architecture and deployment-mode comparisons plus a 2–3 minute real remote-site agent demo with no inbound firewall rule. | Media matches RC behavior and support contract. |
| GOV-05 | Consolidate overlapping installation-mode names and recommendations. | A user can choose native, mono, or split mode from one authoritative comparison. |
| GOV-06 | Publish platform/browser support, sizing, ports, data directories, backup scope, upgrade/rollback, agent security/permissions/outbound/scope/update/uninstall, and troubleshooting trees. | Content maps to RC-02/RC-06 and tested ACC procedures. |
| GOV-07 | Publish API/CLI reference, config precedence/env catalog/examples, threat model, hardening, disclosure, privacy, security-update policy, migration guide, and compatibility table. | Generated references match the RC; examples run in docs CI where possible. |
| GOV-08 | Include new feature docs and release notes in MkDocs navigation; do not keep stale generated `site/` output unless deployment requires it. | Source is canonical and docs build reproducibly. |

## Repository and version truth

| ID | Requirement | Acceptance |
|---|---|---|
| GOV-09 | `VERSION` is the sole hand-edited version; manifests, runtime UI/API/CLI, agent manifests, artifacts, Docker labels, tags, and docs derive from it. | CI detects disagreement and build steps do not dirty tracked manifests. |
| GOV-10 | Align or remove legacy backend Poetry version metadata and duplicate nonfunctional Node manifests. | No contradictory package identity/version/license remains. |
| GOV-11 | Correct `CONTRIBUTING.md` branch names, security contact, and license; add root `SECURITY.md`. | Contacts are real and monitored; LICENSE and all package metadata agree. |
| GOV-12 | Review/remove/relocate suspicious `-H`, `-d`, `=1.9.0`, `.idea/`, agent E2E `.env`, profile uploads, `eslint_output.json`, generated `site/`, and other generated/user artifacts. | Tracked-file policy test prevents recurrence; secrets/history are reviewed before removal. |
| GOV-13 | Index historical security reports/plans and mark superseded material; preserve durable decisions as ADRs/release records. | Readers can identify the current source of truth without contradictory active plans. |
| GOV-14 | Root developer commands have useful behavior; root `npm test` must not fail by design. | Documented root commands pass or are removed in favor of explicit workspace commands. |

## Governance and supply chain

| ID | Requirement | Acceptance |
|---|---|---|
| GOV-15 | Verify branch protection and required checks; document the actual branch names/check names. | Repository settings evidence is retained for RC, not merely described. |
| GOV-16 | Add CODEOWNERS for security, migrations, packaging, agent protocol, and release workflows and standard issue/PR template paths. | Test PRs request intended reviewers and GitHub recognizes templates. |
| GOV-17 | Publish semantic versioning, deprecation, supported lifetime, security patch, changelog, release-captain, rollback-authority, and emergency procedures. | EXEC-07 sign-off names the policy and authorized people. |
| GOV-18 | Pin or govern build-tool downloads, including replacing `NFPM_VERSION=latest`. | Rebuilding an RC uses immutable tool identities and produces explainable outputs. |
| GOV-19 | Generate checksums, signatures, SBOMs, provenance/attestations, and user verification steps. | All supported artifacts verify; metadata binds to the same commit/version. |
| GOV-20 | Run artifact installation gates before publication and never move a stable/latest channel until acceptance passes. | Promotion is an explicit post-acceptance action with rollback/deprecation procedure. |
