#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/circuitbreaker/.env
set +a

LOCK_FILE="/run/cb-healthcheck.lock"
LOG_FILE="${CB_DATA_DIR}/logs/healthcheck.log"

# Rate-limit restarts: skip if a restart was triggered within the last 60s
if [[ -f "$LOCK_FILE" ]]; then
  last=$(cat "$LOCK_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if (( now - last < 60 )); then
    echo "$(date -Iseconds) restart already in progress — skipping" >> "$LOG_FILE"
    exit 0
  fi
fi

if curl -sf --max-time 5 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  exit 0
fi

echo "$(date -Iseconds) health check failed — restarting circuitbreaker-backend" >> "$LOG_FILE"
date +%s > "$LOCK_FILE"
systemctl restart circuitbreaker-backend
