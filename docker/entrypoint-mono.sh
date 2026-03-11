#!/usr/bin/env bash
set -euo pipefail

DATA="${CB_DATA_DIR:-/data}"
export CB_DATA_DIR="$DATA"
export CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-/app/backend/alembic.ini}"
export ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-$CB_ALEMBIC_INI}"

# Determine if we're using an external Postgres (CB_DB_URL set and host is not 127.0.0.1/localhost).
# If external, we skip embedded init and temp Postgres and run migrate against CB_DB_URL.
USE_EXTERNAL_DB=0
if [ -n "${CB_DB_URL:-}" ]; then
  DB_HOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); h=(u.hostname or '').lower(); print(h)" 2>/dev/null || true)
  case "$DB_HOST" in
    127.0.0.1|localhost|'') ;;
    *) USE_EXTERNAL_DB=1 ;;
  esac
fi
if [ "$USE_EXTERNAL_DB" -eq 0 ] && [ -n "${CB_DB_PASSWORD:-}" ]; then
  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker"
fi

# Postgres version from Debian package (Bookworm default)
PG_BIN="/usr/lib/postgresql/15/bin"

ensure_data_dirs() {
  mkdir -p "${CB_DATA_DIR:-/data}/pgdata" "${CB_DATA_DIR:-/data}/uploads" "${CB_DATA_DIR:-/data}/nats" "${CB_DATA_DIR:-/data}/tls"
}

run_as_breaker() {
  local cmd="$1"
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u breaker -- env CB_DATA_DIR="$DATA" CB_DB_URL="${CB_DB_URL:-}" CB_DB_PASSWORD="${CB_DB_PASSWORD:-}" CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-}" ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-}" /bin/bash -c "$cmd"
  else
    env CB_DATA_DIR="$DATA" CB_DB_URL="${CB_DB_URL:-}" CB_DB_PASSWORD="${CB_DB_PASSWORD:-}" CB_ALEMBIC_INI="${CB_ALEMBIC_INI:-}" ALEMBIC_CONFIG="${ALEMBIC_CONFIG:-}" /bin/bash -c "$cmd"
  fi
}

if [ "$(id -u)" -eq 0 ]; then
  if ! chown -R breaker:breaker "$DATA" 2>/dev/null; then
    echo "[entrypoint] chown /data not permitted; ensure volume is writable by 1000:1000 (e.g. chown 1000:1000 ./circuitbreaker-data)." >&2
  fi
fi

# Postgres socket/lock dir (symlinked from /var/run/postgresql in image); must exist and be writable by breaker
mkdir -p "$DATA/run/postgresql"
chmod 1777 "$DATA/run/postgresql"
[ "$(id -u)" -eq 0 ] && chown breaker:breaker "$DATA/run/postgresql" 2>/dev/null || true

if [ "$USE_EXTERNAL_DB" -eq 1 ]; then
  # External Postgres: wait for it to be reachable, then run migrate/oobe against CB_DB_URL (do not start temp postgres).
  # Auth state (users, sessions, jwt_secret in app_settings) lives only in this external DB; CB_DATA_DIR and compose-clean do not touch it.
  echo "[entrypoint] Using external Postgres (CB_DB_URL); waiting for it to become ready..."
  PGHOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.hostname or '127.0.0.1')" 2>/dev/null || true)
  PGPORT=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.port or 5432)" 2>/dev/null || true)
  PGUSER=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); print(u.username or 'breaker')" 2>/dev/null || true)
  PGHOST=${PGHOST:-127.0.0.1}
  PGPORT=${PGPORT:-5432}
  PGUSER=${PGUSER:-breaker}
  for i in $(seq 1 120); do
    if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres >/dev/null 2>&1; then
      echo "[entrypoint] External Postgres is ready at ${PGHOST}:${PGPORT}."
      break
    fi
    [ "$i" -eq 120 ] && { echo "[entrypoint] External Postgres did not become ready in time." >&2; exit 1; }
    sleep 1
  done
  run_as_breaker "[ -x /docker/20-migrate.sh ] && /docker/20-migrate.sh"
  run_as_breaker "[ -x /docker/30-oobe.sh ] && /docker/30-oobe.sh"
else
  # Embedded Postgres: init cluster, start temp postgres, migrate, then stop and remove pid so supervisord can start it.
  run_as_breaker 'mkdir -p "${CB_DATA_DIR:-/data}/pgdata" "${CB_DATA_DIR:-/data}/uploads" "${CB_DATA_DIR:-/data}/nats" "${CB_DATA_DIR:-/data}/tls" "${CB_DATA_DIR:-/data}/run/postgresql"; chmod 1777 "${CB_DATA_DIR:-/data}/run/postgresql" 2>/dev/null || true; [ -x /docker/10-init-postgres.sh ] && /docker/10-init-postgres.sh'

  run_as_breaker "${PG_BIN}/postgres -D ${DATA}/pgdata -c config_file=${DATA}/postgresql.conf" &
  POSTGRES_PID=$!

  echo "[entrypoint] Waiting for Postgres to accept connections..."
  for i in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -p 5432 -U breaker -d postgres >/dev/null 2>&1; then
      break
    fi
    [ "$i" -eq 60 ] && { kill $POSTGRES_PID 2>/dev/null; wait $POSTGRES_PID 2>/dev/null; echo "[entrypoint] Postgres did not become ready." >&2; exit 1; }
    sleep 1
  done

  run_as_breaker "[ -x /docker/20-migrate.sh ] && /docker/20-migrate.sh"
  run_as_breaker "[ -x /docker/30-oobe.sh ] && /docker/30-oobe.sh"

  run_as_breaker "${PG_BIN}/pg_ctl -D ${DATA}/pgdata -m fast -w stop"
  wait "$POSTGRES_PID" 2>/dev/null || true
  rm -f "${DATA}/pgdata/postmaster.pid" "${DATA}/pgdata/postmaster.opts" 2>/dev/null || true
fi

# Ensure nginx can start: create self-signed certs if TLS certs are missing
if [ ! -f "${DATA}/tls/fullchain.pem" ] || [ ! -f "${DATA}/tls/privkey.pem" ]; then
  echo "[entrypoint] No TLS certs found; creating self-signed for nginx."
  mkdir -p "${DATA}/tls"
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "${DATA}/tls/privkey.pem" -out "${DATA}/tls/fullchain.pem" \
    -subj "/CN=localhost" 2>/dev/null
  [ "$(id -u)" -eq 0 ] && chown breaker:breaker "${DATA}/tls/fullchain.pem" "${DATA}/tls/privkey.pem" 2>/dev/null || true
fi

# Allow breaker user to reach the Docker socket if mounted
if [ -S /var/run/docker.sock ]; then
  chmod 666 /var/run/docker.sock 2>/dev/null || true
fi

# Run supervisord as root so nginx can bind to port 80
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
