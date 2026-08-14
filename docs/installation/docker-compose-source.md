# Docker Compose — From Source

Build and run Circuit Breaker locally from the Git repository. Use this method if you want to modify the source code, contribute to development, or build your own image.

---

## Prerequisites

- Linux (macOS and Windows with Docker Desktop also supported)
- **Docker Engine 20+** with Compose plugin v2
- **Git**
- Outbound internet access to pull base images during build

---

## Clone and Start

```bash
# 1. Clone the repository
git clone https://github.com/BlkLeg/circuitbreaker.git
cd circuitbreaker

# 2. Copy the environment file and fill in the required secrets
cp .env.example .env

# 3. Build the image and start the container
docker compose up -d --build
```

Before starting, set these four values in `.env` — compose refuses to start without them:

| Variable | Notes |
|---|---|
| `CB_JWT_SECRET` | At least 32 characters. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `CB_VAULT_KEY` | Generate: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `CB_DB_PASSWORD` | Password for the embedded Postgres `breaker` role |
| `NATS_AUTH_TOKEN` | At least 32 characters. Generate: `openssl rand -base64 32` |

The first build takes a few minutes — it compiles the frontend bundle and installs Python dependencies.

To build the image without starting anything:

```bash
make docker-build
```

That runs `docker build -f Dockerfile.mono` and tags the result with the contents of `VERSION`.

---

## What Gets Built

The root `docker-compose.yml` builds one service, `circuitbreaker`, from `Dockerfile.mono`. That single image runs Postgres, PgBouncer, Redis, NATS, the backend API, the workers and nginx under supervisord.

| Container port | Role |
|---|---|
| `8080` | HTTP — redirects to HTTPS (the health endpoint is exempt) |
| `8443` | HTTPS — the application |

Published on the host as `${CB_PORT:-80}` and `${CB_PORT_HTTPS:-443}`.

---

## Accessing the UI

```
https://localhost/
```

The entrypoint generates a self-signed certificate at `/data/tls/` on first start, so your browser will warn. Replace `fullchain.pem` and `privkey.pem` in the data directory with your own certificate and restart to get rid of the warning.

Data lives in `${CB_DATA_DIR:-./circuitbreaker-data}` in the repository root, bind-mounted at `/data`.

---

## Useful Commands

```bash
# Start (build if needed)
docker compose up -d --build

# View logs
docker compose logs -f

# Rebuild after a code change
docker compose up -d --build

# Stop the container (data directory untouched)
docker compose down

# Build the image without starting it
make docker-build
```

---

## Development Workflow

For active frontend or backend development, use the hot-reload dev mode instead of the container:

```bash
# One-time: create the virtualenv and install npm packages
make install

# Start Postgres, Redis and NATS for development (docker-compose.deps.yml)
make deps-up

# Start backend (port 8000) + frontend Vite dev server (port 5173) + monitor workers
make dev

# Backend only
make backend

# Frontend only
make frontend

# Stop dev servers
make stop

# Stop and wipe the dev dependency containers
make deps-down
```

In dev mode the frontend proxies API calls to `http://localhost:8000`. There is no TLS in this mode — access at `http://localhost:5173`.

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
