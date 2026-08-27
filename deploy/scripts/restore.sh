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
# It takes either of the two artifacts this product produces, and does with each one
# exactly what that artifact contains:
#
#   <name>.tar.gz   The full-state snapshot `cb backup` builds — database, uploads,
#                   config and the vault key. Everything below runs.
#   <name>.sql      A bare pg_dump, which is what `install.sh --upgrade` writes to
#   <name>.sql.gz   ${CB_DATA_DIR}/backups/pre-upgrade-*.sql before it migrates
#                   (deploy/setup.sh, run_upgrade). Only the database is replaced.
#
# The second kind is here because the documented rollback for a bad upgrade — "restore
# the pre-upgrade backup" (docs/release/1.0.0-compatibility-policy.md) — named an
# artifact that nothing in the tree would accept: this script's structure check rejected
# it for having no db.sql.gz, and `cb restore` rejected it in the backend verifier. The
# upgrade produced a rollback nobody could perform.
#
# The dump is not the weaker choice there, it is the correct one. run_upgrade takes it
# *after* install.sh has already replaced /opt/circuitbreaker/bin/circuit-breaker with
# the new build and *before* migrations run, so the snapshot builder is not available to
# it: run_full_snapshot opens a session and reads AppSettings through the new ORM against
# the old schema, which raises on every release that adds a column to that table — and
# the pre-upgrade backup is a gate, so a builder that cannot run is an upgrade that
# refuses to start. And a migration changes the schema, not the uploads and not the vault
# key: the database is the whole of what has to go back. What was missing was a consumer,
# not a better artifact.
#
# Restores from a snapshot tarball:
#   - PostgreSQL database
#   - Uploads directory
#   - Vault key (CB_VAULT_KEY in the environment file the service actually reads)
#
# Restores from a bare dump:
#   - PostgreSQL database, and nothing else. Uploads and the vault key on this host are
#     left exactly as they are, which is what a rollback wants: they are not what the
#     upgrade changed.
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

# ── 1b. Decide which of the two artifacts this is ──────────────────────────

# By suffix, deliberately, rather than by sniffing the file: the two shapes are named
# apart at the point they are created (`cb-snapshot-*.tar.gz` from the snapshot builder,
# `pre-upgrade-*.sql` from run_upgrade), and an operator who mistypes one for the other
# is better served by the structure check below failing loudly than by this script
# quietly deciding it knows better than the name.
case "$SNAPSHOT" in
    *.sql|*.sql.gz) RESTORE_KIND="database" ;;
    *)              RESTORE_KIND="snapshot" ;;
esac

# ── 2. Validate required tools ─────────────────────────────────────────────

# jq, rsync and sha256sum read the manifest, sync uploads and check the recorded
# checksum — none of which a bare dump has. Demanding them for a database-only restore
# would refuse a recovery over tools it is not going to call.
# psql, dropdb and createdb are resolved through $PG_BIN_DIR before PATH.
# deploy/setup.sh:1608 already documents why, and qualifies its own pg_dump the
# same way: PGDG installs the client binaries under /usr/pgsql-15/bin on the dnf
# families, which is not on root's PATH. A bare `psql` there is simply "not
# found" — so this script refused the rollback with "Missing required tools:
# psql" on exactly the hosts setup.sh had just told the operator to run it on.
# Unset PG_BIN_DIR (the deb families, and any host where the client tools are on
# PATH) falls through to the plain name, which is what has always worked there.
# PG_BIN_DIR is exported by setup.sh, but this script is also run standalone —
# which is precisely the rollback case setup.sh prints instructions for — so it
# cannot rely on inheriting it. Fall back to the PGDG layout by inspection, and
# to the bare name last so nothing changes on a host where PATH already works.
_pg_bin() {
    local name="$1" candidate
    if [[ -n "${PG_BIN_DIR:-}" && -x "${PG_BIN_DIR}/${name}" ]]; then
        printf '%s' "${PG_BIN_DIR}/${name}"
        return
    fi
    if command -v "$name" &>/dev/null; then
        printf '%s' "$name"
        return
    fi
    # Newest first: a host with two PGDG majors installed should use the later
    # client, which can read a dump taken by either.
    for candidate in $(printf '%s\n' /usr/pgsql-*/bin | sort -rV); do
        if [[ -x "${candidate}/${name}" ]]; then
            printf '%s' "${candidate}/${name}"
            return
        fi
    done
    printf '%s' "$name"
}
PG_PSQL="$(_pg_bin psql)"
PG_DROPDB="$(_pg_bin dropdb)"
PG_CREATEDB="$(_pg_bin createdb)"

