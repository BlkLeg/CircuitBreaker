```
# Circuit Breaker — Native-First Development Shift

## Context
Circuit Breaker (https://github.com/BlkLeg/circuitbreaker) is currently at v0.2.2. The project is shifting its development philosophy: **native installation is now the primary deployment target**. Docker becomes a co-equal packaging artifact, not the development environment. All future features must have 1:1 parity between native and Docker deployments.

---

## Objective
Refactor the repository structure, startup scripts, and tooling so that:
1. The application runs natively on Linux (systemd) as the primary dev/test target
2. Docker consumes the same shared startup scripts — it is no longer the source of truth
3. A `cb` CLI tool unifies operations across both deployment targets
4. All file paths are parameterized via `CB_DATA_DIR` (no hardcoded `/data/` strings)
5. A Proxmox LXC-aware installer exists as a first-class deployment path

---

## New Repository Structure

Create the following layout. Do not move or rename anything inside `apps/backend/` or `apps/frontend/` — only add the `deploy/`, `config/`, and `cb` artifacts.

```
circuitbreaker/
├── apps/
│   ├── backend/          ← unchanged
│   └── frontend/         ← unchanged
├── deploy/
│   ├── common/
│   │   ├── entrypoint.sh       # Shared startup entry (called by both systemd and supervisord)
│   │   ├── 10-configure.sh     # Resolve config.env → env vars
│   │   ├── 20-migrate.sh       # Alembic migrations (extracted from current Dockerfile)
│   │   ├── 30-vault-init.sh    # Vault key bootstrap
│   │   └── healthcheck.sh      # Hits /api/v1/health, exits 0/1
│   ├── native/
│   │   ├── install.sh          # Full native installer (Debian/Ubuntu primary)
│   │   ├── uninstall.sh
│   │   ├── upgrade.sh
│   │   └── systemd/
│   │       ├── circuitbreaker.target
│   │       ├── circuitbreaker-postgres.service
│   │       ├── circuitbreaker-pgbouncer.service
│   │       ├── circuitbreaker-nats.service
│   │       ├── circuitbreaker-redis.service
│   │       ├── circuitbreaker-backend.service
│   │       ├── circuitbreaker-worker@.service   ← template unit (%i = worker type)
│   │       └── circuitbreaker-nginx.service
│   ├── docker/
│   │   ├── Dockerfile              ← refactored to consume deploy/common/
│   │   ├── supervisord.conf        ← Docker-only process supervisor
│   │   └── docker-compose.yml
│   └── proxmox/
│       ├── lxc-install.sh          ← Proxmox LXC-aware installer
│       └── vm-install.sh
├── config/
│   ├── nginx/
│   │   ├── circuitbreaker.conf     ← path-parameterized, works native + Docker
│   │   └── snippets/
│   ├── pgbouncer/
│   │   └── pgbouncer.ini.template
│   └── nats/
│       └── nats-server.conf.template
├── cb                              ← CLI tool (shell script, detect env, dispatch)
├── Makefile                        ← unified targets for native + Docker
└── install.sh                      ← root shortcut → deploy/native/install.sh
```

---

## Task 1 — Extract `deploy/common/` Scripts

Extract the existing startup logic baked into the Dockerfile into reusable shell scripts under `deploy/common/`. These scripts must be callable by both systemd `ExecStartPre=` directives and supervisord `command=` entries.

### `deploy/common/10-configure.sh`
- Load `/etc/circuitbreaker/config.env` (native) or `/data/.env` (Docker) based on `CB_DEPLOY_MODE` env var
- Export all `CB_*` variables to the process environment
- Validate required variables: `CB_DB_URL`, `CB_VAULT_KEY`, `CB_JWT_SECRET`, `NATS_AUTH_TOKEN`
- Exit 1 with a clear error message if any required variable is missing

### `deploy/common/20-migrate.sh`
- Run `alembic upgrade head` using the venv at `$CB_APP_ROOT/backend/.venv`
- Wait for PostgreSQL to be ready (retry loop, max 30s) before running
- Log migration output to `$CB_LOG_DIR/migrations.log`

### `deploy/common/30-vault-init.sh`
- If `CB_VAULT_KEY` is not set, generate a new Fernet key and persist it to `$CB_DATA_DIR/.vault_key`
- Export `CB_VAULT_KEY` for the current process tree
- Never overwrite an existing key

### `deploy/common/entrypoint.sh`
- Calls 10-configure.sh → 30-vault-init.sh → 20-migrate.sh in sequence
- Used as `ExecStartPre=` in the backend systemd unit
- Also called as the Docker `ENTRYPOINT` before handing off to supervisord

### `deploy/common/healthcheck.sh`
- `curl -sf http://localhost:8000/api/v1/health | grep -q '"status":"healthy"'`
- Exit 0 on success, exit 1 on failure
- Used by Docker `HEALTHCHECK` and by `cb status`

