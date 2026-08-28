#!/bin/bash
# nfpm scripts.preinstall — rpm %pre, deb preinst, apk .pre-install.
#
# Takes the pre-upgrade database backup that the documented rollback depends on.
#
# Why this file exists: docs/release/1.0.0-compatibility-policy.md defines rollback
# as "restoring the complete pre-upgrade backup", and docs/installation/upgrading.md
# tells the operator the upgrade takes that backup itself. Both were true only of
# the install.sh path, where deploy/setup.sh's run_upgrade does it. The package path
# had no preinstall hook at all, so `dnf upgrade circuit-breaker` and
# `apt upgrade circuit-breaker` migrated the schema with nothing to go back to --
# a documented recovery procedure whose artifact was never created. Found while
# implementing ADR 0005 Phase 3, whose Tier 1 guarantee is "install, boot, upgrade
# and roll back".
#
# The gate is deliberately the same shape as run_upgrade's: a dump that cannot be
# taken fails the upgrade rather than being warned about, because a warning during
# a package transaction scrolls past and the operator finds out at rollback time.
# The one exception is a database this host cannot reach at all, which is not a
# failed backup -- it is an install with no data to lose.
set -e

# Overridable for the same reason deploy/scripts/restore.sh makes its paths
# overridable: there are two native layouts, and a hook that can only ever read
# one hardcoded path is a hook that cannot be exercised without installing a
# package as root. tests/build/test_package_upgrade_contract.py runs this file
# against a fixture env to check the branch it takes.
ENV_FILE="${CB_ENV_FILE:-/etc/circuit-breaker/circuit-breaker.env}"
DEFAULT_DATA_DIR="${CB_DEFAULT_DATA_DIR:-/var/lib/circuit-breaker}"
SERVICE_USER="${CB_SERVICE_USER:-circuitbreaker}"

# ── is this an upgrade? ─────────────────────────────────────────────────────
# Three packagers, three conventions, and getting it wrong in either direction
# is costly: treating an install as an upgrade dumps a database that does not
# exist yet, and treating an upgrade as an install skips the only backup anyone
# will ask for.
#
#   dpkg preinst : "install" | "install <old>" | "upgrade <old>" | "abort-upgrade <old>"
#   rpm  %pre    : the number of this package that will be installed when the
#                  transaction ends -- 1 on a fresh install, 2 or more on upgrade
#   apk  .pre-install : runs on install only; apk uses a separate .pre-upgrade
#                  script, which nfpm does not emit. Recorded in the phase notes
#                  rather than papered over: on apk this hook cannot fire for an
#                  upgrade, so apk gets no pre-upgrade backup and apk is a Tier 3
#                  ("guaranteed to build") format, not a Tier 1 one.
case "${1:-}" in
    upgrade|abort-upgrade)   IS_UPGRADE=1 ;;
    install|configure|"")    IS_UPGRADE=0 ;;
    *)
        if [ "$1" -ge 2 ] 2>/dev/null; then IS_UPGRADE=1; else IS_UPGRADE=0; fi
        ;;
esac

[ "$IS_UPGRADE" -eq 1 ] || exit 0

echo "Circuit Breaker: upgrade detected — taking a pre-upgrade backup."

# ── what the existing install says about itself ─────────────────────────────
# Read rather than sourced. This runs as root inside a package transaction and
# the file carries CB_VAULT_KEY and the NATS token; parsing two keys out of it
# is cheaper than reasoning about what sourcing it could execute.
cb_env_value() {
    [ -f "$ENV_FILE" ] || return 1
    # Last assignment wins, which is how the shell would have read it.
    sed -n "s/^${1}=//p" "$ENV_FILE" | tail -n 1
}

if [ ! -f "$ENV_FILE" ]; then
    # An upgrade over an install that never generated its environment. There is
    # no connection string to dump with and, by construction, no schema this
    # package ever migrated. Not a backup failure.
    echo "Circuit Breaker: no $ENV_FILE — nothing to back up, continuing."
    exit 0
fi

DB_URL="$(cb_env_value CB_DB_URL || true)"
DATA_DIR="$(cb_env_value CB_DATA_DIR || true)"
[ -n "$DATA_DIR" ] || DATA_DIR="$DEFAULT_DATA_DIR"

if [ -z "$DB_URL" ]; then
    echo "Circuit Breaker: CB_DB_URL is not set in $ENV_FILE — nothing to back up, continuing."
    exit 0
