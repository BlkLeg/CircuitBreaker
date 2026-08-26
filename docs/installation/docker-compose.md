# Docker Compose Installation

Deploy Circuit Breaker with Docker Compose. The compose file runs a single container built from the mono image — Postgres, Redis, NATS, the backend, the workers and nginx all run inside it. No local build required; the image is pulled from GHCR.

---

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

This mode is compose-only: it never runs the native/systemd installer path. It auto-detects Docker, installs Docker (engine + compose plugin) only when missing, downloads `docker-compose.yml`, `docker/docker-compose.socket.yml`, and `.env.example` to `~/.circuitbreaker/`, creates `.env` with generated secrets (if absent), then starts the stack.

Add `--version <version>` to pin the install: the compose file, the root helper daemon and the image all come from that release rather than from `main` and `:latest`. The generated `.env` holds the vault key, the JWT secret and the database password, so it is created `0600` inside `~/.circuitbreaker/`, which is created `0700`. An existing `.env` is never overwritten — the installer keeps it, tightens it to `0600`, and tells you to set `CB_TAG` yourself if you asked for a version.

**Access at:** `https://<host>/`. Port 80 serves a redirect to HTTPS, so use the HTTPS URL — account creation requires a secure context.

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

The compose file defines one service:

| Service | Image | Role |
|---|---|---|
| `circuitbreaker` | `ghcr.io/blkleg/circuitbreaker:latest` | Mono image — Postgres, PgBouncer, Redis, NATS, backend, workers and nginx under supervisord |

Published ports are `${CB_PORT:-80}:8080` (HTTP redirect) and `${CB_PORT_HTTPS:-443}:8443` (application).

To pin a release, set `CB_TAG=<version>` in `.env` — the image line resolves to `${CB_IMAGE:-ghcr.io/blkleg/circuitbreaker:${CB_TAG:-latest}}`. Only `:<version>` and `:latest` tags are published. On a first install, `install.sh --docker --version <version>` writes that `CB_TAG` for you.

---

## Environment Variables

Configure via `.env` in the install directory (`~/.circuitbreaker/.env`).

Required — the stack refuses to start without them:

| Variable | Description |
|---|---|
| `CB_DB_PASSWORD` | Password for the embedded Postgres `breaker` role |
| `CB_VAULT_KEY` | Fernet key for the credential vault |
| `CB_JWT_SECRET` | Session/token signing secret; at least 32 characters |
| `NATS_AUTH_TOKEN` | Internal NATS bus auth; at least 32 characters |

Optional:

| Variable | Default | Description |
|---|---|---|
| `CB_PORT` | `80` | Host port mapped to the container's HTTP redirect listener |
| `CB_PORT_HTTPS` | `443` | Host port mapped to the container's HTTPS listener |
| `CB_DATA_DIR` | `./circuitbreaker-data` | Host directory bind-mounted at `/data` |
| `CB_TAG` / `CB_IMAGE` | `latest` | Image tag, or a full image reference |
| `CB_REDIS_URL` | _(empty — uses the embedded Redis)_ | External Redis URL |
| `CB_RATE_LIMIT_STORAGE_URL` | _(empty)_ | Separate storage backend for rate limits |
| `CB_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Networks allowed to set forwarded headers |
| `CB_EGRESS_PROXY_URL` | _(empty)_ | Forward proxy for outbound HTTP |
| `CB_ALLOW_DIRECT_EGRESS` | `true` | Run without a forward proxy |
| `CB_ALLOW_DEGRADED_DEPENDENCIES` | `false` | Break-glass: waives every dependency gate |
| `CB_AIRGAP` | `false` | Disable outbound calls to the internet |
| `CB_DOCKER_HOST` | _(empty)_ | Docker API endpoint for container discovery |

`CB_ALLOW_DIRECT_EGRESS=true` is the compose default because most homelab hosts have no forward proxy. It waives only the `CB_EGRESS_PROXY_URL` requirement — SSRF and outbound URL policy still apply, and Redis, NATS, rate-limit storage and secrets still fail closed. Set `CB_EGRESS_PROXY_URL` and `CB_ALLOW_DIRECT_EGRESS=false` to force outbound traffic through a proxy. See the [Configuration Reference](configuration.md).

---

## Persistence

| Mount | Contents |
|---|---|
| `${CB_DATA_DIR:-./circuitbreaker-data}` → `/data` | Postgres data, NATS and Redis state, uploads, TLS certificates, vault key |
| `/run/circuitbreaker` → `/run/circuitbreaker` | Socket for the optional host-side helper daemon; harmless if not installed |

There are no named volumes — everything lives in the data directory next to `docker-compose.yml`, so `docker compose down` never touches it. To wipe all data, delete that directory.

---

## HTTPS

The mono image terminates TLS itself with the nginx it bundles. On first start the entrypoint generates a self-signed certificate at `/data/tls/fullchain.pem` and `/data/tls/privkey.pem` (365 days) if none is present, so your browser will warn on first visit.

To use your own certificate, replace those two files in the data directory and restart:

```bash
docker compose restart
```

---

## ARP Scanning

ARP scanning lets the discovery engine resolve MAC addresses and detect hosts more reliably. It requires elevated Linux capabilities.

The compose file already grants `NET_RAW` to the `circuitbreaker` service. For full ARP visibility on the host LAN, add `NET_ADMIN` and host networking to that service:

```yaml
cap_add:
  - NET_ADMIN
network_mode: host
```

> **Docker Desktop limitation:** `network_mode: host` does not work on Docker Desktop for macOS or Windows. ARP scanning is only available on native Linux installs.

Without these capabilities, Circuit Breaker falls back to nmap TCP/ICMP scanning — all other scan types (SNMP, HTTP, Proxmox) work without them.

---

## Docker Socket (Container Discovery)

To enable Circuit Breaker to discover containers running on the Docker host, mount the Docker socket using the override file:

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.socket.yml up -d
```

This bind-mounts `/var/run/docker.sock` into the container read-write. The override file warns that this grants the container near-root-equivalent access to the host — prefer pointing `CB_DOCKER_HOST` at a read-only Docker API proxy (for example `Tecnativa/docker-socket-proxy`) instead.

---

## Manual Setup (without the install script)

```bash
# 1. Create install directory
mkdir -p ~/.circuitbreaker && cd ~/.circuitbreaker

# 2. Download compose file and env template
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/.env.example -o .env

# 3. Edit .env — set CB_DB_PASSWORD, CB_VAULT_KEY, CB_JWT_SECRET and
#    NATS_AUTH_TOKEN at minimum. CB_JWT_SECRET and NATS_AUTH_TOKEN must be
#    at least 32 characters; compose refuses to start if any of the four is unset.
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

# Update to latest image
docker compose pull && docker compose up -d

# Remove the container (data directory is untouched)
docker compose down
```

Data lives in `${CB_DATA_DIR:-./circuitbreaker-data}` on the host, not in a Docker volume — remove that directory to wipe it.

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for all environment variables.
- For remote access over the internet — see [Remote Access & Tunnels](../remote-access.md).
