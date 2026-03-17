# Makefile

# ==============================================================================
# VARIABLES
# ==============================================================================
BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 5173
BACKEND_DIR   ?= apps/backend
FRONTEND_DIR  ?= apps/frontend
# VERSION: raw semver read from the canonical repo-root VERSION file.
# Edit /VERSION to cut a release — everything else derives from it.
VERSION       ?= $(shell cat VERSION 2>/dev/null | tr -d '[:space:]' || git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0-dev")
# RELEASE_TAG: appends -beta for any 0.x.y version; bare version once v1+ is reached.
#   0.1.4  → 0.1.4-beta
#   1.0.0  → 1.0.0
MAJOR         := $(shell echo "$(VERSION)" | cut -d. -f1)
RELEASE_TAG   := $(shell [ "$(MAJOR)" -lt 1 ] 2>/dev/null && echo "$(VERSION)-beta" || echo "$(VERSION)")
OS_ARCH       := $(shell uname -s | tr '[:upper:]' '[:lower:]')-$(shell uname -m)
DOCKER_REPO   ?= $(shell git config --get remote.origin.url | sed 's/.*://;s/\.git$$//' | sed 's/^/ghcr.io\//' | tr '[:upper:]' '[:lower:]')
SNYK_BIN      ?= $(CURDIR)/.tools/snyk
SNYK_PATH     ?= $(CURDIR)
# Single source of truth for deployment (used by install.sh, make up, CI).
COMPOSE_FILE  ?= docker-compose.yml
# Default data dir for compose-clean when .env is not present
CB_DATA_DIR   ?= ./circuitbreaker-data
# Local services for development (make services-up, make migrate, make services-down)
POSTGRES_DEV_NAME   ?= cb-postgres-dev
POSTGRES_DEV_PORT   ?= 5432
POSTGRES_DEV_USER   ?= breaker
POSTGRES_DEV_DB     ?= circuitbreaker
POSTGRES_DEV_PASS   ?= breaker
POSTGRES_DEV_IMAGE  ?= postgres:16-alpine
CB_DB_URL_DEV       ?= postgresql://$(POSTGRES_DEV_USER):$(POSTGRES_DEV_PASS)@localhost:$(POSTGRES_DEV_PORT)/$(POSTGRES_DEV_DB)
# Redis for local dev
REDIS_DEV_NAME      ?= cb-redis-dev
REDIS_DEV_PORT      ?= 6379
REDIS_DEV_IMAGE     ?= redis:7-alpine
CB_REDIS_URL_DEV    ?= redis://localhost:$(REDIS_DEV_PORT)/0
# NATS for local dev
NATS_DEV_NAME       ?= cb-nats-dev
NATS_DEV_PORT       ?= 4222
NATS_DEV_IMAGE      ?= nats:2.10-alpine
NATS_AUTH_TOKEN_DEV ?= dev-token-local-only
CB_NATS_URL_DEV     ?= nats://localhost:$(NATS_DEV_PORT)
# Caddy for local dev
CADDY_PID_FILE      ?= $(CURDIR)/.caddy.pid

# ==============================================================================
# CORE TARGETS
# ==============================================================================
.PHONY: help dev stop backend frontend

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

dev: stop ## Start backend + frontend for local development (run 'make services-up' first)
	@echo "Starting backend  → http://localhost:$(BACKEND_PORT)"
	@cd $(BACKEND_DIR) && \
		CB_DATA_DIR="$${CB_DATA_DIR:-$(CURDIR)/apps/backend/.dev-data}" \
		CB_DB_URL="$${CB_DB_URL:-$(CB_DB_URL_DEV)}" \
		CB_REDIS_URL="$${CB_REDIS_URL:-$(CB_REDIS_URL_DEV)}" \
		NATS_URL="$${NATS_URL:-$(CB_NATS_URL_DEV)}" \
		NATS_AUTH_TOKEN="$${NATS_AUTH_TOKEN:-$(NATS_AUTH_TOKEN_DEV)}" \
		PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT) &
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	@cd $(FRONTEND_DIR) && npm start &

stop: ## Kill any process holding the dev ports
	@lsof -ti tcp:$(BACKEND_PORT)  | xargs kill -9 2>/dev/null || true
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Ports $(BACKEND_PORT) and $(FRONTEND_PORT) cleared."

