# Installation Overview

Circuit Breaker is a homelab topology mapper that runs as a self-hosted Docker application. This section covers every supported installation method so you can choose the one that fits your environment.

---

## System Requirements

| Requirement | Minimum |
|---|---|
| **OS** | Linux (amd64, arm64, arm/v7) |
| **Docker** | Engine 20+ with Compose plugin v2 |
| **RAM** | 1 GB available |
| **Disk** | 500 MB for image + space for your data volume |
| **Network** | Outbound access to `ghcr.io` to pull the image |

> **macOS / Windows:** Circuit Breaker runs inside Docker Desktop. All install methods work the same — replace Linux-specific steps (systemd, CA cert import) with the platform equivalents described in [Configuration Reference](configuration.md#trusting-the-self-signed-ca-certificate).

---

## Method Comparison

| Method | Best for | HTTPS | Effort |
|---|---|---|---|
| [Quick Install (Script)](quick-install.md) | Most Linux users — fastest path to the standard deployment | Auto via Caddy | Low |
| [Docker Compose — Prebuilt Full Stack](docker-compose-prod.md) | The same standard deployment, managed manually | Auto via Caddy | Low |
| [Docker Compose — From Source](docker-compose-source.md) | Contributors or custom builds | Auto via Caddy | Medium |

---

## Which Method Should I Choose?

**I just want to get Circuit Breaker running as fast as possible with full capability (discovery, webhooks, HTTPS).**
→ Use the [Quick Install script](quick-install.md). One command, no build, under 60 seconds.

**I want to manage the compose files directly but still get the same supported Docker experience.**
→ Use [Docker Compose — Prebuilt Full Stack](docker-compose-prod.md). It is the manual equivalent of the installer.

**I want to build Circuit Breaker from source (or contribute to development).**
→ Use [Docker Compose — From Source](docker-compose-source.md). Clones the repo and builds images locally.

**I have a very custom environment and still want a reduced or proxy-managed container flow.**
→ See the advanced references: [Advanced Compose Reference](docker-compose.md) and [Advanced Single Container Reference](manual-docker.md). These are not the standard supported install path.

---

## After Installing

Regardless of method, your next steps are:

1. Open Circuit Breaker in your browser.
2. Complete the **first-run setup wizard** — see [First-Run Setup](first-run.md).
3. Back up the vault key shown at the end of the wizard (only displayed once).
4. Optionally review the [Configuration Reference](configuration.md) to tune environment variables.

---

## Related Pages

- [First-Run Setup](first-run.md)
- [Configuration Reference](configuration.md)
- [Upgrading](upgrading.md)
- [Uninstalling](uninstalling.md)
- [Advanced Compose Reference](docker-compose.md)
- [Advanced Single Container Reference](manual-docker.md)
- [Deployment & Security](../deployment-security.md)
- [Remote Access & Tunnels](../remote-access.md)
