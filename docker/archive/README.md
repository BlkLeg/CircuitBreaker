# Archived Compose files (pre–mono)

These files are **deprecated**. Circuit Breaker now uses a **single-container (mono)** deployment only.

- **Current deployment:** Use [`docker-compose.yml`](../docker-compose.yml) or the root `docker compose up` (which includes it). One image: `ghcr.io/blkleg/circuitbreaker:mono-<tag>` (Postgres + NATS + backend + workers + nginx in one container).
- **Install:** `install-mono.sh` or `curl -fsSL .../install-mono.sh | CB_DB_PASSWORD=... CB_VAULT_KEY=... bash`

Archived files (kept for reference or local dev from source):

| File | Description |
|------|-------------|
| `docker-compose-source.yml` | Multi-service stack built from source (postgres, nats, caddy, backend, workers, frontend). Use from repo root with `docker compose -f docker/archive/docker-compose-source.yml up -d` if you need to run from source. |
| `docker-compose.prod.yml` | Multi-container production stack with prebuilt backend/frontend images (Caddy, separate postgres/nats/workers). Replaced by mono. |
| `docker-compose.prebuilt.yml` | Single prebuilt image (old unified app image, SQLite, port 8080). Replaced by mono. |
| `docker-compose.docker-socket.yml` | Override to mount Docker socket for Docker-aware discovery. For mono, mount when running: `-v /var/run/docker.sock:/var/run/docker.sock:ro`. |
| `docker-compose.dev-db.yml` | Override to expose Postgres on host 5432 for local migrations. Mono runs Postgres inside the container; use `docker exec circuitbreaker pg_isready ...` or run migrations via the app. |