backend: ## Kill port $(BACKEND_PORT) and restart the backend
	@lsof -ti tcp:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting backend → http://localhost:$(BACKEND_PORT)"
	cd $(BACKEND_DIR) && \
		CB_DATA_DIR="$${CB_DATA_DIR:-$(CURDIR)/apps/backend/.dev-data}" \
		CB_DB_URL="$${CB_DB_URL:-$(CB_DB_URL_DEV)}" \
		CB_REDIS_URL="$${CB_REDIS_URL:-$(CB_REDIS_URL_DEV)}" \
		NATS_URL="$${NATS_URL:-$(CB_NATS_URL_DEV)}" \
		NATS_AUTH_TOKEN="$${NATS_AUTH_TOKEN:-$(NATS_AUTH_TOKEN_DEV)}" \
		PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

frontend: ## Kill port $(FRONTEND_PORT) and restart the frontend
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	cd $(FRONTEND_DIR) && npm start

# ==============================================================================
# BUILD & TEST
# ==============================================================================
.PHONY: lint format ci test test-backend test-frontend test-all test-coverage docs docs-build frontend-build snyk-version snyk-auth snyk-test snyk-monitor security-scan

lint: ## Run backend and frontend linters
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff check src/app --select F
	@cd $(FRONTEND_DIR) && npm run lint

format: ## Format backend and frontend code
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff format src/
	@cd $(FRONTEND_DIR) && npm run format

typecheck: ## Run backend (mypy) and frontend (tsc --noEmit) type checks
	@echo "--- Backend type check (mypy, advisory) ---"
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/mypy src/app --ignore-missing-imports || true
	@echo "--- Frontend type check (tsc --noEmit) ---"
	@cd $(FRONTEND_DIR) && npx tsc --noEmit

hooks: ## Install git pre-commit hooks (Husky + lint-staged)
	@cd $(FRONTEND_DIR) && npx husky install ../../.husky && echo "✅ Git hooks installed."

ci: lint test typecheck ## Run linting, tests, and type checks

test: ## Run backend tests (skipped if psycopg2 missing; need Postgres for integration tests)
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && if $(CURDIR)/.venv/bin/python -c "import psycopg2" 2>/dev/null; then \
		PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration -q; \
	else echo "Skipping backend tests (install psycopg2 and run Postgres, or set CB_TEST_DB_URL)."; fi
	@cd $(FRONTEND_DIR) && npm run test

test-backend: ## Run backend tests with verbose output
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration -v --asyncio-mode=auto --cov=src/app

test-frontend: ## Run frontend component tests
	@echo "Running frontend tests..."
	@cd $(FRONTEND_DIR) && npm test

test-all: test-backend test-frontend ## Run all backend + frontend tests

test-coverage: ## Run all tests with coverage reports
	@cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration --cov=src/app --cov-report=term-missing --asyncio-mode=auto
	@cd $(FRONTEND_DIR) && npm run test:coverage

docs: ## Serve docs locally with Zensical
	@echo "Serving docs at http://localhost:8001"
	@.venv/bin/zensical serve

docs-build: ## Build docs with Zensical
	@echo "Building docs site..."
	@.venv/bin/zensical build

frontend-build: ## Build frontend production bundle
	@echo "Building frontend..."
	@cd $(FRONTEND_DIR) && npm ci && npm run build

bundle-analyze: ## Build frontend with bundle visualizer (opens stats.html)
	@echo "Building frontend with bundle analysis..."
	@cd $(FRONTEND_DIR) && npm ci && npm run bundle-analyze

snyk-version: ## Show project-local Snyk CLI version
	@$(SNYK_BIN) --version

snyk-auth: ## Authenticate Snyk using the local CLI binary
	@$(SNYK_BIN) auth

snyk-test: ## Run Snyk open-source scan for this repository
	@$(SNYK_BIN) test --all-projects --path=$(SNYK_PATH)

snyk-monitor: ## Monitor this repository in Snyk for ongoing vulnerability alerts
	@$(SNYK_BIN) monitor --all-projects --path=$(SNYK_PATH)

security-scan: ## Run full security scan (Bandit, Semgrep, Gitleaks, ESLint, Hadolint, Checkov, Trivy fs+config, npm audit). Saves CI minutes by catching issues locally.
	@echo "Starting full security scan..."
	@bash scripts/security_scan.sh

