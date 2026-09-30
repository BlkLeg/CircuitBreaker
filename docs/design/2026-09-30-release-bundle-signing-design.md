# Release bundle signing — design

**Date:** 2026-09-30
**Status:** Approved design, awaiting spec review
**Owner:** shawnji (release, security)
**Requirements served:** NPM-03 (checksum, signature and provenance verification), and the
air-gap and supply-chain principles in `CLAUDE.md`

## Why

A release bundle today carries only `SHA256SUMS`, downloaded from the same place as the tarball.
That proves the download is intact, not that this project built it: anyone able to replace one
release asset can replace both. The container image is already signed with cosign keyless and
carries provenance; the native bundles, which every native, package and npm-CLI install uses, do
not. `install.sh --local-bundle` checks nothing at all, and ADR 0006's npm installer CLI must verify
checksum, signature and provenance before it installs anything (NPM-03).

## Goal and success

Anyone installing a release can prove it came from this project's release pipeline, through
`install.sh`, `install.sh --local-bundle` (including air-gapped), and the npm CLI.

- A tampered tarball, `SHA256SUMS` or signature is refused by all three, online or offline.
- A release cannot be staged unsigned, and a bad signature stops the release before approval.
- Verification works fully offline with tools every supported distro ships.

## Decisions

1. **Ed25519 signature, required; Sigstore attestations, additional.** A detached Ed25519
   signature over `SHA256SUMS` is the check every path must pass, offline included. GitHub build
   provenance attestations (Sigstore) are published beside it for provenance; the npm CLI requires
   them when online, `install.sh` checks them when a verifier is present.
2. **A dedicated key.** A new Ed25519 key signs release bundles only. It is not the agent update
   key, so one compromise cannot forge both.
3. **Key custody.** The private key is `RELEASE_BUNDLE_SIGNING_KEY`, a secret of a new GitHub
   environment `release-signing` whose deployment branch rule allows `main` only. Only the Stage
   Draft Release job declares that environment. This is separate from the `release` environment,
   which only `promote` may declare.
4. **Signature format matches the agent's:** base64 of the raw 64-byte Ed25519 signature, one line,
   in `SHA256SUMS.sig`.
5. **First signed release: 0.4.7.** Earlier releases have no signature and stay installable.

## Non-goals

- Signing individual deb/rpm/apk/AppImage files for their package managers. They are covered by
  `SHA256SUMS` and its signature; repository signing comes with signed repos.
- Replacing cosign keyless for the container image.
- The npm CLI itself. This spec defines the verification contract it implements.

## Trust model

- **Trusted keys** live in `deploy/keys/release-bundle-keys.txt`, one per line:
  `<key-id> <base64 raw 32-byte public key> <first-version> <comment>`. The key id is the first 16
  hex characters of the SHA-256 of the raw public key. `first-version` is the first release that
  key signed.
- **`install.sh` embeds the same list**, because `curl … | bash` is a single file. A policy test
  keeps the embedded list identical to the file.
- **Rotation** adds a new line and keeps the old one, so releases signed by the old key stay
  verifiable. A key is removed only on compromise (see *Compromise*).
- **Verification tries each trusted key** and reports which one verified. A signature no trusted
  key verifies is a failure.

## Release pipeline (`release.yml`)

**Stage Draft Release (`release` job).** After the final `SHA256SUMS` is written and before
`gh release create`:

1. Declare `environment: release-signing` on this job.
2. Write `RELEASE_BUNDLE_SIGNING_KEY` to a `umask 077` temp file, sign `dist/release/SHA256SUMS`
   into `dist/release/SHA256SUMS.sig`, delete the key file in the same step. The key reaches the
   step only through `env:`.
3. Verify the new signature against `deploy/keys/release-bundle-keys.txt` in the same job, so a
   key/list mismatch fails here rather than in the field.
4. Attest build provenance for every bundle tarball with `actions/attest-build-provenance`
   (job permissions gain `attestations: write`; `id-token: write` is already present).
5. `SHA256SUMS.sig` is uploaded with the other assets.

**Verify the candidate before promoting (`promote-verify`).** New step: download the draft's
`SHA256SUMS` and `SHA256SUMS.sig`, verify the signature against the committed key list, check every
tarball's hash, and run `gh attestation verify` on each tarball with `--repo BlkLeg/CircuitBreaker`.
Any failure stops the release before approval is requested.

**Post-publish.** Repeat the signature and hash check against the *published* assets, the same
way it already re-checks published assets.

Rules that still hold: no `continue-on-error` or `always()`; every `${{ }}` reaches shell through
`env:`, quoted; only `promote` declares `environment: release`. The guard tests in
`tests/build/test_release_*.py` and `test_workflow_job_graph.py` are updated for the new steps
and the new environment.

