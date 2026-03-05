# Makefile

# ==============================================================================
# VARIABLES
# ==============================================================================
BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 5173
BACKEND_DIR   ?= backend
FRONTEND_DIR  ?= frontend
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
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT) &
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	@cd $(FRONTEND_DIR) && npm start &

stop: ## Kill any process holding the dev ports
	@lsof -ti tcp:$(BACKEND_PORT)  | xargs kill -9 2>/dev/null || true
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Ports $(BACKEND_PORT) and $(FRONTEND_PORT) cleared."

backend: ## Kill port $(BACKEND_PORT) and restart the backend
	@lsof -ti tcp:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting backend → http://localhost:$(BACKEND_PORT)"
	cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

frontend: ## Kill port $(FRONTEND_PORT) and restart the frontend
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	cd $(FRONTEND_DIR) && npm start

# ==============================================================================
# BUILD & TEST
# ==============================================================================
.PHONY: lint format ci release test test-backend test-frontend test-all test-coverage docs docs-build frontend-build snyk-version snyk-auth snyk-test snyk-monitor

lint: ## Run backend and frontend linters
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff check app --select F
	@cd $(FRONTEND_DIR) && npm run lint

format: ## Format backend and frontend code
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff format .
	@cd $(FRONTEND_DIR) && npm run format

ci: lint test ## Run linting and tests

release: ## Build and push v0.1.4 multi-arch image
	docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -t ghcr.io/blkleg/circuitbreaker:v0.1.4 --push .

test: ## Run backend tests
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/python -m pytest -q
	@cd $(FRONTEND_DIR) && npm run test

test-backend: ## Run backend tests with verbose output
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/python -m pytest tests/ -v --asyncio-mode=auto

test-frontend: ## Run frontend component tests
	@echo "Running frontend tests..."
	@cd $(FRONTEND_DIR) && npm test

test-all: test-backend test-frontend ## Run all backend + frontend tests

test-coverage: ## Run all tests with coverage reports
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/python -m pytest tests/ --cov=app --cov-report=term-missing --asyncio-mode=auto
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
.PHONY: lock docker-build setup-buildx compose-up compose-down compose-clean compose-fresh preflight

lock: ## Regenerate backend/requirements.txt from poetry.lock
	@echo "Regenerating backend/requirements.txt from poetry.lock..."
	@python3 scripts/gen_requirements.py
	@echo "✅ requirements.txt updated — commit the file alongside poetry.lock."

docker-build: ## Build primary beta image with tag 'circuit-breaker:beta'
	@echo "Building circuit-breaker:beta image..."
	DOCKER_BUILDKIT=1 docker build -t circuit-breaker:beta .

setup-buildx: ## Register QEMU binfmt handlers and ensure a multi-arch buildx builder is active
	@echo "Registering QEMU binfmt handlers for multi-arch emulation..."
	docker run --privileged --rm tonistiigi/binfmt --install all
	@echo "Ensuring multi-arch buildx builder is active..."
	docker buildx create --name cb-multiarch --driver docker-container --bootstrap --use 2>/dev/null \
	  || docker buildx use cb-multiarch
	@echo "✅ QEMU + buildx ready."

compose-up: ## Rebuild and start docker compose stack (port 8080)
	@echo "Starting docker-compose stack..."
	DOCKER_BUILDKIT=1 docker compose -f docker/docker-compose.yml up --build -d

compose-down: ## Stop and remove docker compose stack
	@echo "Stopping docker-compose stack..."
	docker compose -f docker/docker-compose.yml down

compose-clean: ## Stop stack and remove all volumes (wipes database & uploads)
	@echo "Stopping stack and removing all volumes..."
	docker compose -f docker/docker-compose.yml down -v
	@echo "✅ Stack stopped and volumes removed."

compose-fresh: ## Wipe all volumes then rebuild and start a clean stack (triggers OOBE)
	@echo "Wiping volumes and starting fresh stack..."
	docker compose -f docker/docker-compose.yml down -v
	DOCKER_BUILDKIT=1 docker compose -f docker/docker-compose.yml up --build -d
	@echo "✅ Fresh stack running — open the app to complete first-run setup."

preflight: test frontend-build docker-build ## Run pre-commit checks (test, build frontend, build docker)
	@echo "\n✅ Preflight checks completed."
	@echo "See PRE_PKG.md for manual matrix/signoff steps."

# ==============================================================================
# RELEASE & NATIVE BUILDS
# ==============================================================================
.PHONY: build-native docker-publish docker-multiarch test-pi-local release-dry-run

build-native: ## Build a native binary for the current OS/ARCH using PyInstaller
	@echo "Building native binary for $(OS_ARCH)..."
	@echo "Ensuring pyinstaller is installed..."
	@.venv/bin/python -m pip install pyinstaller
	@echo "Running PyInstaller..."
	@.venv/bin/pyinstaller --onefile --noconsole \
		--name "circuit-breaker-$(VERSION)-$(OS_ARCH)" \
		$(BACKEND_DIR)/app/main.py
	@echo "✅ Native binary created in dist/"

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
	@echo "\nDRY RUN: Would create release with assets in dist/"
	@ls -l dist
	@echo "\n✅ Release dry-run complete."
