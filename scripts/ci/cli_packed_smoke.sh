#!/usr/bin/env bash
# Packed-tarball smoke for @blkleg/circuitbreaker (NPM-02, NPM-05, NPM-08, NPM-10).
#
# Packs the package exactly as `npm publish` would, installs that .tgz into a
# throwaway prefix with no network, and drives the installed launcher. The
# forwarding target is /usr/bin/echo: a real root-owned executable in a
# root-owned directory, so the trust check runs for real without sudo, and
# echo's output shows exactly which argv arrived.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() { printf '::error::cli packed smoke: %s\n' "$*" >&2; exit 1; }

node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 22 ] || fail "Node $(node -v) is below the package's floor of 22; install Node 22+ to run this smoke"

tarball="$(cd "$ROOT/packages/cli" && npm pack --silent --ignore-scripts --pack-destination "$work")"
[ "$tarball" = "blkleg-circuitbreaker-${VERSION}.tgz" ] || fail "packed $tarball, expected blkleg-circuitbreaker-${VERSION}.tgz"

npm install --global --prefix "$work/prefix" --offline --no-audit --no-fund "$work/$tarball" >/dev/null
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
