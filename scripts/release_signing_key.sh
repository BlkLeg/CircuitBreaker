#!/usr/bin/env bash
# Generate the Ed25519 key pair that signs release bundles' SHA256SUMS.
#
#   scripts/release_signing_key.sh <private-key-out> <first-version> [comment]
#
# Writes the private key (PKCS#8 PEM, mode 0600, never overwritten) and prints
# the trusted-key line for deploy/keys/release-bundle-keys.txt:
#   <key-id> <base64 raw 32-byte public key> <first-version> <comment>
# The private key goes to the release-signing environment's
# RELEASE_BUNDLE_SIGNING_KEY secret and an offline backup, then off this disk.
# See docs/release/bundle-signing.md. Never commit it or paste it anywhere.
set -euo pipefail

out="${1:?usage: release_signing_key.sh <private-key-out> <first-version> [comment]}"
first="${2:?usage: release_signing_key.sh <private-key-out> <first-version> [comment]}"
comment="${3:-release bundle key}"

if [[ -e "$out" ]]; then
  echo "refusing to overwrite $out" >&2
  exit 1
fi

# umask before creation: the key must never exist with a wider mode.
(umask 077 && openssl genpkey -algorithm ed25519 -out "$out")
pub="$(openssl pkey -in "$out" -pubout -outform DER | tail -c 32 | base64 -w0)"
key_id="$(printf '%s' "$pub" | base64 -d | sha256sum | cut -c1-16)"
printf '%s %s %s %s\n' "$key_id" "$pub" "$first" "$comment"
