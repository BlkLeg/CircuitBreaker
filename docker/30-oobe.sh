#!/usr/bin/env bash
# First-run hint only. Backend bootstrap status (needs_bootstrap / auth_enabled)
# is the sole source of truth for whether setup is required — never write a
# filesystem marker that can suppress incomplete onboarding.
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"

echo "[oobe] First-run setup is managed by the backend bootstrap API."
echo "[oobe] Open the web UI to complete onboarding, or run: cb setup"
echo "[oobe] Setup token path (when generated): ${DATA_DIR}/bootstrap-setup-token"
# The token is issued lazily on the first bootstrap-status check (opening the
# web UI, or `cb setup`/`cb setup-token`), so it will not exist yet on a
# container that just started. `cb` is only on PATH for install.sh installs;
# a compose-only setup (docker-compose.yml pulled and run by hand, with no
# install.sh) has no `cb`, so the always-available fallback is named here too.
echo "[oobe] Retrieve with: cb setup-token"
echo "[oobe] No cb CLI on this host? docker exec <container> cat ${DATA_DIR}/bootstrap-setup-token"
echo "[oobe] Nothing there yet? Open the web UI first — the token is generated on first request, not at startup."

# Remove a stale marker from older images so interrupted OOBE cannot be skipped.
rm -f "${DATA_DIR}/.oobe-complete" 2>/dev/null || true

exit 0
