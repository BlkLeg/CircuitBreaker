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

# Integration tests get their own database so a test run never truncates dev data.
# Same host/credentials for both dependency modes: `deps-up` (Docker) and
# `deps-native-up` (systemd) each expose Postgres on localhost:$(POSTGRES_DEV_PORT).
POSTGRES_TEST_DB    ?= circuitbreaker_test
CB_TEST_DB_URL      ?= postgresql://$(POSTGRES_DEV_USER):$(POSTGRES_DEV_PASS)@localhost:$(POSTGRES_DEV_PORT)/$(POSTGRES_TEST_DB)

REDIS_DEV_NAME      ?= cb-redis-dev
REDIS_DEV_PORT      ?= 6379
CB_REDIS_URL_DEV    ?= redis://localhost:$(REDIS_DEV_PORT)/0

NATS_DEV_NAME       ?= cb-nats-dev
NATS_DEV_PORT       ?= 4222
NATS_AUTH_TOKEN_DEV ?= dev-token-local-only
CB_NATS_URL_DEV     ?= nats://localhost:$(NATS_DEV_PORT)
CB_ALLOW_DEGRADED_DEPENDENCIES_DEV ?= true
# Which process owns the background loops (app/core/topology.py). Defaults to
# mono so `make backend` on its own is still a complete appliance and keeps
# running the in-process workers. `make dev` overrides it to `api`, because it
# starts dedicated monitor workers and two owners is the combination
# topology.py refuses to let pass silently.
CB_TOPOLOGY_MODE_DEV ?= mono

DOCKER_REGISTRY   ?= ghcr.io/blkleg/circuitbreaker

PYTHON ?= $(shell python3 -c "import sys; print('python3' if sys.version_info >= (3,12) else 'python3.12')" 2>/dev/null || echo python3.12)

# ==============================================================================
# CORE TARGETS
# ==============================================================================
.PHONY: help install dev backend backend-watch frontend monitor-workers migrate reset-oobe stop ensure-nmap

help: ## Show available targets
	awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Bootstrap dev environment (run once)
	$(PYTHON) -m venv .venv
	$(CURDIR)/.venv/bin/pip install --upgrade pip
	$(CURDIR)/.venv/bin/pip install -e "apps/backend/[dev,otel]"
	npm install --prefix $(FRONTEND_DIR)

ensure-nmap: ## Fail early if the nmap binary is missing (discovery needs it)
	@command -v nmap >/dev/null 2>&1 || { \
	  echo "ERROR: nmap not found. Install it (Fedora: sudo dnf install nmap; Debian: sudo apt install nmap) then re-run."; \
	  exit 1; }

# `migrate` is a prerequisite, not a step inside one of the parallel branches
# below, and that ordering is the whole point: Make finishes every prerequisite
# before it runs the first recipe line, whereas the `&` branches race. The
# backend branch does run `alembic upgrade head` itself, but monitor-workers
# does not wait for it -- so against a fresh database the scheduler started
# ticking once a second while the schema was still being built and logged
# `UndefinedTable: relation "monitor_items" does not exist` for the length of
# the whole migration run. Against an already-migrated database the window is
# zero, which is why this only ever bit someone starting from an empty volume.
dev: ensure-nmap deps-up stop migrate ## Native backend + frontend + monitor workers + deps
	trap 'kill 0; wait' EXIT; \
		$(MAKE) --no-print-directory backend CB_TOPOLOGY_MODE_DEV=api & \
		$(MAKE) --no-print-directory monitor-workers & \
		$(MAKE) --no-print-directory frontend

stop: ## Kill any process holding the dev ports
	lsof -ti tcp:$(BACKEND_PORT) | xargs -r kill -9 || true
	lsof -ti tcp:$(FRONTEND_PORT) | xargs -r kill -9 || true
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
		CB_ALLOW_DEGRADED_DEPENDENCIES="$(CB_ALLOW_DEGRADED_DEPENDENCIES_DEV)" \
		CB_TOPOLOGY_MODE="$(CB_TOPOLOGY_MODE_DEV)" \
		CB_AUTO_MIGRATE=false \
		PYTHONPATH=src $(CURDIR)/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 8 $(CB_UVICORN_ARGS)

backend-watch:  ## Native backend WITH reload (post-fix only)
	$(MAKE) backend --no-print-directory CB_UVICORN_ARGS="--reload"

