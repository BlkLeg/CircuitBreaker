#!/usr/bin/env bash
# Installed as /usr/local/bin/circuit-breaker-rollback by nfpm.yaml.
#
# Rolls a packaged install back to a pre-upgrade backup by driving the product's
# one restore implementation with this layout's paths.
#
# There are two native layouts and they share no paths (packaging/README.md):
# install.sh uses /opt/circuitbreaker, /etc/circuitbreaker/.env, the `breaker`
# role and the circuitbreaker.target unit, while the deb/rpm packages use
# /usr/local, /etc/circuit-breaker/circuit-breaker.env, the `circuitbreaker` role
# and circuit-breaker.service. deploy/scripts/restore.sh already takes every one
# of those as an overridable variable, precisely so the distro-package layout can
# be restored with the same tool instead of a second copy of it -- but until ADR
# 0005 Phase 3 the packages shipped neither the script nor anything that set the
# variables, and docs/installation/upgrading.md printed the /opt/circuitbreaker
# path at operators who had no such file. This is the missing half.
#
# Getting the variables wrong here is silent rather than loud: restore.sh's own
# header records what the old version did when they were unset -- stopped a unit
# that does not exist, dropped the database as roles that do not exist, wrote the
# vault key into a file the packaged unit never reads, and reported success over
# an install whose every encrypted column had become unreadable.
set -euo pipefail

ENV_FILE="${CB_ENV_FILE:-/etc/circuit-breaker/circuit-breaker.env}"
RESTORE="${CB_RESTORE_SCRIPT:-/usr/local/share/circuit-breaker/deploy/scripts/restore.sh}"
BACKUP_DIR_DEFAULT=/var/lib/circuit-breaker/backups

if [ ! -x "$RESTORE" ]; then
    echo "ERROR: $RESTORE is missing or not executable." >&2
    echo "       This package ships it; a missing file means the install is incomplete." >&2
    exit 1
fi

# ── no argument: show what there is to roll back to ────────────────────────
# A rollback tool that answers "usage:" to an operator who does not know the
# filename is a tool that sends them to find one under time pressure. The dumps
# are named by timestamp and live in one directory, so list them.
if [ $# -eq 0 ]; then
    data_dir="$(sed -n 's/^CB_DATA_DIR=//p' "$ENV_FILE" 2>/dev/null | tail -n 1)"
    [ -n "$data_dir" ] || data_dir=/var/lib/circuit-breaker
    backup_dir="${data_dir}/backups"
    [ -d "$backup_dir" ] || backup_dir="$BACKUP_DIR_DEFAULT"

    echo "Usage: circuit-breaker-rollback <pre-upgrade-*.sql | cb-snapshot-*.tar.gz>"
    echo ""
    if compgen -G "$backup_dir/pre-upgrade-*.sql" >/dev/null 2>&1; then
        echo "Pre-upgrade backups in $backup_dir (newest last):"
        ls -1t -r "$backup_dir"/pre-upgrade-*.sql | sed 's/^/  /'
    else
        echo "No pre-upgrade backups found in $backup_dir."
        echo "Those are written by the package's preinstall hook when you upgrade."
    fi
    echo ""
    echo "A pre-upgrade dump restores the DATABASE ONLY, which is the right shape for"
    echo "undoing an upgrade. Reinstall the matching package version first: the dump"
    echo "carries the old schema and the newer binary cannot serve it."
    exit 2
fi

# ── this layout's identities ───────────────────────────────────────────────
# Derived from the env file the service actually reads, not hardcoded, so an
# operator who changed the role or database name in CB_DB_URL is restored into
# the install they have rather than the one the package shipped with.
db_url="$(sed -n 's/^CB_DB_URL=//p' "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
db_name=circuitbreaker
db_owner=circuitbreaker
if [ -n "$db_url" ]; then
    _rest="${db_url#*://}"
    if [ "$_rest" != "$db_url" ]; then
        case "$_rest" in
            *@*)
                _userinfo="${_rest%%@*}"
                _hostpath="${_rest#*@}"
                _user="${_userinfo%%:*}"
                [ -n "$_user" ] && db_owner="$_user"
                ;;
            *) _hostpath="$_rest" ;;
        esac
        _db="${_hostpath##*/}"
        _db="${_db%%\?*}"
        [ -n "$_db" ] && [ "$_db" != "$_hostpath" ] && db_name="$_db"
    fi
fi

export CB_ENV_FILE="$ENV_FILE"
export CB_SERVICE_UNIT=circuit-breaker.service
export CB_DB_NAME="$db_name"
export CB_DB_OWNER="$db_owner"
export CB_DB_SUPERUSER="${CB_DB_SUPERUSER:-postgres}"

exec "$RESTORE" "$@"