# ==============================================================================
# LOCAL SERVICES (dev) - PostgreSQL, Redis, NATS
# ==============================================================================
.PHONY: services-up services-down services-status postgres-up postgres-down redis-up redis-down nats-up nats-down caddy-up caddy-down caddy-status caddy-reload dev-full migrate

services-up: postgres-up redis-up nats-up ## Start all local dev services (Postgres, Redis, NATS)
	@echo ""
	@echo "✅ All services running:"
	@echo "   PostgreSQL: localhost:$(POSTGRES_DEV_PORT)"
	@echo "   Redis:      localhost:$(REDIS_DEV_PORT)"
	@echo "   NATS:       localhost:$(NATS_DEV_PORT)"
	@echo ""
	@echo "Run 'make migrate' to initialize the database, then 'make dev' to start the app."

services-down: postgres-down redis-down nats-down ## Stop and remove all local dev services

services-status: ## Check status of local dev services
	@echo "=== Local Development Services ==="
	@docker ps --filter "name=cb-.*-dev" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" || echo "No services running"

postgres-up: ## Start local Postgres container (port $(POSTGRES_DEV_PORT))
	@if docker inspect $(POSTGRES_DEV_NAME) >/dev/null 2>&1; then \
		docker start $(POSTGRES_DEV_NAME) 2>/dev/null && echo "✅ Postgres started (already exists)" || { echo "❌ Failed to start existing Postgres container"; exit 1; }; \
	else \
		if lsof -Pi :$(POSTGRES_DEV_PORT) -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "❌ Port $(POSTGRES_DEV_PORT) already in use. Stop the existing Postgres service first."; \
			echo "   Check with: lsof -i :$(POSTGRES_DEV_PORT)"; \
			exit 1; \
		fi; \
		echo "Starting Postgres at localhost:$(POSTGRES_DEV_PORT)..."; \
		if docker run -d --name $(POSTGRES_DEV_NAME) -p $(POSTGRES_DEV_PORT):5432 \
			-e POSTGRES_USER=$(POSTGRES_DEV_USER) \
			-e POSTGRES_PASSWORD=$(POSTGRES_DEV_PASS) \
			-e POSTGRES_DB=$(POSTGRES_DEV_DB) \
			$(POSTGRES_DEV_IMAGE) >/dev/null 2>&1; then \
			echo "✅ Postgres running"; \
		else \
			echo "❌ Failed to start Postgres container"; \
			exit 1; \
		fi; \
	fi

postgres-down: ## Stop and remove local Postgres container
	@docker stop $(POSTGRES_DEV_NAME) 2>/dev/null && docker rm $(POSTGRES_DEV_NAME) 2>/dev/null && echo "✅ Postgres stopped" || echo "Postgres not running"

redis-up: ## Start local Redis container (port $(REDIS_DEV_PORT))
	@if docker inspect $(REDIS_DEV_NAME) >/dev/null 2>&1; then \
		docker start $(REDIS_DEV_NAME) 2>/dev/null && echo "✅ Redis started (already exists)" || { echo "❌ Failed to start existing Redis container"; exit 1; }; \
	else \
		if lsof -Pi :$(REDIS_DEV_PORT) -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "❌ Port $(REDIS_DEV_PORT) already in use. Stop the existing Redis service first."; \
			echo "   Check with: lsof -i :$(REDIS_DEV_PORT)"; \
			exit 1; \
		fi; \
		echo "Starting Redis at localhost:$(REDIS_DEV_PORT)..."; \
		if docker run -d --name $(REDIS_DEV_NAME) -p $(REDIS_DEV_PORT):6379 $(REDIS_DEV_IMAGE) >/dev/null 2>&1; then \
			echo "✅ Redis running"; \
		else \
			echo "❌ Failed to start Redis container"; \
			exit 1; \
		fi; \
	fi

redis-down: ## Stop and remove local Redis container
	@docker stop $(REDIS_DEV_NAME) 2>/dev/null && docker rm $(REDIS_DEV_NAME) 2>/dev/null && echo "✅ Redis stopped" || echo "Redis not running"