frontend:  ## Native frontend
	@echo "Starting frontend → http://localhost:5173"
	cd $(FRONTEND_DIR) && npm start

# The monitoring engine needs its own clock + poll workers (supervisord runs
# these in the container). Without them monitors stay "pending" forever.
monitor-workers:  ## Native monitor scheduler + poll worker
	@echo "Starting monitor scheduler + poll worker"
	cd $(BACKEND_DIR) && \
		trap 'kill 0; wait' EXIT; \
		for kind in monitor_scheduler monitor_poll; do \
			CB_DATA_DIR="$(CURDIR)/$(BACKEND_DIR)/.dev-data" \
			CB_DB_URL="$(CB_DB_URL_DEV)" \
			CB_REDIS_URL="$(CB_REDIS_URL_DEV)" \
			NATS_URL="$(CB_NATS_URL_DEV)" \
			NATS_AUTH_TOKEN="$(NATS_AUTH_TOKEN_DEV)" \
			CB_ALLOW_DEGRADED_DEPENDENCIES="$(CB_ALLOW_DEGRADED_DEPENDENCIES_DEV)" \
			CB_TOPOLOGY_MODE=worker \
			PYTHONPATH=src $(CURDIR)/.venv/bin/python -m app.workers.main --type=$$kind & \
		done; \
		wait

migrate: ## Run Alembic DB migrations
	cd $(BACKEND_DIR) && CB_DB_URL="$(CB_DB_URL_DEV)" PYTHONPATH=src $(CURDIR)/.venv/bin/alembic upgrade head

reset-oobe: ## Dev only: rewind to the OOBE first-run wizard (keeps existing users until you finish it again)
	cd $(BACKEND_DIR) && CB_DB_URL="$(CB_DB_URL_DEV)" PYTHONPATH=src $(CURDIR)/.venv/bin/python -m app.scripts.reset_oobe

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

.PHONY: build build-deps build-in-release-image build-release build-from-source release-local release-tag release-retag release-untag docker-build docker-push sign sbom

build: ## Build native app (tarball + deb + rpm + apk + AppImage + .pkg.tar.zst)
	cd $(FRONTEND_DIR) && npm ci && npm run build
	.venv/bin/python scripts/build_native_release.py --clean

build-deps: ## Install build toolchain (nfpm, appimagetool, Python 3.12, Node 20)
	bash scripts/install-build-deps.sh

# A PyInstaller bundle inherits the glibc floor of whatever built it, so `make
# build` on a modern workstation produces packages that will not run on the
# distros in the support matrix -- the deb row failed exactly that way on Debian
# 12. This reproduces the release job's ubuntu-22.04 / Python 3.12 environment so
# the artifact has the floor the released one has. ADR 0005 Phase 3, F8.
build-in-release-image: ## Build packages inside the ubuntu-22.04 image the release job uses
	bash scripts/build-in-release-image.sh

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

release-tag: ## Tag current HEAD as vVERSION (first release of this version — fails if the tag already exists)
	git tag -a "v$$(cat VERSION)" -m "Circuit Breaker v$$(cat VERSION)"
	@echo "Tagged v$$(cat VERSION) -> $$(git rev-parse --short HEAD). Push with: git push origin v$$(cat VERSION)"

release-retag: ## Move an existing vVERSION tag to current HEAD (re-trigger a failed or updated Release run)
	git tag -d "v$$(cat VERSION)"
	git tag -a "v$$(cat VERSION)" -m "Circuit Breaker v$$(cat VERSION)"
	@echo "Retagged v$$(cat VERSION) -> $$(git rev-parse --short HEAD)."
	@echo "Push with:"
	@echo "  git push origin :refs/tags/v$$(cat VERSION)"
	@echo "  git push origin v$$(cat VERSION)"

# Deletes on origin first: that is the copy that matters, and if it is already
# gone this stops before touching the local tag, so nothing claims to have
# removed something it did not. release-retag is the better move when the
# intent is to re-run Release against a new HEAD; this one is for withdrawing
# a tag outright.
release-untag: ## Delete the vVERSION tag on origin and locally (fails if origin has no such tag)
	git push origin ":refs/tags/v$$(cat VERSION)"
	git tag -d "v$$(cat VERSION)" || echo "no local tag v$$(cat VERSION); origin's is gone"
	@echo "Deleted v$$(cat VERSION) on origin."
	@echo "A Release run the tag already started is NOT cancelled, and a published"
	@echo "GitHub Release survives its tag: gh release delete v$$(cat VERSION)"

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
security-check: ## Run security scans (gate mode — fails on HIGH/CRIT)
	./scripts/security_scan.sh --gate

