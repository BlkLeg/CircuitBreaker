#!/usr/bin/env bash
# Circuit Breaker — Disaster Recovery Restore Script
#
# Usage: restore.sh <path-to-snapshot.tar.gz>
#
# Restores a full Circuit Breaker state from a snapshot tarball:
#   - PostgreSQL database
#   - Uploads directory
#   - Vault key (CB_VAULT_KEY in /etc/circuitbreaker/.env)
#
# ⚠  WARNING: The snapshot contains the vault key in plaintext.
#    Treat this machine and the snapshot file as sensitive after restore.
#
# Requires: tar, gzip, psql, rsync, jq, sed, sha256sum

set -euo pipefail

# ── 1. Argument check ──────────────────────────────────────────────────────

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <path-to-snapshot.tar.gz>" >&2
    exit 1
fi

SNAPSHOT="$1"

if [[ ! -f "$SNAPSHOT" ]]; then
    echo "ERROR: Snapshot file not found: $SNAPSHOT" >&2
    exit 1
fi

# ── 2. Validate required tools ─────────────────────────────────────────────

REQUIRED_TOOLS=(tar gzip psql rsync jq sed sha256sum)
MISSING=()
for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" &>/dev/null; then
        MISSING+=("$tool")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: Missing required tools: ${MISSING[*]}" >&2
    echo "       Install them and re-run." >&2
    exit 1
fi

# ── 3. Source environment ──────────────────────────────────────────────────

ENV_FILE="/etc/circuitbreaker/.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    set +u
    source "$ENV_FILE"
    set -u
fi

CB_DATA_DIR="${CB_DATA_DIR:-/var/lib/circuitbreaker}"

# ── 4. Validate tarball structure ──────────────────────────────────────────

echo "==> Validating snapshot: $SNAPSHOT"

# Check required entries exist in tarball
TARBALL_CONTENTS=$(tar -tzf "$SNAPSHOT" 2>&1) || {
    echo "ERROR: Cannot read tarball: $SNAPSHOT" >&2
    exit 1
}

for required_file in "db.sql.gz" "vault.key" "manifest.json"; do
    if ! echo "$TARBALL_CONTENTS" | grep -q "$required_file"; then
        echo "ERROR: Snapshot is missing required file: $required_file" >&2
        exit 1
    fi
done

# Verify vault.key is non-empty
VAULT_KEY_BYTES=$(tar -xOf "$SNAPSHOT" "$(echo "$TARBALL_CONTENTS" | grep 'vault\.key$' | head -1)" 2>/dev/null | wc -c)
if [[ "$VAULT_KEY_BYTES" -lt 1 ]]; then
    echo "ERROR: vault.key inside snapshot is empty — this snapshot cannot restore credentials." >&2
    exit 1
fi

# ── 5. Extract and display manifest ───────────────────────────────────────

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

MANIFEST_PATH=$(echo "$TARBALL_CONTENTS" | grep 'manifest\.json$' | head -1)
tar -xOf "$SNAPSHOT" "$MANIFEST_PATH" > "$TMPDIR/manifest.json"

echo ""
echo "Snapshot details:"
jq '.' "$TMPDIR/manifest.json"
echo ""

# ── 6. Verify db.sql.gz SHA-256 checksum ──────────────────────────────────

echo "==> Verifying database checksum..."

DB_MEMBER=$(echo "$TARBALL_CONTENTS" | grep 'db\.sql\.gz$' | head -1)
tar -xOf "$SNAPSHOT" "$DB_MEMBER" > "$TMPDIR/db.sql.gz"

ACTUAL_SHA=$(sha256sum "$TMPDIR/db.sql.gz" | awk '{print $1}')
EXPECTED_SHA=$(jq -r '.db_checksum_sha256' "$TMPDIR/manifest.json")

if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
    echo "ERROR: Database checksum mismatch!" >&2
    echo "  Expected: $EXPECTED_SHA" >&2
    echo "  Actual:   $ACTUAL_SHA" >&2
    exit 1
fi

