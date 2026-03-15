#!/usr/bin/env bash
# Generates a .env file with unique secrets for Circuit Breaker.
# Run from the same directory as docker-compose.yml.
set -euo pipefail

if [[ -f ".env" ]]; then
  echo "ERROR: .env already exists. Remove it first to regenerate." >&2
  exit 1
fi

command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl is required." >&2; exit 1; }

gen() { openssl rand -base64 32 | tr -d '\n/+='; }

CB_JWT_SECRET=$(gen)
CB_VAULT_KEY=$(gen)
NATS_AUTH_TOKEN=$(gen)
CB_REDIS_PASS=$(gen)
CB_DB_PASSWORD=$(gen)

cat > .env <<EOF
# Generated on $(date -u +%Y-%m-%dT%H:%M:%SZ) — do not share.
CB_JWT_SECRET=${CB_JWT_SECRET}
CB_VAULT_KEY=${CB_VAULT_KEY}
NATS_AUTH_TOKEN=${NATS_AUTH_TOKEN}
CB_REDIS_PASS=${CB_REDIS_PASS}
CB_DB_PASSWORD=${CB_DB_PASSWORD}
CB_DOMAIN=localhost
# CB_TLS_EMAIL=
# CB_DATA_DIR=./circuitbreaker-data
# CB_PORT_HTTP=80
# CB_PORT_HTTPS=443
# CB_TAG=v0.2.0
EOF
chmod 600 .env

echo "Created .env — edit CB_DOMAIN if needed, then run: docker compose up -d"
