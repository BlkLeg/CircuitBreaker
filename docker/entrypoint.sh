#!/bin/bash
# Entrypoint: fix /app/data ownership, then exec the app as the non-root user (breaker26).
set -e

# Auto-construct embedded PostgreSQL URL from CB_DB_PASSWORD when CB_DB_URL is not set
if [ -z "${CB_DB_URL:-}" ] && [ -n "${CB_DB_PASSWORD:-}" ]; then
  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker"
fi

if [ -z "${CB_VAULT_KEY}" ]; then
    if [ ! -f /data/.env ] || ! grep -q "CB_VAULT_KEY" /data/.env 2>/dev/null; then
        echo "WARN [vault]: No CB_VAULT_KEY found in environment or /data/.env."
        echo "WARN [vault]: Fresh install: vault key will be generated during OOBE."
        echo "WARN [vault]: Existing install: ensure /data/.env contains CB_VAULT_KEY."
    fi
fi

if [ "$(id -u)" = "0" ]; then
    chown -R breaker26:breaker26 /app/data
fi

_cleanup() {
  echo "SIGTERM received, shutting down gracefully..."
  if [ ! -z "$APP_PID" ]; then
    kill -TERM "$APP_PID" || true
    wait "$APP_PID" || true
  fi
  exit 0
}
trap _cleanup TERM INT

if [ "$(id -u)" = "0" ]; then
    gosu breaker26 "$@" &
    APP_PID=$!
    wait $APP_PID
else
    "$@" &
    APP_PID=$!
    wait $APP_PID
fi
