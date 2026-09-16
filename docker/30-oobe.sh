#!/usr/bin/env bash
# First-run hint only. Backend bootstrap status (needs_bootstrap / auth_enabled)
# is the sole source of truth for whether setup is required — never write a
# filesystem marker that can suppress incomplete onboarding.
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"

echo "[oobe] First-run setup is managed by the backend bootstrap API."
echo "[oobe] Open the web UI to complete onboarding, or run: cb setup"
echo "[oobe] Setup token path (when generated): ${DATA_DIR}/bootstrap-setup-token"
echo "[oobe] Retrieve with: cb setup-token"

# Remove a stale marker from older images so interrupted OOBE cannot be skipped.
rm -f "${DATA_DIR}/.oobe-complete" 2>/dev/null || true

exit 0
