# Quick Install

The fastest way to get Circuit Breaker running. Choose the method that fits your environment.

---

## Native (Recommended)

Installs Circuit Breaker directly on your Linux host as a **systemd service**. No Docker required.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

**What it does:**

- Installs Python dependencies and the Circuit Breaker application
- Creates a `circuitbreaker` system user and data directory
- Installs and enables a systemd service (`circuitbreaker`)
- Installs the `cb` CLI tool to `/usr/local/bin/cb`
- Runs database migrations automatically

**Access at:** `http://<host>:8088`

**Non-interactive install** (accepts all defaults):

```bash
CB_YES=1 curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

**After install:**

```bash
cb status       # Show service status
cb logs -f      # Follow live logs
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

Takes about 3 minutes. Circuit Breaker is accessible at `http://<container-ip>:8088` when done.

→ See the full guide: [Proxmox LXC Installation](proxmox-lxc.md)

---

## Docker Compose

Installs the full Circuit Breaker stack — backend, frontend, workers, Caddy reverse proxy, and NATS — using Docker Compose.

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

**Non-interactive:**

```bash
CB_YES=1 curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

**Access at:** `http://<host>:8088` (HTTP) or `https://<domain>` (if Caddy HTTPS is configured)

→ See the full guide: [Docker Compose Installation](docker-compose.md)

---

## Next Step

Open Circuit Breaker in your browser and complete the **[First-Run Setup](first-run.md)** wizard to create your admin account.
