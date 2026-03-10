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

# ==============================================================================
# CORE TARGETS
# ==============================================================================
.PHONY: help dev stop backend frontend

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

dev: stop ## Start backend + frontend for local development
	@echo "Starting backend  → http://localhost:$(BACKEND_PORT)"
	@cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT) &
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	@cd $(FRONTEND_DIR) && npm start &

stop: ## Kill any process holding the dev ports
	@lsof -ti tcp:$(BACKEND_PORT)  | xargs kill -9 2>/dev/null || true
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Ports $(BACKEND_PORT) and $(FRONTEND_PORT) cleared."

backend: ## Kill port $(BACKEND_PORT) and restart the backend
	@lsof -ti tcp:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting backend → http://localhost:$(BACKEND_PORT)"
	cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

frontend: ## Kill port $(FRONTEND_PORT) and restart the frontend
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	cd $(FRONTEND_DIR) && npm start

# ==============================================================================
# BUILD & TEST
# ==============================================================================
.PHONY: lint format ci release test test-backend test-frontend test-all test-coverage docs docs-build frontend-build snyk-version snyk-auth snyk-test snyk-monitor

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

release: ## Build and push v0.2.0 multi-arch image
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -t ghcr.io/blkleg/circuitbreaker:v0.2.0 --push .

test: ## Run backend tests
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration -q
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

# ==============================================================================
# DOCKER & COMPOSE
# ==============================================================================
.PHONY: lock docker-build setup-buildx compose-up compose-down compose-clean compose-fresh compose-pull-bases tunnel-up tunnel-down trust-ca preflight dev-stop-install db-migrate db-migrate-local db-postgres-up db-seed-default-team

db-migrate: ## Run Alembic migrations to head (requires running postgres container)
	@echo "Running Alembic migrations..."
	docker exec cb-backend alembic upgrade head
	@echo "✅ Migrations applied."

db-postgres-up: ## Start Postgres in Docker with port 5432 exposed (for local migrations / dev). Run from repo root.
	@echo "Starting Postgres (port 5432 exposed)..."
	docker compose -f docker-compose.yml -f docker/docker-compose.dev-db.yml up -d postgres
	@echo "Waiting for Postgres to be ready..."
	@until docker exec cb-postgres pg_isready -U breaker -d circuitbreaker 2>/dev/null; do sleep 1; done
	@echo "✅ Postgres is ready. Run 'make db-migrate-local' to apply migrations."

db-migrate-local: ## Run Alembic migrations via backend container (run 'make db-postgres-up' first; builds backend image if needed)
	@echo "Running Alembic migrations (in backend container)..."
	DOCKER_BUILDKIT=1 docker compose -f docker-compose.yml -f docker/docker-compose.dev-db.yml run --rm backend alembic upgrade head
	@echo "✅ Migrations applied."

db-seed-default-team: ## Seed Default Team (id=1) and assign all existing data to it
	@echo "Seeding Default Team..."
	docker exec cb-backend python -m app.scripts.seed_default_team
	@echo "✅ Default Team seeded."

lock: ## Regenerate apps/backend/requirements.txt from poetry.lock
	@echo "Regenerating apps/backend/requirements.txt from poetry.lock..."
	@python3 scripts/gen_requirements.py
	@echo "✅ requirements.txt updated — commit the file alongside poetry.lock."

docker-build: ## Build unified beta image + compose services from local source
	@echo "Building circuit-breaker:beta (unified image)..."
	DOCKER_BUILDKIT=1 docker build -t circuit-breaker:beta .
	@echo "Building compose services (cb-backend, cb-frontend)..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build
	@echo "✅ All images built from local source."

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

compose-up: dev-stop-install ## Rebuild and start docker compose stack (stops install-script container first)
	@echo "Starting docker-compose stack..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose up --build -d

compose-rebuild-frontend: ## Force rebuild frontend image (no cache) and recreate container — use after changing frontend code
	@echo "Rebuilding frontend image (no cache)..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build --no-cache frontend
	@echo "Recreating frontend container..."
	docker compose up -d --force-recreate frontend
	@echo "✅ Frontend rebuilt. Hard-refresh the browser (Ctrl+Shift+R / Cmd+Shift+R) to avoid cached assets."

compose-rebuild-backend: ## Force rebuild backend image (no cache) and recreate container — use after changing backend code (e.g. new API routes)
	@echo "Rebuilding backend image (no cache)..."
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose build --no-cache backend
	@echo "Recreating backend container..."
	docker compose up -d --force-recreate backend
	@echo "✅ Backend rebuilt. Status and other new API routes will be available."

compose-down: ## Stop and remove docker compose stack
	@echo "Stopping docker-compose stack..."
	docker compose down

