# ADR 0004: npm Is Not a Supported 1.0 Distribution Channel

**Status:** Accepted for 1.0 planning
**Date:** 2026-08-19
**Requirements:** NPM-01 through NPM-15, RC-03, EXEC-06
**Decision owners:** Distribution, security, release

## Context

`specs/1.0.0/08-npm-distribution.md` treats npm as a conditional channel: every requirement in it
begins "If npm is a supported 1.0 channel". Fifteen requirements sit behind that condition and
nobody has recorded an answer, so the ledger carries them as unmet work rather than as a decision.

The tree gives no evidence npm was ever started. There is no `@blkleg/*` package, no publish
workflow, and the root `package.json` is `private: true`. `apps/frontend/package.json` is a
workspace manifest for the bundled UI, not a publishable artifact.

The distribution channels that do exist and are tested are native systemd packages
(deb/rpm/apk/Arch/AppImage/tar for `amd64` and `arm64`) and the mono container image
`ghcr.io/blkleg/circuitbreaker`. Both carry signing, checksums, SBOMs and a publication gate in
`release.yml`: the packages must install and uninstall cleanly on a fresh host before anything is
published, and the image is vulnerability-scanned before it is signed. Adding npm would mean a new
package identity, a registry namespace with its own MFA and access review, trusted publishing via
OIDC, cross-platform tarball smoke tests on Linux/macOS/Windows, and a compromise-and-revocation
procedure — NPM-12 through NPM-15 — for a channel with no current users.

## Decision

npm is **not** a supported distribution channel for Circuit Breaker 1.0.

1. The root repository manifest stays `private: true`, and
   `tests/build/test_tracked_file_policy.py::test_root_npm_manifest_stays_private` asserts it, so
   an accidental `npm publish` from the repository root is refused rather than merely discouraged.
2. No package is published to npmjs under any name for the 1.0 line.
3. NPM-01 through NPM-15 are recorded as **not applicable** for 1.0 under exception `EXC-003`,
   not as unmet requirements.
4. Documentation names native and mono — the two deployment modes that ship, per
   [the installation overview](../installation/index.md#deployment-modes) — as the only supported
   installation methods, and does not present `npm`/`npx` examples.

`docs/release/1.0.0-support-contract.md` listed npm distribution as deferred "until the NPM slices
pass"; this ADR converts that open-ended deferral into a decision for the 1.0 line, and the support
contract's npm row now points here.

## Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| Publish an installer CLI now (NPM-03) | A wrapper that downloads and verifies signed artifacts duplicates `install.sh`, while adding a registry account, a publish credential and three new platform test matrices to the release gate. |
| Publish an API client/SDK now (NPM-04) | An SDK is a compatibility promise. RC-03 records that 1.0 makes no stable public API or SDK guarantee, so the SDK would either be unversionable or would force a promise the release contract declines to make. |
| Reserve the namespace without publishing | Insufficient on its own: NPM-12 asks for organization MFA, two maintainers and periodic access review, which is ongoing governance for an unused name. Worth doing as squatting defence, but it is not a release requirement and does not change this decision. |
| Leave the decision open | NPM-01 blocks EXEC-06, so an unanswered question is indistinguishable from an unmet requirement at the release gate. Fifteen rows would stay red for a channel nobody intends to ship. |

## Consequences

- Fifteen release requirements close as excepted without writing a package, and the supply-chain
  surface stays at two governed channels — no namespace to defend, no registry access review, no
  publish credential to rotate.
- Users who expect an `npx @blkleg/circuitbreaker` installer do not get one. `install.sh` is the
  equivalent entry point and is documented as such.
- Documentation and release notes must not show `npm install` or `npx` as an installation path;
  doing so would reintroduce the promise this ADR declines.
- `specs/1.0.0/08-npm-distribution.md` stays in the spec set as the design for a future channel,
  not as open 1.0 work.

## Long-term reopening criteria

npm can be reconsidered after 1.0 when there is a reason to ship it. Reopening requires:

- answering NPM-01's first question — installer CLI or API client/SDK — before any implementation;
- for the SDK path, the API compatibility window and contract tests that RC-03 currently declines
  to promise;
- namespace, MFA, two maintainers and access review under NPM-12; and
- trusted publishing with provenance under NPM-13, so no long-lived token exists.

Superseding this ADR is the mechanism; the exception register row `EXC-003` closes with it.
