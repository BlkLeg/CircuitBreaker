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

# Redis: authenticated PING — port-open is not enough when requirepass is set.
#
# The client is resolved here, at every backend start, rather than baked in when
# the installer wrote this file. RHEL/Rocky/AlmaLinux 10 ship Valkey instead of
# Redis and provide only valkey-cli, so a hardcoded redis-cli made this loop
# spin until MAX_WAIT and then kill the backend with "Redis did not accept
# authenticated connections within 60s" — while the redis unit itself was
# running fine and `cb doctor` reported it OK, which made the real cause
# invisible. Resolving at runtime also means an operator who later installs the
# other client does not have to re-run the installer for this to keep working.
REDIS_CLI="$(command -v redis-cli 2>/dev/null || command -v valkey-cli 2>/dev/null || true)"
if [[ -z "$REDIS_CLI" ]]; then
  echo "FATAL: neither redis-cli nor valkey-cli is installed; cannot verify Redis" >&2
  exit 1
fi

# An empty password is not something to wait out. requirepass would be unset on
# the server too, so the loop below could only ever succeed by accident, and
# sixty seconds of silence is a worse answer than one line naming the file.
# validate-secrets.sh already refuses an empty CB_REDIS_PASSWORD as an
# ExecStartPre before this script; checking again is cheap and keeps this script
# correct when it is run by hand, which is exactly when it is being used to
# diagnose something.
if [[ -z "${CB_REDIS_PASSWORD:-}" ]]; then
  echo "FATAL: CB_REDIS_PASSWORD is empty in /etc/circuitbreaker/.env" >&2
  echo "Redis is configured with requirepass, so no client can connect." >&2
  exit 1
fi

# The client's own stderr is kept and reported on timeout.
#
# This loop discarded it (`2>/dev/null`), so every failure — wrong password,
# connection refused, a client binary that does not exist — produced the same
# sentence: "Redis did not accept authenticated connections within 60s". That
# one sentence is what a Rocky Linux 10 install printed while Redis was
# healthy, the password was correct and the only actual problem was that
# `redis-cli` is not a file on a Valkey host. It cost two speculative fixes
# before anyone could see which of those cases it was.
#
# The error is kept in a file rather than a variable so the loop body stays a
# single pipeline, and the file is created with a private umask because the
# client echoes its own argv — including -a — into some error paths.
REDIS_PROBE_ERR="$(umask 077; mktemp)"
trap 'rm -f "$REDIS_PROBE_ERR"' EXIT

echo "Waiting for Redis to accept authenticated connections..."
elapsed=0
while ! "$REDIS_CLI" -h 127.0.0.1 -p 6379 -a "${CB_REDIS_PASSWORD}" --no-auth-warning PING 2>"$REDIS_PROBE_ERR" | grep -q PONG; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Redis did not accept authenticated connections within ${MAX_WAIT}s" >&2
    echo "  client:     ${REDIS_CLI}" >&2
    # The password never reaches this output: only the client's message does,
    # and `-a <value>` is rewritten if the client echoed the argv back.
    echo "  last error: $(sed -e "s/-a [^ ]*/-a <redacted>/g" "$REDIS_PROBE_ERR" | tr '\n' ' ' | head -c 400)" >&2
    echo "Check: journalctl -u circuitbreaker-redis -n 50" >&2
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
#
# psql's message is kept for the same reason the Redis one is: "cannot connect
# within 60s" does not distinguish a wrong password from a database that does
# not exist from pgbouncer refusing the pool, and those have different fixes.
echo "Waiting for DB to accept connections..."
DB_PROBE_ERR="$(umask 077; mktemp)"
trap 'rm -f "$REDIS_PROBE_ERR" "$DB_PROBE_ERR"' EXIT
elapsed=0
while ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>"$DB_PROBE_ERR"; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Cannot connect to DB through pgbouncer within ${MAX_WAIT}s" >&2
    echo "  last error: $(tr '\n' ' ' < "$DB_PROBE_ERR" | head -c 400)" >&2
    echo "Check: journalctl -u circuitbreaker-pgbouncer -n 50" >&2
    exit 1
  fi
done

# Docker socket proxy — only check when Docker is enabled.
#
# Unlike every probe above it, this one WARNS and continues. The proxy feeds
# container telemetry, which is opt-in on top of the core product: the installer
# itself treats a failed Docker install as a cb_warn and carries on, and none of
# the topology, device or monitoring features touch it. Nothing about the
# backend requires it to exist.
#
# It used to `exit 1`, which made an optional feature able to kill the whole
# application at ExecStartPre. That is how a one-line packaging defect — the
# proxy unit shipped with an unrendered ${CB_DOCKER_BIN} and failed 203/EXEC —
# presented as "Backend failed to start", pointing the operator at the backend
# journal, three services away from the cause. The proxy being down is now
# visible in the backend journal and in `cb doctor` without also being fatal.
#
# The 60s budget is unchanged: on a first start `docker run` may still be
# pulling tecnativa/docker-socket-proxy, and a slow pull that eventually
# succeeds should still leave container telemetry working.
if [[ "${DOCKER_PROXY_ENABLED:-false}" == "true" ]]; then
  echo "Waiting for Docker socket proxy..."
  elapsed=0
  docker_proxy_ready=false
  while [[ $elapsed -lt $MAX_WAIT ]]; do
    if curl -sf http://127.0.0.1:2375/version &>/dev/null; then
      docker_proxy_ready=true
      break
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
  done
  if [[ "$docker_proxy_ready" == "true" ]]; then
    echo "Docker proxy ready (${elapsed}s)"
  else
    echo "WARNING: Docker socket proxy not responding within ${MAX_WAIT}s — starting anyway." >&2
    echo "  Container telemetry will be unavailable until it recovers; nothing else is affected." >&2
    echo "  Check: journalctl -u circuitbreaker-docker-proxy -n 30" >&2
  fi
fi