nats-up: ## Start local NATS container (port $(NATS_DEV_PORT))
	@if docker inspect $(NATS_DEV_NAME) >/dev/null 2>&1; then \
		docker start $(NATS_DEV_NAME) 2>/dev/null && echo "✅ NATS started (already exists)" || { echo "❌ Failed to start existing NATS container"; exit 1; }; \
	else \
		if lsof -Pi :$(NATS_DEV_PORT) -sTCP:LISTEN -t >/dev/null 2>&1; then \
			echo "❌ Port $(NATS_DEV_PORT) already in use. Stop the existing NATS service first."; \
			echo "   Check with: lsof -i :$(NATS_DEV_PORT)"; \
			exit 1; \
		fi; \
		echo "Starting NATS at localhost:$(NATS_DEV_PORT)..."; \
		if docker run -d --name $(NATS_DEV_NAME) -p $(NATS_DEV_PORT):4222 $(NATS_DEV_IMAGE) -js --auth $(NATS_AUTH_TOKEN_DEV) >/dev/null 2>&1; then \
			echo "✅ NATS running (JetStream enabled)"; \
		else \
			echo "❌ Failed to start NATS container"; \
			exit 1; \
		fi; \
	fi

nats-down: ## Stop and remove local NATS container
	@docker stop $(NATS_DEV_NAME) 2>/dev/null && docker rm $(NATS_DEV_NAME) 2>/dev/null && echo "✅ NATS stopped" || echo "NATS not running"

caddy-up: ## Start Caddy reverse proxy for dev (https://circuitbreaker.lab)
	@if [ -f "$(CADDY_PID_FILE)" ] && kill -0 $$(cat $(CADDY_PID_FILE)) 2>/dev/null; then \
		echo "✅ Caddy already running (PID $$(cat $(CADDY_PID_FILE)))"; \
	else \
		echo "Starting Caddy for https://circuitbreaker.lab..."; \
		caddy start --config Caddyfile.dev --pidfile $(CADDY_PID_FILE); \
		if [ $$? -eq 0 ]; then \
			echo "✅ Caddy started → https://circuitbreaker.lab"; \
			echo "   Note: Accept self-signed cert warning in browser on first visit"; \
			echo "   Or trust CA cert: http://circuitbreaker.lab/caddy-root-ca.crt"; \
		else \
			echo "❌ Failed to start Caddy"; \
			exit 1; \
		fi \
	fi

caddy-down: ## Stop Caddy reverse proxy
	@if [ -f "$(CADDY_PID_FILE)" ]; then \
		caddy stop --config Caddyfile.dev; \
		rm -f $(CADDY_PID_FILE); \
		echo "✅ Caddy stopped"; \
	else \
		echo "ℹ️  Caddy not running"; \
	fi

caddy-status: ## Check Caddy status
	@if [ -f "$(CADDY_PID_FILE)" ] && kill -0 $$(cat $(CADDY_PID_FILE)) 2>/dev/null; then \
		echo "✅ Caddy running (PID $$(cat $(CADDY_PID_FILE)))"; \
		echo "   Access: https://circuitbreaker.lab"; \
	else \
		echo "❌ Caddy not running"; \
		exit 1; \
	fi

caddy-reload: ## Reload Caddyfile.dev without downtime
	@caddy reload --config Caddyfile.dev

dev-full: services-up caddy-up dev ## Full dev stack: services + Caddy + backend + frontend
	@echo ""
	@echo "🚀 Full dev environment running:"
	@echo "   Backend:  http://localhost:$(BACKEND_PORT)"
	@echo "   Frontend: http://localhost:$(FRONTEND_PORT)"
	@echo "   Caddy:    https://circuitbreaker.lab (production-like)"
	@echo ""
	@echo "Use https://circuitbreaker.lab for end-user simulation"

migrate: ## Run Alembic migrations (requires Postgres; set CB_DB_URL or use after make postgres-up)
	@echo "Running migrations..."
	@cd $(BACKEND_DIR) && CB_DB_URL="$${CB_DB_URL:-$(CB_DB_URL_DEV)}" PYTHONPATH=src $(CURDIR)/.venv/bin/alembic upgrade head
	@echo "✅ Migrations complete."

