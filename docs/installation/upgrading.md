# Upgrading

Circuit Breaker runs database migrations automatically on startup — no manual migration steps are required.

For v1.0 release candidates, upgrade and rollback support is controlled by the
[1.0 compatibility policy](../release/1.0.0-compatibility-policy.md). Direct 1.0 upgrade support
starts at `0.3.5` unless the release ledger records additional ACC-12 evidence. Always export and
verify a backup before upgrading.

---

## What changed for operators

Native installs keep the application under `/opt/circuitbreaker/` with its own
Python tree. `circuit-breaker` is a launcher into that tree; on package hosts
`/usr/local/bin/circuit-breaker` remains a symlink. An in-place upgrade replaces
the tree; your `.env`, data directory, vault key and TLS material stay put.

## What to do

Nothing new. Upgrade the same way you always have:

- Native / Proxmox LXC: re-run the installer with `--upgrade` (see [below](#native-proxmox-lxc)).
  `cb update` does not upgrade a native install; it only updates the single-container (mono) image
- Packages: `apt upgrade` / `dnf upgrade` once signed repos exist; until then
  reinstall the newer package the same way you installed
- Docker Compose: pull the image tag you pin (see channels below)
- Single Docker container (mono): `cb update`

## Rollback

During a native upgrade the previous interpreter is renamed to
`python.prev` (and the old launcher to `bin/circuit-breaker.prev`) until
`/readyz` returns 200. After health succeeds those copies are deleted. If the
upgrade fails before that, the installer puts the previous tree back; if you
need a database rollback after a completed upgrade, restore the pre-upgrade
dump and reinstall the previous release (see
[Rollback procedures](#rollback-procedures) below). Package hosts use
`circuit-breaker-rollback`.

## Release channels

Three image/release channels exist; only **stable** is production-supported.

| Channel | How it is produced | What users pull |
|---|---|---|
| **stable** | Promote of a soaked candidate (no rebuild). Default for `install.sh` and `:latest`. | `:X`, `:latest` (never for an rc) |
| **candidate** | Draft GitHub Release becomes a published prerelease; images `:<version>-candidate` / `:candidate`. Opt in with `install.sh --channel candidate` or `CB_TAG=candidate`. | published prereleases and the moving `:candidate` tag |
| **nightly** | Last green push to `dev` after artifact-smoke and compose smoke (amd64 image only). Unsupported for production. | `:nightly`, `:dev-<sha>` |

Draft candidate releases are not reachable from unauthenticated `install.sh`;
release captains soak them with `gh release download` and `--local-bundle`.

---

## Check Your Current Version

```bash
cb version
```

Or in the UI: **Settings → About**.

---

## Native / Proxmox LXC

If you installed natively with `install.sh` or with the Proxmox LXC helper
(`cb-proxmox-deploy.sh`), upgrade by re-running the installer in upgrade mode:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | sudo bash -s -- --upgrade
```

Running the installer on a host that already has Circuit Breaker detects the
install and upgrades it anyway; `--upgrade` just makes that explicit. In order,
it:

1. **Backs up the database** to `${CB_DATA_DIR}/backups/pre-upgrade-<stamp>.sql`,
   and stops if that backup cannot be taken (see
   [Rollback procedures](#rollback-procedures)). If the database is not running
   there is nothing to lose, so it warns and continues.
2. **Stops the services** and swaps in the new release, keeping the old
   application tree as `python.prev` until the new one is healthy.
3. **Applies configuration and database migrations.**
4. **Restarts** `circuitbreaker.target` and waits for `/readyz`. If the new
   release never reports healthy, it puts the previous one back.

`cb update` is not the way to do this. On a native install it stops and prints
the command above; it upgrades only the single-container (mono) image.

### Upgrade options

| Option | Use it to |
|---|---|
| `--version <version>` | Install a specific release instead of the latest, e.g. `--version 0.4.6` (no leading `v`) |
| `--channel candidate` | Allow published pre-releases; the default, `stable`, never picks one |
| `--local-bundle <path>` | Upgrade from a release tarball you downloaded yourself |
| `--airgap` | Make no outbound request at all; needs `--local-bundle` and dependencies already installed |
| `--unattended` | Skip every prompt (scripts, Proxmox LXC) |
| `--force-deps` | Reinstall system dependencies as well |

For an offline or air-gapped host, download the release tarball
(`circuit-breaker_<version>_linux_<arch>.tar.gz`), the release's `SHA256SUMS` and
its `SHA256SUMS.sig` from [GitHub Releases](https://github.com/BlkLeg/CircuitBreaker/releases) on a
connected machine, and check it there:

```bash
sha256sum -c --ignore-missing SHA256SUMS
```

The installer verifies a bundle it downloads itself. For one you hand it with
`--local-bundle`, it verifies the signature and hash when `SHA256SUMS` and
`SHA256SUMS.sig` are both next to the tarball. Releases before 0.4.7 have no
signature, so the check above is yours there. Then copy the tarball, `SHA256SUMS`,
`SHA256SUMS.sig` and `install.sh` to the host and run:

```bash
sudo bash install.sh --local-bundle circuit-breaker_<version>_linux_amd64.tar.gz --airgap --unattended
```

### Proxmox LXC

Run the same command inside the container, either over SSH:

```bash
ssh root@<container-ip>
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --upgrade
```

or from the Proxmox host:

```bash
pct exec <CTID> -- bash -c "curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --upgrade --unattended"
```

Inside the container you are already root, so `sudo` is not needed.

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

Only `:<version>`, `:latest`, `:candidate`, and `:nightly` tags are published
(see [Release channels](#release-channels)). `CB_IMAGE` overrides the whole
image reference if you host your own build.

---

## Verifying the Upgrade

```bash
cb version
```

Or check **Settings → About** in the UI.

---

## Rollback procedures

### Native / Proxmox LXC

While an upgrade is in flight, `/opt/circuitbreaker/python.prev` holds the
previous interpreter until `/readyz` succeeds; afterwards it is removed. If
`/readyz` never answers, the installer rolls the tree back itself. After a
completed upgrade that you need to undo, restore the pre-upgrade dump and
reinstall the previous release:

```bash
sudo /opt/circuitbreaker/deploy/scripts/restore.sh ${CB_DATA_DIR}/backups/pre-upgrade-<stamp>.sql
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | sudo bash -s -- --version <previous-version>
```

Give `--version` **without** the leading `v` — the installer adds it when
looking up the release tag. Reinstalling the previous release after the restore
is what keeps Alembic from migrating the restored schema forward again.

### Distribution packages (deb / rpm)

Packages install the same hermetic tree under `/opt/circuitbreaker/`. Prefer the
wrapper the package ships — it supplies the package unit name, role and
environment file:

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

  That path is the `install.sh` layout. On a deb/rpm host the restore script is at
  `/usr/local/share/circuit-breaker/deploy/scripts/restore.sh` and expects a
  different unit name, role and environment file — run
  `sudo circuit-breaker-rollback <file>` there, which supplies them.
  See [Distribution packages](#distribution-packages-deb-rpm) above.

  Note that a bare dump restores the **database only** — no `uploads/`, no `CB_VAULT_KEY` rewrite, no
  nginx site config. That is the right shape for rolling back an upgrade, where those are unchanged.
  For a host rebuild, use a snapshot: see [Backup & Restore](../backup-restore.md).

---

## Related

- [Backup & Restore](../backup-restore.md) — recommended before major upgrades
- [cb CLI Tool](../cb-cli.md) — `cb version`, `cb backup` and `cb update` (single-container installs)
