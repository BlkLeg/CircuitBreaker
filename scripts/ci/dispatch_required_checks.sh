#!/usr/bin/env bash
# Dispatch every workflow that produces a required status check, on one branch.
#
# Usage: dispatch_required_checks.sh <branch> [dev|main]
#
#   <branch>   the branch whose head SHA must end up carrying all 21 required
#              checks (the PR head branch, not the base).
#   [base]     the branch the PR merges into; selects which gate workflow
#              supplies Lint / Security Gate / Backend tests / Test. Defaults
#              to `dev`, where every automated PR in this repo is opened.
#
# Why this exists: a commit pushed with GITHUB_TOKEN does not trigger `push`
# or `pull_request` workflows, so a bot-authored commit on a PR branch (the
# Dependabot lockfile sync is the first one) never receives the required
# checks and the PR can never merge. `workflow_dispatch` IS allowed from
# GITHUB_TOKEN, and the check runs of a dispatched run attach to the head SHA
# of the ref it was dispatched on — which is the SHA the rulesets look at.
#
# Which workflow yields which required check (both rulesets require the same
# 21 names; tests/build/test_dispatch_required_checks.py proves every one of
# them is produced by a job in a workflow dispatched here):
#
#   dev-ci.yml (base dev) / ci.yml (base main)
#       Lint, Security Gate, Backend tests (shard 1/4..4/4),
#       Backend coverage gate, Fresh-install migrations, Test
#   security.yml
#       the ten security jobs (Suppression Metadata .. Go Vulnerability Scan)
#   codeql.yml
#       Analyze (Python), Analyze (JavaScript / TypeScript)
#
# Every dispatch is attempted even if an earlier one fails, so one run of this
# script reports every workflow that could not be started; the exit status is
# non-zero if any of them failed.
#
# The repository is whatever `gh` resolves: GH_REPO if set, otherwise the
# origin of the current checkout.

set -euo pipefail

# shellcheck source=scripts/ci/lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

usage() {
    printf 'usage: %s <branch> [dev|main]\n' "$(basename "$0")" >&2
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage
    exit 2
fi

branch="$1"
base="${2:-dev}"

if [ -z "$branch" ]; then
    printf '::error::dispatch_required_checks: branch name is empty\n' >&2
    usage
    exit 2
fi
# A leading dash would be parsed by gh as an option, not a ref.
case "$branch" in
    -*)
        printf '::error::dispatch_required_checks: refusing branch name starting with "-": %s\n' \
            "$branch" >&2
        exit 2
        ;;
esac

case "$base" in
    dev) gate_workflow="dev-ci.yml" ;;
    main) gate_workflow="ci.yml" ;;
    *)
        printf '::error::dispatch_required_checks: base must be "dev" or "main", got: %s\n' \
            "$base" >&2
        usage
        exit 2
        ;;
esac

cb::require_tool gh "the GitHub CLI dispatches the workflows"

workflows=("$gate_workflow" "security.yml" "codeql.yml")
failed=()

for workflow in "${workflows[@]}"; do
    printf 'dispatching %s on %s (base %s)\n' "$workflow" "$branch" "$base"
    if gh workflow run "$workflow" --ref "$branch"; then
        printf 'dispatched %s on %s\n' "$workflow" "$branch"
    else
        status=$?
        printf '::error::failed to dispatch %s on %s (gh exited %s)\n' \
            "$workflow" "$branch" "$status" >&2
        failed+=("$workflow")
    fi
done

if [ "${#failed[@]}" -gt 0 ]; then
    printf '::error::%s of %s workflow dispatches failed: %s — the required checks will not all appear on %s\n' \
        "${#failed[@]}" "${#workflows[@]}" "${failed[*]}" "$branch" >&2
    exit 1
fi

printf 'all %s workflows dispatched on %s\n' "${#workflows[@]}" "$branch"
