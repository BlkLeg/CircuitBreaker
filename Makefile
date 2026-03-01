BACKEND_PORT  := 8000
FRONTEND_PORT := 5173
BACKEND_DIR   := backend
FRONTEND_DIR  := frontend

.PHONY: dev stop backend frontend docs docs-build test frontend-build docker-build preflight help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

dev: stop ## Kill stale processes then start backend + frontend
	@echo "Starting backend  → http://localhost:$(BACKEND_PORT)"
	@cd $(BACKEND_DIR) && .venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT) &
	@echo "Starting frontend → http://localhost:$(FRONTEND_PORT)"
	@cd $(FRONTEND_DIR) && npm start &

stop: ## Kill any process holding the dev ports
	@lsof -ti tcp:$(BACKEND_PORT)  | xargs kill -9 2>/dev/null || true
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Ports $(BACKEND_PORT) and $(FRONTEND_PORT) cleared."

backend: ## Kill port $(BACKEND_PORT) and restart the backend (foreground)
	@lsof -ti tcp:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	cd $(BACKEND_DIR) && .venv/bin/uvicorn app.main:app --reload --port $(BACKEND_PORT)

frontend: ## Kill port $(FRONTEND_PORT) and restart the frontend (foreground)
	@lsof -ti tcp:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	cd $(FRONTEND_DIR) && npm start

docs: ## Serve docs locally with Zensical
	.venv/bin/zensical serve

docs-build: ## Build docs with Zensical
	.venv/bin/zensical build

test: ## Run backend tests
	cd $(BACKEND_DIR) && ../.venv/bin/pytest -q

frontend-build: ## Build frontend production bundle
	cd $(FRONTEND_DIR) && npm ci && npm run build

docker-build: ## Build primary beta image
	docker build -t circuit-breaker:beta .

compose-up: ## Tear down stale containers, rebuild, and start docker compose stack (port 8080)
	docker compose -f docker/docker-compose.yml down
	docker compose -f docker/docker-compose.yml up --build -d

compose-down: ## Stop and remove docker compose stack
	docker compose -f docker/docker-compose.yml down

preflight: test frontend-build docker-build ## Run tonight-safe preflight checks
	@echo "Preflight command set completed. See PRE_PKG.md for manual matrix/signoff steps."
