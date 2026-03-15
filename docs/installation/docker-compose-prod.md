# Docker Compose — Prebuilt Full Stack

Deploy Circuit Breaker with the standard prebuilt Docker stack from GHCR. No clone or build required and it matches the supported experience delivered by the quick installer.

This is the manual equivalent of the quick installer: same full capability, same discovery and worker support, and the same recommended Docker experience.

---

## Prerequisites

- Linux (macOS/Windows with Docker Desktop also supported)
- **Docker Engine 20+** with Compose plugin v2
- Ports **80** and **443** available (nginx in container)
- Outbound internet access to pull from `ghcr.io`

---

## Quick Start

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

If the interactive installer asks which Docker path to use, choose the full Docker or Compose option.

Non-interactive:

```bash
CB_MODE=compose CB_YES=1 curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

### Manual setup

```bash
# 1. Create install directory
mkdir -p ~/.circuitbreaker && cd ~/.circuitbreaker

# 2. Download compose and env template
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/.env.example -o .env
# Edit .env: CB_DB_PASSWORD, CB_VAULT_KEY, CB_JWT_SECRET, NATS_AUTH_TOKEN

# 3. Edit .env, then start the standard stack
docker compose up -d
```

Access at **http://localhost** or **https://localhost** (self-signed cert at first run). Trust the certificate when prompted.

---

## Tagged releases

Pin to a specific version:

```bash
CB_TAG=v1.2.0 curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Or with manual setup:

```bash
CB_TAG=v1.2.0 docker compose up -d
```

---

## Upgrade

```bash
cd ~/.circuitbreaker
docker compose pull
docker compose up -d
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
