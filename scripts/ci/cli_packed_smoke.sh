#!/usr/bin/env bash
# Packed-tarball smoke for @blkleg/circuitbreaker (NPM-02, NPM-03, NPM-05, NPM-08,
# NPM-09, NPM-10).
#
# Packs the package exactly as `npm publish` would, installs it by name into a
# throwaway prefix the way a user does, and drives the installed launcher. The
# name resolves through a one-package registry on 127.0.0.1 that serves the .tgz
# with the `_hasShrinkwrap` flag npmjs.com sets on publish, so npm honours the
# shipped npm-shrinkwrap.json as it will for `npm install -g`. sigstore's tree
# then comes from the npm cache that `npm ci --ignore-scripts` in packages/cli
# filled (registry.npmjs.org only on a cache miss), and is checked against the
# shrinkwrap with no install scripts anywhere in it (NPM-10). The
# forwarding target is /usr/bin/echo: a real root-owned executable in a
# root-owned directory, so the trust check runs for real without sudo, and
# echo's output shows exactly which argv arrived. Finally `install --plan`
# runs air-gapped against a tiny local bundle: the installed package trusts
# only the real release key, so an unsigned bundle and one signed with a
# throwaway key are both refused (exit 5), and `install` without --yes refuses before mutation (exit 2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
work="$(mktemp -d)"
registry_pid=""
trap '[ -z "$registry_pid" ] || kill "$registry_pid" 2>/dev/null; rm -rf "$work"' EXIT

fail() { printf '::error::cli packed smoke: %s\n' "$*" >&2; exit 1; }

# The package's own launcher check, so this guard cannot drift from engines.
node -e "import('$ROOT/packages/cli/src/runtime.js').then(m=>{const p=m.unsupportedRuntime(); if(p){console.error(p);process.exit(1)}})" \
    || fail "Node $(node -v) is below the package's floor; install a supported Node to run this smoke"

if [[ $# -gt 0 ]]; then
  [[ $# -eq 1 && -f "$1" ]] || fail "usage: cli_packed_smoke.sh [accepted.tgz]"
  tarball="blkleg-circuitbreaker-${VERSION}.tgz"
  cp -- "$1" "$work/$tarball"
else
  tarball="$(cd "$ROOT/packages/cli" && npm pack --silent --ignore-scripts --pack-destination "$work")"
fi
[ "$tarball" = "blkleg-circuitbreaker-${VERSION}.tgz" ] || fail "packed $tarball, expected blkleg-circuitbreaker-${VERSION}.tgz"

node "$ROOT/scripts/ci/cli_local_registry.mjs" "$work/$tarball" "$ROOT/packages/cli/package.json" > "$work/registry.port" &
registry_pid=$!
for _ in $(seq 100); do [ -s "$work/registry.port" ] && break; sleep 0.1; done
port="$(cat "$work/registry.port")"
[ -n "$port" ] || fail "the local registry did not start"

npm install --global --prefix "$work/prefix" --prefer-offline --no-audit --no-fund \
    "--@blkleg:registry=http://127.0.0.1:${port}/" "@blkleg/circuitbreaker@${VERSION}" >/dev/null
installed="$work/prefix/lib/node_modules/@blkleg/circuitbreaker"
python3 "$ROOT/scripts/ci/cli_terminal_smoke.py" --package "$installed" \
    || fail "the packed terminal renderer failed PTY acceptance"
[ -d "$installed/node_modules/sigstore" ] || fail "sigstore was not installed with the package"
node "$ROOT/scripts/ci/cli_installed_tree_check.mjs" "$installed" \
    || fail "the installed dependency tree is not the shipped npm-shrinkwrap.json, or runs install scripts"
bin_entries="$(ls "$work/prefix/bin")"
[ "$bin_entries" = "circuitbreaker" ] || fail "install created bin entries: $bin_entries"
[ "$(ls "$work/prefix/lib/node_modules")" = "@blkleg" ] || fail "install created more than the one package"
cli="$work/prefix/bin/circuitbreaker"

mkdir -p "$work/home"
export HOME="$work/home"
export CB_IDENTITY_PATH="$work/missing.json"

out="$("$cli" --version)" || fail "--version without an install exited $?"
grep -q "CLI       ${VERSION}" <<<"$out" || fail "--version did not report $VERSION: $out"

set +e
"$cli" status >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 3 ] || fail "status without identity exited $code, expected 3"

cat > "$work/identity.json" <<JSON
{"schema_version": 1, "mode": "package", "version": "${VERSION}", "installed_at": "2026-09-30T00:00:00Z", "cli_path": "/usr/bin/echo"}
JSON
export CB_IDENTITY_PATH="$work/identity.json"

out="$(cd "$work" && "$cli" token create --name '$(touch pwned)' '; rm -rf /')" || fail "forwarded command exited $?"
[ "$out" = 'token create --name $(touch pwned) ; rm -rf /' ] || fail "argv changed in transit: $out"
[ ! -e "$work/pwned" ] || fail "an argument was evaluated by a shell"

set +e
"$cli" update --yes >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 3 ] || fail "update exited $code, expected 3 (package lifecycle uses its authoritative manager)"

set +e
CIRCUITBREAKER_FORWARDED=1 "$cli" status >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 2 ] || fail "forwarding loop exited $code, expected 2"

bundle="$work/bundle"
mkdir -p "$bundle/src/bin" && printf '#!/bin/sh\n' > "$bundle/src/bin/circuit-breaker"
tar -czf "$bundle/circuit-breaker_9.9.9_linux_amd64.tar.gz" -C "$bundle/src" .
(cd "$bundle" && sha256sum circuit-breaker_9.9.9_linux_amd64.tar.gz | sed 's/  /  .\//' > SHA256SUMS)

set +e
CB_AIRGAP=true "$cli" install --plan --local-bundle "$bundle/circuit-breaker_9.9.9_linux_amd64.tar.gz" >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 5 ] || fail "unsigned, unpinned local bundle exited $code, expected 5"

bash "$ROOT/scripts/release_signing_key.sh" "$work/throwaway.pem" 9.9.9 smoke >/dev/null
bash "$ROOT/scripts/ci/sign_release_sums.sh" "$work/throwaway.pem" "$bundle/SHA256SUMS" "$bundle/SHA256SUMS.sig"
set +e
err="$(CB_AIRGAP=true "$cli" install --plan --local-bundle "$bundle/circuit-breaker_9.9.9_linux_amd64.tar.gz" 2>&1 >/dev/null)"; code=$?
set -e
[ "$code" -eq 5 ] || fail "throwaway-signed bundle exited $code, expected 5"
grep -q 'Keys tried' <<<"$err" || fail "refusal did not name the trusted keys: $err"

set +e
CB_IDENTITY_PATH="$work/missing.json" "$cli" install >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 2 ] || fail "install without --yes exited $code, expected 2"

printf 'cli packed smoke: %s passed on Node %s\n' "$tarball" "$(node -v)"
