# Installation Overview

Circuit Breaker is a self-hosted homelab topology mapper. It installs natively on Linux via systemd — no Docker required. Docker Compose is available as an alternative for users who prefer container-based deployments.

---

## System Requirements

| Requirement | Minimum |
|---|---|
| **OS** | Linux (amd64, arm64) |
| **RAM** | 1 GB available |
| **Disk** | 2 GB |
| **Network** | Outbound internet access (to download the installer and image) |

> **Docker not required for native installs.** The default install method runs Circuit Breaker directly as a systemd service. Docker is only needed if you choose the `--docker` flag.

---

## Method Comparison

| Method | Best for | Port | Effort |
|---|---|---|---|
| [Native Systemd](quick-install.md#native-recommended) | Most Linux users — fastest path, no Docker | 8088 | Low |
| [Proxmox LXC](proxmox-lxc.md) | Proxmox VE users — isolated container on the PVE host | 8088 | Low |
| [Docker Compose](docker-compose.md) | Users who prefer containerised deployments | 8088 / 443 | Low |

---

## Which Method Should I Choose?

**I want to get Circuit Breaker running as fast as possible on a Linux server.**
→ Use the [Quick Install script](quick-install.md). One command, no Docker required, under 2 minutes.

**I'm running Proxmox VE and want Circuit Breaker in an isolated LXC container.**
→ Use the [Proxmox LXC installer](proxmox-lxc.md). Runs on the PVE host, creates and configures the container automatically.

**I want a full container stack (Caddy, NATS, workers) managed with Docker Compose.**
→ Use the [Docker Compose](docker-compose.md) method.

---

## After Installing

Regardless of method, your next steps are:

1. Open Circuit Breaker in your browser at `http://<host>:8088` (or your configured domain).
2. Complete the **first-run setup wizard** — see [First-Run Setup](first-run.md).
3. Back up the vault key shown at the end of the wizard (only displayed once).
4. Optionally review the [Configuration Reference](configuration.md) to tune environment variables.

---

## Related Pages

- [First-Run Setup](first-run.md)
- [Configuration Reference](configuration.md)
- [Upgrading](upgrading.md)
- [Uninstalling](uninstalling.md)
- [Deployment & Security](../deployment-security.md)
- [Remote Access & Tunnels](../remote-access.md)