---

## Task 2 — Systemd Units

Create all units under `deploy/native/systemd/`. All units must:
- Run as user `breaker` (UID 1000), group `breaker`
- Load env from `EnvironmentFile=/etc/circuitbreaker/config.env`
- Use `Restart=on-failure` and `RestartSec=5`
- Write logs to journald (no manual log file needed — journald handles it)

### Startup ordering (mirror current supervisord priorities exactly):
1. `circuitbreaker-postgres.service` — `After=network.target`
2. `circuitbreaker-pgbouncer.service` — `After=circuitbreaker-postgres.service`, `Requires=circuitbreaker-postgres.service`
3. `circuitbreaker-nats.service` — `After=network.target`
4. `circuitbreaker-redis.service` — `After=network.target`
5. `circuitbreaker-backend.service` — `After=` all four above, `Requires=` postgres + pgbouncer. `ExecStartPre=/opt/circuitbreaker/deploy/common/entrypoint.sh`
6. `circuitbreaker-worker@.service` — template unit. `After=circuitbreaker-backend.service`. `ExecStart=/opt/circuitbreaker/backend/.venv/bin/python -m app.workers.main --type %i`
7. `circuitbreaker-nginx.service` — `After=circuitbreaker-backend.service`

### `circuitbreaker.target`
```ini
[Unit]
Description=Circuit Breaker
Wants=circuitbreaker-postgres.service \
      circuitbreaker-pgbouncer.service \
      circuitbreaker-nats.service \
      circuitbreaker-redis.service \
      circuitbreaker-backend.service \
      circuitbreaker-worker@discovery.service \
      circuitbreaker-worker@telemetry.service \
      circuitbreaker-worker@webhook.service \
      circuitbreaker-worker@notification.service \
      circuitbreaker-nginx.service

[Install]
WantedBy=multi-user.target
```

---

## Task 3 — Refactor Dockerfile

The Dockerfile must now consume `deploy/common/` rather than duplicating startup logic.

```dockerfile
# Build stages (frontend-builder, backend-builder) remain unchanged

FROM debian:bookworm-slim AS runtime

# Install same system packages as native install.sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-15 pgbouncer redis-server nginx supervisor curl \
    && rm -rf /var/lib/apt/lists/*

# Install NATS server binary
RUN curl -L https://github.com/nats-io/nats-server/releases/download/v2.10.14/nats-server-v2.10.14-linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin --strip-components=1 nats-server-v2.10.14-linux-amd64/nats-server

# Copy application
COPY --from=backend-builder /app/backend /opt/circuitbreaker/backend
COPY --from=frontend-builder /app/frontend/dist /opt/circuitbreaker/frontend

# Copy shared scripts and configs (single source of truth)
COPY deploy/common /opt/circuitbreaker/deploy/common
COPY deploy/docker/supervisord.conf /etc/supervisor/conf.d/circuitbreaker.conf
COPY config/ /opt/circuitbreaker/config/

RUN chmod +x /opt/circuitbreaker/deploy/common/*.sh

ENV CB_DEPLOY_MODE=docker
ENV CB_DATA_DIR=/data
ENV CB_APP_ROOT=/opt/circuitbreaker
ENV CB_LOG_DIR=/data

VOLUME ["/data"]
EXPOSE 8080 8443

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=60s \
    CMD /opt/circuitbreaker/deploy/common/healthcheck.sh

ENTRYPOINT ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
```

### `deploy/docker/supervisord.conf`
Mirror the systemd ordering exactly using supervisord `priority=` values:
- postgres: priority=10
- pgbouncer: priority=15
- nats: priority=20
- redis: priority=25
- backend: priority=30, `command=bash -c "/opt/circuitbreaker/deploy/common/entrypoint.sh && uvicorn ..."`
- worker-discovery: priority=35
- worker-telemetry: priority=35
- worker-webhook: priority=35
- worker-notification: priority=35
- nginx: priority=40

---

## Task 4 — Path Abstraction

### Audit and fix all hardcoded `/data/` paths
Search `apps/backend/src/` for any hardcoded `/data/` path strings. Replace every instance with a settings variable.

In `apps/backend/src/app/core/config.py`, add/ensure these fields exist on the `Settings` Pydantic model:

