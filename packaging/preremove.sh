#!/bin/bash
# nfpm scripts.preremove — rpm %preun, deb prerm, apk .pre-deinstall.
#
# Stops and disables the service when the package is going away, and does
# NOTHING when it is being replaced by a newer version of itself.
#
# The distinction is not cosmetic, and its absence was a live defect. rpm runs
# the *old* package's %preun after the *new* package's %post during an upgrade:
#
#   1. new %pre        (preinstall.sh, $1=2)
#   2. new files unpacked
#   3. new %post       (postinstall.sh, $1=2 — enables the unit)
#   4. old %preun      (this file, $1=1)
#   5. old files removed
#
# So an unconditional `systemctl stop` + `systemctl disable` here ran last and
# undid step 3: every `dnf upgrade circuit-breaker` finished with the service
# stopped AND disabled, and the next reboot did not bring it back. Nothing in
# the pipeline started a packaged service, so nothing saw it. Found by ADR 0005
# Phase 3's upgrade row, which is the first thing in this project to upgrade a
# package and then look.
set -e

# dpkg prerm : "remove" | "upgrade <new>" | "deconfigure ..." | "failed-upgrade <new>"
# rpm  %preun: the number of this package that will remain -- 0 on the last
#              erase, 1 during an upgrade
# apk        : no argument
case "${1:-}" in
    upgrade|failed-upgrade|deconfigure)
        # The package is being replaced, not removed. postinstall.sh has already
        # run for the new version and owns the unit's state from here.
        exit 0
        ;;
    remove|purge|"")
        # Genuine removal: fall through.
        ;;
    *)
        if [ "$1" -ge 1 ] 2>/dev/null; then
            exit 0
        fi
        ;;
esac

if systemctl is-active --quiet circuit-breaker.service 2>/dev/null; then
  systemctl stop circuit-breaker.service
fi
if systemctl is-enabled --quiet circuit-breaker.service 2>/dev/null; then
  systemctl disable circuit-breaker.service
fi
systemctl daemon-reload 2>/dev/null || true
