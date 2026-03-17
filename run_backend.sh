#!/bin/bash
# Helper script to safely restart the backend after code changes
# This avoids watchfiles reload issues by running without --reload
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/apps/backend"
# Kill any existing process on port 8000
lsof -ti tcp:8000 | xargs kill -9 2>/dev/null || true
sleep 1
echo "Running DB migrations..."
CB_DB_URL="${CB_DB_URL:-postgresql://breaker:breaker@localhost/circuitbreaker}" \
PYTHONPATH=src \
  ../../.venv/bin/alembic upgrade head
echo "Starting backend (without auto-reload to avoid watchfiles issues)..."
CB_DATA_DIR="${CB_DATA_DIR:-$(pwd)/.dev-data}" \
CB_DB_URL="${CB_DB_URL:-postgresql://breaker:breaker@localhost/circuitbreaker}" \
CB_REDIS_URL="${CB_REDIS_URL:-redis://localhost:6379/0}" \
NATS_URL="${NATS_URL:-nats://localhost:4222}" \
NATS_AUTH_TOKEN="${NATS_AUTH_TOKEN:-}" \
CB_AUTO_MIGRATE=false \
PYTHONPATH=src \
  ../../.venv/bin/uvicorn app.main:app --port 8000 --host 127.0.0.1
