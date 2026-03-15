#!/usr/bin/env bash
# deploy/common/30-vault-init.sh — Vault key bootstrap (Fernet encryption key).
# Ensures CB_VAULT_KEY is available without ever overwriting an existing key.
set -euo pipefail

LOG_TAG="[vault-init]"

DATA="${CB_DATA_DIR:-/data}"
VAULT_KEY_FILE="${DATA}/.vault_key"
DATA_ENV_FILE="${DATA}/.env"

# ── 1. Already set in environment → export and done ─────────────────────────
if [ -n "${CB_VAULT_KEY:-}" ]; then
  echo "${LOG_TAG} CB_VAULT_KEY already set in environment."
  export CB_VAULT_KEY
  return 0 2>/dev/null || exit 0
fi

# ── 2. Dedicated vault key file exists → read and export ────────────────────
if [ -f "$VAULT_KEY_FILE" ]; then
  _key="$(cat "$VAULT_KEY_FILE")"
  if [ -n "$_key" ]; then
    echo "${LOG_TAG} Loaded vault key from ${VAULT_KEY_FILE}."
    export CB_VAULT_KEY="$_key"
    return 0 2>/dev/null || exit 0
  fi
fi

# ── 3. Data .env file has CB_VAULT_KEY → read and export ────────────────────
if [ -f "$DATA_ENV_FILE" ]; then
  _key="$(grep -s '^CB_VAULT_KEY=' "$DATA_ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ -n "$_key" ]; then
    echo "${LOG_TAG} Loaded vault key from ${DATA_ENV_FILE}."
    export CB_VAULT_KEY="$_key"
    return 0 2>/dev/null || exit 0
  fi
fi

# ── 4. No key anywhere → generate a new Fernet key ─────────────────────────
echo "${LOG_TAG} No existing vault key found. Generating new Fernet key..."
CB_VAULT_KEY="$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
export CB_VAULT_KEY

# Persist to dedicated file (mode 0600, readable only by owner)
printf '%s' "$CB_VAULT_KEY" > "$VAULT_KEY_FILE"
chmod 0600 "$VAULT_KEY_FILE"
if [ "$(id -u)" -eq 0 ]; then
  chown breaker:breaker "$VAULT_KEY_FILE" 2>/dev/null || true
fi

echo "${LOG_TAG} Generated and stored new vault key at ${VAULT_KEY_FILE}."
