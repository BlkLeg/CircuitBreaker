#!/usr/bin/env bash
# deploy/common/entrypoint.sh — Main orchestrator.
# Sources the numbered scripts in order, handles Postgres lifecycle, TLS, Redis,
# pgbouncer, and OOBE — then either returns (systemd ExecStartPre=) or execs
# supervisord (Docker).
set -euo pipefail

LOG_TAG="[entrypoint]"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helper: run command as breaker when we are root ─────────────────────────
run_as_breaker() {
  local cmd="$1"
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u breaker -- env \
      CB_DATA_DIR="${CB_DATA_DIR:-/data}" \
      CB_DB_URL="${CB_DB_URL:-}" \
      CB_DB_PASSWORD="${CB_DB_PASSWORD:-}" \
      CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-}" \
      ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-}" \
      CB_DEPLOY_MODE="${CB_DEPLOY_MODE:-docker}" \
      CB_APP_ROOT="${CB_APP_ROOT:-/opt/circuitbreaker}" \
      CB_LOG_DIR="${CB_LOG_DIR:-/var/log/circuitbreaker}" \
      CB_VAULT_KEY="${CB_VAULT_KEY:-}" \
      USE_EXTERNAL_DB="${USE_EXTERNAL_DB:-0}" \
      NATS_AUTH_TOKEN="${NATS_AUTH_TOKEN:-}" \
      CB_JWT_SECRET="${CB_JWT_SECRET:-}" \
      /bin/bash -c "$cmd"
  else
    /bin/bash -c "$cmd"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Configuration + validation + data dirs
# ═══════════════════════════════════════════════════════════════════════════════
echo "${LOG_TAG} Phase 1: Configuration and validation..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/10-configure.sh"

DATA="${CB_DATA_DIR:-/data}"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Vault key bootstrap
# ═══════════════════════════════════════════════════════════════════════════════
echo "${LOG_TAG} Phase 2: Vault key bootstrap..."
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/30-vault-init.sh"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Postgres cluster init (embedded only, if not yet initialized)
# ═══════════════════════════════════════════════════════════════════════════════
if [ "${USE_EXTERNAL_DB:-0}" -eq 0 ]; then
  echo "${LOG_TAG} Phase 3: Embedded Postgres cluster init..."
  run_as_breaker "bash ${SCRIPT_DIR}/init-postgres.sh"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: TLS certificate generation (self-signed if missing)
# ═══════════════════════════════════════════════════════════════════════════════
if [ ! -f "${DATA}/tls/fullchain.pem" ] || [ ! -f "${DATA}/tls/privkey.pem" ]; then
  echo "${LOG_TAG} Phase 4: No TLS certs found; creating self-signed for nginx."
  mkdir -p "${DATA}/tls"
  openssl req -x509 -nodes -days 365 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "${DATA}/tls/privkey.pem" -out "${DATA}/tls/fullchain.pem" \
    -subj "/CN=localhost" 2>/dev/null
  if [ "$(id -u)" -eq 0 ]; then
    chown breaker:breaker "${DATA}/tls/fullchain.pem" "${DATA}/tls/privkey.pem" 2>/dev/null || true
  fi
else
  echo "${LOG_TAG} Phase 4: TLS certs present, skipping generation."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5: Redis password generation (if missing)
# ═══════════════════════════════════════════════════════════════════════════════
REDIS_PASS_FILE="${DATA}/.redis_pass"
if [ -n "${CB_REDIS_PASS:-}" ]; then
  printf '%s' "$CB_REDIS_PASS" > "$REDIS_PASS_FILE"
  chmod 600 "$REDIS_PASS_FILE"
  [ "$(id -u)" -eq 0 ] && chown breaker:breaker "$REDIS_PASS_FILE" 2>/dev/null || true
elif [ ! -f "$REDIS_PASS_FILE" ]; then
  echo "${LOG_TAG} Phase 5: Generating Redis password..."
  openssl rand -base64 32 | tr -d '\n' > "$REDIS_PASS_FILE"
  chmod 600 "$REDIS_PASS_FILE"
  [ "$(id -u)" -eq 0 ] && chown breaker:breaker "$REDIS_PASS_FILE" 2>/dev/null || true
  echo "${LOG_TAG} Generated Redis password at ${REDIS_PASS_FILE}."
else
  echo "${LOG_TAG} Phase 5: Redis password already exists."
fi

export CB_REDIS_PASSWORD
CB_REDIS_PASSWORD="$(cat "$REDIS_PASS_FILE")"

# Default CB_REDIS_URL to include the generated password
if [ -z "${CB_REDIS_URL_SET_BY_USER:-}" ]; then
  export CB_REDIS_URL="redis://:${CB_REDIS_PASSWORD}@127.0.0.1:6379/0"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6: pgbouncer userlist generation
# ═══════════════════════════════════════════════════════════════════════════════
if [ "${USE_EXTERNAL_DB:-0}" -eq 0 ] && [ -n "${CB_DB_URL:-}" ]; then
  echo "${LOG_TAG} Phase 6: Generating pgbouncer userlist..."
  PG_PASS="${CB_DB_PASSWORD:-breaker}"
  printf '"breaker" "%s"\n' "$PG_PASS" > "${DATA}/pgbouncer_userlist.txt"
  chmod 640 "${DATA}/pgbouncer_userlist.txt"
  chown breaker:breaker "${DATA}/pgbouncer_userlist.txt" 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7: Docker socket access (Docker mode only)