# ==============================================================================
# DOCKER & COMPOSE (same docker-compose.yml as production; override CB_IMAGE for dev)
# ==============================================================================
ENV_FILE := $(if $(wildcard .env.local),.env.local,.env)
.PHONY: lock setup-buildx up down reset logs shell build compose-build compose-up compose-down compose-clean compose-reset-db compose-fresh compose-up-local tunnel-up tunnel-down preflight dev-stop-install db-seed-default-team test-mono-e2e docker-mono docker-mono-local docker-mono-release install-cb install-local secrets health

up: dev-stop-install ## Start stack with locally built image (CB_IMAGE=...:dev). Copy .env.example to .env.local first.
	CB_IMAGE=$(DOCKER_REPO):dev docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build

down: ## Stop stack (keep volumes)
	docker compose -f $(COMPOSE_FILE) down

reset: ## Full teardown — remove containers and volumes (destructive)
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans
	@docker volume rm circuitbreaker-data 2>/dev/null || true

logs: ## Tail container logs
	docker compose -f $(COMPOSE_FILE) logs -f --tail=100

shell: ## Open shell in running app container
	docker compose -f $(COMPOSE_FILE) exec circuitbreaker sh

build: ## Build mono image locally as $(DOCKER_REPO):dev
	@echo "Building mono image as $(DOCKER_REPO):dev..."
	docker build -f Dockerfile.mono -t $(DOCKER_REPO):dev .
	@echo "Run 'make up' to start the stack."

secrets: ## Generate fresh secrets for .env.local
	@echo "CB_JWT_SECRET=$$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
	@echo "CB_VAULT_KEY=$$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
	@echo "CB_DB_PASSWORD=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
	@echo "NATS_AUTH_TOKEN=$$(openssl rand -base64 32)"

health: ## Hit health endpoint (requires stack running)
	@curl -sf "http://localhost:$${CB_PORT:-80}/api/v1/health" | jq .

install-local: ## Run install.sh locally (same as one-liner users run)
	@bash install.sh

db-seed-default-team: ## Seed Default Team (id=1) in mono container; run after compose-up
	@echo "Seeding Default Team..."
	docker exec circuitbreaker python -m app.scripts.seed_default_team
	@echo "✅ Default Team seeded."

lock: ## Regenerate apps/backend/requirements.txt from poetry.lock
	@echo "Regenerating apps/backend/requirements.txt from poetry.lock..."
	@python3 scripts/gen_requirements.py
	@echo "✅ requirements.txt updated — commit the file alongside poetry.lock."

compose-build: ## Build mono image only (no up). Use before compose-up to force rebuild.
	@echo "Building mono image..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -f $(COMPOSE_FILE) build circuitbreaker
	@echo "✅ Mono image built. Run 'make compose-up' to start."

setup-buildx: ## Register QEMU binfmt handlers and ensure a multi-arch buildx builder is active
	@echo "Registering QEMU binfmt handlers for multi-arch emulation..."
	docker run --privileged --rm tonistiigi/binfmt --install all
	@echo "Ensuring multi-arch buildx builder is active..."
	docker buildx create --name cb-multiarch --driver docker-container --bootstrap --use 2>/dev/null \
	  || docker buildx use cb-multiarch
	@echo "✅ QEMU + buildx ready."

dev-stop-install: ## Stop the install-script-deployed container if running (avoids port/name conflicts)
	@if docker inspect circuit-breaker >/dev/null 2>&1; then \
		echo "Stopping install-script container 'circuit-breaker'..."; \
		docker stop circuit-breaker >/dev/null 2>&1 || true; \
		echo "✅ Stopped. Data volume 'circuit-breaker-data' is preserved."; \
		echo "   Restart later with: docker start circuit-breaker"; \
	else \
		echo "No install-script container found — nothing to stop."; \
	fi

compose-up: dev-stop-install ## Build (if needed) and start mono container
	@echo "Starting docker-compose stack..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -f $(COMPOSE_FILE) up --build -d

compose-down: ## Stop docker compose stack (data kept)
	@echo "Stopping docker-compose stack..."
	docker compose -f $(COMPOSE_FILE) down

