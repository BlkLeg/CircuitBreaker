# Makefile

# ==============================================================================
# VARIABLES
# ==============================================================================
BACKEND_PORT  ?= 8000
FRONTEND_PORT ?= 5173
BACKEND_DIR   ?= backend
FRONTEND_DIR  ?= frontend
VERSION       ?= $(shell git describe --tags --abbrev=0 2>/dev/null || echo "v0.1.0-dev")
OS_ARCH       := $(shell uname -s | tr '[:upper:]' '[:lower:]')-$(shell uname -m)
DOCKER_REPO   ?= $(shell git config --get remote.origin.url | sed 's/.*://;s/\.git$$//' | sed 's/^/ghcr.io\//' | tr '[:upper:]' '[:lower:]')

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
.PHONY: test test-backend test-frontend test-all test-coverage docs docs-build frontend-build

test: ## Run backend tests
	@echo "Running backend tests..."
	@cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/python -m pytest -q

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

# ==============================================================================
# DOCKER & COMPOSE
# ==============================================================================
.PHONY: docker-build compose-up compose-down preflight

docker-build: ## Build primary beta image with tag 'circuit-breaker:beta'
	@echo "Building circuit-breaker:beta image..."
	docker build -t circuit-breaker:beta .

compose-up: ## Rebuild and start docker compose stack (port 8080)
	@echo "Starting docker-compose stack..."
	docker compose -f docker/docker-compose.yml up --build -d

compose-down: ## Stop and remove docker compose stack
	@echo "Stopping docker-compose stack..."
	docker compose -f docker/docker-compose.yml down

preflight: test frontend-build docker-build ## Run pre-commit checks (test, build frontend, build docker)
	@echo "\n✅ Preflight checks completed."
	@echo "See PRE_PKG.md for manual matrix/signoff steps."

# ==============================================================================
# RELEASE & NATIVE BUILDS
# ==============================================================================
.PHONY: build-native docker-multiarch test-pi-local release-dry-run

build-native: ## Build a native binary for the current OS/ARCH using PyInstaller
	@echo "Building native binary for $(OS_ARCH)..."
	@echo "Ensuring pyinstaller is installed..."
	@.venv/bin/python -m pip install pyinstaller
	@echo "Running PyInstaller..."
	@.venv/bin/pyinstaller --onefile --noconsole \
		--name "circuit-breaker-$(VERSION)-$(OS_ARCH)" \
		$(BACKEND_DIR)/app/main.py
	@echo "✅ Native binary created in dist/"

docker-publish: ## Build and push a multi-arch Docker image to DOCKER_REPO
	@echo "Building and publishing multi-arch image to $(DOCKER_REPO)..."
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t "$(DOCKER_REPO):$(VERSION)" \
		-t "$(DOCKER_REPO):latest" \
		--push .

docker-multiarch: ## Build and push a multi-arch Docker image (requires login)
	@echo "Building multi-arch image for $(VERSION)..."
	docker buildx build --platform linux/amd64,linux/arm64 \
		-t $(DOCKER_REPO):$(VERSION) --push .

test-pi-local: ## Test the ARM64 Docker image locally using emulation
	@echo "Testing ARM64 image..."
	docker run --rm -d --name cb-pi-test -p 8080:8080 --platform linux/arm64 $(DOCKER_REPO):$(VERSION)
	@echo "Giving container 10s to start..."
	@sleep 10
	@curl -f http://localhost:8080/health
	@docker stop cb-pi-test

release-dry-run: build-native ## Run a dry-run of the release process
	@echo "\nDRY RUN: Would create release with assets in dist/"
	@ls -l dist
	@echo "\n✅ Release dry-run complete."
