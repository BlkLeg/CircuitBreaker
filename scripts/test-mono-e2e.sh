#!/usr/bin/env bash
# E2E test for the mono (single-container) deployment.
# Starts the mono container, waits for health, verifies API and frontend, then tears down.
#
# Usage (from repo root):
#   ./scripts/test-mono-e2e.sh
#   CB_MONO_IMAGE=ghcr.io/blkleg/circuitbreaker:0.4.2 ./scripts/test-mono-e2e.sh
#
# Optional: BUILD_MONO=1 to build the image first (make docker-build).
#
# This is the local/manual counterpart to the `Build Docker (smoke test)` job in
# .github/workflows/dev-ci.yml. That job drives the image through
# docker-compose.yml, because it is gating what users are handed; this script
# drives an arbitrary image tag with `docker run`, because its job is to answer
# "does THIS image boot" for a tag you already have. Keep the assertions in step
# — a probe that passes here and fails there, or the reverse, means one of the
# two is lying about the same image.

set -euo pipefail

CONTAINER_NAME="${CB_MONO_E2E_CONTAINER:-cb-mono-e2e}"
HTTP_PORT="${CB_MONO_E2E_PORT:-18999}"
# The SPA is served only from the :8443 block in nginx.mono.conf, so a run that
# publishes 8080 alone can never reach the frontend. The old script published
# exactly that and then asserted 200 on http://…/ — an assertion the mono image
# has never been able to satisfy.
HTTPS_PORT="${CB_MONO_E2E_HTTPS_PORT:-18998}"
DATA_DIR="${CB_MONO_E2E_DATA:-}"
# Default matches `make docker-build`, which tags $(DOCKER_REGISTRY):$(cat VERSION).
# It was `…:mono-latest`, a tag that has never been built or published — the
# script's default therefore named an image that could only ever fail to pull.
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEFAULT_IMAGE="ghcr.io/blkleg/circuitbreaker:$(cat "${REPO_ROOT}/VERSION")"
IMAGE="${CB_MONO_IMAGE:-$DEFAULT_IMAGE}"
MAX_WAIT="${CB_MONO_E2E_MAX_WAIT:-180}"

if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR=$(mktemp -d)
  CLEANUP_DATA=1
else
  CLEANUP_DATA=0
fi

# The four required secrets are written here rather than passed as -e flags, so
# they never appear in this script's own `ps` output on a shared machine.
ENV_FILE=$(mktemp)

