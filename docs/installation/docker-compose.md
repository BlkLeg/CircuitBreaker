# Docker Compose Installation

Deploy Circuit Breaker as a full stack using Docker Compose. Includes Caddy reverse proxy (automatic HTTPS), background workers, and NATS message broker. No local build required — all images are pulled from GHCR.

---

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

Non-interactive:

```bash
CB_YES=1 curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

This mode is compose-only: it never runs the native/systemd installer path. It auto-detects Docker, installs Docker (engine + compose plugin) only when missing, downloads `docker-compose.yml`, `docker/docker-compose.socket.yml`, and `.env.example` to `~/.circuitbreaker/`, creates `.env` with generated secrets (if absent), then starts the stack.

**Access at:** `http://<host>:8088` (HTTP) or `https://<domain>` (with Caddy HTTPS configured)

---

## Prerequisites

- Linux (amd64 or arm64)
- **Docker Engine 20+** with Compose plugin v2 (`docker compose` — not legacy `docker-compose`)
- Outbound internet access to pull from `ghcr.io`

Check your Compose version:

```bash
docker compose version
# Docker Compose version v2.x.x
```

---

## Services

The full stack runs the following services:

| Service | Image | Role |
|---|---|---|
| `backend` | `ghcr.io/blkleg/circuitbreaker:backend-*` | FastAPI application |
| `frontend` | `ghcr.io/blkleg/circuitbreaker:frontend-*` | React SPA (served via nginx) |
| `worker` | same as backend | Discovery workers (2 replicas) |
| `webhook-worker` | same as backend | Webhook dispatch |
| `notification-worker` | same as backend | Alerts and notifications |
| `caddy` | `caddy:2-alpine` | Reverse proxy, automatic HTTPS |
| `nats` | `nats:2-alpine` | Internal message broker |

Optional:

| Profile | Service | Role |
|---|---|---|
| `--profile pg` | `postgres` | PostgreSQL (instead of SQLite) |

---

## Environment Variables

Configure via `.env` in the install directory (`~/.circuitbreaker/.env`):

| Variable | Default | Description |
|---|---|---|
| `CB_DOMAIN` | `circuitbreaker.local` | Domain Caddy listens on |
| `CB_TLS_EMAIL` | _(empty)_ | Required for ACME/Let's Encrypt on public domains |
| `CB_LOCAL_CERTS` | `local_certs` | Use local CA for `.local` / LAN hostnames |
| `CB_DB_URL` | `sqlite:////data/app.db` | Database URL (override for PostgreSQL) |
| `CB_VAULT_KEY` | _(empty)_ | Fernet key for credential vault; auto-generated at OOBE if empty |
| `CB_DB_PASSWORD` | _(empty)_ | PostgreSQL password (used with `--profile pg`) |
| `NATS_AUTH_TOKEN` | _(empty)_ | NATS authentication token |
| `NATS_TLS` | `false` | Enable TLS for NATS connections |
| `DB_POOL_SIZE` | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `20` | SQLAlchemy max overflow connections |

---

## Persistence

| Volume / Mount | Contents |
|---|---|
| `backend-data` (named volume) | Database (`app.db`), vault key, uploads |
| `caddy_data` (named volume) | Caddy TLS certificates and state |
| `nats_data` (named volume) | NATS JetStream state |
| `postgres_data` (named volume) | PostgreSQL data (with `--profile pg`) |
| `./icons/` (bind mount) | Custom icons synced into containers |
| `./branding/` (bind mount) | Custom branding assets |

Data volumes survive `docker compose down`. To wipe all data: `docker compose down -v`.

---

## Caddy HTTPS

Caddy handles HTTPS automatically:

- **LAN / `.local` hostnames:** Caddy generates a local CA and issues a self-signed certificate. You must trust the CA certificate in your browser and OS.
- **Public domains:** Set `CB_TLS_EMAIL` to enable ACME/Let's Encrypt. No manual certificate management needed.

### Trusting the local CA certificate

After first start, download the CA cert from Caddy:

```bash
curl -k https://<host>/api/caddy/ca -o caddy-local-ca.crt
```

**Linux (system-wide):**

```bash
sudo cp caddy-local-ca.crt /usr/local/share/ca-certificates/caddy-local-ca.crt
sudo update-ca-certificates
```

**macOS:**

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-local-ca.crt
```

**Windows:** Double-click the `.crt` file → Install Certificate → Local Machine → Trusted Root Certification Authorities.

**Firefox:** Preferences → Privacy & Security → Certificates → View Certificates → Authorities → Import.

---

## ARP Scanning

ARP scanning lets the discovery engine resolve MAC addresses and detect hosts more reliably. It requires elevated Linux capabilities.

Add to `docker-compose.yml` for the `backend` and `worker` services:

```yaml
cap_add:
  - NET_RAW
  - NET_ADMIN
network_mode: host
```

> **Docker Desktop limitation:** `network_mode: host` does not work on Docker Desktop for macOS or Windows. ARP scanning is only available on native Linux installs.

Without these capabilities, Circuit Breaker falls back to nmap TCP/ICMP scanning — all other scan types (SNMP, HTTP, Proxmox) work without them.

---

## Docker Socket (Container Discovery)

To enable Circuit Breaker to discover containers running on the Docker host, mount the Docker socket using the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.socket.yml up -d
```

This bind-mounts `/var/run/docker.sock` into the backend container with read-only access. Only enable this if you trust the Circuit Breaker application with socket access.

---

## Manual Setup (without the install script)

```bash
# 1. Create install directory
mkdir -p ~/.circuitbreaker && cd ~/.circuitbreaker

# 2. Download compose file and env template
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/.env.example -o .env

# 3. Edit .env — set CB_VAULT_KEY, NATS_AUTH_TOKEN, and CB_DOMAIN at minimum
nano .env

# 4. Start the stack
docker compose up -d
```

---

## Useful Commands

```bash
# Start (detached)
docker compose up -d

# View logs
docker compose logs -f

# Stop without removing data
docker compose down

# Update to latest images
docker compose pull && docker compose up -d

# Remove containers and all data
docker compose down -v
```

Or use the `cb` CLI if installed:

```bash
cb status
cb logs -f
cb update
cb restart
cb uninstall
```

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
- For remote access over the internet — see [Remote Access & Tunnels](../remote-access.md).
