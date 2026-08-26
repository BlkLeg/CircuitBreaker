# Upgrading

Circuit Breaker runs database migrations automatically on startup — no manual migration steps are required.

For v1.0 release candidates, upgrade and rollback support is controlled by the
[1.0 compatibility policy](../release/1.0.0-compatibility-policy.md). Direct 1.0 upgrade support
starts at `0.3.5` unless the release ledger records additional ACC-12 evidence. Always export and
verify a backup before upgrading.

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

This re-runs the installer in upgrade mode, which pulls the latest release, restarts the `circuitbreaker.target` units, and runs migrations automatically.

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

### What persists across upgrades

There are no named volumes. Everything lives in the host data directory bind-mounted at `/data`:

| Mount | Contents |
|---|---|
| `${CB_DATA_DIR:-./circuitbreaker-data}` → `/data` | Postgres data, NATS and Redis state, uploads, TLS certificates, vault key |

Recreating the container never touches it.

### Pinning to a specific version

Set the tag in `~/.circuitbreaker/.env`:

```bash
CB_TAG=1.0.0
```

Then:

```bash
docker compose up -d
```

Only `:<version>` and `:latest` tags are published. `CB_IMAGE` overrides the whole image reference if you host your own build.

---

## Verifying the Upgrade

```bash
cb version
```

Or check **Settings → About** in the UI.

---

## Rollback

### Native / Proxmox LXC

Re-run the installer with the `--version` flag. Give the version **without** the leading `v` — the installer adds it when looking up the release tag:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --version 0.3.5
```

### Docker Compose

Set `CB_TAG` in `~/.circuitbreaker/.env` to the previous version, then:

```bash
docker compose up -d
```

Editing `.env` is the rollback path for an existing install: re-running `install.sh --docker
--version <version>` preserves the `.env` you already have — secrets live in it — so it only warns
you to set `CB_TAG`. `--version` writes `CB_TAG` itself on a first install, where there is no `.env`
to preserve.

Review the [release notes](../updates/v0.2.0-overview.md) before rolling back to check for irreversible schema changes.

After 1.0 migrations run, binary downgrade is not supported. Restore the complete pre-upgrade backup
instead of starting an older binary against a newer schema.

---

## Related

- [Backup & Restore](../backup-restore.md) — recommended before major upgrades
- [cb CLI Tool](../cb-cli.md) — `cb update` and `cb version` reference