security-report: ## Run full security scan report (non-blocking)
	./scripts/security_scan.sh

.PHONY: lint format test test-db test-backend test-frontend security-check security-report verify-fast verify verify-full verify-fleet verify-fleet-upgrade

# This target is NOT `scripts/ci/tier0-static.sh`, and that is deliberate
# rather than an oversight: lint-staged (root package.json) runs `make lint`
# on every commit that touches a staged .ts/.tsx/.py file, so it has to stay
# ruff+mypy+eslint fast. tier0-static.sh is the definition of record for the
# full Tier 0 gate (ADR 0005) — it also runs the Alembic single-head check,
# the tests/build repo-policy suite and the release-control ledger validator,
# none of which belong on the commit-time path. `make verify-fast` runs that
# script; use it, not this target, when you want the real Tier 0 gate. This
# is a known, accepted third copy of ruff/mypy/eslint's *invocation* (not
# their *pass/fail semantics*, which the tools themselves own) — narrower in
# scope than tier0-static.sh, not a divergent reimplementation of it.
lint: ## Run backend and frontend linters (fast subset for pre-commit; see comment)
	cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff check src/app
	cd $(BACKEND_DIR) && PYTHONPATH=src $(CURDIR)/.venv/bin/mypy src/app
	cd $(FRONTEND_DIR) && npm run lint

format: ## Format backend and frontend code
	cd $(BACKEND_DIR) && $(CURDIR)/.venv/bin/ruff format src/
	cd $(FRONTEND_DIR) && npm run format

test: test-backend test-frontend ## Run all tests natively (provisions the test DB first)

test-db: ## Create the integration test database if it is missing (never drops it)
	$(CURDIR)/.venv/bin/python scripts/ensure_test_db.py "$(CB_TEST_DB_URL)"

# Why the two CB_ALLOW_* flags: the integration suite boots the REAL app lifespan,
# and tests/integration/conftest.py deliberately points NATS at an unreachable port
# so startup fails fast instead of hanging on a broker connect. Production startup
# treats a dead broker — and a missing egress proxy — as fatal, so without these the
# app aborts with "CRITICAL STARTUP FAILED" and every fixture dies in setup. They are
# load-bearing, not leftovers; do not delete them.
test-backend: test-db ## Run backend integration tests natively
	cd $(BACKEND_DIR) && \
		CB_TEST_DB_URL="$(CB_TEST_DB_URL)" \
		CB_ALLOW_DEGRADED_DEPENDENCIES=true \
		CB_ALLOW_DIRECT_EGRESS=true \
		PYTHONPATH=src $(CURDIR)/.venv/bin/pytest ../../tests/integration -q

test-frontend: ## Run frontend unit tests natively
	cd $(FRONTEND_DIR) && npm test

# ADR 0005: the verification ladder. Each target is a thin caller of the script
# GitHub Actions also calls, so "it passed locally" means the same gate ran —
# not a local reimplementation of it.
#
# `verify`'s 4-minute budget is a hard constraint, not a preference: a gate
# slower than the developer's patience gets bypassed, and a bypassed gate is
# worse than no gate at all, because branch protection still reports it
# satisfied. Measured on 2026-08-27, the full Tier 1 (backend suite included,
# CB_VERIFY_BACKEND=shards) took 6m43s — 68% over budget — while Tier 1 with
# the backend suite skipped (CB_VERIFY_BACKEND=off) took 1m46s, 2m14s under
# budget. So `verify` runs with the backend suite off by default; the omission
# is never silent — cb::skipped prints it on every run. The backend suite
# still runs on every push in CI, and locally via `verify-full` when you want
# it. Re-measure before changing this default; don't re-derive it from taste.
#
# Re-measured 2026-08-27 after the govulncheck preflight was fixed: 3m17s, not
# the 1m46s recorded above. The earlier figure was taken on a host where
# security_scan.sh's section 10 could not resolve govulncheck, so it never paid
# for the Go vulnerability scan. 3m17s is still inside the budget, but the
# headroom is 43s rather than 2m14s — the next gate added to Tier 1 has to be
# measured, not assumed to fit.
verify-fast: ## Tier 0 only — static gates (~90s)
	scripts/ci/tier0-static.sh

