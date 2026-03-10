#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"
APP_DIR="/app/backend"
export CB_DATA_DIR="${DATA_DIR}"
export CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-${APP_DIR}/alembic.ini}"
export ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-${CB_ALEMBIC_INI}}"

if [ ! -f "${CB_ALEMBIC_INI}" ]; then
  echo "[migrate] ERROR: Alembic config not found at ${CB_ALEMBIC_INI}." >&2
  exit 1
fi

if [ ! -d "${APP_DIR}/migrations" ]; then
  echo "[migrate] ERROR: Alembic migrations directory missing at ${APP_DIR}/migrations." >&2
  exit 1
fi

# Detect if we're using an external Postgres (CB_DB_URL set and host is not 127.0.0.1/localhost).
USE_EXTERNAL_DB=0
if [ -n "${CB_DB_URL:-}" ]; then
  DB_HOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); h=(u.hostname or '').lower(); print(h)" 2>/dev/null || true)
  case "$DB_HOST" in
    127.0.0.1|localhost|'') ;;
    *) USE_EXTERNAL_DB=1 ;;
  esac
fi

if [ "$USE_EXTERNAL_DB" -eq 1 ]; then
  echo "[migrate] Using external Postgres from CB_DB_URL."
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

  echo "[migrate] Waiting for Postgres to become ready at ${PGHOST}:${PGPORT}..."
  for i in $(seq 1 60); do
    if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres >/dev/null 2>&1; then
      echo "[migrate] Postgres is ready."
      break
    fi
    echo "[migrate] Postgres not ready yet, retrying (${i}/60)..."
    sleep 1
  done

  if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker -d postgres >/dev/null 2>&1; then
    echo "[migrate] ERROR: Postgres did not become ready in time." >&2
    exit 1
  fi

  echo "[migrate] Ensuring circuitbreaker database exists..."
  if ! psql "postgresql://breaker:${CB_DB_PASSWORD}@${PGHOST}:${PGPORT}/postgres" -tAc "SELECT 1 FROM pg_database WHERE datname = 'circuitbreaker'" | grep -q 1; then
    psql "postgresql://breaker:${CB_DB_PASSWORD}@${PGHOST}:${PGPORT}/postgres" -v ON_ERROR_STOP=1 -c 'CREATE DATABASE "circuitbreaker" OWNER breaker'
  fi

  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@${PGHOST}:${PGPORT}/circuitbreaker"
fi

echo "[migrate] Running Alembic migrations from ${APP_DIR}..."
(
  cd "${APP_DIR}"
  alembic -c "${CB_ALEMBIC_INI}" upgrade head
)

echo "[migrate] Database migrations complete."
