# Makefile for CircuitBreaker (Native Dev Focus)

# ==============================================================================
# VARIABLES
# ==============================================================================
BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 5173
BACKEND_DIR   ?= apps/backend
FRONTEND_DIR  ?= apps/frontend

CB_DATA_DIR   ?= ./circuitbreaker-data

# Local services for development
POSTGRES_DEV_NAME   ?= cb-postgres-dev
POSTGRES_DEV_PORT   ?= 5432
POSTGRES_DEV_USER   ?= breaker
POSTGRES_DEV_DB     ?= circuitbreaker
POSTGRES_DEV_PASS   ?= breaker
CB_DB_URL_DEV       ?= postgresql://$(POSTGRES_DEV_USER):$(POSTGRES_DEV_PASS)@localhost:$(POSTGRES_DEV_PORT)/$(POSTGRES_DEV_DB)

REDIS_DEV_NAME      ?= cb-redis-dev
REDIS_DEV_PORT      ?= 6379
CB_REDIS_URL_DEV    ?= redis://localhost:$(REDIS_DEV_PORT)/0

NATS_DEV_NAME       ?= cb-nats-dev
NATS_DEV_PORT       ?= 4222
NATS_AUTH_TOKEN_DEV ?= dev-token-local-only
CB_NATS_URL_DEV     ?= nats://localhost:$(NATS_DEV_PORT)

# ==============================================================================
# CORE TARGETS
# ==============================================================================
.PHONY: help install dev backend backend-watch frontend migrate stop

help: ## Show available targets
	awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Bootstrap dev environment (run once)
	python3.12 -m venv .venv
	$(CURDIR)/.venv/bin/pip install --upgrade pip
	$(CURDIR)/.venv/bin/pip install -e "apps/backend/[dev]"

dev: deps-up stop ## Native backend + frontend + deps
	trap 'kill 0' EXIT; $(MAKE) --no-print-directory backend & $(MAKE) --no-print-directory frontend

stop: ## Kill any process holding the dev ports
	lsof -ti tcp:$(BACKEND_PORT) | xargs kill -9 || true
	lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 || true
	echo "Ports $(BACKEND_PORT) and $(FRONTEND_PORT) cleared."

backend:  ## Native backend (ZERO DOCKER DRIFT)
	@echo "Running migrations..."
	cd $(BACKEND_DIR) && \
		CB_DB_URL="postgresql://breaker:breaker@localhost:5432/circuitbreaker" \
		PYTHONPATH=src $(CURDIR)/.venv/bin/alembic upgrade head
	@echo "Starting backend → http://localhost:8000"
	cd $(BACKEND_DIR) && \
		CB_DATA_DIR="$(CURDIR)/$(BACKEND_DIR)/.dev-data" \
		CB_DB_URL="postgresql://breaker:breaker@localhost:5432/circuitbreaker" \
		CB_REDIS_URL="redis://localhost:6379/0" \
		NATS_URL="nats://localhost:4222" \
		NATS_AUTH_TOKEN="dev-token-local-only" \
		CB_AUTO_MIGRATE=false \
		PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 $(CB_UVICORN_ARGS)

backend-watch:  ## Native backend WITH reload (post-fix only)
	$(MAKE) backend --no-print-directory CB_UVICORN_ARGS="--reload"

frontend:  ## Native frontend
	@echo "Starting frontend → http://localhost:5173"
	cd $(FRONTEND_DIR) && npm start

migrate: ## Run Alembic DB migrations
	cd $(BACKEND_DIR) && CB_DB_URL="$(CB_DB_URL_DEV)" PYTHONPATH=src $(CURDIR)/.venv/bin/alembic upgrade head

# ==============================================================================
# DEPENDENCIES (Local Services)
# ==============================================================================
.PHONY: deps-up deps-down deps-native-up deps-native-down

deps-up:  ## Start deps only (Postgres/Redis/NATS) via Docker
	docker compose -f docker-compose.deps.yml up -d

deps-down:  ## Stop Docker deps
	docker compose -f docker-compose.deps.yml down -v

deps-native-up:  ## Start native systemd deps (prod-parity: same units as install.sh)
	sudo systemctl start circuitbreaker-postgres circuitbreaker-pgbouncer circuitbreaker-redis circuitbreaker-nats

deps-native-down:  ## Stop native systemd deps
	sudo systemctl stop circuitbreaker-nats circuitbreaker-redis circuitbreaker-pgbouncer circuitbreaker-postgres

# ==============================================================================
# CODE QUALITY & TESTING
# ==============================================================================
.PHONY: lint format test build

lint: ## Run backend and frontend linters
	cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff check src/app
	cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/mypy src/app
	cd $(FRONTEND_DIR) && npm run lint

format: ## Format backend and frontend code
	cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff format src/
	cd $(FRONTEND_DIR) && npm run format

test: ## Run tests natively
	cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration -q
	cd $(FRONTEND_DIR) && npm test

build: ## Build native app
	cd $(FRONTEND_DIR) && npm ci && npm run build
	.venv/bin/python scripts/build_native_release.py --clean