cleanup() {
  docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
  shred -u "$ENV_FILE" 2>/dev/null || rm -f "$ENV_FILE"
  if [[ "$CLEANUP_DATA" -eq 1 ]] && [[ -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
  fi
}
trap cleanup EXIT

# Ephemeral and per-run. These were literals — `CB_DB_PASSWORD=e2etestpass` and
# a 34-character CB_VAULT_KEY — which is a hardcoded credential in a tracked
# file regardless of it being "only a test value", and gitleaks is entitled to
# say so. The vault key was also not a Fernet key: Fernet wants urlsafe base64
# of 32 bytes, so the old literal could not have decrypted anything and the
# container would refuse to start on it today.
#
# CB_JWT_SECRET and NATS_AUTH_TOKEN are new here. Neither was set, and both are
# ${VAR:?} guards now, so this script could not start the current image at all.
hexgen() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
umask 077
{
  printf 'CB_DB_PASSWORD=%s\n' "$(hexgen)"
  printf 'CB_JWT_SECRET=%s\n' "$(hexgen)"
  printf 'NATS_AUTH_TOKEN=%s\n' "$(hexgen)"
  printf 'CB_VAULT_KEY=%s\n' \
    "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
} > "$ENV_FILE"

echo "[E2E] Using image: $IMAGE"
echo "[E2E] Ports: ${HTTP_PORT} (http) ${HTTPS_PORT} (https)  Data: $DATA_DIR  Container: $CONTAINER_NAME"

if [[ "${BUILD_MONO:-0}" == "1" ]]; then
  # `make docker-build`, not `make docker-mono`: the latter is not a target and
  # never has been, so this branch used to fail silently into the fallback
  # below — printing "Build failed or image not found" for a build that was
  # never attempted.
  echo "[E2E] Building mono image (make docker-build)..."
  make -C "$REPO_ROOT" docker-build
  IMAGE="$DEFAULT_IMAGE"
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "[E2E] Image not present locally: $IMAGE"
  echo "[E2E] Build it with BUILD_MONO=1 $0, or set CB_MONO_IMAGE to one you have."
  exit 1
fi

echo "[E2E] Starting container..."
docker run -d --name "$CONTAINER_NAME" \
  -p "${HTTP_PORT}:8080" \
  -p "${HTTPS_PORT}:8443" \
  -v "${DATA_DIR}:/data" \
  --env-file "$ENV_FILE" \
  "$IMAGE"

dump_logs_and_fail() {
  echo "[E2E] $1"
  echo "[E2E] Last 80 log lines:"
  docker logs "$CONTAINER_NAME" 2>&1 | tail -80
  exit 1
}

# /api/v1/livez, not /api/v1/health: /health is the legacy probe that
# api/health.py's own docstring says new consumers should not use, and it
# reports dependency state, so it goes red for a slow Redis on a container that
# started perfectly.
#
# The body is matched, not just the status. The :8080 server block 301-redirects
# anything it does not proxy and `curl -f` counts a 301 as success, so
# `curl -sf .../livez` alone passes against a container whose backend never came
# up. This is the same probe as the HEALTHCHECK in Dockerfile.mono and the
# healthcheck in docker-compose.yml, deliberately.
echo "[E2E] Waiting for /api/v1/livez (max ${MAX_WAIT}s)..."
start=$SECONDS
while true; do
  if curl -fsS --max-time 4 "http://127.0.0.1:${HTTP_PORT}/api/v1/livez" 2>/dev/null \
      | grep -q '"alive"'; then
    echo "[E2E] Live after $((SECONDS - start))s"
    break
  fi
  if [[ $((SECONDS - start)) -ge "$MAX_WAIT" ]]; then
    dump_logs_and_fail "Timeout waiting for /livez."
  fi
  sleep 3
done

# Readiness is asked separately and after, because it fails for different
# reasons: never-live is the application process, live-but-never-ready is a
# dependency — embedded Postgres, NATS, Redis, or a migration that did not
# finish. Collapsing the two into one probe throws away the diagnosis.
echo "[E2E] Waiting for /api/v1/readyz..."
start=$SECONDS
while true; do
  code=$(curl -s -o /tmp/cb-mono-readyz.json -w '%{http_code}' --max-time 5 \
    "http://127.0.0.1:${HTTP_PORT}/api/v1/readyz" || true)
  if [[ "$code" == "200" ]]; then
    echo "[E2E] Ready after $((SECONDS - start))s"
    cat /tmp/cb-mono-readyz.json
    echo
    break
  fi
  if [[ $((SECONDS - start)) -ge "$MAX_WAIT" ]]; then
    echo "[E2E] Last /readyz body:"
    cat /tmp/cb-mono-readyz.json 2>/dev/null || echo "(no response body)"
    dump_logs_and_fail "Timeout waiting for /readyz."
  fi
  sleep 3
done

# Asserted, not followed. The :8080 block proxies only the health endpoints and
# the ACME challenge; everything else is `return 301 https://$host$request_uri`,
# which is a security control. Using curl -L here would keep this test passing
# if that redirect were ever removed.
echo "[E2E] Checking the HTTP -> HTTPS redirect..."
status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
  "http://127.0.0.1:${HTTP_PORT}/")
if [[ "$status" != "301" ]]; then
  dump_logs_and_fail "GET / over HTTP returned $status (expected a 301 to HTTPS)"
fi

# -k: entrypoint-mono.sh writes a self-signed certificate on first boot when
# /data/tls is empty, which is the state every fresh run is in. This asserts
# nginx and the bundle, not the trust chain.
echo "[E2E] Checking frontend (https /)..."
status=$(curl -sk -o /tmp/cb-mono-index.html -w "%{http_code}" --max-time 10 \
  "https://127.0.0.1:${HTTPS_PORT}/")
if [[ "$status" != "200" ]]; then
  dump_logs_and_fail "Frontend returned HTTP $status over TLS (expected 200)"
fi
# A 200 that is not the SPA shell means the Alpine builder stage produced no
# bundle and nginx is serving something else — a case the status code alone
# cannot see.
if ! grep -qi '<div id="root"' /tmp/cb-mono-index.html; then
  echo "[E2E] First 400 bytes of the response:"
  head -c 400 /tmp/cb-mono-index.html
  echo
  dump_logs_and_fail "GET / returned 200 but not the SPA shell"
fi

# supervisord is the only thing that knows about the other twelve processes.
# Every program in docker/supervisord.mono.conf is long-running with
# autorestart=true, so FATAL, BACKOFF or EXITED all mean something died — and a
# dead telemetry or monitor worker is invisible to every probe above, because
# the API keeps answering.
echo "[E2E] Checking supervisord programs..."
# `|| true`: supervisorctl exits non-zero when any program is not RUNNING, which
# is the condition being reported rather than a reason to abort here.
docker exec "$CONTAINER_NAME" \
  supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status \
  > /tmp/cb-mono-supervisor.txt 2>&1 || true
cat /tmp/cb-mono-supervisor.txt
# Not a count: supervisord.mono.conf has 13 [program:] sections, but
# worker-monitor-poll sets numprocs=2 with a process_name template, so
# supervisorctl reports 14 processes. Any hardcoded total is wrong again as soon
# as a program or a numprocs changes. Reading the state column also catches
# STOPPED and a stuck STARTING, which a FATAL grep does not.
not_running=$(awk 'NF && $2 != "RUNNING" {print}' /tmp/cb-mono-supervisor.txt)
if [[ -n "$not_running" ]]; then
  echo "[E2E] Not RUNNING:"
  echo "$not_running"
  dump_logs_and_fail "A supervisord program is not RUNNING"
fi
# Non-vacuous guard: the `|| true` above means a failed exec leaves an empty
# file, which satisfies every assertion made over it.
for proc in postgres nats redis backend-api nginx; do
  grep -Eq "^${proc}[[:space:]]" /tmp/cb-mono-supervisor.txt \
    || dump_logs_and_fail "supervisorctl did not report ${proc}"
done

# A container that crashed and was restarted back into health passes everything
# above. This is what separates "came up" from "kept coming up".
restarts=$(docker inspect -f '{{.RestartCount}}' "$CONTAINER_NAME")
if [[ "$restarts" != "0" ]]; then
  dump_logs_and_fail "Container restarted ${restarts} time(s) during the run"
fi

# A container that ignores SIGTERM is SIGKILLed after the timeout, which users
# meet as a `docker stop` that hangs and, with an embedded Postgres, as an
# unclean shutdown. Timing the stop is what makes that visible.
echo "[E2E] Checking SIGTERM shutdown..."
start=$SECONDS
docker stop -t 30 "$CONTAINER_NAME" >/dev/null
elapsed=$((SECONDS - start))
if [[ "$elapsed" -ge 30 ]]; then
  dump_logs_and_fail "Container did not exit on SIGTERM; killed after ${elapsed}s"
fi
echo "[E2E] Stopped in ${elapsed}s"

rm -f /tmp/cb-mono-readyz.json /tmp/cb-mono-index.html /tmp/cb-mono-supervisor.txt
echo "[E2E] All checks passed."
exit 0
