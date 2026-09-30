#!/usr/bin/env bash
# Sign SHA256SUMS with the release bundle key: base64 of the raw 64-byte
# Ed25519 signature, one line. Used by release.yml (real key, from the
# release-signing environment) and release-dry-run.yml (throwaway key).
#
#   scripts/ci/sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>
set -euo pipefail

key="${1:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"
sums="${2:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"
out="${3:?usage: sign_release_sums.sh <private-key-pem> <SHA256SUMS> <out.sig>}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
openssl pkeyutl -sign -inkey "$key" -rawin -in "$sums" -out "$tmp"
if [[ "$(wc -c < "$tmp")" -ne 64 ]]; then
  echo "sign_release_sums: expected a 64-byte Ed25519 signature" >&2
  exit 1
fi
{ base64 -w0 < "$tmp"; printf '\n'; } > "$out"
