#!/usr/bin/env bash
# Circuit Breaker — Disaster Recovery Restore Script
#
# Usage: restore.sh <path-to-snapshot.tar.gz>
#
# `cb restore <archive>` is the supported entry point on every install mode, and on a
# native install it drives this script — verifying the archive with the backend's own
# verifier, confirming with the operator and taking a safety snapshot before calling in
# here. This script stays directly callable for disaster recovery, when `cb` or its
# install.conf is part of what was lost.
#
# Restores a full Circuit Breaker state from a snapshot tarball:
#   - PostgreSQL database
#   - Uploads directory
#   - Vault key (CB_VAULT_KEY in the environment file the service actually reads)
#
# There are two native layouts and they share no paths (packaging/README.md). This
# script's defaults are the `install.sh` one it was written for; every path, unit and
# role it needs is an overridable variable so the distro-package layout can be restored
# with the same tool instead of a second copy of it. `cb restore` on a `binary` install
# sets them. Getting this wrong is silent: the old version stopped a unit that does not
# exist on a package host (`|| true`), dropped the database as roles that do not exist
# there, and wrote the vault key into a file the packaged unit never reads — then
# reported success over an install whose every encrypted column had become unreadable.
#
#   CB_ENV_FILE       environment file to source and to write CB_VAULT_KEY back into
#   CB_SERVICE_UNIT   systemd unit stopped for the restore and started again after it
#   CB_DB_NAME        database dropped, recreated and loaded
#   CB_DB_OWNER       role that owns it, and that the dump is replayed as
#   CB_DB_SUPERUSER   role used to drop and create it
#   CB_DATA_DIR       uploads root — a value in the sourced env file wins over one
#                     passed in, and /var/lib/circuitbreaker is the fallback both
#                     layouts land on when nothing names it (db_backup.py's default)
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

# The install.sh-native layout, which is what this script defaults to. `cb restore` on a
# `binary` (deb/rpm/apk) install overrides all five — see the header.
ENV_FILE="${CB_ENV_FILE:-/etc/circuitbreaker/.env}"
CB_SERVICE_UNIT="${CB_SERVICE_UNIT:-circuitbreaker.target}"
CB_DB_NAME="${CB_DB_NAME:-circuitbreaker}"
CB_DB_OWNER="${CB_DB_OWNER:-breaker}"
CB_DB_SUPERUSER="${CB_DB_SUPERUSER:-postgres}"

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

# `|| true` used to stand here. On a host without this unit that is not resilience: it
# is the database being dropped out from under a service that never stopped, and the
# only clue is a line of output nobody is reading. Nothing has been destroyed yet, so a
# stop that did not happen is a refusal.
echo "==> Stopping ${CB_SERVICE_UNIT}..."
if ! systemctl cat "$CB_SERVICE_UNIT" >/dev/null 2>&1; then
    echo "ERROR: systemd unit '${CB_SERVICE_UNIT}' does not exist on this host." >&2
    echo "       This snapshot is being restored onto a layout it does not match." >&2
    echo "       install.sh installs circuitbreaker.target; the deb/rpm/apk packages" >&2
    echo "       install circuit-breaker.service. Set CB_SERVICE_UNIT (and CB_ENV_FILE," >&2
    echo "       CB_DB_OWNER, CB_DB_SUPERUSER) to this host's layout and re-run." >&2
    echo "       Nothing has been changed." >&2
    exit 1
fi
if ! systemctl stop "$CB_SERVICE_UNIT"; then
    echo "ERROR: could not stop ${CB_SERVICE_UNIT} — refusing to restore under a live" >&2
    echo "       service. Nothing has been changed." >&2
    exit 1
