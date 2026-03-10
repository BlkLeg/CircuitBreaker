#!/usr/bin/env bash
# E2E test for the mono (single-container) deployment.
# Starts the mono container, waits for health, verifies API and frontend, then tears down.
#
# Usage (from repo root):
#   ./scripts/test-mono-e2e.sh
#   CB_MONO_IMAGE=ghcr.io/blkleg/circuitbreaker:mono-v0.2.0 ./scripts/test-mono-e2e.sh
#
# Optional: BUILD_MONO=1 to build the mono image first (make docker-mono TAG=test-e2e).

set -euo pipefail

CONTAINER_NAME="${CB_MONO_E2E_CONTAINER:-cb-mono-e2e}"
HTTP_PORT="${CB_MONO_E2E_PORT:-18999}"
DATA_DIR="${CB_MONO_E2E_DATA:-}"
IMAGE="${CB_MONO_IMAGE:-ghcr.io/blkleg/circuitbreaker:mono-latest}"
MAX_WAIT="${CB_MONO_E2E_MAX_WAIT:-120}"

if [[ -z "$DATA_DIR" ]]; then
  DATA_DIR=$(mktemp -d)
  CLEANUP_DATA=1
else
  CLEANUP_DATA=0
fi

cleanup() {
  docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
  if [[ "$CLEANUP_DATA" -eq 1 ]] && [[ -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
  fi
}
trap cleanup EXIT

echo "[E2E] Using image: $IMAGE"
echo "[E2E] Port: $HTTP_PORT  Data: $DATA_DIR  Container: $CONTAINER_NAME"

if [[ "${BUILD_MONO:-0}" == "1" ]]; then
  REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
  echo "[E2E] Building mono image (tag test-e2e)..."
  make -C "$REPO_ROOT" docker-mono TAG=test-e2e 2>/dev/null || true
  IMAGE="ghcr.io/blkleg/circuitbreaker:mono-test-e2e"
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "[E2E] Build failed or image not found; trying default image."
    IMAGE="${CB_MONO_IMAGE:-ghcr.io/blkleg/circuitbreaker:mono-latest}"
  fi
fi

echo "[E2E] Starting container..."
docker run -d --name "$CONTAINER_NAME" \
  -p "${HTTP_PORT}:80" \
  -v "${DATA_DIR}:/data" \
  -e "CB_DB_PASSWORD=e2etestpass" \
  -e "CB_VAULT_KEY=e2etestvaultkey32byteslong!!!!!!!!" \
  "$IMAGE"

echo "[E2E] Waiting for /api/v1/health (max ${MAX_WAIT}s)..."
start=$SECONDS
while true; do
  if curl -sf "http://127.0.0.1:${HTTP_PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "[E2E] Health OK after $((SECONDS - start))s"
    break
  fi
  if [[ $((SECONDS - start)) -ge "$MAX_WAIT" ]]; then
    echo "[E2E] Timeout waiting for health. Logs:"
    docker logs "$CONTAINER_NAME" 2>&1 | tail -80
    exit 1
  fi
  sleep 3
done

echo "[E2E] Checking health response..."
health=$(curl -sf "http://127.0.0.1:${HTTP_PORT}/api/v1/health")
if ! echo "$health" | grep -q '"status"' || ! echo "$health" | grep -q 'ok'; then
  echo "[E2E] Health response unexpected: $health"
  exit 1
fi

echo "[E2E] Checking frontend (/)..."
status=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${HTTP_PORT}/")
if [[ "$status" != "200" ]]; then
  echo "[E2E] Frontend returned HTTP $status (expected 200)"
  exit 1
fi

echo "[E2E] All checks passed."
exit 0
