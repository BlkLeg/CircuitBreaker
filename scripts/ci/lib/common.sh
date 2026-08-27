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

cb::use_go_bin() {
    # `go install` writes to `go env GOBIN`, or `go env GOPATH`/bin when GOBIN
    # is unset. Neither is on PATH by default on Fedora or on a GitHub runner,
    # so a gate that asks `command -v govulncheck` directly reports "not found"
    # for an install that is present and correct — and the hint it prints tells
    # the developer to run the very `go install` they already ran.
    #
    # Resolving the prefix here rather than in each caller keeps one definition
    # of "where Go tools live" (P1). No toolchain is not an error at this point:
    # there is simply nothing to resolve, and `cb::require_tool go` is what
    # names the real problem.
    command -v go >/dev/null 2>&1 || return 0

    local go_bin
    go_bin="$(go env GOBIN 2>/dev/null)"
    [ -n "$go_bin" ] || go_bin="$(go env GOPATH 2>/dev/null)/bin"
    [ -n "$go_bin" ] && [ "$go_bin" != "/bin" ] || return 0

    case ":$PATH:" in
        *":$go_bin:"*) ;;
        *) PATH="$go_bin:$PATH"; export PATH ;;
    esac
}
