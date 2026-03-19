#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/circuitbreaker/.env
set +a

fail() { echo "ERROR: $*" >&2; exit 1; }

PLACEHOLDERS="CHANGE_ME changeme placeholder todo test secret password"

check_secret() {
  local name="$1" value="$2" min_len="${3:-0}"
  [[ -z "$value" ]] && fail "$name is not set or empty"
  for p in $PLACEHOLDERS; do
    [[ "${value,,}" == "${p,,}" ]] && fail "$name contains placeholder value: $value"
  done
  if (( min_len > 0 )) && (( ${#value} < min_len )); then
    fail "$name is too short (${#value} chars, minimum $min_len)"
  fi
}

check_secret "CB_JWT_SECRET"   "${CB_JWT_SECRET:-}"   64
check_secret "CB_VAULT_KEY"    "${CB_VAULT_KEY:-}"    32
check_secret "CB_NATS_TOKEN"   "${CB_NATS_TOKEN:-}"    0
check_secret "CB_DB_PASSWORD"  "${CB_DB_PASSWORD:-}"   0
check_secret "CB_REDIS_PASSWORD" "${CB_REDIS_PASSWORD:-}" 0
