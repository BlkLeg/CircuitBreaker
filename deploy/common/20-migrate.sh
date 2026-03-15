#!/usr/bin/env bash
# deploy/common/20-migrate.sh — Alembic database migrations.
# Adapted from docker/20-migrate.sh with deploy-mode-aware paths.
set -euo pipefail

LOG_TAG="[migrate]"

DATA_DIR="${CB_DATA_DIR:-/data}"
APP_ROOT="${CB_APP_ROOT:-/opt/circuitbreaker}"
LOG_DIR="${CB_LOG_DIR:-/var/log/circuitbreaker}"
MIGRATION_LOG="${LOG_DIR}/migrations.log"

# ── Determine app directory and alembic binary ──────────────────────────────
if [ "${CB_DEPLOY_MODE:-docker}" = "native" ]; then
  APP_DIR="${APP_ROOT}/backend"
  ALEMBIC_BIN="${APP_DIR}/.venv/bin/alembic"
  if [ ! -x "$ALEMBIC_BIN" ]; then
    # Fallback: try system-wide alembic
    ALEMBIC_BIN="$(command -v alembic 2>/dev/null || true)"
    if [ -z "$ALEMBIC_BIN" ]; then
      echo "${LOG_TAG} ERROR: alembic not found in venv or system PATH." >&2
      exit 1
    fi
  fi
else
  APP_DIR="/app/backend"
  ALEMBIC_BIN="alembic"
fi

export CB_DATA_DIR="${DATA_DIR}"
export CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-${APP_DIR}/alembic.ini}"
export ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-${CB_ALEMBIC_INI}}"

# ── Validate prerequisites ──────────────────────────────────────────────────
if [ ! -f "${CB_ALEMBIC_INI}" ]; then
  echo "${LOG_TAG} ERROR: Alembic config not found at ${CB_ALEMBIC_INI}." >&2
  exit 1
fi

if [ ! -d "${APP_DIR}/migrations" ]; then
  echo "${LOG_TAG} ERROR: Alembic migrations directory missing at ${APP_DIR}/migrations." >&2
  exit 1
fi

# ── Detect external vs embedded Postgres ────────────────────────────────────
USE_EXTERNAL_DB="${USE_EXTERNAL_DB:-0}"
if [ "$USE_EXTERNAL_DB" = "0" ] && [ -n "${CB_DB_URL:-}" ]; then
  DB_HOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); h=(u.hostname or '').lower(); print(h)" 2>/dev/null || true)
  case "$DB_HOST" in
    127.0.0.1|localhost|'') ;;
    *) USE_EXTERNAL_DB=1 ;;
  esac
fi

# ── Ensure circuitbreaker database exists ───────────────────────────────────
if [ "$USE_EXTERNAL_DB" -eq 1 ]; then
  echo "${LOG_TAG} Using external Postgres from CB_DB_URL."
  python3 - <<'PY'
import os
import sys
from urllib.parse import urlparse, urlunparse

url = os.environ.get("CB_DB_URL", "")
if not url:
    print("[migrate] ERROR: CB_DB_URL is not set.", file=sys.stderr)
    sys.exit(1)
u = urlparse(url)
postgres_url = urlunparse(u._replace(path="/postgres"))
try:
    import psycopg2

    conn = psycopg2.connect(postgres_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'circuitbreaker'")
    if not cur.fetchone():
        cur.execute('CREATE DATABASE "circuitbreaker"')
        print("[migrate] Created database circuitbreaker.")
    cur.close()
    conn.close()
except Exception as exc:  # noqa: BLE001
    print(f"[migrate] ERROR: Failed to ensure circuitbreaker database: {exc}", file=sys.stderr)
    sys.exit(1)
PY
else
  PGHOST="127.0.0.1"
  PGPORT="5432"

  echo "${LOG_TAG} Waiting for Postgres to become ready at ${PGHOST}:${PGPORT}..."
  for i in $(seq 1 60); do
    if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres >/dev/null 2>&1; then
      echo "${LOG_TAG} Postgres is ready."
      break
    fi
    echo "${LOG_TAG} Postgres not ready yet, retrying (${i}/60)..."
    sleep 1
  done

  if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres >/dev/null 2>&1; then
    echo "${LOG_TAG} ERROR: Postgres did not become ready in time." >&2
    exit 1
  fi

  echo "${LOG_TAG} Ensuring circuitbreaker database exists..."
  export PGPASSWORD="${CB_DB_PASSWORD:-}"
  if ! psql -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'circuitbreaker'" | grep -q 1; then
    psql -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE "circuitbreaker" OWNER breaker'
  fi
  unset PGPASSWORD

  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD:-}@${PGHOST}:${PGPORT}/circuitbreaker"
fi

# ── Run Alembic migrations ──────────────────────────────────────────────────
echo "${LOG_TAG} Running Alembic migrations from ${APP_DIR}..."
mkdir -p "$(dirname "$MIGRATION_LOG")" 2>/dev/null || true

if ! ( cd "${APP_DIR}" && ${ALEMBIC_BIN} -c "${CB_ALEMBIC_INI}" upgrade head 2>&1 | tee -a "$MIGRATION_LOG" ); then
  echo "${LOG_TAG} Migration failed. Check ${MIGRATION_LOG} for details." >&2
  echo "${LOG_TAG} If the error was 'Can't locate revision identified by ...', the database has a" >&2
  echo "${LOG_TAG} revision that this deployment does not contain." >&2
  if [ "${CB_DEPLOY_MODE:-docker}" = "docker" ]; then
    echo "${LOG_TAG} Rebuild the image: docker compose build --no-cache && docker compose up -d" >&2
  else
    echo "${LOG_TAG} Update the application: cb update" >&2
  fi
  exit 1
fi

echo "${LOG_TAG} Database migrations complete."
