#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker — Mono Container Install
#
# The container runs as breaker (UID/GID 1000). To avoid permission issues, the data dir
# is chowned to PUID:PGID (default 1000:1000). Set PUID/PGID to your host user (e.g.
# $(id -u) / $(id -g)) so the container can write to the mounted volume.

echo "Circuit Breaker — Mono Container Install"

DATA_DIR="${CB_DATA_DIR:-circuitbreaker-data}"
HTTP_PORT="${CB_PORT_HTTP:-80}"
HTTPS_PORT="${CB_PORT_HTTPS:-443}"
TAG="${CB_TAG:-latest}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ -z "${CB_DB_PASSWORD:-}" ]; then
  echo "ERROR: CB_DB_PASSWORD is required (PostgreSQL breaker user password)." >&2
  exit 1
fi

if [ -z "${CB_VAULT_KEY:-}" ]; then
  echo "WARNING: CB_VAULT_KEY not set — generating a new key."
  CB_VAULT_KEY="$(openssl rand -base64 32)"
  export CB_VAULT_KEY
  echo "Generated CB_VAULT_KEY; will save to data dir for reuse (back it up securely)."
fi

mkdir -p "${DATA_DIR}"

# Chown data dir so the container user (1000:1000) can write; avoids permission errors in rootless Docker
if [ "$(id -u)" -eq 0 ]; then
  chown -R "${PUID}:${PGID}" "${DATA_DIR}"
else
  if command -v sudo >/dev/null 2>&1; then
    sudo chown -R "${PUID}:${PGID}" "${DATA_DIR}" 2>/dev/null || echo "Warning: could not chown ${DATA_DIR} to ${PUID}:${PGID}. If the container fails with permission errors, run: sudo chown -R ${PUID}:${PGID} ${DATA_DIR}" >&2
  else
    echo "Warning: run as root or use 'chown -R ${PUID}:${PGID} ${DATA_DIR}' so the container can write to the data dir." >&2
  fi
fi

# Persist CB_VAULT_KEY to data dir for reuse (optional; -e still overrides at run time)
if [ -n "${CB_VAULT_KEY:-}" ] && [ ! -f "${DATA_DIR}/.cb_vault_key" ]; then
  printf '%s' "${CB_VAULT_KEY}" > "${DATA_DIR}/.cb_vault_key"
  chmod 600 "${DATA_DIR}/.cb_vault_key"
  [ "$(id -u)" -eq 0 ] && chown "${PUID}:${PGID}" "${DATA_DIR}/.cb_vault_key" 2>/dev/null || true
fi

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
if [ -f "${DATA_DIR}/.cb_vault_key" ]; then
  echo "   (CB_VAULT_KEY saved in ${DATA_DIR}/.cb_vault_key — back it up securely.)"
fi

