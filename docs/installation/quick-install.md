# Quick Install

The fastest way to get Circuit Breaker running. Choose the method that fits your environment.

---

## What changed for operators

Native installs (this script and the `.deb` / `.rpm` packages) ship a **hermetic
runtime tree** under `/opt/circuitbreaker/`: a pinned Python interpreter, the
application, and its wheels. The `circuit-breaker` command is a small launcher
into that tree, not a self-extracting binary. On package hosts,
`/usr/local/bin/circuit-breaker` is a symlink to
`/opt/circuitbreaker/bin/circuit-breaker`. Upgrades keep the same commands and
paths you already use.

## What to do

Nothing special on first install or upgrade. Use the commands below (or
`install.sh --upgrade` / `cb update`). Package hosts keep using their package
manager once signed repos exist; until then the tarball path below is the
default.

## Rollback

During an upgrade the previous interpreter is kept as
`/opt/circuitbreaker/python.prev` until `/readyz` succeeds; after health it is
removed. If health fails before that, restore the pre-upgrade backup and
reinstall the previous release:

```bash
sudo /opt/circuitbreaker/deploy/scripts/restore.sh /var/lib/circuitbreaker/backups/pre-upgrade-<stamp>.sql
```

On package hosts use `sudo circuit-breaker-rollback` instead. Full detail:
[Upgrading — Rollback](upgrading.md#rollback-procedures).

## Release channels

`install.sh --channel stable` (default) picks the newest published non-prerelease.
`--channel candidate` opts into published prereleases. Docker tags
`:candidate` and `:nightly` are the matching image channels — see
[Upgrading — Release channels](upgrading.md#release-channels).

---

## Native (Recommended)

Installs Circuit Breaker directly on your Linux host as a **systemd service**. No Docker required.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

> **What is verified about this path.** Every release builds this tarball. The
> release gate unpacks it, asserts the launcher can import the application
> (`--selftest`), and the installer journey installs the tarball, boots the
> units, and probes `/readyz` across the support matrix. See
> [ADR 0005 — Verification tiers and platform support](../adr/0005-verification-tiers-and-platform-support.md)
> for exactly which guarantees are in force today. Packages (`.deb`, `.rpm`)
> carry the strongest upgrade/rollback guarantees once Tier 1 is in force.

**What it does:**

- Downloads a prebuilt release bundle and installs the hermetic tree to `/opt/circuitbreaker`
- Creates the `breaker` system user and the data directory `/var/lib/circuitbreaker`
- Installs and enables the `circuitbreaker.target` unit group — Postgres, PgBouncer, Redis, NATS, the backend and the workers — behind nginx
- Installs the `cb` CLI tool to `/usr/local/bin/cb`
- Runs database migrations automatically on first start

**Access at:** `https://<host>/` — TLS is enabled by default with a self-signed certificate. Port `8088` serves an HTTP redirect to HTTPS only; account creation needs the secure context.

**Egress proxy:** the generated `/etc/circuitbreaker/.env` sets `CB_ALLOW_DIRECT_EGRESS=true`, because most homelab hosts have no forward proxy. That waives only the `CB_EGRESS_PROXY_URL` requirement — SSRF and outbound URL policy still apply, and Redis, NATS, rate-limit storage and secrets still fail closed. Set it to `false` once you have configured `CB_EGRESS_PROXY_URL`. See the [Configuration Reference](configuration.md).

**Non-interactive install** (skips all prompts, uses defaults):

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --unattended
```

**Candidate channel** (published prereleases only):

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --channel candidate
```

**After install:**

```bash
cb status       # Show service status
cb doctor       # Run health checks
cb logs         # Follow live logs
cb backup       # Dump the database
cb update       # Upgrade to latest release
cb version      # Show installed version
cb uninstall    # Remove Circuit Breaker from this system
```

See [cb CLI Tool](../cb-cli.md) for the full reference.

---

## Proxmox LXC

Runs on your Proxmox VE host. Creates a Debian 12 LXC container and installs Circuit Breaker inside it automatically.

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-deploy.sh)"
```

Takes about 3 minutes. Circuit Breaker is accessible at `https://<container-ip>:8088` when done.

→ See the full guide: [Proxmox LXC Installation](proxmox-lxc.md)

---

## Docker Compose

Runs Circuit Breaker as a single container — Postgres, Redis, NATS, the backend, the workers and nginx are all inside the mono image — using Docker Compose. This path never prompts.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

**Access at:** `https://<host>/` (HTTP on port 80 redirects)

→ See the full guide: [Docker Compose Installation](docker-compose.md)

---

## Testing a Dev Build

Every push to `dev` that passes lint, tests and the security gate builds and
smoke-tests both install paths without needing a merge to `main` first:

**Docker Compose** — `dev-ci.yml` publishes a rolling `ghcr.io/blkleg/circuitbreaker:dev`
image after the compose smoke passes. Point the installer at the `dev` branch
and that image with:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/dev/install.sh | bash -s -- --docker --version dev
```

Or by hand, the same way the [Manual Setup](docker-compose.md#manual-setup-without-the-install-script)
section does it for a release, just from `dev` instead of `main`:

```bash
mkdir -p ~/cb-dev && cd ~/cb-dev
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/dev/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/dev/.env.example -o .env
# edit .env: set CB_DB_PASSWORD, CB_VAULT_KEY, CB_JWT_SECRET, NATS_AUTH_TOKEN, and CB_TAG=dev
docker compose up -d
```

**Native (`.deb`/tarball)** — `dev-ci.yml` also builds the native amd64
packages and runs the same install-and-boot gate release candidates get
(`artifact-smoke.yml`), but it does not publish a rolling channel the way the
Docker image does — GitHub only retains the build for 3 days as a workflow
artifact. Grab the latest one with the [GitHub CLI](https://cli.github.com/)
and hand it to `--local-bundle`, the flag the installer journey suite itself
uses (see `CLAUDE.md`):

```bash
gh run download --repo BlkLeg/CircuitBreaker \
  -n dev-packages-amd64 \
  -R "$(gh run list --repo BlkLeg/CircuitBreaker --workflow dev-ci.yml --branch dev --json databaseId --jq '.[0].databaseId')" \
  --dir ./dev-packages
bash install.sh --local-bundle ./dev-packages/circuit-breaker_*_linux_amd64.tar.gz --unattended --no-tls
```

This is the same tarball path `curl | bash` installs from a release — it just
comes from a workflow artifact instead of a GitHub Release, so nothing about
`install.sh` itself needs to know it is a pre-release build.

---

## Next Step

Open Circuit Breaker in your browser and complete the **[First-Run Setup](first-run.md)** wizard to create your admin account.
