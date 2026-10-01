# Release bundle signing

Every release from 0.4.7 on publishes `SHA256SUMS.sig`: an Ed25519 signature over
`SHA256SUMS`, made by the Stage Draft Release job with a key only that job can read.
The job signs only when it runs from `refs/heads/main`, checked in the workflow code
as well as by the environment's branch rule.
`install.sh` checks the signature before it trusts any hash. The design is
[the bundle signing design](../design/2026-09-30-release-bundle-signing-design.md).

## What install.sh accepts

- A signed release (0.4.7 and later) installs only if `SHA256SUMS.sig` verifies
  against a key in the trusted list. This needs OpenSSL 3.
- An unsigned release is accepted without `--version` only if it is exactly 0.4.6
  (`CB_LAST_UNSIGNED_RELEASE`, the last unsigned release) with a canonical tag.
- Any other release below 0.4.7 needs an explicit `--version X.Y.Z`, with no leading `v`.
- A non-canonical version always needs a signature.
- The build-provenance attestation is checked only when `gh` is installed and logged
  in. It is never checked when air-gapped, and a failed check never blocks the install.

## One-time setup

1. Generate the key pair on a trusted machine, outside the repository:

   ```bash
   make release-signing-key OUT=$HOME/secure/release-bundle.pem FIRST=0.4.7
   ```

   This runs `scripts/release_signing_key.sh <out.pem> <first-version> [comment]`. It
   prints one line, `<key-id> <public key> 0.4.7 <comment>`. The private key is
   written with mode 0600.

2. Append that line to `deploy/keys/release-bundle-keys.txt`. Then copy the file's
   exact contents into the heredoc in `_cb_embedded_release_keys` in
   `deploy/lib/bundle-signature.sh`. Then run `python3 scripts/ci/sync_installer_ui.py`,
   so `install.sh` carries the same list. `tests/build` fails if the three differ.

3. Create the environment, allowing deployments from `main` only:

   ```bash
   gh api -X PUT repos/BlkLeg/CircuitBreaker/environments/release-signing \
     -F 'deployment_branch_policy[protected_branches]=false' \
     -F 'deployment_branch_policy[custom_branch_policies]=true'
   gh api -X POST repos/BlkLeg/CircuitBreaker/environments/release-signing/deployment-branch-policies \
     -f name=main -f type=branch
   ```

4. Store the private key as the environment's secret, read from the file so it
   never appears on a command line or in shell history:

   ```bash
   gh secret set RELEASE_BUNDLE_SIGNING_KEY --env release-signing < $HOME/secure/release-bundle.pem
   ```

5. Keep an offline backup, for example on an encrypted USB key. Then remove the
   working copy with `shred -u $HOME/secure/release-bundle.pem`. Never commit the
   private key or paste it anywhere.

The first candidate after this proves the setup: the Stage job verifies its own
signature against the committed key list, and `promote-verify` checks it again
before asking for approval.

## Rotation

Generate a new key the same way, with `FIRST=<the next version>`. Add its line and
keep the old one, so older releases still verify. Replace the environment secret.

## Compromise

1. Remove the compromised key's line from `deploy/keys/release-bundle-keys.txt`,
   the library heredoc and `install.sh` (sync script), and from the npm CLI's copy
   once it ships.
2. Add a new key (rotation, above).
3. Re-sign each affected release's `SHA256SUMS` with the new key:
   `scripts/ci/sign_release_sums.sh <new.pem> SHA256SUMS SHA256SUMS.sig`. Then
   replace the asset with `gh release upload v<version> SHA256SUMS.sig --clobber`.
4. Publish an advisory naming the removed key id. Any release still carrying only
   the old signature now fails verification, by design.

## Verifying by hand

See [security verification](../installation/security-verification.md#release-bundle-signature).