compose-clean: ## Stop stack, remove volumes, and wipe data dir (full reset; data is lost)
	@echo "Stopping stack and removing all volumes..."
	docker compose -f $(COMPOSE_FILE) down -v
	@DATA_DIR=""; \
	if [ -f .env ]; then \
	  DATA_DIR=$$(grep -E '^CB_DATA_DIR=' .env 2>/dev/null | sed 's/^CB_DATA_DIR=//' | tr -d '"' | tr -d "'" | tr -d '\n\r' | head -1); \
	fi; \
	if [ -z "$$DATA_DIR" ]; then DATA_DIR="$(CB_DATA_DIR)"; fi; \
	echo "Wiping data directory: $$DATA_DIR"; \
	rm -rf "$$DATA_DIR"; \
	DB_URL=""; \
	if [ -f .env ]; then \
	  DB_URL=$$(grep -E '^CB_DB_URL=' .env 2>/dev/null | sed 's/^CB_DB_URL=//' | tr -d '"' | tr -d "'" | tr -d '\n\r' | head -1); \
	fi; \
	if [ -n "$$DB_URL" ]; then \
	  DB_HOST=$$(echo "$$DB_URL" | sed -n 's/.*@\([^:/]*\).*/\1/p'); \
	  if [ -n "$$DB_HOST" ] && [ "$$DB_HOST" != "localhost" ] && [ "$$DB_HOST" != "127.0.0.1" ]; then \
	    echo ""; \
	    echo "⚠️  CB_DB_URL points to external host '$$DB_HOST'. Users and sessions live in that database."; \
	    echo "   This wipe did NOT touch that database. To fully reset (new account / OOBE), drop and"; \
	    echo "   recreate the circuitbreaker database, or see docs/installation/configuration.md."; \
	    echo ""; \
	  fi; \
	fi; \
	echo "✅ Stack stopped, volumes removed, and data directory wiped."; \
	echo ""; \
	echo "To fully log out and see the setup wizard again, clear the 'cb_session' cookie for this site in your browser (DevTools → Application → Cookies), or use a private/incognito window."

compose-reset-db: ## Drop and recreate the Circuit Breaker DB (for external Postgres full reset). Requires psql and CB_DB_URL in .env. Run compose-down first.
	@if [ ! -f .env ]; then echo "No .env file. Set CB_DB_URL and run again."; exit 1; fi; \
	DB_URL=$$(grep -E '^CB_DB_URL=' .env 2>/dev/null | sed 's/^CB_DB_URL=//' | tr -d '"' | tr -d "'" | tr -d '\n\r' | head -1); \
	if [ -z "$$DB_URL" ]; then echo "CB_DB_URL not set in .env."; exit 1; fi; \
	DB_NAME=$$(echo "$$DB_URL" | sed -n 's|.*/\([^/?]*\)$$|\1|p'); \
	ADMIN_URL=$$(echo "$$DB_URL" | sed "s|/[^/?]*$$|/postgres|"); \
	echo "Dropping and recreating database '$$DB_NAME' (ensure stack is stopped: make compose-down)."; \
	psql "$$ADMIN_URL" -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$$DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true; \
	psql "$$ADMIN_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$$DB_NAME\";" -c "CREATE DATABASE \"$$DB_NAME\";"; \
	echo "✅ Database $$DB_NAME reset. Run 'make compose-up' and clear the cb_session cookie for a full OOBE."

install-cb: ## Install the cb CLI for the mono stack (container name: circuitbreaker)
	@echo "Installing cb command to /usr/local/bin/cb..."
	@sudo install -Dm755 cb /usr/local/bin/cb
	@mkdir -p $(HOME)/.circuit-breaker
	@chmod 700 $(HOME)/.circuit-breaker
	@printf '# Circuit Breaker — install config (written by make install-cb)\nCB_MODE=compose\nCB_CONTAINER=circuitbreaker\nCB_BACKEND_CONTAINER=circuitbreaker\nCB_DATA_DIR=/data\nCB_PORT=80\nCB_IMAGE=\nCB_VOLUME=\n' > $(HOME)/.circuit-breaker/install.conf
	@chmod 600 $(HOME)/.circuit-breaker/install.conf
	@echo "✅ cb installed. Run: cb help"

tunnel-up: ## Start the Cloudflare Tunnel container (requires CLOUDFLARE_TUNNEL_TOKEN in .env)
	@echo "Starting Cloudflare Tunnel..."
	@docker rm -f cb-cloudflared >/dev/null 2>&1 || true
	docker compose -f $(COMPOSE_FILE) --profile tunnel up -d --no-deps --force-recreate cloudflared
	@echo "✅ Tunnel container started. Check logs: docker logs cb-cloudflared -f"