```python
class Settings(BaseSettings):
    # Deployment
    deploy_mode: str = Field("docker", env="CB_DEPLOY_MODE")  # "docker" | "native"
    
    # Path roots — all other paths derive from these
    data_dir: Path = Field(Path("/data"), env="CB_DATA_DIR")
    app_root: Path = Field(Path("/opt/circuitbreaker"), env="CB_APP_ROOT")
    log_dir: Path = Field(None, env="CB_LOG_DIR")  # defaults to data_dir
    
    # Derived paths (computed properties, not env vars)
    @property
    def postgres_data_dir(self) -> Path:
        return self.data_dir / "postgres"
    
    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"
    
    @property
    def tls_dir(self) -> Path:
        return self.data_dir / "tls"
    
    @property
    def vault_key_path(self) -> Path:
        return self.data_dir / ".vault_key"
    
    @property
    def effective_log_dir(self) -> Path:
        return self.log_dir or self.data_dir
```

Every service and worker that references file paths must import `settings` from `app.core.config` and use these properties. No raw string paths.

---

## Task 5 — Native `install.sh`

Create `deploy/native/install.sh` for Debian/Ubuntu. It must:

1. Check for root / sudo
2. Detect OS (Debian 12 / Ubuntu 22.04+ supported, warn otherwise)
3. Create system user: `useradd -r -m -s /bin/bash -u 1000 breaker`
4. Install system packages: `postgresql-15 pgbouncer redis-server nginx supervisor python3.12 python3.12-venv nodejs npm`
5. Install NATS server binary to `/usr/local/bin/nats-server`
6. Create directory layout:
   - `/opt/circuitbreaker/` (owned by breaker)
   - `/etc/circuitbreaker/` (owned by root, readable by breaker)
   - `/var/lib/circuitbreaker/` (owned by breaker)
   - `/var/log/circuitbreaker/` (owned by breaker)
7. Copy application files to `/opt/circuitbreaker/`
8. Create Python venv at `/opt/circuitbreaker/backend/.venv` and install requirements
9. Build frontend: `npm ci && npm run build` → copy dist to `/opt/circuitbreaker/frontend/`
10. Generate config at `/etc/circuitbreaker/config.env` with sane defaults, prompting for:
    - Admin email
    - Admin password
    - Port (default 8080)
    - Data directory (default `/var/lib/circuitbreaker`)
11. Run `deploy/common/30-vault-init.sh` to generate vault key
12. Install and enable systemd units from `deploy/native/systemd/`
13. Configure nginx from `config/nginx/circuitbreaker.conf` (substitute paths)
14. Configure pgbouncer from `config/pgbouncer/pgbouncer.ini.template`
15. Initialize PostgreSQL cluster and create `breaker` DB user + `circuitbreaker` database
16. Run `deploy/common/20-migrate.sh` (first-time schema creation)
17. `systemctl enable --now circuitbreaker.target`
18. Run `deploy/common/healthcheck.sh` and print success/failure

---

## Task 6 — `cb` CLI Tool

Create `cb` as a POSIX shell script at the repo root. Install it to `/usr/local/bin/cb` during native install, and add it to the Docker image at `/usr/local/bin/cb`.

The script auto-detects deployment mode:
```sh
detect_mode() {
    if systemctl is-active circuitbreaker-backend.service &>/dev/null 2>&1; then
        echo "native"
    elif docker ps --filter name=circuitbreaker -q 2>/dev/null | grep -q .; then
        echo "docker"
    else
        echo "unknown"
    fi
}
```

### Required commands:

| Command | Native behavior | Docker behavior |
|---|---|---|
| `cb start` | `systemctl start circuitbreaker.target` | `docker compose up -d` |
| `cb stop` | `systemctl stop circuitbreaker.target` | `docker compose down` |
| `cb restart` | `systemctl restart circuitbreaker.target` | `docker compose restart` |
| `cb status` | `systemctl status circuitbreaker-*.service` + healthcheck | `docker compose ps` + healthcheck |
| `cb logs [-f] [svc]` | `journalctl -u circuitbreaker-$svc` | `docker compose logs [-f] circuitbreaker` |
| `cb upgrade [ver]` | run `deploy/native/upgrade.sh` | pull new image + recreate |
| `cb backup` | `pg_dump` → `$CB_DATA_DIR/backups/cb_$(date +%Y%m%d).sql` | same via `docker exec` |
| `cb restore <file>` | `psql < file` | same via `docker exec` |
| `cb config set K=V` | append/replace in `/etc/circuitbreaker/config.env` | append to `$CB_DATA_DIR/.env` |
| `cb config get K` | grep config.env | grep .env |
| `cb migrate` | run `deploy/common/20-migrate.sh` | `docker exec ... alembic upgrade head` |
| `cb shell` | `psql -U breaker circuitbreaker` | `docker exec -it ... psql ...` |

---

## Task 7 — Proxmox LXC Installer

Create `deploy/proxmox/lxc-install.sh`. This script runs **on the Proxmox host** (not inside the LXC).

