# Quick Install (Script)

The quickest way to install Circuit Breaker on a Linux host. A single command pulls the image, configures persistence, and optionally sets up HTTPS via an embedded Caddy reverse proxy.

---

## Prerequisites

- Linux (amd64, arm64, or arm/v7)
- **Docker Engine 20+** must already be installed ([install Docker](https://docs.docker.com/engine/install/))
- **curl or wget** — the install script uses one of these for all downloads. If neither is installed (e.g. on a minimal Ubuntu server), install one before running the script:
  ```bash
  sudo apt-get update && sudo apt-get install -y curl   # or: apt-get install -y wget
  ```
- `sudo` or root access (for systemd service and CA certificate installation)

---

## Run the Installer

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Or with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

The script is intended to land users on the standard Docker deployment. If you are using the interactive flow, choose the full Docker or Compose option when prompted.

---

## What the Script Does

1. **Detects your architecture** — supports amd64, arm64, and arm/v7.
2. **Verifies Docker** is installed and meets the minimum version requirement.
3. **Prompts for install mode** — use the full Docker deployment for the standard supported setup.
4. **Docker mode** — downloads the standard Docker deployment files, generates or reuses persistent configuration and secrets, starts the full supported stack with discovery, workers, webhooks, and HTTPS support, installs the self-signed CA certificate when local TLS is enabled, installs the `cb` CLI tool to `/usr/local/bin/cb`, and can create a **systemd service** so Circuit Breaker starts on boot.
5. **Binary mode** — exists for native package testing and platform-specific workflows and is not the standard recommended install path while native builds remain under active validation.

---

## Non-Interactive Mode

Suitable for scripted/CI deployments. Set `CB_YES=1` to accept all defaults without prompts:

```bash
CB_YES=1 CB_MODE=docker curl -fsSL \
  https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Or download first, then run with flags:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh -o install.sh
bash install.sh --mode docker --yes
```

---

## Environment Variable Overrides

All options can be passed as environment variables when piping through bash, or as flags when running the script directly.

| Variable | Flag | Default | Description |
|---|---|---|---|
| `CB_MODE` | `--mode docker\|binary` | _(prompted)_ | Install mode |
| `CB_VERSION` | `--version TAG` | `latest` | Image or binary version tag |
| `CB_PORT` | `--port PORT` | `8080` | Host port Circuit Breaker listens on |
| `CB_CONTAINER` | `--container NAME` | `circuit-breaker` | Docker container name |
| `CB_VOLUME` | `--volume NAME` | `circuit-breaker-data` | Docker volume name (or host path) |
| `CB_IMAGE` | `--image IMAGE` | `ghcr.io/blkleg/circuitbreaker:latest` | Override the Docker image |
| `CB_TLS` | `--tls` | _(off)_ | Enable HTTPS via Caddy |
| `CB_HOSTNAME` | `--hostname NAME` | `circuitbreaker.local` | Hostname for the TLS certificate |
| `CB_YES` | `--yes` | `0` | Non-interactive: accept all defaults |
| `CB_NO_SYSTEMD` | `--no-systemd` | `0` | Skip systemd service creation (useful in WSL) |
| `CB_NO_DESKTOP` | `--no-desktop` | `0` | Skip `.desktop` launcher file (binary mode) |

### Example: Docker with TLS on a custom hostname

```bash
CB_MODE=docker CB_TLS=1 CB_HOSTNAME=cb.lan CB_YES=1 \
  curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

### Example: Specific version, no systemd

```bash
bash install.sh --mode docker --version v0.2.2 --no-systemd
```

---

## After Installation

### Accessing the UI

- **Without TLS (default):** `http://localhost:8080` or `http://<host-ip>:8080`
- **With TLS (`--tls`):** `https://circuitbreaker.local` (or your custom `--hostname`)

If you enabled TLS, you may see a browser warning on first open until the self-signed CA certificate is trusted. The script installs it system-wide automatically, but your browser may need to be restarted. See [Trusting the CA Certificate](configuration.md#trusting-the-self-signed-ca-certificate) for per-platform instructions.

### The `cb` CLI

The installer places `cb` at `/usr/local/bin/cb`. Common commands:

```bash
cb status       # Show container/service status
cb logs -f      # Follow live logs
cb restart      # Restart Circuit Breaker
cb update       # Pull latest image and restart
cb version      # Show installed version
cb uninstall    # Remove Circuit Breaker from this system
```

See [cb CLI Tool](../cb-cli.md) for the full reference.

### Next Step

Open Circuit Breaker in your browser and complete the **[First-Run Setup](first-run.md)** wizard to create your admin account.

---

## Troubleshooting

**`docker: command not found`** — Docker is not installed. [Install Docker Engine](https://docs.docker.com/engine/install/) first.

**`permission denied`** — Run with `sudo bash install.sh ...` or ensure your user is in the `docker` group (`sudo usermod -aG docker $USER`, then log out and back in).

**Container exits immediately** — Check logs with `docker logs circuit-breaker`. A missing `CB_VAULT_KEY` after an interrupted install can cause startup failures; run `cb vault-recover` to resolve.

**Browser certificate warning** — The self-signed CA was not trusted by the browser. Restart the browser after install, or see [Trusting the CA Certificate](configuration.md#trusting-the-self-signed-ca-certificate).

If you need a native package or a custom reduced deployment, treat that as an advanced path and start from [Installation Overview](index.md) rather than the quick install flow.