tunnel-down: ## Stop the Cloudflare Tunnel container
	@echo "Stopping Cloudflare Tunnel..."
	docker compose -f $(COMPOSE_FILE) --profile tunnel stop cloudflared
	@echo "✅ Tunnel stopped."

compose-fresh: dev-stop-install ## Wipe volumes, rebuild mono image, and start (triggers OOBE)
	@echo "Wiping volumes and starting fresh stack..."
	docker compose -f $(COMPOSE_FILE) down -v
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -f $(COMPOSE_FILE) up --build -d
	@echo "✅ Fresh stack running — open the app to complete first-run setup."

preflight: test frontend-build ## Run tests, build frontend, build mono image
	@echo "Building mono image..."
	@DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose -f $(COMPOSE_FILE) build circuitbreaker
	@echo "\n✅ Preflight checks completed."
	@echo "See PRE_PKG.md for manual matrix/signoff steps."

# ==============================================================================
# RELEASE & NATIVE BUILDS
# ==============================================================================
.PHONY: build-native build-native-docker docker-multiarch test-pi-local release-dry-run deb rpm package-all

build-native: frontend-build ## Build a packaged native archive for the current OS/ARCH
	@echo "Building packaged native release for $(OS_ARCH)..."
	@echo "Ensuring pyinstaller is installed..."
	@.venv/bin/python -c "import pip" >/dev/null 2>&1 || .venv/bin/python -m ensurepip --upgrade
	@.venv/bin/python -m pip install pyinstaller
	@echo "Running native packaging..."
	@.venv/bin/python scripts/build_native_release.py --clean
	@echo "✅ Native package(s) created in dist/native/"

deb: build-native ## Build .deb package (requires nfpm)
	@command -v nfpm >/dev/null || { echo "Install nfpm: https://nfpm.goreleaser.com/install/"; exit 1; }
	VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager deb --target dist/native/
	@echo "deb package created in dist/native/"

rpm: build-native ## Build .rpm package (requires nfpm)
	@command -v nfpm >/dev/null || { echo "Install nfpm: https://nfpm.goreleaser.com/install/"; exit 1; }
	VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager rpm --target dist/native/
	@echo "rpm package created in dist/native/"

package-all: build-native ## Build tar.gz + deb + rpm (requires nfpm)
	@echo "Building all native packages for $(OS_ARCH)..."
	@if command -v nfpm >/dev/null 2>&1; then \
		VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager deb --target dist/native/; \
		VERSION=$(VERSION) GOARCH=amd64 nfpm package --config nfpm.yaml --packager rpm --target dist/native/; \
	else echo "nfpm not found — skipping deb/rpm. tar.gz still available in dist/native/"; fi
	@echo "Packages in dist/native/"

build-native-docker: ## Build native archive inside Ubuntu 22.04 container (glibc-compatible for older VMs)
	@echo "Building native package in Docker (Ubuntu 22.04, glibc 2.35)..."
	@mkdir -p dist/native
	@docker build -f docker/Dockerfile.native -t cb-native-build . \
		&& docker run --rm -v "$(CURDIR)/dist/native:/out" cb-native-build
	@echo "✅ glibc-compatible native package(s) in dist/native/"

docker-multiarch: setup-buildx ## Build and push a multi-arch Docker image (requires login)
	@echo "Building multi-arch image for $(RELEASE_TAG)..."
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):$(RELEASE_TAG) --push .

docker-mono: setup-buildx ## Build and push mono image (no E2E; use docker-mono-release to test before push)
	$(if $(TAG),,$(error TAG is required, e.g. make docker-mono TAG=v0.2.0))
	@echo "Building and pushing mono image as $(DOCKER_REPO):mono-$(TAG) and :mono-latest..."
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
		-f Dockerfile.mono \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):mono-$(TAG) -t $(DOCKER_REPO):mono-latest --push .
	@echo "Done. Pull with: $(DOCKER_REPO):mono-$(TAG)"

docker-mono-local: ## Build mono image for current platform only (no push). Run with: CB_TAG=local docker compose up -d --no-build
	@echo "Building local production mono image as $(DOCKER_REPO):mono-local..."
	docker build -f Dockerfile.mono \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):mono-local .
	@echo "✅ Image built. Start stack with: make compose-up-local"
	@echo "   Or: CB_TAG=local docker compose -f $(COMPOSE_FILE) up -d --no-build"