# ═══════════════════════════════════════════════════════════════════════════════
if [ -S /var/run/docker.sock ] && [ "$(id -u)" -eq 0 ]; then
  DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || echo "")
  if [ -n "$DOCKER_GID" ] && [ "$DOCKER_GID" != "0" ]; then
    groupadd -g "$DOCKER_GID" -o docker-host 2>/dev/null || true
    usermod -aG docker-host breaker 2>/dev/null || true
  else
    chgrp breaker /var/run/docker.sock 2>/dev/null || true
    chmod 660 /var/run/docker.sock 2>/dev/null || true
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8: Start temp Postgres (embedded) → run migrations → stop
# ═══════════════════════════════════════════════════════════════════════════════
echo "${LOG_TAG} Phase 8: Database migrations..."

# Detect PG_BIN for embedded Postgres
if [ -x "/usr/lib/postgresql/15/bin/postgres" ]; then
  PG_BIN="/usr/lib/postgresql/15/bin"
elif [ -x "/usr/lib/postgresql/16/bin/postgres" ]; then
  PG_BIN="/usr/lib/postgresql/16/bin"
elif [ -x "/usr/lib/postgresql/17/bin/postgres" ]; then
  PG_BIN="/usr/lib/postgresql/17/bin"
elif command -v postgres >/dev/null 2>&1; then
  PG_BIN="$(dirname "$(command -v postgres)")"
else
  PG_BIN=""
fi

if [ "${USE_EXTERNAL_DB:-0}" -eq 1 ]; then
  # External Postgres: wait for it, then migrate
  echo "${LOG_TAG} Using external Postgres (CB_DB_URL); waiting for it to become ready..."
  PGHOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.hostname or '127.0.0.1')" 2>/dev/null || true)
  PGPORT=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.port or 5432)" 2>/dev/null || true)
  PGUSER=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.username or 'breaker')" 2>/dev/null || true)
  PGHOST=${PGHOST:-127.0.0.1}
  PGPORT=${PGPORT:-5432}
  PGUSER=${PGUSER:-breaker}
  for i in $(seq 1 120); do
    if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres >/dev/null 2>&1; then
      echo "${LOG_TAG} External Postgres is ready at ${PGHOST}:${PGPORT}."
      break
    fi
    [ "$i" -eq 120 ] && { echo "${LOG_TAG} External Postgres did not become ready in time." >&2; exit 1; }
    sleep 1
  done
  run_as_breaker "bash ${SCRIPT_DIR}/20-migrate.sh"
else
  # Embedded Postgres: start temp instance, migrate, then stop
  if [ -z "$PG_BIN" ]; then
    echo "${LOG_TAG} ERROR: Postgres binaries not found for embedded mode." >&2
    exit 1
  fi

  run_as_breaker "${PG_BIN}/postgres -D ${DATA}/pgdata -c config_file=${DATA}/postgresql.conf" &
  POSTGRES_PID=$!

  echo "${LOG_TAG} Waiting for Postgres to accept connections..."
  for i in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -p 5432 -U breaker -d postgres >/dev/null 2>&1; then
      break
    fi
    if [ "$i" -eq 60 ]; then
      kill $POSTGRES_PID 2>/dev/null; wait $POSTGRES_PID 2>/dev/null
      echo "${LOG_TAG} Postgres did not become ready." >&2
      exit 1
    fi
    sleep 1
  done

  run_as_breaker "bash ${SCRIPT_DIR}/20-migrate.sh"

  # Stop temp Postgres — supervisord or systemd will manage it at runtime
  run_as_breaker "${PG_BIN}/pg_ctl -D ${DATA}/pgdata -m fast -w stop"
  wait "$POSTGRES_PID" 2>/dev/null || true
  rm -f "${DATA}/pgdata/postmaster.pid" "${DATA}/pgdata/postmaster.opts" 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9: pgbouncer pool URL (set AFTER migrations)
# ═══════════════════════════════════════════════════════════════════════════════
if [ "${USE_EXTERNAL_DB:-0}" -eq 0 ] && [ -n "${CB_DB_URL:-}" ]; then
  export CB_DB_POOL_URL="$(echo "$CB_DB_URL" | sed 's/:5432/:6432/')"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10: Vault key auto-sync (adopt data-volume copy if rotated)
# ═══════════════════════════════════════════════════════════════════════════════
_DATA_ENV="${DATA}/.env"
if [ -f "$_DATA_ENV" ]; then
  _data_vault_key="$(grep -s '^CB_VAULT_KEY=' "$_DATA_ENV" | head -1 | cut -d= -f2-)"
  if [ -n "$_data_vault_key" ] && [ "$_data_vault_key" != "${CB_VAULT_KEY:-}" ]; then
    echo "${LOG_TAG} Vault key updated by auto-rotation — syncing from data volume."
    export CB_VAULT_KEY="$_data_vault_key"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11: OOBE marker
# ═══════════════════════════════════════════════════════════════════════════════
OOBE_MARKER="${DATA}/.oobe-complete"
if [ ! -f "${OOBE_MARKER}" ]; then
  echo "${LOG_TAG} First run detected. Complete the web OOBE in your browser."
  touch "${OOBE_MARKER}"
  [ "$(id -u)" -eq 0 ] && chown breaker:breaker "${OOBE_MARKER}" 2>/dev/null || true
else
  echo "${LOG_TAG} OOBE marker already present."
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Final: Mode-dependent exit
# ═══════════════════════════════════════════════════════════════════════════════
echo "${LOG_TAG} All initialization phases complete."

if [ "${CB_DEPLOY_MODE:-docker}" = "native" ]; then
  # systemd ExecStartPre= mode: return after initialization
  echo "${LOG_TAG} Native mode — initialization done, returning to systemd."
  exit 0
else
  # Docker mode: exec supervisord
  echo "${LOG_TAG} Docker mode — starting supervisord..."
  exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
fi
