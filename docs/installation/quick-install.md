# Quick Install

The fastest way to get Circuit Breaker running. Choose the method that fits your environment.

---

## Native (Recommended)

Installs Circuit Breaker directly on your Linux host as a **systemd service**. No Docker required.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

**What it does:**

- Downloads a prebuilt release bundle and installs it to `/opt/circuitbreaker`
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

## Next Step

Open Circuit Breaker in your browser and complete the **[First-Run Setup](first-run.md)** wizard to create your admin account.