compose-pull-bases: ## Pre-pull base images to speed up first compose build (run before compose-up on fresh VPS)
	@echo "Pre-pulling base images for compose build..."
	@docker pull python:3.12-slim-bookworm
	@docker pull node:20-alpine
	@docker pull nginxinc/nginx-unprivileged:1.27-alpine
	@docker pull caddy:2-alpine
	@docker pull nats:2-alpine
	@echo "✅ Base images cached. Run 'make compose-up' to build and start."

compose-clean: ## Stop stack and remove all volumes (wipes database & uploads)
	@echo "Stopping stack and removing all volumes..."
	docker compose down -v
	@echo "✅ Stack stopped and volumes removed."

install-cb: ## Install the cb CLI tool for this compose stack (writes /usr/local/bin/cb + install.conf)
	@echo "Installing cb command to /usr/local/bin/cb..."
	@sudo install -Dm755 cb /usr/local/bin/cb
	@mkdir -p $(HOME)/.circuit-breaker
	@chmod 700 $(HOME)/.circuit-breaker
	@printf '# Circuit Breaker — install config (written by make install-cb)\nCB_MODE=compose\nCB_CONTAINER=cb-backend\nCB_BACKEND_CONTAINER=cb-backend\nCB_DATA_DIR=/app/data\nCB_PORT=443\nCB_IMAGE=\nCB_VOLUME=\n' > $(HOME)/.circuit-breaker/install.conf
	@chmod 600 $(HOME)/.circuit-breaker/install.conf
	@echo "✅ cb installed. Run: cb help"

tunnel-up: ## Start the Cloudflare Tunnel container (requires CLOUDFLARE_TUNNEL_TOKEN in .env)
	@echo "Starting Cloudflare Tunnel..."
	@docker rm -f cb-cloudflared >/dev/null 2>&1 || true
	docker compose --profile tunnel up -d --no-deps --force-recreate cloudflared
	@echo "✅ Tunnel container started. Check logs: docker logs cb-cloudflared -f"

tunnel-down: ## Stop the Cloudflare Tunnel container
	@echo "Stopping Cloudflare Tunnel..."
	docker compose --profile tunnel stop cloudflared
	@echo "✅ Tunnel stopped."

compose-fresh: dev-stop-install ## Wipe all volumes then rebuild and start a clean stack (triggers OOBE)
	@echo "Wiping volumes and starting fresh stack..."
	docker compose down -v
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker compose up --build -d
	@echo "✅ Fresh stack running — open the app to complete first-run setup."
	@echo "💡 Run 'make trust-ca' to trust the new Caddy CA for HTTPS."

trust-ca: ## Extract Caddy root CA and install into system + browser trust stores
	@echo "─── Extracting Caddy root CA ───"
	@mkdir -p $(HOME)/.circuit-breaker
	@tries=0; \
	while ! docker exec cb-caddy test -f /data/caddy/pki/authorities/local/root.crt 2>/dev/null; do \
		tries=$$((tries + 1)); \
		if [ $$tries -ge 15 ]; then echo "❌ Timed out waiting for Caddy CA. Is cb-caddy running?"; exit 1; fi; \
		echo "  Waiting for Caddy to generate CA... ($$tries/15)"; \
		sleep 2; \
	done
	@docker cp cb-caddy:/data/caddy/pki/authorities/local/root.crt $(HOME)/.circuit-breaker/caddy-root-ca.crt
	@echo "✅ CA extracted to $(HOME)/.circuit-breaker/caddy-root-ca.crt"
	@echo ""
	@echo "─── Installing into system trust store (requires sudo) ───"
	@if [ -d /etc/pki/ca-trust/source/anchors ]; then \
		if sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /etc/pki/ca-trust/source/anchors/circuit-breaker-caddy-ca.crt \
		   && sudo update-ca-trust; then \
			echo "✅ CA trusted by system (Fedora/RHEL)."; \
		else \
			echo "⚠️  sudo failed. Run manually:"; \
			echo "   sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /etc/pki/ca-trust/source/anchors/circuit-breaker-caddy-ca.crt && sudo update-ca-trust"; \
		fi; \
	elif [ -d /usr/local/share/ca-certificates ]; then \
		if sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /usr/local/share/ca-certificates/circuit-breaker-caddy-ca.crt \
		   && sudo update-ca-certificates; then \
			echo "✅ CA trusted by system (Debian/Ubuntu)."; \
		else \
			echo "⚠️  sudo failed. Run manually:"; \
			echo "   sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /usr/local/share/ca-certificates/circuit-breaker-caddy-ca.crt && sudo update-ca-certificates"; \
		fi; \
	elif [ -d /etc/ca-certificates/trust-source/anchors ]; then \
		if sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /etc/ca-certificates/trust-source/anchors/circuit-breaker-caddy-ca.crt \
		   && sudo trust extract-compat; then \
			echo "✅ CA trusted by system (Arch)."; \
		else \
			echo "⚠️  sudo failed. Run manually:"; \
			echo "   sudo cp $(HOME)/.circuit-breaker/caddy-root-ca.crt /etc/ca-certificates/trust-source/anchors/circuit-breaker-caddy-ca.crt && sudo trust extract-compat"; \
		fi; \
	else \
		echo "⚠️  Could not detect system CA store. Install manually."; \
	fi
	@echo ""
	@echo "─── Installing into browser trust store (NSS) ───"
	@if command -v certutil >/dev/null 2>&1; then \
		mkdir -p $(HOME)/.pki/nssdb; \
		certutil -d sql:$(HOME)/.pki/nssdb -D -n "CircuitBreaker-Caddy-CA" 2>/dev/null || true; \
		certutil -d sql:$(HOME)/.pki/nssdb -A -t "C,," -n "CircuitBreaker-Caddy-CA" -i $(HOME)/.circuit-breaker/caddy-root-ca.crt; \
		echo "✅ CA trusted by Chrome / Brave / Chromium."; \
	else \
		echo "⚠️  certutil not found. Install nss-tools (Fedora) or libnss3-tools (Debian)."; \
		echo "   Then run: certutil -d sql:$(HOME)/.pki/nssdb -A -t 'C,,' -n 'CircuitBreaker-Caddy-CA' -i $(HOME)/.circuit-breaker/caddy-root-ca.crt"; \
	fi
	@echo ""
	@echo "─── Checking /etc/hosts ───"
	@if grep -q "circuitbreaker.local" /etc/hosts 2>/dev/null; then \
		echo "✅ circuitbreaker.local already in /etc/hosts."; \
	else \
		if echo "127.0.0.1  circuitbreaker.local" | sudo tee -a /etc/hosts >/dev/null; then \
			echo "✅ Added circuitbreaker.local → 127.0.0.1 to /etc/hosts."; \
		else \
			echo "⚠️  sudo failed. Run manually:"; \
			echo "   echo '127.0.0.1  circuitbreaker.local' | sudo tee -a /etc/hosts"; \
		fi; \
	fi
	@echo ""
	@echo "─── Done ───"
	@echo "Close ALL browser windows, reopen, and visit https://circuitbreaker.local"
	@echo "(Browsers cache certificate state per-session — a full restart is required.)"