fi

# ── locate the client tools ────────────────────────────────────────────────
# PG_BIN_DIR first, then PATH, then the two layouts PGDG uses. deploy/setup.sh
# and deploy/scripts/restore.sh both qualify their client binaries the same way
# and for the same reason: PGDG installs pg_dump under /usr/pgsql-<n>/bin on the
# dnf families, which is not on root's PATH, so a bare `pg_dump` there is simply
# not found.
cb_pg_bin() {
    local name=$1 candidate
    if [ -n "${PG_BIN_DIR:-}" ] && [ -x "${PG_BIN_DIR}/${name}" ]; then
        printf '%s' "${PG_BIN_DIR}/${name}"
        return 0
    fi
    if command -v "$name" >/dev/null 2>&1; then
        command -v "$name"
        return 0
    fi
    for candidate in /usr/pgsql-*/bin/"$name" /usr/lib/postgresql/*/bin/"$name"; do
        if [ -x "$candidate" ]; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

PG_DUMP="$(cb_pg_bin pg_dump || true)"
PG_ISREADY="$(cb_pg_bin pg_isready || true)"

# ── is there a database to back up? ────────────────────────────────────────
# Unreachable is not the same as failed. An operator upgrading a host whose
# database lives elsewhere and is currently down, or who has never finished
# configuring one, has no data at risk from this transaction, and refusing the
# upgrade would strand them. A database that answers and then cannot be dumped
# is the case this gate exists for.
if [ -z "$PG_DUMP" ] || [ -z "$PG_ISREADY" ]; then
    echo "Circuit Breaker: PostgreSQL client tools not found — skipping the pre-upgrade backup." >&2
    echo "  Install them (Fedora: postgresql, Debian/Ubuntu: postgresql-client) and take a" >&2
    echo "  backup by hand before upgrading if this host holds data you need." >&2
    exit 0
fi

if ! "$PG_ISREADY" -d "$DB_URL" >/dev/null 2>&1; then
    echo "Circuit Breaker: database is not reachable — skipping the pre-upgrade backup."
    exit 0
fi

# ── take it ────────────────────────────────────────────────────────────────
BACKUP_DIR="${DATA_DIR}/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/pre-upgrade-${STAMP}.sql"

# Owned by the service user, not root. The scheduled backups
# (services/db_backup.py and the nightly snapshot) write into this same
# directory as circuitbreaker, so a root-owned 0755 directory created here would
# fix this dump and permanently break every scheduled one -- trading a visible
# failure for a silent one. deploy/setup.sh:1633 records the identical decision
# for the install.sh layout.
mkdir -p "$BACKUP_DIR"
if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR"
fi
chmod 755 "$BACKUP_DIR"

# mktemp rather than a fixed /tmp name. This runs as root during a package
# transaction, and a predictable path in a world-writable directory is a symlink
# an unprivileged local user can plant before the upgrade runs.
DUMP_ERR="$(mktemp)"
trap 'rm -f "$DUMP_ERR"' EXIT

if ! "$PG_DUMP" "$DB_URL" > "$BACKUP_FILE" 2>"$DUMP_ERR" \
   || [ ! -s "$BACKUP_FILE" ]; then
    # Remove the stub before failing. A zero-byte file sitting among real dumps
    # reads as a usable backup months later, which is worse than having none.
    rm -f "$BACKUP_FILE"
    echo "::error::Circuit Breaker: pre-upgrade backup failed — refusing to upgrade without one." >&2
    if [ -s "$DUMP_ERR" ]; then
        echo "pg_dump said:" >&2
        sed 's/^/  /' "$DUMP_ERR" >&2
    fi
    echo "  Take a verified backup by hand, then retry the upgrade." >&2
    exit 1
fi

# The dump is a database in a file: readable by its owner only.
chmod 600 "$BACKUP_FILE"
if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_FILE"
fi

echo "Circuit Breaker: pre-upgrade backup saved to $BACKUP_FILE"
# Name the command that consumes it, on the same screen. An operator reading
# this at 3am should not have to work out what to do with the file they were
# just handed -- and on a package host that command is the shipped wrapper, not
# the /opt/circuitbreaker path the docs used to print for every layout.
echo "    Roll back with: sudo circuit-breaker-rollback $BACKUP_FILE"
