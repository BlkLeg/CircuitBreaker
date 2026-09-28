#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${CB_DATA_DIR:-/data}"
PGDATA="${DATA_DIR}/pgdata"
CONF_FILE="${DATA_DIR}/postgresql.conf"

if [ -f "${PGDATA}/PG_VERSION" ]; then
  echo "[init-postgres] Existing Postgres data directory detected at ${PGDATA}, skipping init."
  exit 0
fi

if [ -z "${CB_DB_PASSWORD:-}" ]; then
  echo "[init-postgres] ERROR: CB_DB_PASSWORD is required for initial database setup." >&2
  exit 1
fi

echo "[init-postgres] Initializing Postgres cluster in ${PGDATA}..."
mkdir -p "${PGDATA}"
chmod 700 "${PGDATA}"

echo "${CB_DB_PASSWORD}" > "${DATA_DIR}/.pg_pass"
chmod 600 "${DATA_DIR}/.pg_pass"

# Debian postgresql package installs binaries under /usr/lib/postgresql/15/bin (not in PATH)
#
# Encoding and locale are explicit, never inherited. initdb otherwise derives
# both from the environment, and a process with no LANG gets the POSIX locale
# and a SQL_ASCII cluster: every non-ASCII value then fails to insert with
# "'ascii' codec can't encode character". That shipped in 0.4.4, when the
# runtime base moved to debian:12-slim, which sets no locale. The C locale is
# compatible with any encoding on every libc, so this cannot fail on a host
# that lacks a particular UTF-8 locale. See app/db/encoding.py for how
# clusters already created as SQL_ASCII keep working.
/usr/lib/postgresql/15/bin/initdb -D "${PGDATA}" --username=breaker --pwfile="${DATA_DIR}/.pg_pass" \
  --encoding=UTF8 --locale=C
rm -f "${DATA_DIR}/.pg_pass"

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

echo "[init-postgres] Postgres cluster initialized."

