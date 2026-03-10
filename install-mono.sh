#!/usr/bin/env bash
set -euo pipefail

echo "Circuit Breaker — Mono Container Install"

DATA_DIR="${CB_DATA_DIR:-circuitbreaker-data}"
HTTP_PORT="${CB_PORT_HTTP:-80}"
HTTPS_PORT="${CB_PORT_HTTPS:-443}"
TAG="${CB_TAG:-latest}"

if [ -z "${CB_DB_PASSWORD:-}" ]; then
  echo "ERROR: CB_DB_PASSWORD is required (PostgreSQL breaker user password)." >&2
  exit 1
fi

if [ -z "${CB_VAULT_KEY:-}" ]; then
  echo "WARNING: CB_VAULT_KEY not set — generating a new key."
  CB_VAULT_KEY="$(openssl rand -base64 32)"
  export CB_VAULT_KEY
  echo "Generated CB_VAULT_KEY (not persisted on host; back it up from inside the app after OOBE)."
fi

mkdir -p "${DATA_DIR}"

RUN_CMD=(
  docker run -d
  --name circuitbreaker
  -p "${HTTP_PORT}:80"
  -v "${DATA_DIR}:/data"
  -e "CB_DB_PASSWORD=${CB_DB_PASSWORD}"
  -e "CB_VAULT_KEY=${CB_VAULT_KEY}"
)

if [ -n "${NATS_AUTH_TOKEN:-}" ]; then
  RUN_CMD+=(-e "NATS_AUTH_TOKEN=${NATS_AUTH_TOKEN}")
fi

if [ "${CB_ENABLE_TLS:-}" = "1" ] || [ "${CB_ENABLE_TLS:-}" = "true" ]; then
  RUN_CMD+=(-p "${HTTPS_PORT}:443")
fi

RUN_CMD+=("ghcr.io/blkleg/circuitbreaker:mono-${TAG}")

echo ""
echo "Running:"
printf '  %q ' "${RUN_CMD[@]}"
echo ""

"${RUN_CMD[@]}"

echo ""
echo "✅ Circuit Breaker mono container started."
echo "📁 Data directory: ${DATA_DIR}"
echo "🌐 Open: http://localhost:${HTTP_PORT}"
echo "   (Configure TLS by mounting certs into ${DATA_DIR}/tls and setting CB_ENABLE_TLS=1.)"

