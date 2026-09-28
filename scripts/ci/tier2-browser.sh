#!/usr/bin/env bash
# Tier 2 — browser E2E. The one definition of how the Playwright suite runs.
# Called per shard by browser-e2e.yml inside the Playwright container, and for
# the whole suite by `make verify-composed-browser` on a laptop. Design D1/P1:
# tests/build/test_tier2_wiring.py fails if either caller re-inlines it.
#
# Usage: tier2-browser.sh [SHARD]      SHARD is N/M, e.g. 1/2
set -euo pipefail

# Validate before anything else runs: the shard reaches the command line, and a
# malformed one should cost nothing and say what was wrong.
if [[ $# -gt 1 ]] || { [[ $# -eq 1 ]] && ! [[ $1 =~ ^[0-9]+/[0-9]+$ ]]; }; then
  printf '::error::tier2-browser.sh takes at most one shard argument of the form N/M, got: %q\n' "$*" >&2
  exit 2
fi

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

# playwright.config.ts keys its JUnit reporter, retries, workers, forbidOnly and
# reuseExistingServer on process.env.CI. GitHub sets CI=true. A laptop does not,
# and without it a local run writes no junit.xml and behaves unlike CI, which is
# the drift P1 forbids.
export CI="${CI:-1}"

cb::require_tool npx
cb::require_file apps/frontend/node_modules "run 'cd apps/frontend && npm ci' first"

shard_args=()
if [[ $# -eq 1 ]]; then
  shard_args=(--shard="$1")
fi

# The visual-* projects carry the REL-18 baselines (docs/testing-visual-baselines.md).
# They are separate projects so a stale baseline fails the visual gate and not the
# functional one.
mkdir -p "$CB_REPO_ROOT/artifacts"
cd apps/frontend
npx playwright test "${shard_args[@]}" \
  --project=chromium \
  --project=firefox \
  --project=webkit \
  --project=mobile-chrome \
  --project=visual-desktop \
  --project=visual-mobile \
  2>&1 | tee "$CB_REPO_ROOT/artifacts/playwright.log"
