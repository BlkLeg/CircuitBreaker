# Circuit Breaker — Proxmox LXC (Native, No Docker)

One-command deployment to a Proxmox LXC container. All services run natively via systemd on Debian 12 — no Docker, no nesting, no compose.

## Quick Start

From the **Proxmox VE host** shell:

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/proxmox/ct/circuitbreaker.sh)"
```

This creates an unprivileged Debian 12 container and provisions everything automatically.

## Architecture

```
LXC Container (Debian 12, unprivileged, no nesting)
├── systemd: postgresql.service              (Postgres 15, apt)
├── systemd: cb-pgbouncer.service            (transaction-mode pooling on :6432)
├── systemd: nats-server.service             (JetStream on :4222, ~20MB RAM)
├── systemd: cb-redis.service                (128MB LRU cache on :6379)
├── systemd: circuitbreaker.service          (uvicorn on 127.0.0.1:8000)
├── systemd: circuitbreaker-worker@.service  (4 instances: discovery, webhook, notification, telemetry)
└── systemd: nginx.service                   (HTTP :80 redirect + HTTPS :443, self-signed TLS)
```

**RAM target**: ~400-600 MB steady-state (vs ~1.2 GB with Docker overhead).

## Services

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL | 5432 | Primary database |
| PgBouncer | 6432 | Connection pooling (transaction mode) |
| NATS | 4222 | Event bus with JetStream |
| Redis | 6379 | Telemetry cache + pub/sub |
| Uvicorn | 8000 | FastAPI backend (localhost only) |
| Workers x4 | — | Discovery, webhook, notification, telemetry |
| nginx | 80/443 | Reverse proxy + static frontend + TLS |

## Managing Services

```bash
# Status of all services
systemctl status postgresql cb-pgbouncer nats-server cb-redis \
    circuitbreaker circuitbreaker-worker@{0,1,2,3} nginx

# Restart the API
systemctl restart circuitbreaker

# View API logs
journalctl -u circuitbreaker -f

# View worker logs (discovery=0, webhook=1, notification=2, telemetry=3)
journalctl -u circuitbreaker-worker@0 -f

# View all CB-related logs
journalctl -u circuitbreaker -u 'circuitbreaker-worker@*' -f
```

## Verification

```bash
# Health check (HTTP — exempt from redirect)
curl http://localhost/api/v1/health

# Health check (HTTPS)
curl -k https://localhost/api/v1/health

# HTTPS redirect
curl -I http://localhost/

# PgBouncer connectivity
psql -h 127.0.0.1 -p 6432 -U cb circuitbreaker -c "SELECT 1"

# RAM usage
free -m
```

## Updating

```bash
cb-update
```

Pulls the latest tag, installs dependencies, rebuilds the frontend, runs migrations, and restarts all services.

## File Locations

| Path | Purpose |
|------|---------|
| `/opt/circuitbreaker/` | Application source (root-owned, read-only to app) |
| `/var/lib/circuitbreaker/` | Runtime data (uploads, vault, TLS certs, NATS, Redis) |
| `/var/log/circuitbreaker/` | Application logs |
| `/etc/circuitbreaker.env` | Environment config (chmod 640 root:breaker) |
| `/etc/nginx/sites-available/circuitbreaker` | nginx config |
| `/etc/pgbouncer/circuitbreaker.ini` | PgBouncer config |
| `/etc/redis/circuitbreaker.conf` | Redis config |

## Custom TLS

Replace the self-signed certificate:

```bash
cp /path/to/your/fullchain.pem /var/lib/circuitbreaker/tls/fullchain.pem
cp /path/to/your/privkey.pem /var/lib/circuitbreaker/tls/privkey.pem
chown breaker:breaker /var/lib/circuitbreaker/tls/*
chmod 600 /var/lib/circuitbreaker/tls/privkey.pem
systemctl reload nginx
```

## Security

- Uvicorn runs as `breaker:1000` (never root)
- `/etc/circuitbreaker.env` is `chmod 640 root:breaker`
- `/var/lib/circuitbreaker` owned by `breaker:1000`
- App source `/opt/circuitbreaker` owned by root (not writable by app)
- Systemd hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`
- NATS requires auth token; Redis requires password
- nginx adds CSP, HSTS, X-Frame-Options, and other security headers
- HTTP-to-HTTPS redirect on all routes (health check exempt)

## Container Defaults

| Setting | Value |
|---------|-------|
| Type | Unprivileged (no nesting) |
| OS | Debian 12 |
| RAM | 1024 MB |
| CPU | 2 vCPU |
| Disk | 6 GB |
| Network | DHCP on vmbr0 |