if [[ "$RESTORE_KIND" == "snapshot" ]]; then
    REQUIRED_TOOLS=(tar gzip "$PG_PSQL" "$PG_DROPDB" "$PG_CREATEDB" rsync jq sed sha256sum)
else
    REQUIRED_TOOLS=(gzip "$PG_PSQL" "$PG_DROPDB" "$PG_CREATEDB" sed)
fi
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

# ── 4. Validate structure ──────────────────────────────────────────────────
#
# Steps 4-6 are the snapshot's structure, manifest and recorded checksum; the else
# branch is everything a bare dump can be checked for. Both bodies are left at their
# own indentation rather than shifted one level in, so that what this script does to a
# snapshot stays line-for-line comparable with what it always did.

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if [[ "$RESTORE_KIND" == "snapshot" ]]; then

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

else

echo "==> Validating database dump: $SNAPSHOT"

# A bare dump carries no manifest and no recorded checksum, so there is nothing to
# verify it against — which is worth saying out loud rather than leaving the operator to
# infer it from a step that did not print. What can be checked is that the file is not
# empty and is what it claims to be. `pg_dump`'s plain format — the only format psql can
# replay, and so the only one that can arrive here — always opens with that header, and
# a dump truncated by a full disk or a killed process is exactly what this catches while
# the service is still up and the database still intact. `zcat -f` reads .sql and .sql.gz
# through the same pipe.
#
# The head is captured before it is matched rather than piped straight into grep: this
# script runs under `pipefail`, and `grep -q` closing the pipe early makes the producer
# exit 141, which would fail the check on precisely the dumps that pass it.
if [[ ! -s "$SNAPSHOT" ]]; then
    echo "ERROR: ${SNAPSHOT} is empty — there is nothing in it to restore." >&2
    exit 1
fi
DUMP_HEAD=$(zcat -f "$SNAPSHOT" 2>/dev/null | head -n 40) || true
if ! grep -q "PostgreSQL database dump" <<<"$DUMP_HEAD"; then
    echo "ERROR: ${SNAPSHOT} does not look like a pg_dump — its header line is missing." >&2
    echo "       Expected a plain-SQL dump such as the one install.sh --upgrade writes" >&2
    echo "       to \${CB_DATA_DIR}/backups/pre-upgrade-*.sql, or a full snapshot" >&2
    echo "       tarball from 'cb backup'. Nothing has been changed." >&2
    exit 1
fi
echo "    Dump header OK — no manifest and no recorded checksum to verify (a bare dump carries neither)"

fi

# ── 7. Confirm with user ───────────────────────────────────────────────────

echo ""
if [[ "$RESTORE_KIND" == "snapshot" ]]; then
    echo "⚠  This will STOP the Circuit Breaker service, DROP the existing database,"
    echo "   and REPLACE all data with the snapshot contents."
else
    # Naming what is *not* replaced is the point of this branch. An operator who has
    # been told "REPLACE all data" and then finds their uploads and vault key untouched
    # has been misled about what they just did, in the one direction that matters:
    # a database-only restore leaves this host's encrypted columns readable precisely
    # because the vault key was left alone.
    echo "⚠  This will STOP the Circuit Breaker service, DROP the existing database,"
    echo "   and REPLACE it with the contents of this dump."
    echo "   Uploads and the vault key on this host are NOT touched — a bare dump"
    echo "   carries neither, and a rollback does not need them changed."
fi
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

# The dump this replays, whichever artifact it came from. `zcat -f` at step 10 reads
# a gzipped member and a plain .sql through the same pipe, so the two kinds differ
# here in one variable rather than in a second copy of the replay.
DUMP_SOURCE="$SNAPSHOT"

if [[ "$RESTORE_KIND" == "snapshot" ]]; then
    echo "==> Extracting snapshot..."
    tar -xzf "$SNAPSHOT" -C "$TMPDIR"

    # Find the top-level snapshot directory inside the tarball
    SNAP_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name "cb-snapshot-*" | head -1)
    if [[ -z "$SNAP_DIR" ]]; then
        echo "ERROR: Could not find snapshot directory inside tarball." >&2
        exit 1
    fi
    DUMP_SOURCE="$SNAP_DIR/db.sql.gz"
