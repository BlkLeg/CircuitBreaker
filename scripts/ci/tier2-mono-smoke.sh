#!/usr/bin/env bash
# Tier 2 — mono image compose smoke. The one definition of "the image is
# STARTED, not just built": mint ephemeral secrets, bring the image up through
# docker-compose.yml, assert liveness, readiness, the HTTP->HTTPS redirect, the
# SPA over TLS, every supervisord program running, zero restarts and a clean
# SIGTERM stop — then always collect diagnostics and tear down.
#
# Called by mono-smoke.yml with the image already built and tagged by the
# caller. tests/build/test_ci_script_contract.py fails if this script re-grows
# a `|| true` or drifts from strict bash (ADR 0005, P1).
#
# Usage: tier2-mono-smoke.sh IMAGE
set -euo pipefail

# Validate before anything else runs: a malformed invocation should cost
# nothing and say what was wrong.
if [[ $# -ne 1 ]]; then
  printf '::error::tier2-mono-smoke.sh takes exactly one argument, the image to smoke-test\n' >&2
  exit 2
fi

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

cb::require_tool docker
cb::require_tool curl
cb::require_tool python3

CB_IMAGE="$1"
# Not 80/443 by default: the runner already has services on the low ports,
# and a bind failure here would read as a container fault. Overridable so a
# caller running two smokes at once does not collide.
CB_SMOKE_PORT="${CB_SMOKE_PORT:-18080}"
CB_SMOKE_PORT_HTTPS="${CB_SMOKE_PORT_HTTPS:-18443}"
# RUNNER_TEMP is a GitHub Actions runner path; the fallback keeps this script
# runnable outside that environment too.
CB_SMOKE_DATA_DIR="${RUNNER_TEMP:-$CB_REPO_ROOT/.smoke-tmp}/cb-smoke-data"

# The .env holds four live secrets. They are ephemeral and single-run, but the
# workspace is not guaranteed to be discarded before another step reads it,
# and `docker compose down -v` needs the file to resolve the project.
# Teardown first, then remove it, always — via the EXIT trap below, which
# fires whether the assertions below passed or not and preserves the real
# exit code.
teardown() {
  if ! docker compose -f docker-compose.yml down -v --remove-orphans; then
    echo "::warning::docker compose down failed during smoke teardown"
  fi
  shred -u .env 2>/dev/null || rm -f .env
  if ! sudo rm -rf "${CB_SMOKE_DATA_DIR}"; then
    echo "::warning::could not remove ${CB_SMOKE_DATA_DIR}"
  fi
}

# if: always() — the run that most needs its logs is the one that failed
# before reaching the step that would have collected them.
collect_diagnostics() {
  mkdir -p artifacts/diagnostics
  if ! docker compose -f docker-compose.yml ps -a > artifacts/diagnostics/compose-ps.txt 2>&1; then :; fi
  if ! docker compose -f docker-compose.yml logs --no-color --timestamps \
    > artifacts/diagnostics/container.log 2>&1; then :; fi
  if ! docker inspect circuitbreaker > artifacts/diagnostics/inspect.json 2>&1; then :; fi
  if ! cp /tmp/supervisor-status.txt artifacts/diagnostics/ 2>/dev/null; then :; fi
  if ! cp /tmp/readyz.json artifacts/diagnostics/ 2>/dev/null; then :; fi
}

on_exit() {
  local rc=$?
  collect_diagnostics
  teardown
  exit "$rc"
}
trap on_exit EXIT

# The image must be STARTED, not just built: a broken entrypoint, failed
# migration, dying supervisord program, unparseable nginx config or empty
# frontend bundle are all invisible from outside an unstarted image.
#
# Through docker-compose.yml rather than a hand-written `docker run`,
# because that file is what users get and what install.sh uses —
# read_only, the tmpfs set, cap_drop/cap_add and the healthcheck are all
# part of what has to work.

# Ephemeral, per-run, never stored: the four values compose guards with
# ${VAR:?}. token_hex for the three opaque ones; the vault needs a real
# Fernet key (urlsafe base64 of 32 bytes) or it rejects it at startup.
#
# ::add-mask:: is registered before the values are written anywhere, so a
# later step dumping the environment is redacted rather than leaked.
mint_secrets() {
  hexgen() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
  DB_PASSWORD="$(hexgen)"
  JWT_SECRET="$(hexgen)"
  NATS_TOKEN="$(hexgen)"
  VAULT_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  for secret in "${DB_PASSWORD}" "${JWT_SECRET}" "${NATS_TOKEN}" "${VAULT_KEY}"; do
    if [[ ${GITHUB_ACTIONS:-} == true ]]; then
      echo "::add-mask::${secret}"
    fi
  done

  # printf per line rather than a heredoc: the values are written
  # verbatim with no chance of picking up the block's indentation.
  umask 077
  {
    printf 'CB_DB_PASSWORD=%s\n' "${DB_PASSWORD}"
    printf 'CB_JWT_SECRET=%s\n' "${JWT_SECRET}"
    printf 'NATS_AUTH_TOKEN=%s\n' "${NATS_TOKEN}"
    printf 'CB_VAULT_KEY=%s\n' "${VAULT_KEY}"
    printf 'CB_IMAGE=%s\n' "${CB_IMAGE}"
    # Not 80/443: the runner already has services on the low ports, and
    # a bind failure here would read as a container fault.
    printf 'CB_PORT=%s\n' "${CB_SMOKE_PORT}"
    printf 'CB_PORT_HTTPS=%s\n' "${CB_SMOKE_PORT_HTTPS}"
    printf 'CB_DATA_DIR=%s\n' "${CB_SMOKE_DATA_DIR}"
  } > .env
  echo "wrote .env with $(wc -l < .env) settings (values masked)"
}

start_compose() {
  mkdir -p "${CB_SMOKE_DATA_DIR}"
  # No --build: the image under test is the one the step above tagged,
  # and CB_IMAGE points compose at it. Letting compose build would test
  # a second, differently-cached image.
  docker compose -f docker-compose.yml up -d
  docker compose -f docker-compose.yml ps
}

# The probe is character-for-character the one in the compose healthcheck
# and in Dockerfile.mono, including the grep. That is not redundancy: the
# :8080 server block 301-redirects anything it does not proxy, and
# `curl -f` treats a 301 as success, so a status-only probe passes against
# a container whose backend never started. Matching "alive" in the body is
# what makes this an assertion about the application.
wait_livez() {
  for attempt in $(seq 1 60); do
    if curl -fsS --max-time 4 "http://127.0.0.1:${CB_SMOKE_PORT}/api/v1/livez" | grep -q '"alive"'; then
      echo "live after ${attempt} attempt(s)"
      return 0
    fi
    sleep 5
  done
  echo "::error::container never reported live within 300s"
  exit 1
}

# Separate from /livez with its own budget: live-but-never-ready is a
# dependency that did not come up, never-live is the process itself, and
# the distinction is the diagnosis. Dockerfile.mono healthchecks only
# /livez so a slow dependency cannot cause a restart loop — right for the
# runtime, wrong for a gate, so readiness is asserted here.
wait_readyz() {
  for attempt in $(seq 1 36); do
    code=""
    if fetched="$(curl -s -o /tmp/readyz.json -w '%{http_code}' --max-time 5 "http://127.0.0.1:${CB_SMOKE_PORT}/api/v1/readyz")"; then
      code="$fetched"
    fi
    if [ "${code}" = "200" ]; then
      echo "ready after ${attempt} attempt(s)"
      cat /tmp/readyz.json
      return 0
    fi
    sleep 5
  done
  echo "::error::container never became ready within 180s; last /readyz body:"
  cat /tmp/readyz.json 2>/dev/null || echo "(no response body)"
  exit 1
}

# The mono image does not serve the SPA over HTTP at all: nginx.mono.conf's
# :8080 block proxies only the health endpoints and the ACME challenge,
# and its `location /` is `return 301 https://$host$uri`. The SPA lives in
# the :8443 block. So probe HTTP for the redirect and HTTPS for the app.
#
# The redirect is asserted, never followed — pushing non-health traffic to
# TLS is a security control, and a silent -L would let its removal pass.
assert_http_redirect() {
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${CB_SMOKE_PORT}/")"
  [ "${code}" = "301" ] \
    || { echo "::error::GET / over HTTP returned ${code}, expected a 301 to HTTPS"; exit 1; }
  echo "HTTP -> HTTPS redirect in place"
}

# -k because entrypoint-mono.sh generates a self-signed certificate on
# first boot when /data/tls is empty, which is exactly the state a fresh
# container is in. The assertion is about nginx and the frontend bundle,
# not about the trust chain.
#
# A 200 alone is not enough: an image whose Alpine builder stage produced
# no bundle would still answer, so the SPA shell is what is checked.
assert_tls_spa() {
  code="$(curl -sk -o /tmp/index.html -w '%{http_code}' --max-time 10 "https://127.0.0.1:${CB_SMOKE_PORT_HTTPS}/")"
  [ "${code}" = "200" ] || { echo "::error::GET / over HTTPS returned HTTP ${code}, expected 200"; exit 1; }
  grep -qi '<div id="root"' /tmp/index.html \
    || { echo "::error::GET / returned 200 but not the SPA shell"; head -c 400 /tmp/index.html; exit 1; }
  echo "frontend served over TLS"
}

# supervisord is the only thing that knows whether the other twelve
# processes are alive. Every program in supervisord.mono.conf is
# long-running with autorestart=true, so FATAL, BACKOFF or EXITED all mean
# something died — and with the API answering on :8080, a dead telemetry
# or monitor worker is invisible to every probe above it.
assert_supervisord_running() {
  # The same -c the entrypoint execs supervisord with. Guarded with
  # `if ! …; then :; fi` rather than `|| true`: `supervisorctl status` exits
  # non-zero when any program is not RUNNING, which is the case this step
  # exists to report rather than to abort on — the assertions below read the
  # output instead.
  if ! docker compose -f docker-compose.yml exec -T circuitbreaker \
    supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status \
    | tee /tmp/supervisor-status.txt; then
    :
  fi

  # Assert state, never a process count: `numprocs` means the number of
  # processes does not match the number of [program:] sections, and any
  # hardcoded total breaks the next time either changes.
  #
  # Reading the state column is stricter than grepping for FATAL — an
  # unanticipated STOPPED, or a STARTING that never settles, fails here
  # too. Retried, because /readyz answering does not mean every worker
  # has finished starting.
  all_running=""
  for attempt in $(seq 1 6); do
    if ! docker compose -f docker-compose.yml exec -T circuitbreaker \
      supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status \
      > /tmp/supervisor-status.txt 2>&1; then
      :
    fi
    not_running="$(awk 'NF && $2 != "RUNNING" {print}' /tmp/supervisor-status.txt)"
    if [ -z "${not_running}" ]; then
      all_running="yes"
      break
    fi
    echo "attempt ${attempt}: not yet all RUNNING"
    sleep 5
  done
  cat /tmp/supervisor-status.txt

  if [ -z "${all_running}" ]; then
    echo "::error::a supervisord program is not RUNNING"
    awk 'NF && $2 != "RUNNING" {print}' /tmp/supervisor-status.txt
    exit 1
  fi

  # Non-vacuous guard. An exec that failed outright leaves an empty file —
  # and every assertion over an empty file passes, including the one
  # immediately above. These five are the processes without which the
  # container is not the product, so requiring them by name proves the
  # status was actually read.
  for proc in postgres nats redis backend-api nginx; do
    grep -Eq "^${proc}[[:space:]]" /tmp/supervisor-status.txt \
      || { echo "::error::supervisorctl did not report ${proc}"; exit 1; }
  done
  echo "all supervisord programs running"
}

# A container that crashed and was restarted back into health passes every
# probe above. RestartCount is what separates "came up" from "kept coming
# up": restart is `unless-stopped`, so anything above zero is a boot the
# image did not survive.
assert_no_restarts() {
  restarts="$(docker inspect -f '{{.RestartCount}}' circuitbreaker)"
  echo "RestartCount=${restarts}"
  [ "${restarts}" = "0" ] || { echo "::error::container restarted ${restarts} time(s) during the smoke run"; exit 1; }
}

# `stop`, not `down`, and its own step: a container that ignores SIGTERM is
# stopped by SIGKILL ten seconds later, which users experience as a
# `docker compose down` that hangs and, with an embedded Postgres, as an
# unclean shutdown. Timing the stop is how that becomes visible here.
assert_clean_stop() {
  start="${SECONDS}"
  docker compose -f docker-compose.yml stop -t 30
  elapsed="$(( SECONDS - start ))"
  echo "stopped in ${elapsed}s"
  [ "${elapsed}" -lt 30 ] || { echo "::error::container did not exit on SIGTERM; it was killed after ${elapsed}s"; exit 1; }
}

mint_secrets
start_compose
wait_livez
wait_readyz
assert_http_redirect
assert_tls_spa
assert_supervisord_running
assert_no_restarts
assert_clean_stop

echo "mono smoke passed for ${CB_IMAGE}"
