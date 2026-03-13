#!/usr/bin/env bash
set -euo pipefail

readonly REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

declare -a HEAD_BLOCKLIST=(
  ".github/workflows/.env"
  ".github/workflows/.env.*"
  "docker/circuitbreaker-data/backend_api_err.log"
  "docker/circuitbreaker-data/tls/privkey.pem"
)

declare -a HISTORY_WATCH=(
  "docker/circuitbreaker-data/backend_api_err.log"
)

echo "[secret-guard] scanning tracked files in HEAD"
head_hits=0
for path in "${HEAD_BLOCKLIST[@]}"; do
  if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
    echo "[secret-guard] BLOCKED tracked file in HEAD: $path"
    head_hits=$((head_hits + 1))
  fi
done

if [[ "$head_hits" -gt 0 ]]; then
  echo "[secret-guard] FAIL: remove blocked files from HEAD before merge."
  exit 1
fi

echo "[secret-guard] scanning historical exposure watch-list"
for path in "${HISTORY_WATCH[@]}"; do
  hits="$(git log --all --oneline -- "$path" | wc -l | tr -d ' ')"
  if [[ "$hits" != "0" ]]; then
    echo "[secret-guard] HISTORY exposure detected for $path ($hits commits)"
    echo "[secret-guard] ACTION: verify credential rotation and decide on history rewrite."
  fi
done

echo "[secret-guard] PASS: no blocked secret files tracked in HEAD."