compose-up-local: dev-stop-install docker-mono-local ## Build local mono image and start stack (no GHCR push)
	@echo "Starting stack with local image $(DOCKER_REPO):mono-local..."
	CB_TAG=local docker compose -f $(COMPOSE_FILE) up -d --no-build
	CB_DATA_DIR=$(CB_DATA_DIR) docker compose -f $(COMPOSE_FILE) up -d --no-build
	@echo "✅ Stack running. Open the app (e.g. http://localhost) — use .env for CB_DB_PASSWORD and CB_VAULT_KEY."

docker-mono-release: setup-buildx ## Build mono, run E2E test, then push (recommended for releases)
	$(if $(TAG),,$(error TAG is required, e.g. make docker-mono-release TAG=v0.2.0))
	@echo "Step 1/3: Building mono image for current platform (E2E test)..."
	docker build -f Dockerfile.mono \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):mono-$(TAG) .
	@echo "Step 2/3: Running E2E test..."
	@CB_MONO_IMAGE="$(DOCKER_REPO):mono-$(TAG)" ./scripts/test-mono-e2e.sh
	@echo "Step 3/3: E2E passed. Pushing multi-arch..."
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
		-f Dockerfile.mono \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):mono-$(TAG) -t $(DOCKER_REPO):mono-latest --push .
	@echo "Done. Pull with: $(DOCKER_REPO):mono-$(TAG)"

test-mono-e2e: ## Run E2E test for mono container (starts container, health + frontend check, teardown)
	@./scripts/test-mono-e2e.sh

test-pi-local: ## Test the ARM64 mono image locally using emulation (build or pull mono image first)
	@echo "Testing ARM64 mono image $(DOCKER_REPO):mono-$(RELEASE_TAG)..."
	docker run --rm -d --name cb-pi-test -p 8080:80 -e CB_DB_PASSWORD=test -e CB_VAULT_KEY=test --platform linux/arm64 $(DOCKER_REPO):mono-$(RELEASE_TAG)
	@echo "Giving container 15s to start..."
	@sleep 15
	@curl -f http://localhost:8080/api/v1/health
	@docker stop cb-pi-test

release-dry-run: build-native ## Run a dry-run of the release process
	@echo "\nDRY RUN: Would create release with assets in dist/native/"
	@ls -l dist/native
	@echo "\n✅ Release dry-run complete."

# ==============================================================================
# SECURITY VERIFICATION
# ==============================================================================
.PHONY: check-user check-security

check-user: ## Verify mono container is NOT running as root
	@echo "→ Checking container user..."
	@docker compose exec circuitbreaker id
	@docker compose exec circuitbreaker whoami
	@echo ""
	@echo "→ Checking image user config..."
	@docker inspect $$(docker compose ps -q circuitbreaker 2>/dev/null || echo "circuitbreaker") \
		--format 'Image user: {{.Config.User}}' 2>/dev/null || echo "Container not running"
	@echo ""
	@echo "→ Checking /data permissions..."
	@docker compose exec circuitbreaker ls -la /data | head -10
	@echo ""
	@echo "→ Verifying read-only root filesystem..."
	@docker compose exec circuitbreaker sh -c \
		"touch /test_root_write 2>&1 || echo 'GOOD: root filesystem is read-only'"

check-security: check-user ## Full security posture check
	@echo ""
	@echo "→ Checking capabilities..."
	@docker compose exec circuitbreaker sh -c "cat /proc/self/status | grep CapEff"
	@echo ""
	@echo "→ Checking no-new-privileges..."
	@docker compose exec circuitbreaker sh -c "cat /proc/self/status | grep NoNewPrivs"
	@echo "  Expected: NoNewPrivs: 1"
	@echo ""
	@echo "→ Verifying /tmp is writable..."
	@docker compose exec circuitbreaker sh -c \
		"touch /tmp/test && rm /tmp/test && echo 'GOOD: /tmp writable'"
	@echo ""
	@echo "→ Verifying /data is writable..."
	@docker compose exec circuitbreaker sh -c \
		"touch /data/.test && rm /data/.test && echo 'GOOD: /data writable'"
	@echo ""
	@echo "✅ Security verification complete."
