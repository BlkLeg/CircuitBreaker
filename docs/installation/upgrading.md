# Upgrading

Circuit Breaker handles database migrations automatically on startup — no manual migration steps are required. Simply pull the new image and restart.

---

## Check Your Current Version

```bash
cb version
```

Or via the API:
```
GET http://localhost:8080/api/v1/version
```

Or in the UI: **Settings → About**.

---

## Quick Install (Script) / Single Container

If you installed with `install.sh` and the `cb` CLI is available:

```bash
cb update
```

This pulls the latest image from GHCR and restarts the container. Your data volume is preserved.

### Manual update (without `cb`)

```bash
docker pull ghcr.io/blkleg/circuitbreaker:latest
docker restart circuit-breaker
```

If the image tag has changed or you want a clean restart:

```bash
docker pull ghcr.io/blkleg/circuitbreaker:latest
docker stop circuit-breaker
docker rm circuit-breaker
# Re-run your original docker run command
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  ghcr.io/blkleg/circuitbreaker:latest
```

The named volume (`circuit-breaker-data`) is preserved — your database, vault key, and uploads are intact.

---

## Docker Compose — Prebuilt

```bash
docker compose pull
docker compose up -d
```

Compose pulls the new image and recreates the container with zero configuration changes.

---

## Docker Compose — From Source

```bash
git pull
docker compose -f docker/docker-compose.yml up -d --build
```

Or via Makefile:

```bash
git pull
make compose-up
```

This rebuilds the local images from the updated source and recreates the containers.

To update a single service (e.g. just the backend after a Python change):

```bash
docker compose -f docker/docker-compose.yml up -d --build backend
```

---

## Pinning to a Specific Version

To upgrade to a specific release rather than `latest`, set the version tag:

### Quick install / single container

```bash
CB_VERSION=v0.2.0 cb update
# or
docker pull ghcr.io/blkleg/circuitbreaker:v0.2.0
```

### Docker Compose prebuilt

Edit `docker-compose.yml`:
```yaml
image: ghcr.io/blkleg/circuitbreaker:v0.2.0
```

Then:
```bash
docker compose up -d
```

### Docker Compose from source

Check out the desired tag:
```bash
git fetch --tags
git checkout v0.2.0
docker compose -f docker/docker-compose.yml up -d --build
```

---

## What Persists Across Upgrades

As long as the data volume is not removed, upgrades preserve:

- **SQLite database** (`app.db`) — all your hardware, services, networks, scans, etc.
- **Vault key file** (`.env` inside the volume) — encrypted credentials remain readable.
- **Uploads** — custom icons, branding assets.
- **App settings** — auth config, SMTP, OAuth providers, theme preferences.

Database schema changes are applied automatically on startup via inline migrations. No action required.

---

## Rollback

If an upgrade causes issues, stop the new container and start the previous image version:

```bash
docker stop circuit-breaker
docker run -d \
  --name circuit-breaker \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -v circuit-breaker-data:/data \
  ghcr.io/blkleg/circuitbreaker:v0.1.4   # previous version
```

Review the [release notes](../updates/v0.2.0-overview.md) before rolling back to check for irreversible schema changes.

---

## Related

- [Backup & Restore](../backup-restore.md) — recommended before major upgrades
- [cb CLI Tool](../cb-cli.md) — `cb update` and `cb version` reference
