#!/usr/bin/env bash
#
# Run install.sh end to end and prove the result works.
#
# Nothing has ever executed this installer. pages.yml publishes it, release.yml
# attaches it, and tests/build/ greps its text — so every defect in the most
# prominently documented install path has been found by users.
#
# One file, run identically in CI and locally, because a journey that only
# exists as workflow YAML cannot be reproduced when it fails.
#
# Usage: installer-journey.sh <bundle.tar.gz>
set -euo pipefail

BUNDLE="${1:?usage: installer-journey.sh <bundle.tar.gz>}"
# 8088 is nginx's front port (install.sh:40 CB_PORT), and nginx proxies
# `location /api/` to the backend on 127.0.0.1:8000
# (deploy/systemd/circuitbreaker-backend.service:39 forces --port 8000).
# Health routes live under the v1 prefix (api/routing.py:522), so the paths
# below are /api/v1/..., not bare. NOTE: the PACKAGED deb/rpm unit uses 8080
# instead — do not copy this port into that gate, or that one into this.
PORT="${CB_JOURNEY_PORT:-8088}"
READY_BUDGET="${CB_JOURNEY_READY_BUDGET:-180}"
EVIDENCE="${CB_JOURNEY_EVIDENCE:-/tmp/installer-journey}"

mkdir -p "$EVIDENCE"

section() { printf '\n=== %s ===\n' "$1"; }

fail() {
  printf '::error::%s\n' "$1" >&2
  section "Diagnostics"
  tail -n 200 /var/lib/circuitbreaker/logs/install.log 2>/dev/null || true
  systemctl status 'circuitbreaker-*' --no-pager -l 2>/dev/null || true
  journalctl -u 'circuitbreaker-*' --no-pager -n 200 2>/dev/null || true
  exit 1
}

section "Install from the staged bundle"
# --local-bundle, so the journey does not depend on a published release and
# makes no outbound request for the artifact under test. --unattended, because
# there is no operator. --no-tls, because a self-signed certificate adds a
# failure mode this job is not trying to characterise.
#
# Output is captured rather than streamed so the phase ledger can be asserted
# below; it is echoed back on both paths so a failure is still readable.
set +e
bash install.sh --local-bundle "$BUNDLE" --unattended --no-tls \
  > "$EVIDENCE/install-stdout.log" 2>&1
INSTALL_RC=$?
set -e
cat "$EVIDENCE/install-stdout.log"
[ "$INSTALL_RC" -eq 0 ] || fail "install.sh exited $INSTALL_RC"

section "Assert the installer reported every phase"
# --unattended selects the renderer's plain mode, which prints one timestamped
# line per phase transition. The final phase is the one that proves the run
# reached the end rather than exiting early with status 0 from a subshell.
for phase in \
  "Pre-flight checks" \
  "Downloading bundle" \
  "Installing files" \
  "System dependencies" \
  "Preparing database" \
  "Services and networking" \
  "Starting Circuit Breaker"; do
  grep -qF "$phase" "$EVIDENCE/install-stdout.log" \
    || fail "installer never reported the phase: $phase"
done

section "Wait for /livez"
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:${PORT}/api/v1/livez" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "http://127.0.0.1:${PORT}/api/v1/livez" > "$EVIDENCE/livez.json" \
  || fail "service never answered /livez"

section "Wait for /readyz"
deadline=$(( SECONDS + READY_BUDGET ))
code=000
while [ "$SECONDS" -lt "$deadline" ]; do
  code="$(curl -s -o "$EVIDENCE/readyz.json" -w '%{http_code}' \
    "http://127.0.0.1:${PORT}/api/v1/readyz")" || code=000
  [ "$code" = "200" ] && break
  sleep 2
done
[ "$code" = "200" ] || fail "service never became ready (last /readyz was $code)"
cat "$EVIDENCE/readyz.json"

section "Assert the installed binary contains its application"
/opt/circuitbreaker/bin/circuit-breaker --selftest \
  || fail "the installed binary failed its self-test"

section "Journey complete"
