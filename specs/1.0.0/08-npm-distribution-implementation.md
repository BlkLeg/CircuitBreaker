# npm Distribution — Sprint Implementation Slices

**Companion spec:** [08-npm-distribution.md](./08-npm-distribution.md)
**Status:** Blocked on product-purpose decision

## Standalone slice plans

- [NPM-1 — Product and namespace](./slices/npm-1-product-namespace.md)
- [NPM-2A — Administration/installer CLI](./slices/npm-2a-cli.md)
- [NPM-2B — API client/SDK](./slices/npm-2b-sdk.md)
- [NPM-3 — Manifest and tarball](./slices/npm-3-manifest-tarball.md)
- [NPM-4 — Platform and failure acceptance](./slices/npm-4-platform-failure.md)
- [NPM-5 — Registry security](./slices/npm-5-registry-security.md)
- [NPM-6 — Documentation and final gate](./slices/npm-6-documentation-final-gate.md)

## Slice NPM-1 — Product and namespace decision

**Requirements:** NPM-01, NPM-02
**Depends on:** RC scope and API stability decisions

- [ ] Compare administration/installer CLI and API SDK options against user need, maintenance cost,
  platform support, and existing artifact strategy.
- [ ] Choose package name, scope, commands/API, supported Node/platform matrix, and semver relationship.
- [ ] Reserve/verify the namespace before public documentation promises it.
- [ ] Create a dedicated package boundary and ensure the repository root remains private/unpublishable.

**Verification:** Approved ADR states one package purpose and release ownership; no hybrid package scope remains.

## Slice NPM-2A — Administration/installer CLI

**Requirements:** NPM-03
**Runs only if:** CLI is selected

- [ ] Define artifact resolution, platform mapping, explicit install/update/uninstall commands, and
  noninteractive output/exit codes.
- [ ] Verify checksum, signature, and provenance before any installation mutation.
- [ ] Define privilege prompts, interrupted-operation journal, rollback, proxy, and offline behavior.
- [ ] Add clean-runner install/status/update/rollback/uninstall tests using signed candidates.

**Verification:** Corrupt or mismatched artifacts fail closed before privileged changes.

## Slice NPM-2B — API client/SDK

**Requirements:** NPM-04
**Runs only if:** SDK is selected

- [ ] Define generated/manual client boundary, TypeScript types, error model, authentication, retries,
  supported server API versions, and independent semver.
- [ ] Add contract generation drift checks and tests against every supported server version.
- [ ] Document browser/Node runtime support, bundling, and security considerations.

**Verification:** Published types/runtime behavior match the accepted OpenAPI contract and compatibility matrix.

## Slice NPM-3 — Package manifest and allowlisted tarball

**Requirements:** NPM-05, NPM-06, NPM-07
**Depends on:** NPM-1 and selected NPM-2 path

- [ ] Add accurate manifest identity, support links, engines/OS/CPU, bin or exports, and MIT license.
- [ ] Define `files` allowlist, `.npmignore` defense, size/count budgets, and source-map policy.
- [ ] Exclude env files, credentials, uploads, secret fixtures, caches, reports, and monorepo assets.
- [ ] Run `npm pack --dry-run`, inspect unpacked tarball, and fail unexpected contents.

**Verification:** The packed tarball contains only documented runtime, license, and user documentation files.

## Slice NPM-4 — Platform and failure acceptance

**Requirements:** NPM-08, NPM-09, NPM-10, NPM-11
**Depends on:** NPM-3

- [ ] Test exact `.tgz` on all claimed Linux/macOS/Windows, Node, and package-manager combinations.
- [ ] Cover offline, proxy, interruption, unsupported OS/arch, integrity mismatch, permissions, update,
  rollback where promised, and uninstall.
- [ ] Prove lifecycle scripts perform no download or privileged mutation.
- [ ] Enforce parity among package, `VERSION`, tag, release, artifacts, labels, and reported version.

**Verification:** Clean-runner matrix passes with actionable errors and recoverable state.

## Slice NPM-5 — Registry security and publication

**Requirements:** NPM-12, NPM-13, NPM-14, NPM-15
**Depends on:** NPM-4, GOV supply-chain controls

- [ ] Require organization MFA, two maintainers, recovery ownership, and periodic access review.
- [ ] Configure trusted publishing/OIDC, protected environment, provenance, and accepted-commit gate.
- [ ] Scan packed and installed dependencies and include the package in the release SBOM.
- [ ] Publish RCs to `next`; promote `latest` only after exact-tarball acceptance.
- [ ] Tabletop compromise, deprecation, corrected-patch, and revocation procedures.

**Verification:** Provenance verifies publicly, no long-lived token is used where avoidable, and a
nonaccepted commit cannot publish or promote.

## Slice NPM-6 — User documentation and final gate

**Requirements:** Completes NPM-01 through NPM-15
**Depends on:** NPM-5

- [ ] Publish purpose, prerequisites, platforms, privileges, proxy/offline/network/telemetry behavior,
  verification, update/uninstall, and native/container relationship.
- [ ] Automate every published `npm`, `npx`, or alternative package-manager example.
- [ ] Run exact `.tgz` install and applicable status/update/uninstall journey; verify provenance,
  downloaded artifacts, versions, checksums, tag, and SBOM.

**Verification:** NPM release gate passes before any `latest` promotion.
