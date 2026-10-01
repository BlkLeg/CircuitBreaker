#!/usr/bin/env bash
# Packed-tarball smoke for @blkleg/circuitbreaker (NPM-02, NPM-05, NPM-08, NPM-10).
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
# echo's output shows exactly which argv arrived.
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

tarball="$(cd "$ROOT/packages/cli" && npm pack --silent --ignore-scripts --pack-destination "$work")"
[ "$tarball" = "blkleg-circuitbreaker-${VERSION}.tgz" ] || fail "packed $tarball, expected blkleg-circuitbreaker-${VERSION}.tgz"

node "$ROOT/scripts/ci/cli_local_registry.mjs" "$work/$tarball" "$ROOT/packages/cli/package.json" > "$work/registry.port" &
registry_pid=$!
for _ in $(seq 100); do [ -s "$work/registry.port" ] && break; sleep 0.1; done
port="$(cat "$work/registry.port")"
[ -n "$port" ] || fail "the local registry did not start"

npm install --global --prefix "$work/prefix" --prefer-offline --no-audit --no-fund \
    "--@blkleg:registry=http://127.0.0.1:${port}/" "@blkleg/circuitbreaker@${VERSION}" >/dev/null
installed="$work/prefix/lib/node_modules/@blkleg/circuitbreaker"
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
{"schema_version": 1, "mode": "native", "version": "${VERSION}", "installed_at": "2026-09-30T00:00:00Z", "cli_path": "/usr/bin/echo"}
JSON
export CB_IDENTITY_PATH="$work/identity.json"

out="$(cd "$work" && "$cli" token create --name '$(touch pwned)' '; rm -rf /')" || fail "forwarded command exited $?"
[ "$out" = 'token create --name $(touch pwned) ; rm -rf /' ] || fail "argv changed in transit: $out"
[ ! -e "$work/pwned" ] || fail "an argument was evaluated by a shell"

set +e
"$cli" update >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 3 ] || fail "update exited $code, expected 3 (lifecycle refused in this build)"

set +e
CIRCUITBREAKER_FORWARDED=1 "$cli" status >/dev/null 2>&1; code=$?
set -e
[ "$code" -eq 2 ] || fail "forwarding loop exited $code, expected 2"

printf 'cli packed smoke: %s passed on Node %s\n' "$tarball" "$(node -v)"
