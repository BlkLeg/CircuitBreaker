#!/bin/bash
# nfpm scripts.rpm.posttrans — rpm %posttrans, and rpm only.
#
# The one scriptlet that runs after the OLD package's %preun.
#
# ADR 0005 Phase 3, F5. rpm's upgrade order is:
#
#   1. new %pre        (preinstall.sh — records the unit state)
#   2. new files unpacked
#   3. new %post       (postinstall.sh — enables, try-restart)
#   4. OLD %preun      (the old package's preremove — stops and disables)
#   5. old files removed
#   6. new %posttrans  (this file — puts back what step 4 took away)
#
# Slice 1 made preremove.sh a no-op when the package is being replaced, which
# fixes upgrades *from* a version carrying that fix. It cannot fix an upgrade
# from a version already published: step 4 runs the old package's copy, and
# every released version through v1.0.0-rc.4 stops and disables unconditionally.
# Confirmed against the artifact rather than the tree —
# `rpm -qp --scripts circuit-breaker_0.3.4_amd64.rpm` shows a %preun with no $1
# guard. postinstall.sh's try-restart happens at step 3, one step too early to
# help.
#
# deb and apk do not need this. dpkg runs the old prerm BEFORE unpacking and the
# new postinst last, so postinstall.sh already has the final word there; adding a
# second restart path for them would be two mechanisms for one guarantee.
#
# This restores the state preinstall.sh recorded rather than enabling
# unconditionally. An upgrade must not start a service the operator had
# deliberately stopped — the same reason postinstall.sh uses try-restart rather
# than restart.
set -e

UNIT_STATE_FILE="${CB_UNIT_STATE_FILE:-/run/circuit-breaker/pre-upgrade-unit-state}"
SERVICE_NAME="${CB_SERVICE_NAME:-circuit-breaker.service}"

# No stamp means preinstall did not run as an upgrade — a fresh install, where
# postinstall has already done the enabling and there is nothing to restore.
[ -f "$UNIT_STATE_FILE" ] || exit 0

enabled=0
active=0
# Read, not sourced: the file is written by preinstall.sh one step earlier and
# holds two integers, but it sits in a world-readable directory and sourcing it
# would execute whatever it contains.
while IFS='=' read -r key value; do
    case "$key" in
        enabled) enabled="$value" ;;
        active)  active="$value" ;;
    esac
done < "$UNIT_STATE_FILE"

# Removed before acting, not after: a stamp that survives a failure here would
# steer the *next* upgrade with a state from this one.
rm -f "$UNIT_STATE_FILE"

systemctl daemon-reload 2>/dev/null || true

if [ "$enabled" = "1" ] && ! systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo "Circuit Breaker: re-enabled $SERVICE_NAME — the previous package's uninstall scriptlet disabled it during the upgrade."
fi

if [ "$active" = "1" ] && ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo "Circuit Breaker: restarted $SERVICE_NAME — the previous package's uninstall scriptlet stopped it during the upgrade."
fi

exit 0