echo "    Checksum OK: $ACTUAL_SHA"

# ── 7. Confirm with user ───────────────────────────────────────────────────

echo ""
echo "⚠  This will STOP the Circuit Breaker service, DROP the existing database,"
echo "   and REPLACE all data with the snapshot contents."
echo ""
read -r -p "Continue? [y/N] " CONFIRM
CONFIRM="${CONFIRM:-N}"
if [[ "${CONFIRM,,}" != "y" ]]; then
    echo "Aborted." >&2
    exit 1
fi

# ── 8. Stop service ────────────────────────────────────────────────────────

echo "==> Stopping circuitbreaker.target..."
systemctl stop circuitbreaker.target || true

# ── 9. Extract full tarball ────────────────────────────────────────────────

echo "==> Extracting snapshot..."
tar -xzf "$SNAPSHOT" -C "$TMPDIR"

# Find the top-level snapshot directory inside the tarball
SNAP_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name "cb-snapshot-*" | head -1)
if [[ -z "$SNAP_DIR" ]]; then
    echo "ERROR: Could not find snapshot directory inside tarball." >&2
    exit 1
fi

# ── 10. Restore database ───────────────────────────────────────────────────

echo "==> Restoring database..."
dropdb -h 127.0.0.1 -U postgres circuitbreaker 2>/dev/null || true
createdb -h 127.0.0.1 -U postgres -O breaker circuitbreaker
zcat "$SNAP_DIR/db.sql.gz" | psql -h 127.0.0.1 -U breaker circuitbreaker

# ── 11. Restore uploads ────────────────────────────────────────────────────

echo "==> Restoring uploads..."
mkdir -p "$CB_DATA_DIR/uploads"
rsync -a --delete "$SNAP_DIR/uploads/" "$CB_DATA_DIR/uploads/"

# ── 12. Restore vault key ──────────────────────────────────────────────────

echo "==> Updating vault key in $ENV_FILE..."
NEW_VAULT_KEY=$(cat "$SNAP_DIR/vault.key")
if [[ -z "$NEW_VAULT_KEY" ]]; then
    echo "ERROR: Extracted vault.key is empty." >&2
    exit 1
fi

if grep -q "^CB_VAULT_KEY=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^CB_VAULT_KEY=.*|CB_VAULT_KEY=${NEW_VAULT_KEY}|" "$ENV_FILE"
else
    echo "CB_VAULT_KEY=${NEW_VAULT_KEY}" >> "$ENV_FILE"
fi

# ── 13. Restore config files (Caddyfile, TLS certs, full .env) ────────────

echo "==> Restoring config files (if present in snapshot)..."
if echo "$TARBALL_CONTENTS" | grep -q "config/"; then
    if [[ -f "$SNAP_DIR/config/Caddyfile" ]]; then
        cp "$SNAP_DIR/config/Caddyfile" /etc/caddy/Caddyfile
        echo "    Restored Caddyfile"
    fi
    if [[ -f "$SNAP_DIR/config/certs/cert.pem" ]]; then
        mkdir -p /etc/caddy/certs
        cp "$SNAP_DIR/config/certs/cert.pem" /etc/caddy/certs/cert.pem
        cp "$SNAP_DIR/config/certs/key.pem"  /etc/caddy/certs/key.pem
        echo "    Restored TLS certificates"
    fi
    if [[ -f "$SNAP_DIR/config/.env" ]]; then
        cp "$SNAP_DIR/config/.env" /etc/circuitbreaker/.env
        echo "    Restored full .env (includes vault key)"
    fi
else
    echo "    No config/ dir in snapshot — vault key already restored in step 12"
fi

# ── 14. Start service ──────────────────────────────────────────────────────

echo "==> Starting circuitbreaker.target..."
systemctl start circuitbreaker.target

# ── 15. Done ───────────────────────────────────────────────────────────────

echo ""
echo "✓ Restore complete."
echo ""
echo "⚠  Vault key updated from snapshot."
echo "   Treat this machine and the snapshot file as sensitive."
