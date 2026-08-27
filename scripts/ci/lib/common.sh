# Shared helpers for the scripts/ci gate scripts (ADR 0005, Phase 1).
#
# Sourced, never executed. The rules encoded here are the ones that make
# `make verify` worth trusting:
#
#   * cb::require_tool exits 127 rather than letting a gate pass because the
#     tool that implements it was not installed. security_scan.sh already
#     applies this to Gitleaks — "a gate that 'passes' because the scanner is
#     absent is not a gate" — and issue #106 is what it looks like when a
#     section does not.
#   * cb::skipped is the ONLY sanctioned way to record that an informational
#     step did not run. `|| true` is not, because it spells "did not run" and
#     "found nothing" identically.

# shellcheck shell=bash

CB_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export CB_REPO_ROOT
CB_EVIDENCE_ROOT="${CB_EVIDENCE_ROOT:-$CB_REPO_ROOT/artifacts}"
export CB_EVIDENCE_ROOT

cb::section() {
    printf '\n\033[1m▸ %s\033[0m\n' "$1"
}

cb::require_tool() {
    local tool=$1 hint=${2:-}
    if command -v "$tool" >/dev/null 2>&1; then
        return 0
    fi
    printf '::error::required tool not found: %s%s\n' \
        "$tool" "${hint:+ — $hint}" >&2
    exit 127
}

cb::require_file() {
    local path=$1 hint=${2:-}
    if [ -e "$path" ]; then
        return 0
    fi
    printf '::error::required path not found: %s%s\n' \
        "$path" "${hint:+ — $hint}" >&2
    exit 127
}

cb::skipped() {
    printf 'SKIPPED (%s): %s\n' "$2" "$1"
}

cb::evidence_dir() {
    # Flat, and deliberately so: ci.yml and dev-ci.yml both write
    # artifacts/junit/ and artifacts/logs/ directly, with no per-tier
    # subdirectory, and four jobs consume those paths. A local run should
    # produce the same tree a CI artifact download does.
    mkdir -p "$CB_EVIDENCE_ROOT/junit" "$CB_EVIDENCE_ROOT/logs"
    printf '%s' "$CB_EVIDENCE_ROOT"
}