fi

# ── 10. Restore database ───────────────────────────────────────────────────

echo "==> Restoring database..."

# The superuser half goes over the Unix socket as the postgres OS user, not over
# TCP as -U postgres. deploy/config/pg_hba.conf is `local all postgres peer` and
# `host all all 127.0.0.1/32 md5`, and setup.sh initdb's the cluster with
# --auth-host=md5 and never sets a password on the postgres role — so
# `dropdb -h 127.0.0.1 -U postgres` can never authenticate on a host this
# installer built. It failed silently too: dropdb's failure was swallowed by
# `|| true` and createdb was the line that actually died, under set -e, *after*
# step 8 had already stopped the service. An operator following the rollback
# instructions setup.sh prints after a failed upgrade took their install down
# and restored nothing.
#
# `su -s /bin/sh postgres -c` is the shape setup.sh:513 already uses to create
# this database in the first place; peer auth over the socket is why it works
# there and why it works here.
_as_superuser() {
    # Switch user only when that is both necessary and possible. Running as the
    # superuser account already (someone invoking this as `postgres`) needs no
    # switch, and a non-root caller cannot make one — in that case run the
    # command as ourselves and let pg_hba decide, which is a comprehensible
    # authentication error rather than a confusing `su: Authentication failure`.
    if [[ "$(id -un)" == "$CB_DB_SUPERUSER" || "$(id -u)" -ne 0 ]]; then
        sh -c "$1"
    else
        su -s /bin/sh "$CB_DB_SUPERUSER" -c "$1"
    fi
}

if ! _as_superuser "$(printf '%s %q' "$PG_DROPDB" "$CB_DB_NAME")" 2>/dev/null; then
    : # absent database is the normal case on a clean recovery host
fi
if ! _as_superuser "$(printf '%s -O %q %q' "$PG_CREATEDB" "$CB_DB_OWNER" "$CB_DB_NAME")"; then
    echo "ERROR: could not create database '${CB_DB_NAME}' as ${CB_DB_SUPERUSER}." >&2
    echo "       ${CB_SERVICE_UNIT} has been left stopped and nothing was restored." >&2
    echo "       This step runs over the local socket as the '${CB_DB_SUPERUSER}' OS" >&2
    echo "       user; check that the user exists and that pg_hba.conf grants it" >&2
    echo "       'local all ${CB_DB_SUPERUSER} peer'." >&2
    exit 1
fi
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
# PGPASSWORD, because pg_hba is md5 for 127.0.0.1 and this connects as the owner
# role over TCP. It comes from the same $ENV_FILE this script already sources at
# step 3 — every psql call in setup.sh sets it the same way. Without it the
# replay prompts for a password on a non-interactive stdin that is already busy
# carrying the dump, and fails.
if ! PGPASSWORD="${CB_DB_PASSWORD:-}" zcat -f "$DUMP_SOURCE" \
    | PGPASSWORD="${CB_DB_PASSWORD:-}" "$PG_PSQL" \
        -h 127.0.0.1 -U "$CB_DB_OWNER" -v ON_ERROR_STOP=1 "$CB_DB_NAME"; then
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

# ── 11-13. Snapshot-only members ───────────────────────────────────────────
#
# A bare dump has no uploads, no vault.key and no config/, so there is nothing here for
# it to do. Skipping is not a degraded restore: an upgrade migrates the schema and
# leaves all three alone, so this host's copies are already the ones that match the
# database just replayed.
if [[ "$RESTORE_KIND" == "snapshot" ]]; then

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

fi  # end snapshot-only members

# ── 14. Start service ──────────────────────────────────────────────────────

echo "==> Starting ${CB_SERVICE_UNIT}..."
systemctl start "$CB_SERVICE_UNIT"

# ── 15. Done ───────────────────────────────────────────────────────────────

echo ""
echo "✓ Restore complete."
echo ""
if [[ "$RESTORE_KIND" == "snapshot" ]]; then
    echo "⚠  Vault key updated from snapshot."
    echo "   Treat this machine and the snapshot file as sensitive."
else
    echo "   The database was replaced from the dump. Uploads and the vault key were"
    echo "   left as they were — a bare dump carries neither."
    echo "   Treat the dump file as sensitive: it is the whole database in plain text."
fi
