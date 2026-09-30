# NPM-01 evidence: npm installer CLI approved (2026-09-30)

**Requirement:** NPM-01 — choose and document one purpose: administration/installer CLI or API
client/SDK. Acceptance: name, commands/API, supported platforms, versioning and relationship to
server artifacts are approved before implementation.

**Decision record:** [ADR 0006](../../../docs/adr/0006-npm-installer-cli-for-1.0.md), which
supersedes ADR 0004.

**Approver:** shawnji, the project's sole maintainer (distribution and security owner per
`specs/1.0.0/release-control/owner-map.md`), on 2026-09-30.

## Maintainer's words

Purpose, in answer to NPM-01's question (installer CLI, API client/SDK, both, or later):

> Installer CLI

The remaining items, in answer to the list ADR 0006 raised:

> That is the package name. All of the commands available in the native app should carry over.
> Linux for now, Microsoft testing/development begins after v0.5.0. Versioning moves in lock step
> with VERSION and release tags. We'll have a recorded exception for the lack of a second
> maintainer. I have 2FA enabled on my account and will use access tokens when possible

## What was approved, against NPM-01's acceptance

| NPM-01 item | Approved |
|---|---|
| Purpose | Installer and management CLI. No API client/SDK (NPM-04 excepted under EXC-004). |
| Name | `@blkleg/circuitbreaker` |
| Commands | Every native `cb` command, plus `install` and `rollback` (NPM-03). `update` performs the native upgrade. |
| Supported platforms | Linux only for 1.0. Windows development and testing begins after v0.5.0. |
| Versioning | Lockstep with `VERSION` and the release tags (NPM-11). |
| Relationship to server artifacts | Downloads and verifies the signed release bundles `install.sh` installs; ships no server code (NPM-03, NPM-05). |

Related, recorded with this approval:

- **NPM-12:** the two-maintainer clause is excepted under EXC-005. The maintainer's npm account has
  two-factor authentication. Organization MFA, recovery ownership and access review remain
  required.
- **NPM-13:** releases publish through GitHub Actions trusted publishing (OIDC) with provenance.
  "Access tokens when possible" is recorded as the fallback where OIDC cannot be used — a granular,
  publish-only token scoped to the package, short-lived, revoked once trusted publishing is set up.
