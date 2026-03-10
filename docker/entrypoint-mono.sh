#!/usr/bin/env bash
set -euo pipefail

# Ensure /data exists and is writable by breaker
mkdir -p "${CB_DATA_DIR:-/data}"
chown -R breaker:breaker "${CB_DATA_DIR:-/data}" || true

# Set CB_DB_URL at runtime from CB_DB_PASSWORD so we never bake a password into the image
if [ -n "${CB_DB_PASSWORD:-}" ]; then
  export CB_DB_URL="postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker"
fi

echo "[entrypoint-mono] Running init scripts..."
for script in /docker/[0-9][0-9]-*.sh; do
  if [ -x "${script}" ]; then
    echo "[entrypoint-mono] Executing ${script}..."
    "${script}"
  fi
done

echo "[entrypoint-mono] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf

