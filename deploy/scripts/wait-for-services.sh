#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/circuitbreaker/.env
set +a

MAX_WAIT=60
INTERVAL=2

wait_port() {
  local name=$1 host=$2 port=$3 elapsed=0
  while ! nc -z "$host" "$port" 2>/dev/null; do
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      echo "FATAL: $name did not start within ${MAX_WAIT}s" >&2
      echo "Run: cb doctor" >&2
      exit 1
    fi
  done
}

wait_port "pgbouncer"  127.0.0.1 6432

# Redis: authenticated PING — port-open is not enough when requirepass is set
echo "Waiting for Redis to accept authenticated connections..."
elapsed=0
while ! redis-cli -h 127.0.0.1 -p 6379 -a "${CB_REDIS_PASSWORD}" --no-auth-warning PING 2>/dev/null | grep -q PONG; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Redis did not accept authenticated connections within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# NATS: JetStream health endpoint — TCP-open does not mean JetStream is initialised
echo "Waiting for NATS JetStream to become ready..."
elapsed=0
while ! curl -sf http://127.0.0.1:8222/healthz >/dev/null 2>&1; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: NATS JetStream did not become ready within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# Actual DB connection test - port open ≠ DB accepting connections
echo "Waiting for DB to accept connections..."
elapsed=0
while ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Cannot connect to DB through pgbouncer within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# Docker socket proxy — only check when Docker is enabled
if [[ "${DOCKER_PROXY_ENABLED:-false}" == "true" ]]; then
  echo "Waiting for Docker socket proxy..."
  elapsed=0
  while ! curl -sf http://127.0.0.1:2375/version &>/dev/null; do
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      echo "FATAL: Docker socket proxy not responding within ${MAX_WAIT}s" >&2
      echo "Check: journalctl -u circuitbreaker-docker-proxy -n 30" >&2
      exit 1
    fi
  done
  echo "Docker proxy ready (${elapsed}s)"
fi
