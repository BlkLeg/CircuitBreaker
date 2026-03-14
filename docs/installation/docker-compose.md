# Advanced Compose Reference

This page documents a custom Compose pattern for users who intentionally want to manage their own reverse proxy or deviate from the standard deployment.

It is not the primary supported install path. For the standard tested experience, use [Quick Install (Script)](quick-install.md) or [Docker Compose — Prebuilt Full Stack](docker-compose-prod.md).

---

## Prerequisites

- Linux, macOS, or Windows with **Docker Engine 20+** and the **Compose plugin v2** (`docker compose` — not the legacy `docker-compose`)
- Outbound internet access to pull from `ghcr.io`

Check your Compose version:

```bash
docker compose version
# Docker Compose version v2.x.x
```

---

## Custom Compose Example

```bash
# 1. Download the compose file
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/docker-compose.prebuilt.yml \
  -o docker-compose.yml

# 2. Start Circuit Breaker
docker compose up -d
```

This starts Circuit Breaker on **port 8080** behind your own surrounding infrastructure:

```
http://localhost:8080
http://<host-ip>:8080
```

---

## Compose File Overview

This custom compose file runs a single container with a named volume for persistence:

```yaml
services:
  circuit-breaker:
    image: ghcr.io/blkleg/circuitbreaker:latest
    ports:
      - "8080:8080"
    volumes:
      - circuit-breaker-data:/data
    environment:
      - DATABASE_URL=sqlite:////data/app.db
      - UPLOADS_DIR=/data/uploads
      - CB_VAULT_KEY=
    restart: unless-stopped

volumes:
  circuit-breaker-data:
```

The container listens on port 8080 and stores everything in the `circuit-breaker-data` named volume.

---

## Setting a Vault Key

The vault key encrypts stored credentials (SNMP passwords, Proxmox tokens, SMTP credentials). If you leave `CB_VAULT_KEY` empty, Circuit Breaker will auto-generate one during the [first-run wizard](first-run.md) and write it to `/data/.env` inside the volume.

To pre-seed a persistent key before first launch, generate one and set it in the compose file or a `.env` file:

```bash
# Generate a key
openssl rand -base64 32
```

Then set it in `docker-compose.yml`:

```yaml
environment:
  - CB_VAULT_KEY=your-generated-key-here
```

Or create a `.env` file alongside `docker-compose.yml`:

```
CB_VAULT_KEY=your-generated-key-here
```

---

## Restricting Network Exposure

By default the container binds to all network interfaces (`0.0.0.0:8080`). To restrict it to loopback only (when using a local reverse proxy):

```yaml
ports:
  - "127.0.0.1:8080:8080"
```

---

## Enabling ARP Scanning (Optional)

ARP scanning lets the discovery engine resolve MAC addresses and detect hosts more reliably. It requires elevated Linux capabilities and should only be used on trusted, isolated networks.

To enable, uncomment the `cap_add` block in the compose file:

```yaml
    cap_add:
      - NET_RAW
      - NET_ADMIN
```

Without these capabilities, Circuit Breaker falls back to nmap TCP/ICMP scanning — all other scan types (SNMP, HTTP, Proxmox) work without them.

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

# Remove container and data volume
docker compose down -v
```

---

## Next Steps

- Complete the **[First-Run Setup](first-run.md)** wizard on first launch.
- Review the **[Configuration Reference](configuration.md)** for environment variables.
- To add HTTPS, place Circuit Breaker behind a reverse proxy — see [Deployment & Security](../deployment-security.md).
- For remote access over the internet — see [Remote Access & Tunnels](../remote-access.md).
- If you want the standard supported Docker experience instead, use [Docker Compose — Prebuilt Full Stack](docker-compose-prod.md).
