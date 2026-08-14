# Installation Overview

Circuit Breaker is a self-hosted homelab topology mapper. It installs natively on Linux via systemd — no Docker required. Docker Compose is available as an alternative for users who prefer container-based deployments.

For v1.0 release candidates, supported platforms and deployment modes are controlled by the
[v1.0 support contract](../release/1.0.0-support-contract.md). If this page describes a broader
workflow, treat it as beta or development guidance until the matching acceptance evidence is recorded.

---

## System Requirements

| Requirement | Minimum |
|---|---|
| **OS** | Linux (amd64, arm64) |
| **RAM** | 1 GB available |
| **Disk** | 2 GB |
| **Network** | Outbound internet access (to download the installer and image) |

> **Docker not required to run Circuit Breaker natively.** The default install method runs Circuit Breaker directly as systemd units. The installer does install Docker CE if it is absent, so container telemetry works — that step is best-effort and the install continues normally if it fails.

---

## Method Comparison

| Method | Best for | Port | Effort |
|---|---|---|---|
| [Native Systemd](quick-install.md#native-recommended) | Most Linux users — fastest path, no containers to manage | 443 (8088 redirects to it) | Low |
| [Proxmox LXC](proxmox-lxc.md) | Proxmox VE users — isolated container on the PVE host | 8088 (HTTPS) | Low |
| [Docker Compose](docker-compose.md) | Users who prefer containerised deployments | 80 / 443 | Low |
| [Single Docker Container](manual-docker.md) | One `docker run` behind your own reverse proxy | 8080 / 8443 (container) | Low |
| [From Source](docker-compose-source.md) | Developers building the image from the repository | 80 / 443 | Medium |

---

## Which Method Should I Choose?

**I want to get Circuit Breaker running as fast as possible on a Linux server.**
→ Use the [Quick Install script](quick-install.md). One command, no Docker required, under 2 minutes.

**I'm running Proxmox VE and want Circuit Breaker in an isolated LXC container.**
→ Use the [Proxmox LXC installer](proxmox-lxc.md). Runs on the PVE host, creates and configures the container automatically.

**I want to run Circuit Breaker as a container managed with Docker Compose.**
→ Use the [Docker Compose](docker-compose.md) method. It runs the single mono image, which bundles Postgres, Redis, NATS, the backend, the workers and nginx.

**I want to build the image from the repository.**
→ See [Docker Compose — From Source](docker-compose-source.md).

---

## After Installing

Regardless of method, your next steps are:

1. Open Circuit Breaker in your browser at the HTTPS URL the installer prints — `https://<host>/` for a native or Docker Compose install, `https://<container-ip>:8088` for Proxmox LXC. Plain HTTP redirects to HTTPS and cannot complete account creation, which requires a secure context.
2. Complete the **first-run setup wizard** — see [First-Run Setup](first-run.md).
3. Back up the vault key shown at the end of the wizard (only displayed once).
4. Optionally review the [Configuration Reference](configuration.md) to tune environment variables.

---

## Related Pages

- [First-Run Setup](first-run.md)
- [Single Docker Container](manual-docker.md)
- [Docker Compose — From Source](docker-compose-source.md)
- [Configuration Reference](configuration.md)
- [Upgrading](upgrading.md)
- [Uninstalling](uninstalling.md)
- [Deployment & Security](../deployment-security.md)
- [Remote Access & Tunnels](../remote-access.md)
