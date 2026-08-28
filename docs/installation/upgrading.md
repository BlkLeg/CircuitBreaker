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

### Distribution packages (deb / rpm)

A package install is not the `install.sh` layout and does not share its paths, so the
`/opt/circuitbreaker/...` command below does not exist on these hosts. Use the wrapper the package
ships instead:

```bash
sudo circuit-breaker-rollback
```

Called with no argument it lists the pre-upgrade backups it can restore. Called with one it performs
the restore.

**Reinstall the previous package first.** This is not optional, and it is the step that is easy to
miss:

```bash
# 1. stop the service
sudo systemctl stop circuit-breaker

# 2. go back to the previous package
sudo dnf downgrade circuit-breaker          # Fedora / RHEL
sudo apt install circuit-breaker=<old>      # Debian / Ubuntu

# 3. restore the dump the upgrade took
sudo circuit-breaker-rollback /var/lib/circuit-breaker/backups/pre-upgrade-<stamp>.sql
```

The pre-upgrade dump carries the **old** schema. Circuit Breaker runs `alembic upgrade head` at
startup, so restoring it while the newer binary is installed migrates the schema straight back
forward and the rollback silently undoes itself. Downgrading first is what prevents that.

The dump is taken by the package's `preinstall` hook, which runs on upgrade transactions only. Like
`install.sh --upgrade`, **it fails the upgrade if the backup cannot be taken** rather than migrating
with nothing to go back to. It skips the backup, and says so, in the two cases where there is
nothing at risk: no environment file, or a database this host cannot reach.

> `apk` packages get no pre-upgrade backup. Alpine calls a separate `.pre-upgrade` script that nfpm
> does not emit, which is one reason `apk` is a build-only (Tier 3) format rather than a Tier 1 one.
> See [ADR 0005](../adr/0005-verification-tiers-and-platform-support.md).

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

`install.sh --upgrade` takes that backup itself, to `${CB_DATA_DIR}/backups/pre-upgrade-<stamp>.sql`,
before it stops the services. Two things about it are worth knowing before you need it:

* **It now fails the upgrade if it cannot be taken.** It used to print "Backup saved" unconditionally
  — over a `pg_dump` that had exited non-zero, or written nothing, or not been found on `PATH` at
  all. The upgrade then migrated the schema, and the documented recovery pointed at a file that was
  empty or absent.
* **The artifact is a bare `.sql`, and `deploy/scripts/restore.sh` accepts it** as well as a full
  `cb-snapshot-*.tar.gz`. The rollback the upgrade prints is directly runnable:

  ```bash
  sudo /opt/circuitbreaker/deploy/scripts/restore.sh ${CB_DATA_DIR}/backups/pre-upgrade-<stamp>.sql
  ```

  That path is the `install.sh` layout. On a deb/rpm host the same script is at
  `/usr/local/share/circuit-breaker/deploy/scripts/restore.sh` and expects a different unit name,
  role and environment file — run `sudo circuit-breaker-rollback <file>` there, which supplies them.
  See [Distribution packages](#distribution-packages-deb--rpm) above.

  Note that a bare dump restores the **database only** — no `uploads/`, no `CB_VAULT_KEY` rewrite, no
  nginx site config. That is the right shape for rolling back an upgrade, where those are unchanged.
  For a host rebuild, use a snapshot: see [Backup & Restore](../backup-restore.md).

---

## Related

- [Backup & Restore](../backup-restore.md) — recommended before major upgrades
- [cb CLI Tool](../cb-cli.md) — `cb update` and `cb version` reference
