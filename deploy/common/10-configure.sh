#!/usr/bin/env bash
# deploy/common/10-configure.sh — Config loading, validation, and data-dir setup.
# Source: decomposed from docker/entrypoint-mono.sh lines 1-96.
set -euo pipefail

LOG_TAG="[configure]"

# ── Detect deploy mode ──────────────────────────────────────────────────────
if [ -n "${CB_DEPLOY_MODE:-}" ]; then
  : # already set by caller
elif [ -d /run/systemd/system ]; then
  CB_DEPLOY_MODE="native"
else
  CB_DEPLOY_MODE="docker"
fi
export CB_DEPLOY_MODE

echo "${LOG_TAG} Deploy mode: ${CB_DEPLOY_MODE}"

# ── Load config ─────────────────────────────────────────────────────────────
if [ "$CB_DEPLOY_MODE" = "native" ]; then
  _config_file="/etc/circuitbreaker/config.env"
else
  _config_file="${CB_DATA_DIR:-/data}/.env"
fi

if [ -f "$_config_file" ]; then
  echo "${LOG_TAG} Loading config from ${_config_file}"
  set -a
  # shellcheck disable=SC1090
  source "$_config_file"
  set +a
else
  echo "${LOG_TAG} Config file ${_config_file} not found; using environment variables only."
fi

# ── Canonical path exports ──────────────────────────────────────────────────
DATA="${CB_DATA_DIR:-/data}"
export CB_DATA_DIR="$DATA"
export CB_APP_ROOT="${CB_APP_ROOT:-/opt/circuitbreaker}"
export CB_LOG_DIR="${CB_LOG_DIR:-/var/log/circuitbreaker}"

if [ "$CB_DEPLOY_MODE" = "docker" ]; then
  export CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-/app/backend/alembic.ini}"
else
  export CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-${CB_APP_ROOT}/backend/alembic.ini}"
fi
export ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-$CB_ALEMBIC_INI}"

# ── Required secret validation ──────────────────────────────────────────────
if [ -z "${CB_JWT_SECRET:-}" ]; then
  echo "FATAL: CB_JWT_SECRET is required but not set. Generate one with:" >&2
  echo "  python3 -c \"import secrets; print(secrets.token_hex(32))\"" >&2
  exit 1
fi

if [ ${#CB_JWT_SECRET} -lt 32 ] || [ "${CB_JWT_SECRET}" = "CHANGE_ME" ]; then
  echo "FATAL: CB_JWT_SECRET must be at least 32 characters and not 'CHANGE_ME'." >&2
  exit 1
fi

if [ -n "${CB_VAULT_KEY:-}" ] && [ "${CB_VAULT_KEY}" = "${CB_JWT_SECRET}" ]; then
  echo "FATAL: CB_JWT_SECRET and CB_VAULT_KEY must be different values." >&2
  exit 1
fi

if [ -z "${NATS_AUTH_TOKEN:-}" ]; then
  echo "FATAL: NATS_AUTH_TOKEN is required but not set. Generate one with:" >&2
  echo "  openssl rand -base64 32" >&2
  exit 1
fi

if [ ${#NATS_AUTH_TOKEN} -lt 32 ] || [ "${NATS_AUTH_TOKEN}" = "CHANGE_ME" ]; then
  echo "FATAL: NATS_AUTH_TOKEN must be at least 32 characters and not 'CHANGE_ME'." >&2
  exit 1
fi

echo "${LOG_TAG} Secret validation passed."

# ── Auto-construct CB_DB_URL if not set ─────────────────────────────────────
if [ -z "${CB_DB_URL:-}" ] && [ -n "${CB_DB_PASSWORD:-}" ]; then
  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker"
  echo "${LOG_TAG} Auto-constructed CB_DB_URL from CB_DB_PASSWORD (embedded Postgres)."
fi

# ── Detect external vs embedded Postgres ────────────────────────────────────
USE_EXTERNAL_DB=0
if [ -n "${CB_DB_URL:-}" ]; then
  DB_HOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); h=(u.hostname or '').lower(); print(h)" 2>/dev/null || true)
  if [ -z "$DB_HOST" ]; then
    echo "FATAL: CB_DB_URL is set but appears malformed (no hostname found)." >&2
    echo "  Expected format: postgresql://user:pass@host:port/dbname" >&2
    exit 1
  fi
  case "$DB_HOST" in
    127.0.0.1|localhost|'') ;;
    *) USE_EXTERNAL_DB=1 ;;
  esac
fi
export USE_EXTERNAL_DB

# ── Create data directories ─────────────────────────────────────────────────
echo "${LOG_TAG} Ensuring data directories under ${DATA}..."
mkdir -p \
  "${DATA}/pgdata" \
  "${DATA}/uploads" \
  "${DATA}/nats" \
  "${DATA}/tls" \
  "${DATA}/certs" \
  "${DATA}/redis" \
  "${DATA}/run/postgresql" \
  "${DATA}/tmp" \
  "${DATA}/backups"

mkdir -p "${CB_LOG_DIR}" 2>/dev/null || true

# ── Fix ownership if running as root ────────────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then
  chown root:root "${DATA}/run/postgresql" 2>/dev/null || true
  chmod 1777 "${DATA}/run/postgresql"

  if ! chown -R breaker:breaker "${DATA}" 2>/dev/null; then
    echo "${LOG_TAG} chown ${DATA} not permitted; ensure volume is writable by 1000:1000." >&2
  fi

  # PostgreSQL requires strict 0700 permissions on its data directory
  if [ -d "${DATA}/pgdata" ]; then
    chmod 700 "${DATA}/pgdata"
  fi

  chown -R breaker:breaker "${CB_LOG_DIR}" 2>/dev/null || true
  mkdir -p /var/log/nginx 2>/dev/null || true
else
  chmod 1777 "${DATA}/run/postgresql" 2>/dev/null || true
fi

echo "${LOG_TAG} Configuration complete."