preflight: test frontend-build docker-build ## Run pre-commit checks (test, build frontend, build docker)
	@echo "\n✅ Preflight checks completed."
	@echo "See PRE_PKG.md for manual matrix/signoff steps."

# ==============================================================================
# RELEASE & NATIVE BUILDS
# ==============================================================================
.PHONY: build-native build-native-docker docker-publish docker-multiarch test-pi-local release-dry-run

build-native: frontend-build ## Build a packaged native archive for the current OS/ARCH
	@echo "Building packaged native release for $(OS_ARCH)..."
	@echo "Ensuring pyinstaller is installed..."
	@.venv/bin/python -m pip install pyinstaller
	@echo "Running native packaging..."
	@.venv/bin/python scripts/build_native_release.py --clean
	@echo "✅ Native package(s) created in dist/native/"

build-native-docker: ## Build native archive inside Ubuntu 22.04 container (glibc-compatible for older VMs)
	@echo "Building native package in Docker (Ubuntu 22.04, glibc 2.35)..."
	@mkdir -p dist/native
	@docker build -f docker/Dockerfile.native -t cb-native-build . \
		&& docker run --rm -v "$(CURDIR)/dist/native:/out" cb-native-build
	@echo "✅ glibc-compatible native package(s) in dist/native/"

docker-publish: setup-buildx ## Build and push a multi-arch Docker image to DOCKER_REPO
	@echo "Building and publishing multi-arch image to $(DOCKER_REPO) as $(RELEASE_TAG)..."
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
		--no-cache \
		--build-arg APP_VERSION=$(VERSION) \
		-t "$(DOCKER_REPO):$(RELEASE_TAG)" \
		-t "$(DOCKER_REPO):latest" \
		--push .

docker-multiarch: setup-buildx ## Build and push a multi-arch Docker image (requires login)
	@echo "Building multi-arch image for $(RELEASE_TAG)..."
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 \
		--build-arg APP_VERSION=$(VERSION) \
		-t $(DOCKER_REPO):$(RELEASE_TAG) --push .

test-pi-local: ## Test the ARM64 Docker image locally using emulation
	@echo "Testing ARM64 image $(RELEASE_TAG)..."
	docker run --rm -d --name cb-pi-test -p 8080:8080 --platform linux/arm64 $(DOCKER_REPO):$(RELEASE_TAG)
	@echo "Giving container 10s to start..."
	@sleep 10
	@curl -f http://localhost:8080/health
	@docker stop cb-pi-test

release-dry-run: build-native ## Run a dry-run of the release process
	@echo "\nDRY RUN: Would create release with assets in dist/native/"
	@ls -l dist/native
	@echo "\n✅ Release dry-run complete."