## Installer (`install.sh`)

**Signature check.** A new function verifies a `SHA256SUMS`/`SHA256SUMS.sig` pair against the
embedded trusted keys with OpenSSL 3 (`openssl pkeyutl -verify -rawin`, the raw key wrapped as a
DER SubjectPublicKeyInfo). Every distro in the installer journey (Ubuntu 22.04, Debian 12, Fedora,
Rocky, AlmaLinux, Arch) ships OpenSSL 3. Order is always **signature, then hash**: the hash list is
trusted only once its signature verifies.

| Situation | Behaviour |
|---|---|
| Download, release ≥ 0.4.7 | `SHA256SUMS` and `.sig` are required. Bad or missing signature, or hash mismatch: stop, fail closed |
| Download, release < 0.4.7 (for example `--version` for a rollback) | No signature exists. Verify the hash as today and warn that the release predates signing |
| `--local-bundle`, `SHA256SUMS` and `.sig` next to the tarball | Must verify, as for a download. Closes the gap where a local bundle was not checked at all |
| `--local-bundle`, only `SHA256SUMS` next to it | Verify the hash, warn that the signature is missing |
| `--local-bundle`, neither file | Warn that the bundle is unverified and continue, as today, so local development builds keep working |
| `--skip-signature` | Skip the signature check with a warning; the hash is still checked. Sits beside `--skip-checksum` |
| Attestation | If `gh` or `cosign` is present and the host is online, verify it and report the result; otherwise say it was not checked. Never required, since air-gapped hosts cannot reach Sigstore |

The air-gap and upgrade docs change to "copy the tarball, `SHA256SUMS` and `SHA256SUMS.sig`".
Error messages name the file, the key ids tried and the fix, following the installer's existing
`cb_fail "<what>" "<what to do>"` pattern.

## Contract for the npm installer CLI

The npm CLI (`@blkleg/circuitbreaker`, ADR 0006) implements the same check:

- **Trusted keys:** the same `deploy/keys/release-bundle-keys.txt` content, embedded in the package
  and kept equal by a test.
- **Files:** `SHA256SUMS`, `SHA256SUMS.sig` and the tarball, from the GitHub release for the version.
- **Order:** signature (Node's built-in `crypto.verify('ed25519', …)`), then hash, then attestation.
- **Attestation:** required when online, verified with sigstore-js against
  `BlkLeg/CircuitBreaker`'s release workflow. With `CB_AIRGAP=true` it is skipped and the signature
  alone decides.
- **Failure:** stop before changing anything on the host, with the same messages as `install.sh`.

## Key setup and compromise

**Setup (once, by the maintainer).** Generate the key pair locally; commit only the public key line
to `deploy/keys/release-bundle-keys.txt` and `install.sh`; create the `release-signing` environment
with a `main`-only deployment branch rule; store the private key as its
`RELEASE_BUNDLE_SIGNING_KEY` secret; keep an offline backup. The private key is never committed,
logged or pasted into a chat.

**Compromise.** Remove the key's line from the trusted list in `install.sh`, the key file and the
npm package; add a new key; re-sign the affected releases' `SHA256SUMS` with the new key and
replace their `.sig` assets; publish an advisory naming the key id. Any release signed only by the
removed key then fails verification, by design.

## Testing

- **Installer unit tests** (`tests/build/`), each with a throwaway key generated at test time and
  never stored: good signature; tampered `SHA256SUMS`; tampered tarball; signature from an unknown
  key; missing signature for a release ≥ 0.4.7; pre-0.4.7 fallback warning; each `--local-bundle`
  row of the table; `--skip-signature`.
- **Key list parity test:** the embedded list in `install.sh` equals
  `deploy/keys/release-bundle-keys.txt`, and every line parses with a key id that matches its key.
- **Release-graph tests** updated: the Stage job declares `release-signing` and signs before
  `gh release create`; `promote-verify` verifies signature and attestations; post-publish verifies;
  only `promote` declares `release`.
- **End to end:** the 0.4.7 release candidate is the first live proof. The installer journey runs
  before staging, so it installs from unsigned build output and exercises the "neither file" row;
  the signed path is proven by `promote-verify` before approval and by post-publish after it, both
  against the real key and real assets.

## Rollout

1. Maintainer creates the key pair and the `release-signing` environment (instructions in the
   implementation plan).
2. Land the pipeline, installer and test changes on `dev`.
3. 0.4.7 is the first signed release. NPM-03's server-artifact half is then evidenced; the npm
   CLI's own verification is evidenced when the CLI ships.
4. Record NPM-12 progress: the `@blkleg` npm organization was created on 2026-09-30.