It must:
1. Accept `--vmid`, `--storage`, `--hostname` flags (with sane defaults)
2. Download or use a cached Debian 12 CT template
3. Create the LXC with `pct create`:
   - Unprivileged container
   - `lxc.cap.keep: net_raw` in the LXC config (needed for ARP scanning)
   - Bind mount a Proxmox storage path to `/var/lib/circuitbreaker` inside the CT
   - 2 CPU cores, 2GB RAM minimum
4. Start the container and wait for network
5. `pct exec $VMID -- bash -c "curl -fsSL <url>/deploy/native/install.sh | bash"`
6. Print the container IP and access URL on completion

---

## Task 8 — Makefile Targets

Update the `Makefile` to treat native as the primary dev workflow:

```makefile
# Native development (primary)
dev-deps:        ## Install system deps for native dev (Debian/Ubuntu)
dev-init:        ## Init local DB, run migrations, create admin user
dev:             ## Start native dev servers (uvicorn --reload + vite + workers)
dev-stop:        ## Stop native dev servers

# Testing (native, no Docker required)
test:            ## Run all tests (backend + frontend)
test-backend:    ## pytest against local postgres
test-frontend:   ## vitest

# Build artifacts
build-frontend:  ## npm ci && npm run build
build-docker:    ## Build Docker image (consumes deploy/common/)
build-all:       ## build-frontend + build-docker

# Docker (packaging/distribution, not dev)
docker-up:       ## docker compose up -d
docker-down:     ## docker compose down
docker-logs:     ## docker compose logs -f

# Native install testing
test-install:    ## Spin up bare Debian container, run install.sh, hit /health
```

---

## Config Templates

### `config/nginx/circuitbreaker.conf`
Parameterize these values (substituted by install.sh using `envsubst`):
- `CB_PORT` (default 8080)
- `CB_SSL_PORT` (default 8443)  
- `CB_DATA_DIR` (for TLS cert paths)
- `CB_APP_ROOT` (for static file root)

The template must be functionally identical between native and Docker deployments.

### `config/pgbouncer/pgbouncer.ini.template`
Substitute:
- `CB_DB_USER`
- `CB_DB_NAME`
- `CB_DATA_DIR` (for unix socket path)

### `config/nats/nats-server.conf.template`
Substitute:
- `NATS_AUTH_TOKEN`
- `CB_DATA_DIR` (for JetStream storage path)
- `NATS_TLS` (enable/disable TLS block)

---

## Environment Variables (Canonical List)

Add these to `docker/.env.example` and document in `deploy/native/install.sh`:

```bash
# Deployment
CB_DEPLOY_MODE=native           # "native" | "docker"
CB_PORT=8080
CB_SSL_PORT=8443

# Paths (native defaults shown; Docker uses /data)
CB_DATA_DIR=/var/lib/circuitbreaker
CB_APP_ROOT=/opt/circuitbreaker
CB_LOG_DIR=/var/log/circuitbreaker

# Database
CB_DB_URL=postgresql+asyncpg://breaker:password@localhost:6432/circuitbreaker
CB_DB_POOL_SIZE=10
CB_DB_MAX_OVERFLOW=10

# Security
CB_VAULT_KEY=                   # Auto-generated by 30-vault-init.sh if empty
CB_JWT_SECRET=                  # Auto-generated if empty
CB_AUTH_ENABLED=true

# NATS
NATS_AUTH_TOKEN=                # Required
NATS_URL=nats://localhost:4222
NATS_TLS=false

# Workers
CB_WORKER_TYPES=discovery,telemetry,webhook,notification
```

---

## Acceptance Criteria

The implementation is complete when all of the following are true:

- [ ] `make dev` starts the full application stack natively (no Docker) and the app is usable at `http://localhost:8080`
- [ ] `deploy/native/install.sh` runs to completion on a fresh Debian 12 VM and `/api/v1/health` returns `{"status":"healthy"}`
- [ ] `deploy/proxmox/lxc-install.sh` creates a working LXC container on a Proxmox host
- [ ] `make build-docker` produces a working Docker image where supervisord calls `deploy/common/entrypoint.sh` before starting the backend
- [ ] `docker compose up` on the new image passes all existing healthchecks
- [ ] No hardcoded `/data/` strings exist anywhere in `apps/backend/src/` (grep confirms zero matches)
- [ ] `cb start`, `cb stop`, `cb status`, `cb logs`, `cb backup` all work in both native and Docker modes
- [ ] All existing backend tests pass in native dev mode (`make test-backend`)
- [ ] All existing frontend tests pass (`make test-frontend`)
- [ ] `make test-install` passes (bare Debian container, install from scratch, health check green)
```