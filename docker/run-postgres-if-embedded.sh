#!/usr/bin/env bash
# When CB_DB_URL points to an external host, do not start embedded Postgres (supervisord
# keeps this program "running" via sleep infinity). Otherwise exec the real postgres.
set -euo pipefail

PG_CMD=(/usr/lib/postgresql/15/bin/postgres -D /data/pgdata -p 5432 -c "unix_socket_directories=/data/run/postgresql" -c config_file=/data/postgresql.conf -c shared_preload_libraries=timescaledb)

# ── Stale lock guard ──────────────────────────────────────────────────────────
# If postmaster.pid exists but the recorded PID is no longer running, remove it.
# Without this, a previous postgres that exited without cleanup (e.g. SIGKILL)
# will prevent every subsequent restart with exit code 2.
_PGDATA="/data/pgdata"
_PID_FILE="${_PGDATA}/postmaster.pid"
if [ -f "${_PID_FILE}" ]; then
  _OLD_PID=$(head -1 "${_PID_FILE}" 2>/dev/null || true)
  if [ -n "${_OLD_PID}" ] && ! kill -0 "${_OLD_PID}" 2>/dev/null; then
    echo "[postgres] Removing stale postmaster.pid (PID ${_OLD_PID} not running)"
    rm -f "${_PID_FILE}"
  fi
fi
# ─────────────────────────────────────────────────────────────────────────────

if [ -n "${CB_DB_URL:-}" ]; then
  DB_HOST=$(python3 -c "import os; from urllib.parse import urlparse; u=urlparse(os.environ.get('CB_DB_URL','')); h=(u.hostname or '').lower(); print(h)" 2>/dev/null || true)
  case "$DB_HOST" in
    127.0.0.1|localhost|'') exec "${PG_CMD[@]}" ;;
    *) exec sleep infinity ;;
  esac
fi
exec "${PG_CMD[@]}"