fi

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
dropdb -h 127.0.0.1 -U "$CB_DB_SUPERUSER" "$CB_DB_NAME" 2>/dev/null || true
createdb -h 127.0.0.1 -U "$CB_DB_SUPERUSER" -O "$CB_DB_OWNER" "$CB_DB_NAME"
# `-v ON_ERROR_STOP=1` is not optional here, and this line went without it for a long
# time. psql's default is to report a failed statement on stderr and carry straight on
# to the next one, exiting 0 as long as it reached the end of its input — so a replay
# that created two tables out of ninety was indistinguishable, to `set -e` and to the
# operator, from one that created all ninety. The script then synced uploads, rewrote
# the vault key, started the unit and printed "Restore complete." over a database
# missing most of its schema. That is the worst possible outcome for a disaster
# recovery tool: the evidence the operator acts on is the success line itself.
#
# The failure shapes this catches are the ordinary ones for a recovery host, not exotic
# ones: an extension the snapshot uses that this PostgreSQL cannot load, a role the dump
# grants to that does not exist here, a server older than the one the dump came from.
#
# `if !` rather than a bare pipeline is required so errexit does not kill the script
# before the message below prints; pipefail still surfaces a zcat failure. Deliberately
# no `--single-transaction`: `cb`'s container path (cb:693, cb:696) and the snapshot
# round-trip test replay with ON_ERROR_STOP alone, TimescaleDB — which this schema uses
# where it is available — has its own rules about what may be replayed inside one
# transaction, and step 10 already drops and recreates the database, so re-running the
# restore is what cleans up a partial load.
if ! zcat "$SNAP_DIR/db.sql.gz" \
    | psql -h 127.0.0.1 -U "$CB_DB_OWNER" -v ON_ERROR_STOP=1 "$CB_DB_NAME"; then
    echo "ERROR: the dump did not replay cleanly — see the psql errors above." >&2
    echo "       The database was NOT restored and ${CB_SERVICE_UNIT} has been left" >&2
    echo "       stopped; what is in '${CB_DB_NAME}' now is a partial load and must" >&2
    echo "       not be served. Common causes: this host's PostgreSQL lacks an" >&2
    echo "       extension the snapshot uses (timescaledb needs it in" >&2
    echo "       shared_preload_libraries), a role the dump grants to does not exist" >&2
    echo "       here, a major-version mismatch, or no disk space." >&2
    echo "       Fix the cause and re-run with the same snapshot — step 10 drops and" >&2
    echo "       recreates the database, so the partial load is discarded." >&2
    exit 1
fi

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

# ── 13. Restore config files (nginx site config, full .env) ───────────────

echo "==> Restoring config files (if present in snapshot)..."
if echo "$TARBALL_CONTENTS" | grep -q "config/"; then
    if [[ -f "$SNAP_DIR/config/nginx/circuitbreaker.conf" ]]; then
        cp "$SNAP_DIR/config/nginx/circuitbreaker.conf" /etc/nginx/conf.d/circuitbreaker.conf
        echo "    Restored nginx site config"
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx || true
        else
            echo "    WARNING: restored nginx config failed validation; not reloading." >&2
        fi
    fi
    # config/.env is captured from /etc/circuitbreaker/.env, which is the install.sh
    # layout's file. Copying it onto a package host would replace that host's env file
    # with one full of paths and roles it does not have — and step 12 has already put
    # the vault key where this host's unit reads it.
    if [[ -f "$SNAP_DIR/config/.env" ]]; then
        if [[ "$ENV_FILE" == "/etc/circuitbreaker/.env" ]]; then
            cp "$SNAP_DIR/config/.env" /etc/circuitbreaker/.env
            echo "    Restored full .env (includes vault key)"
        else
            echo "    Skipped config/.env: it belongs to the install.sh layout, and this"
            echo "    host reads ${ENV_FILE}. The vault key was written there in step 12."
        fi
    fi
else
    echo "    No config/ dir in snapshot — vault key already restored in step 12"
fi

# ── 14. Start service ──────────────────────────────────────────────────────

echo "==> Starting ${CB_SERVICE_UNIT}..."
systemctl start "$CB_SERVICE_UNIT"

# ── 15. Done ───────────────────────────────────────────────────────────────

echo ""
echo "✓ Restore complete."
echo ""
echo "⚠  Vault key updated from snapshot."
echo "   Treat this machine and the snapshot file as sensitive."
