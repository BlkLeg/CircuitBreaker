#!/usr/bin/env bash
# deploy/common/init-postgres.sh — Postgres cluster initialization.
# Moved from docker/10-init-postgres.sh with parameterized paths.
# Only runs if $CB_DATA_DIR/pgdata/PG_VERSION does not exist.
set -euo pipefail

LOG_TAG="[init-postgres]"

DATA_DIR="${CB_DATA_DIR:-/data}"
PGDATA="${DATA_DIR}/pgdata"
CONF_FILE="${DATA_DIR}/postgresql.conf"

# ── Skip if already initialized ─────────────────────────────────────────────
if [ -f "${PGDATA}/PG_VERSION" ]; then
  echo "${LOG_TAG} Existing Postgres data directory detected at ${PGDATA}, skipping init."
  exit 0
fi

# ── Require a DB password ───────────────────────────────────────────────────
if [ -z "${CB_DB_PASSWORD:-}" ]; then
  echo "${LOG_TAG} ERROR: CB_DB_PASSWORD is required for initial database setup." >&2
  exit 1
fi

# ── Detect Postgres binaries ────────────────────────────────────────────────
# Debian/Ubuntu package path; native installs may have it in PATH already.
if [ -x "/usr/lib/postgresql/15/bin/initdb" ]; then
  PG_INITDB="/usr/lib/postgresql/15/bin/initdb"
elif [ -x "/usr/lib/postgresql/16/bin/initdb" ]; then
  PG_INITDB="/usr/lib/postgresql/16/bin/initdb"
elif [ -x "/usr/lib/postgresql/17/bin/initdb" ]; then
  PG_INITDB="/usr/lib/postgresql/17/bin/initdb"
elif command -v initdb >/dev/null 2>&1; then
  PG_INITDB="initdb"
else
  echo "${LOG_TAG} ERROR: initdb not found. Install postgresql." >&2
  exit 1
fi

echo "${LOG_TAG} Initializing Postgres cluster in ${PGDATA}..."
mkdir -p "${PGDATA}"
chmod 700 "${PGDATA}"

# ── Create temp password file for initdb ────────────────────────────────────
echo "${CB_DB_PASSWORD}" > "${DATA_DIR}/.pg_pass"
chmod 600 "${DATA_DIR}/.pg_pass"

${PG_INITDB} -D "${PGDATA}" --username=breaker --pwfile="${DATA_DIR}/.pg_pass"
rm -f "${DATA_DIR}/.pg_pass"

# ── Write postgresql.conf with parameterized paths ──────────────────────────
cat > "${CONF_FILE}" <<EOF
data_directory = '${PGDATA}'
hba_file = '${PGDATA}/pg_hba.conf'
ident_file = '${PGDATA}/pg_ident.conf'
unix_socket_directories = '${DATA_DIR}/run/postgresql'
listen_addresses = '127.0.0.1'
port = 5432
max_connections = 100
shared_buffers = 128MB
wal_level = 'replica'
synchronous_commit = on
fsync = on
full_page_writes = on
log_destination = 'stderr'
logging_collector = off
log_statement = 'none'
EOF

echo "${LOG_TAG} Postgres cluster initialized."
