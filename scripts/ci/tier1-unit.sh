#!/usr/bin/env bash
# Tier 1 — unit and integration gates. Everything a developer must pass before
# pushing (ADR 0005 §4). Budget: 4 minutes wall clock. That budget is a hard
# constraint: a gate slower than the developer's patience gets bypassed, and a
# bypassed gate is worse than none because branch protection still reports it
# satisfied.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

EVIDENCE="$(cb::evidence_dir)"
CB_VERIFY_BACKEND="${CB_VERIFY_BACKEND:-shards}"

cb::require_tool docker "the backend suite and the security gate both need it"
cb::require_tool npm
cb::require_file .venv/bin/pytest "run 'make install' to build the dev virtualenv"
cb::require_file apps/frontend/node_modules "run 'cd apps/frontend && npm ci' first"
# govulncheck is invoked by security_scan.sh, not by this script directly — but that
# call is section 10 of 10, after the frontend suite and all four backend shards have
# already run. Without this preflight, a missing govulncheck is only discovered after
# paying the full multi-minute cost of everything ahead of it in the gate, which is
# exactly the kind of late, expensive failure this tier exists to prevent.
cb::require_tool govulncheck \
    "install: go install golang.org/x/vuln/cmd/govulncheck@v1.7.0 — the security gate fails closed without it"

cb::section "Frontend unit tests"
( cd apps/frontend && npm test ) 2>&1 | tee "$EVIDENCE/logs/frontend.log"

cb::section "Backend suite (mode: $CB_VERIFY_BACKEND)"
if [ "$CB_VERIFY_BACKEND" = "off" ]; then
    # Explicit, never silent: the operator asked for this, and the run has to
    # say so rather than reporting a pass that covered less than it looks like.
    cb::skipped "backend suite" "CB_VERIFY_BACKEND=off"
else
    # The four shards CI runs, run concurrently. Same sharder, same partition,
    # so "shard 3 failed" means the same set of tests here as in CI.
    #
    # The shard is applied by generating a FILE LIST and passing it to pytest,
    # exactly as dev-ci.yml does. Setting a SHARD env var and running `pytest
    # tests` would not shard anything — it would run the whole ~2900-test suite
    # in each of the four processes. backend_shard.py emits apps/backend-relative
    # paths, so the list is generated from the repo root and consumed after the
    # cd. --cov-fail-under=0 because coverage is enforced across the combined
    # shards, not per shard.
    pids=()
    for shard in 1 2 3 4; do
        python3 tests/build/backend_shard.py --index "$shard" --total 4 \
            > "$EVIDENCE/logs/backend-shard-$shard-files.txt"
        (
            cd apps/backend
            # shellcheck disable=SC2046  # word splitting is the point: one arg per file
            PYTHONPATH=src "$CB_REPO_ROOT/.venv/bin/pytest" \
                $(cat "$EVIDENCE/logs/backend-shard-$shard-files.txt") \
                --junitxml="$EVIDENCE/junit/backend-shard-$shard.xml" \
                --cov-fail-under=0 \
                -p no:cacheprovider \
                > "$EVIDENCE/logs/backend-shard-$shard.log" 2>&1
        ) &
        pids+=("$!")
    done
    failed=0
    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            failed=1
            printf '::error::backend shard %s failed — see %s\n' \
                "$((i + 1))" "$EVIDENCE/logs/backend-shard-$((i + 1)).log" >&2
        fi
    done
    [ "$failed" -eq 0 ] || exit 1
fi

cb::section "Security gate"
./scripts/security_scan.sh --gate

cb::section "Tier 1 complete"
