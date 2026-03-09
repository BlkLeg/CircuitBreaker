# Docker Compose — From Source

Build and run Circuit Breaker locally from the Git repository. Use this method if you want to modify the source code, contribute to development, or build your own custom image.

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

# 2. Copy the environment file
cp .env.example .env

# 3. Build images and start all services
docker compose -f docker/docker-compose.yml up -d --build
```

Or using the Makefile shortcut:

```bash
make compose-up
```

The first build takes a few minutes — it compiles the frontend bundle and installs Python dependencies. Subsequent starts are fast.

---

## What Gets Built

The `docker/docker-compose.yml` file builds these services from source:

| Service | Role | Port (internal) |
|---|---|---|
| `caddy` | Reverse proxy — HTTPS, routing | 80, 443 |
| `backend` | FastAPI application | 8000 |
| `frontend` | React app served by nginx | 8080 |
| `worker` | Discovery worker (2 replicas) | — |
| `webhook-worker` | Webhook dispatch worker | — |
| `notification-worker` | Alert/notification worker | — |
| `nats` | NATS JetStream message bus | 4222 |

All services share the `circuitbreaker` bridge network. Caddy routes external traffic to frontend and backend.

---

## Accessing the UI

By default Caddy binds to ports 80 and 443 and serves at:

```
https://circuitbreaker.local
```

You will need to trust the self-signed CA certificate. See [Trusting the CA Certificate](configuration.md#trusting-the-self-signed-ca-certificate).

To add the domain to your hosts file (Linux/macOS):

```bash
echo "127.0.0.1 circuitbreaker.local" | sudo tee -a /etc/hosts
```

Or extract and trust the CA automatically with:

```bash
make trust-ca
```

---

## Optional Profiles

### PostgreSQL (instead of SQLite)

```bash
docker compose -f docker/docker-compose.yml --profile pg up -d --build
```

Set `CB_DB_PASSWORD` in `.env` before starting if you want a custom password (default: `breaker`).

### Cloudflare Tunnel

```bash
docker compose -f docker/docker-compose.yml --profile tunnel up -d
```

Requires `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. See [Remote Access & Tunnels](../remote-access.md).

---

## Environment File

Edit `.env` in the repository root to configure the stack:

```bash
# .env
CB_VAULT_KEY=          # Leave blank to auto-generate during OOBE
CB_DB_PASSWORD=breaker # PostgreSQL password (--profile pg only)
CB_DOMAIN=circuitbreaker.local
CB_TLS_EMAIL=          # Required for public ACME/Let's Encrypt certs
```

See the full variable list in the [Configuration Reference](configuration.md).

---

## Useful Commands

```bash
# Start all services (build if needed)
docker compose -f docker/docker-compose.yml up -d --build

# View logs for all services
docker compose -f docker/docker-compose.yml logs -f

# Rebuild a single service after a code change
docker compose -f docker/docker-compose.yml up -d --build backend

# Stop without removing volumes
docker compose -f docker/docker-compose.yml down

# Wipe everything and start fresh
make compose-fresh

# Pre-build all images without starting
make docker-build
```

---

## Development Workflow

For active frontend or backend development, use the hot-reload dev mode instead of the full compose stack:

```bash
# Start backend (port 8000) + frontend Vite dev server (port 5173)
make dev

# Backend only
make backend

# Frontend only
make frontend

# Stop dev servers
make stop
```

In dev mode the frontend proxies API calls to `http://localhost:8000`. No Caddy/TLS in this mode — access at `http://localhost:5173`.

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
