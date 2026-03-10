#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"
PGHOST="127.0.0.1"
PGPORT="5432"

echo "[migrate] Waiting for Postgres to become ready at ${PGHOST}:${PGPORT}..."

for i in {1..60}; do
  if pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker >/dev/null 2>&1; then
    echo "[migrate] Postgres is ready."
    break
  fi
  echo "[migrate] Postgres not ready yet, retrying (${i}/60)..."
  sleep 1
done

if ! pg_isready -h "${PGHOST}" -p "${PGPORT}" -U breaker >/dev/null 2>&1; then
  echo "[migrate] ERROR: Postgres did not become ready in time." >&2
  exit 1
fi

echo "[migrate] Ensuring circuitbreaker database exists..."
psql "postgresql://breaker:${CB_DB_PASSWORD}@${PGHOST}:${PGPORT}/postgres" \
  -v ON_ERROR_STOP=1 \
  -c "DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'circuitbreaker') THEN
      PERFORM dblink_exec('dbname=' || current_database(), 'CREATE DATABASE circuitbreaker OWNER breaker');
   END IF;
END
\$\$;" || true

export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@${PGHOST}:${PGPORT}/circuitbreaker"
export CB_DATA_DIR="${DATA_DIR}"

echo "[migrate] Running Alembic migrations via app.main.run_alembic_upgrade()..."
python - <<'PY'
from app.main import run_alembic_upgrade

run_alembic_upgrade()
PY

echo "[migrate] Database migrations complete."

