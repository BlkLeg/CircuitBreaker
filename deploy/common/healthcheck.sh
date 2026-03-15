#!/usr/bin/env bash
# deploy/common/healthcheck.sh — Health probe for Docker HEALTHCHECK and `cb status`.
set -euo pipefail

PORT="${CB_HEALTHCHECK_PORT:-8080}"

curl -sf "http://localhost:${PORT}/api/v1/health" | grep -q '"status":"healthy"'
