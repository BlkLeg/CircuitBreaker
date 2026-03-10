# Docker Compose — Prebuilt Full Stack

Deploy Circuit Breaker with the full compose stack (backend, frontend, workers, Caddy, NATS) using prebuilt GHCR images. No clone or build required—typically completes in under 60 seconds.

This mode provides full capability: discovery workers, webhooks, notifications, and HTTPS via Caddy.

---

## Prerequisites

- Linux (macOS/Windows with Docker Desktop also supported)
- **Docker Engine 20+** with Compose plugin v2
- Ports **80** and **443** available (Caddy)
- Outbound internet access to pull from `ghcr.io`

---

## Quick Start

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Choose **option 2 (Compose stack)** when prompted.

Non-interactive:

```bash
CB_MODE=compose CB_YES=1 curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

### Manual setup

```bash
# 1. Create install directory
mkdir -p ~/.circuit-breaker && cd ~/.circuit-breaker

# 2. Download compose files
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/docker-compose.prod.yml -o docker-compose.prod.yml
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/Caddyfile -o Caddyfile
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/.env.example -o .env

# 3. Start stack
docker compose -f docker-compose.prod.yml up -d
```

Access at **https://localhost** or **https://\<host-ip\>**. Trust the Caddy CA when prompted.

---

## Tagged releases

Pin to a specific version:

```bash
CB_TAG=v1.2.0 curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Or with manual setup:

```bash
CB_TAG=v1.2.0 docker compose -f docker-compose.prod.yml up -d
```

---

## Upgrade

```bash
cd ~/.circuit-breaker
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Or use the `cb` command (after `install.sh`):

```bash
cb update
```

---

## Environment variables

Edit `.env` in the install directory:

| Variable | Default | Description |
|----------|---------|-------------|
| `CB_TAG` | `latest` | Image tag suffix (e.g. `v1.2.0` → `backend-v1.2.0`) |
| `CB_VAULT_KEY` | (empty) | Fernet key for credential vault; auto-generated at OOBE if empty |
| `CB_DOMAIN` | `circuitbreaker.local` | Domain Caddy listens on |
| `CB_TLS_EMAIL` | (empty) | Required for ACME/Let's Encrypt on public domains |
| `CB_LOCAL_CERTS` | `local_certs` | Use local CA for `.local` / LAN |

---

## What gets deployed

| Service | Image | Role |
|---------|-------|------|
| backend | `ghcr.io/blkleg/circuitbreaker:backend-*` | FastAPI app |
| frontend | `ghcr.io/blkleg/circuitbreaker:frontend-*` | React SPA (nginx) |
| worker | same as backend | Discovery (2 replicas) |
| webhook-worker | same as backend | Webhook dispatch |
| notification-worker | same as backend | Alerts/notifications |
| caddy | `caddy:2-alpine` | Reverse proxy, HTTPS |
| nats | `nats:2-alpine` | Message broker |

---

## Useful commands

```bash
# Status
cb status

# Logs
cb logs -f

# Restart
cb restart

# Update
cb update
# or: docker compose -f ~/.circuit-breaker/docker-compose.prod.yml pull && docker compose up -d

# Uninstall
cb uninstall
```

---

## Next steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)**.
- For remote access — see [Remote Access & Tunnels](../remote-access.md).