verify: verify-fast ## Tier 0 + Tier 1 minus the backend suite — the pre-push gate (budget: 4 min, measured 3m17s)
	CB_VERIFY_BACKEND=off scripts/ci/tier1-unit.sh

verify-full: verify-fast ## Tier 0 + full Tier 1 including the backend suite (measured 6m43s)
	CB_VERIFY_BACKEND=shards scripts/ci/tier1-unit.sh

# T3. Not part of `verify` and deliberately not wired into any workflow yet: it
# boots a VM, downloads a 556MB image on first run, and takes minutes, which is
# not a pre-push gate. Phase 2 shipped the install row; Phase 3 adds the upgrade
# and rollback row below, and the remaining formats and architectures after it.
#
# CB_CANDIDATE is required rather than defaulted to a dist/ glob. The claim this
# tier makes is "*this* candidate installs and boots"; a target that tests
# whatever .rpm happened to be lying in dist/ makes that claim about a file whose
# provenance nobody checked, which is #106's defect class wearing different
# clothes.
# CB_ROW selects which matrix row to run. It defaults to the Fedora row the
# first slice built, so the common case stays a one-variable command, but the
# deb rows are reachable without editing the Makefile:
#   make verify-fleet CB_ROW=debian-deb-amd64 CB_CANDIDATE=dist/native/...deb
# dispatch.sh rejects a row whose declared mode does not match the arguments, so
# a mistyped row fails with the reason rather than running the wrong journey.
verify-fleet: ## Tier 3 — install+boot a candidate on an ephemeral VM (CB_CANDIDATE=path/to.rpm|.deb, CB_ROW=matrix row)
	@test -n "$(CB_CANDIDATE)" || { \
	  echo "ERROR: set CB_CANDIDATE to the package under test, e.g."; \
	  echo "  make build && make verify-fleet CB_CANDIDATE=dist/native/circuit-breaker_$$(cat VERSION)_amd64.rpm"; \
	  exit 2; }
	scripts/ci/fleet/dispatch.sh "$(or $(CB_ROW),fedora-rpm-amd64)" "$(CB_CANDIDATE)"

# The other half of the Tier 1 guarantee. Two artifacts, because an upgrade needs
# something to upgrade FROM: the tier installs CB_CANDIDATE_PREVIOUS, boots it,
# seeds a marker, upgrades to CB_CANDIDATE, then executes the documented rollback
# and asserts the pre-upgrade schema and data are back.
#
# CB_CANDIDATE_PREVIOUS is an explicit path for the same reason CB_CANDIDATE is,
# and one more: the two must be genuinely different versions. dnf treats an
# "upgrade" to the identical NEVRA as a no-op and exits zero, so a defaulted or
# mistyped path here would produce a passing run that upgraded nothing. dispatch.sh
# rejects two files with the same name; it cannot tell you the versions inside
# them differ, so build them from two different VERSION values.
verify-fleet-upgrade: ## Tier 3 — upgrade N-1→N and roll back (CB_CANDIDATE=..., CB_CANDIDATE_PREVIOUS=..., CB_ROW=matrix row)
	@test -n "$(CB_CANDIDATE)" || { \
	  echo "ERROR: set CB_CANDIDATE to the package being upgraded TO, e.g."; \
	  echo "  make verify-fleet-upgrade CB_CANDIDATE=dist/native/circuit-breaker_$$(cat VERSION)_amd64.rpm \\"; \
	  echo "                            CB_CANDIDATE_PREVIOUS=/path/to/circuit-breaker_<older>_amd64.rpm"; \
	  exit 2; }
	@test -n "$(CB_CANDIDATE_PREVIOUS)" || { \
	  echo "ERROR: set CB_CANDIDATE_PREVIOUS to the package being upgraded FROM."; \
	  echo "  Build it by checking out the previous tag and running 'make build', or keep"; \
	  echo "  the artifact from the last release. It must be a LOWER version than"; \
	  echo "  CB_CANDIDATE, or dnf will treat the upgrade as a no-op and the row will"; \
	  echo "  pass without having upgraded anything."; \
	  exit 2; }
	scripts/ci/fleet/dispatch.sh "$(or $(CB_ROW),fedora-rpm-amd64-upgrade)" "$(CB_CANDIDATE)" "$(CB_CANDIDATE_PREVIOUS)"
