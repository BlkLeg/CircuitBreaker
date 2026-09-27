#!/usr/bin/env bash
# Tier 2 — composed agent journey. The one definition of the pytest invocation.
# Called by composed-e2e.yml on the runner, and by `make e2e-local` inside the
# uid-1001 runner container. Extra arguments go to pytest (E2E_ARGS='-k name').
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

# composed-e2e.yml pins these at step level too, and
# tests/build/test_tier2_wiring.py fails if the seed values disagree.
export CB_E2E_SEED="${CB_E2E_SEED:-20260826}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
# Each test tears its own stack down in a `finally`, so the logs that explain a
# failure are written here from inside `_down()`, while containers still exist.
export CB_E2E_DIAGNOSTICS_DIR="${CB_E2E_DIAGNOSTICS_DIR:-$CB_REPO_ROOT/diagnostics}"

cb::require_tool python3
cb::require_tool docker "the journey composes its own stack"

# Tests with a live quarantine-register row are deselected, so a quarantined
# failure does not simply fail again on the rerun its row permits
# (composed_rerun_guard.py). An assignment, not a process substitution, so a
# broken register fails this script instead of silently deselecting nothing.
deselect_out="$(python3 "$CB_REPO_ROOT/scripts/ci/composed_rerun_guard.py" deselect)"
deselect=()
if [[ -n $deselect_out ]]; then
  mapfile -t deselect <<<"$deselect_out"
fi

mkdir -p "$CB_E2E_DIAGNOSTICS_DIR"
cd apps/agent/e2e
# -p no:cacheprovider: under `make e2e-local` the runner is uid 1001 and the
# worktree's .pytest_cache belongs to the developer, so pytest's end-of-session
# cache write dies with EACCES after every test has run. That turns a completed
# run into a traceback. CI wants no cross-run cache either.
python3 -m pytest test_agent_e2e.py -v \
  --junitxml=junit-agent-e2e.xml \
  --timeout=3600 \
  -p no:cacheprovider \
  "${deselect[@]}" \
  "$@" \
  2>&1 | tee "$CB_E2E_DIAGNOSTICS_DIR/composed-journey.log"
