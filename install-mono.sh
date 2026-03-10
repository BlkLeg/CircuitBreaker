#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker — Mono Container Install
#
# Downloads docker/docker-compose.yml from the project repository and starts
# the mono container via Docker Compose.  Every user — end user or developer —
# gets the same Compose-driven experience backed by the same compose file.
#
# The container runs as breaker (UID/GID 1000).  To avoid permission issues
# the data dir is chowned to PUID:PGID (default 1000:1000).  Set PUID/PGID to
# your host user (e.g. $(id -u) / $(id -g)) if needed.

echo "Circuit Breaker — Mono Container Install"

DATA_DIR="${CB_DATA_DIR:-circuitbreaker-data}"
HTTP_PORT="${CB_PORT_HTTP:-80}"
HTTPS_PORT="${CB_PORT_HTTPS:-443}"
TAG="${CB_TAG:-latest}"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

COMPOSE_RAW_URL="https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/docker-compose.yml"

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

# Chown data dir so the container user (1000:1000) can write
if [ "$(id -u)" -eq 0 ]; then
  chown -R "${PUID}:${PGID}" "${DATA_DIR}"
else
  if command -v sudo >/dev/null 2>&1; then
    sudo chown -R "${PUID}:${PGID}" "${DATA_DIR}" 2>/dev/null || echo "Warning: could not chown ${DATA_DIR} to ${PUID}:${PGID}. If the container fails with permission errors, run: sudo chown -R ${PUID}:${PGID} ${DATA_DIR}" >&2
  else
    echo "Warning: run as root or use 'chown -R ${PUID}:${PGID} ${DATA_DIR}' so the container can write to the data dir." >&2
  fi
fi

# Persist CB_VAULT_KEY to data dir for reuse
if [ -n "${CB_VAULT_KEY:-}" ] && [ ! -f "${DATA_DIR}/.cb_vault_key" ]; then
  printf '%s' "${CB_VAULT_KEY}" > "${DATA_DIR}/.cb_vault_key"
  chmod 600 "${DATA_DIR}/.cb_vault_key"
  [ "$(id -u)" -eq 0 ] && chown "${PUID}:${PGID}" "${DATA_DIR}/.cb_vault_key" 2>/dev/null || true
fi

# Download compose file (or reuse existing)
COMPOSE_FILE="${DATA_DIR}/docker-compose.yml"
if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "Downloading docker-compose.yml..."
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${COMPOSE_RAW_URL}" -o "${COMPOSE_FILE}"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "${COMPOSE_FILE}" "${COMPOSE_RAW_URL}"
  else
    echo "ERROR: curl or wget is required to download the compose file." >&2
    exit 1
  fi
fi

# Write .env file consumed by docker compose
ENV_FILE="${DATA_DIR}/.env"
cat > "${ENV_FILE}" <<EOF
CB_DB_PASSWORD=${CB_DB_PASSWORD}
CB_VAULT_KEY=${CB_VAULT_KEY}
CB_TAG=${TAG}
CB_PORT_HTTP=${HTTP_PORT}
CB_PORT_HTTPS=${HTTPS_PORT}
CB_DATA_DIR=${DATA_DIR}
NATS_AUTH_TOKEN=${NATS_AUTH_TOKEN:-}
EOF
chmod 600 "${ENV_FILE}"

echo ""
echo "Starting Circuit Breaker via Docker Compose..."
echo "  Compose file : ${COMPOSE_FILE}"
echo "  Data dir     : ${DATA_DIR}"
echo "  Image tag    : mono-${TAG}"
echo ""

docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --pull always

echo ""
echo "✅ Circuit Breaker started."
echo "📁 Data directory : ${DATA_DIR}"
echo "🌐 Open           : http://localhost:${HTTP_PORT}"
echo ""
echo "Manage the stack:"
echo "  Stop  : docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} down"
echo "  Logs  : docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} logs -f"
echo "  Update: docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} pull && \\"
echo "          docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} up -d"
if [ -f "${DATA_DIR}/.cb_vault_key" ]; then
  echo ""
  echo "⚠️  CB_VAULT_KEY saved in ${DATA_DIR}/.cb_vault_key — back it up securely."
fi
