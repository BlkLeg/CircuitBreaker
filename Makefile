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

DOCKER_REGISTRY   ?= ghcr.io/blkleg/circuitbreaker

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
# BUILD & RELEASE
# ==============================================================================
DIST_NATIVE ?= dist/native

.PHONY: build build-deps build-release build-from-source release-local docker-build docker-push sign sbom

build: ## Build native app (tarball + deb + rpm + apk + AppImage + .pkg.tar.zst)
	cd $(FRONTEND_DIR) && npm ci && npm run build
	.venv/bin/python scripts/build_native_release.py --clean

build-deps: ## Install build toolchain (nfpm, appimagetool, Python 3.12, Node 20)
	bash scripts/install-build-deps.sh

build-release: ## Install build deps then build all packages
	$(MAKE) --no-print-directory build-deps
	$(MAKE) --no-print-directory build

build-from-source: ## Full power-user path: deps + venv + build (clean machine → artifacts)
	$(MAKE) --no-print-directory build-deps
	$(MAKE) --no-print-directory install
	$(MAKE) --no-print-directory build

release-local: ## build-release + tag current HEAD with VERSION
	$(MAKE) --no-print-directory build-release
	git tag -a "v$$(cat VERSION)" -m "Release v$$(cat VERSION)"
	@echo "Tagged v$$(cat VERSION). Push with: git push origin v$$(cat VERSION)"

docker-build: ## Build the mono Docker image locally
	docker build -f Dockerfile.mono -t $(DOCKER_REGISTRY):$$(cat VERSION) .

docker-push: ## Push mono image to GHCR (requires docker login to ghcr.io first)
	docker push $(DOCKER_REGISTRY):$$(cat VERSION)
	docker tag $(DOCKER_REGISTRY):$$(cat VERSION) $(DOCKER_REGISTRY):latest
	docker push $(DOCKER_REGISTRY):latest

sign: ## GPG-sign dist/native artifacts + SHA256SUMS (requires GPG_KEY_ID=<email>)
	@[ -n "$(GPG_KEY_ID)" ] || (echo "Error: set GPG_KEY_ID=<fingerprint-or-email>"; exit 1)
	@cd $(DIST_NATIVE) && sha256sum * > SHA256SUMS
	@cd $(DIST_NATIVE) && for f in *.tar.gz *.deb *.rpm *.apk *.pkg.tar.zst *.AppImage *.json SHA256SUMS; do \
	  [ -f "$$f" ] && [[ "$$f" != *.asc ]] || continue; \
	  gpg --armor --detach-sign --local-user "$(GPG_KEY_ID)" "$$f"; \
	  echo "  signed: $$f"; \
	done
	@echo "Signatures written to $(DIST_NATIVE)/*.asc"

sbom: ## Generate SBOM for source dirs using syft (install: https://github.com/anchore/syft/releases/tag/v1.14.0)
	@command -v syft >/dev/null 2>&1 || (echo "Error: syft not found"; exit 1)
	@VERSION=$$(cat VERSION); \
	  syft scan dir:$(BACKEND_DIR) --exclude '**/node_modules' \
	    --output cyclonedx-json=$(DIST_NATIVE)/circuit-breaker_$${VERSION}_sbom-backend.cdx.json \
	    --output spdx-json=$(DIST_NATIVE)/circuit-breaker_$${VERSION}_sbom-backend.spdx.json; \
	  syft scan dir:$(FRONTEND_DIR) --exclude '**/node_modules' \
	    --output cyclonedx-json=$(DIST_NATIVE)/circuit-breaker_$${VERSION}_sbom-frontend.cdx.json \
	    --output spdx-json=$(DIST_NATIVE)/circuit-breaker_$${VERSION}_sbom-frontend.spdx.json
	@echo "SBOMs written to $(DIST_NATIVE)/"

# ==============================================================================
# CODE QUALITY & TESTING
# ==============================================================================
.PHONY: lint format test

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
