# Upgrading

Circuit Breaker runs database migrations automatically on startup — no manual migration steps are required.

---

## Check Your Current Version

```bash
cb version
```

Or in the UI: **Settings → About**.

---

## Native / Proxmox LXC

If you installed natively with `install.sh` or via the Proxmox LXC helper (`cb-proxmox-deploy.sh`), upgrade with:

```bash
cb update
```

This pulls the latest release, restarts the systemd service, and runs migrations automatically.

**For Proxmox LXC:** SSH into the container first, then run `cb update`:

```bash
ssh root@<container-ip>
cb update
```

Or from the PVE host:

```bash
pct exec <CTID> -- cb update
```

### What persists across upgrades

- **Database** — all your hardware, services, networks, scans, topology data
- **Vault key** — encrypted credentials remain readable
- **Uploads** — custom icons and branding assets
- **App settings** — auth config, SMTP, OAuth providers, theme preferences

---

## Docker Compose

```bash
cd ~/.circuitbreaker
docker compose pull
docker compose up -d
```

Or use `cb update` if the `cb` CLI is installed.

### What persists across upgrades

Named Docker volumes preserve all data between container recreations:

| Volume | Contents |
|---|---|
| `backend-data` | Database, vault key, uploads |
| `caddy_data` | Caddy TLS certificates |
| `nats_data` | NATS state |
| `postgres_data` | PostgreSQL data (if using `--profile pg`) |

### Pinning to a specific version

Edit `docker-compose.yml` to set a version tag:

```yaml
image: ghcr.io/blkleg/circuitbreaker:backend-v0.2.0
```

Then:

```bash
docker compose up -d
```

---

## Verifying the Upgrade

```bash
cb version
```

Or check **Settings → About** in the UI.

---

## Rollback

### Native / Proxmox LXC

Re-run the installer with a specific version tag:

```bash
CB_VERSION=v0.1.4 curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

### Docker Compose

Edit `docker-compose.yml` to reference the previous image tag, then:

```bash
docker compose up -d
```

Review the [release notes](../updates/v0.2.0-overview.md) before rolling back to check for irreversible schema changes.

---

## Related

- [Backup & Restore](../backup-restore.md) — recommended before major upgrades
- [cb CLI Tool](../cb-cli.md) — `cb update` and `cb version` reference
