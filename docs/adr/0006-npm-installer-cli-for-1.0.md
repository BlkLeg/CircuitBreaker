# ADR 0006: npm Ships an Installer CLI for 1.0

**Status:** Accepted
**Date:** 2026-09-30
**Supersedes:** [ADR 0004](0004-npm-out-of-scope-for-1.0.md)
**Requirements:** NPM-01 through NPM-15, EXEC-06; RC-03 unchanged
**Decision owner:** shawnji (maintainer), for distribution and security

> **Override — ADR 0004 and EXC-003.** ADR 0004 decided that no Circuit Breaker package is
> published to npm for the 1.0 line, and EXC-003 recorded NPM-01 to NPM-15 as not applicable.
> This ADR reverses that: npm is on the road to 1.0, as an installer CLI. EXC-003 closes, and the
> NPM requirements become open 1.0 work, except NPM-04 (the SDK), which is excepted again under
> EXC-004. To reverse this decision, supersede this ADR the same way.

## Context

ADR 0004 left npm out of 1.0 because nobody had answered NPM-01 — installer CLI or API
client/SDK — and a channel with no answer, no package and no users cost fifteen red ledger rows
and a new supply-chain surface for nothing. Its reopening criteria were: answer NPM-01 first,
reserve and govern the namespace (NPM-12), and publish through trusted publishing with provenance
(NPM-13).

On 2026-09-30 the maintainer decided to include npm in the journey to 1.0 and answered NPM-01:
**an installer CLI.**

## Decision

1. **npm is a 1.0 distribution channel for one package: an installer and management CLI.**
   It is a way into the same install that `install.sh` performs, not a second product.
2. **It installs signed releases, fail-closed.** The CLI downloads the signed server release
   bundle for the host, verifies its checksum, signature and provenance before anything is
   installed, and refuses on any mismatch (NPM-03). It carries every native `cb` command, plus
   install and rollback (see below). Its `preinstall`/`postinstall` scripts download nothing and change nothing on the
   system; every system change follows an explicit command (NPM-10).
3. **It respects air-gap.** With `CB_AIRGAP=true` it makes no outbound request and installs only
   from a bundle it is handed, as `install.sh --local-bundle --airgap` does.
4. **One dedicated package; the repository stays private.** The CLI is its own package (NPM-02).
   The root manifest and `apps/frontend/package.json` stay `private: true`, so nothing else can be
   published by accident.
5. **No SDK.** NPM-04 stays out of scope under EXC-004. RC-03 is unchanged: 1.0 makes no stable
   public API or SDK promise, and the CLI's commands are its only interface.
6. **Until the CLI ships, nothing changes on the user-facing surface.** Documentation and release
   notes must not show `npm install` or `npx` as an installation path until the package is
   published and has passed its NPM gates; advertising a path that does not exist yet is the harm
   ADR 0004 guarded against. `tests/build/test_npm_is_not_a_distribution_channel.py` keeps enforcing
   that — private manifests, no publish workflow, no npm install path in the docs — and is revised
   deliberately in the same change that first publishes the package.

## Approved before implementation (2026-09-30)

NPM-01's acceptance asks for the name, commands, platforms, versioning and relationship to the
server artifacts to be approved before any code is written. The maintainer approved them on
2026-09-30 (evidence: `specs/1.0.0/evidence/npm-01-installer-cli-approval-2026-09-30.md`):

- **Package name:** `@blkleg/circuitbreaker`. The `@blkleg` scope is reserved before the first
  publish (NPM-12).
- **Commands:** every command the native `cb` CLI has carries over — `info`, `status`,
  `resources`, `doctor`, `diag bundle`, `setup`, `setup-token`, `logs`, `restart`, `backup`,
  `restore`, `migrate`, `token`, `user`, `agent`, `config validate`, `vault-recover`, `version`,
  `uninstall` and `help` — plus `install` and `rollback`, which NPM-03 requires. `update` performs
  the native upgrade (`install.sh --upgrade`), where the native `cb update` only points at the
  installer today.
- **Platforms:** Linux only for 1.0, matching the server. Windows development and testing begins
  after v0.5.0; until then Windows is not a claimed platform, and nothing is claimed that NPM-08's
  smoke tests do not cover.
- **Versioning:** lockstep with `VERSION` and the release tags; the package version, tag, GitHub
  Release, downloaded artifacts and reported version agree exactly (NPM-11).
- **Relationship to the server artifacts:** the CLI downloads and verifies the same signed release
  bundles `install.sh` installs; it ships no server code of its own (NPM-03, NPM-05).
- **Maintainers:** one. NPM-12's two-maintainer clause is excepted under **EXC-005**. The
  maintainer's npm account has two-factor authentication; npm organization MFA, documented
  recovery ownership and periodic access review are still required.
- **Publishing credentials:** releases publish through GitHub Actions trusted publishing (OIDC)
  with provenance, from the protected `release` environment (NPM-13). Where OIDC cannot be used —
  npm only allows trusted publishing for a package that already exists, so most likely the first
  publish — a granular access token is used: publish-only, scoped to `@blkleg/circuitbreaker`,
  short-lived, and revoked once trusted publishing is configured.

## Consequences

- The 1.0 release grows a third governed channel: a registry namespace to defend with MFA and
  access review (NPM-12), a publish job using GitHub Actions trusted publishing with provenance
  and a protected environment, with no long-lived token (NPM-13), `next`/`latest` promotion
  (NPM-14), and the package in the SBOM, scans and a compromise procedure (NPM-15).
- The release gate grows too: allowlisted, size-budgeted tarball contents (NPM-05, NPM-07), smoke
  tests of the packed `.tgz` on every claimed platform (NPM-08), failure-path tests (NPM-09) and a
  version-parity gate (NPM-11).
- In the release-control records: EXC-003 closes; NPM-01 passes on the 2026-09-30 approvals
  above; NPM-02, NPM-03 and NPM-05 to NPM-15 are not started; NPM-04 is
  excepted under EXC-004; NPM-12's two-maintainer clause is excepted under EXC-005; RISK-009 stays open, retargeted from "keep npm off the surface" to "ship
  the CLI through its gates, and keep it off the surface until then". EXEC-06 is no longer blocked
  on NPM-01.
- `specs/1.0.0/08-npm-distribution.md` becomes the requirement set for 1.0 work rather than the
  design for a future channel.
