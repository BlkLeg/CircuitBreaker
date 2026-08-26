# Installation Overview

Circuit Breaker is a self-hosted homelab topology mapper. It installs natively on Linux via systemd — no Docker required. A container image is available as an alternative for users who prefer container-based deployments.

**This page is the authoritative comparison of installation modes.** Where another
document names a mode, it means what the [Deployment modes](#deployment-modes)
table below says it means.

For v1.0 release candidates, supported platforms and deployment modes are controlled by the
[v1.0 support contract](../release/1.0.0-support-contract.md). If this page describes a broader
workflow, treat it as beta or development guidance until the matching acceptance evidence is recorded.

---

## System Requirements

| Requirement | Minimum | Enforced how |
|---|---|---|
| **OS** | Linux (amd64, arm64) | Package/binary availability |
| **RAM** | 1 GB available | The native installer *warns* below 1024 MB and drops Redis `maxmemory` from 256 MB to 128 MB below 2048 MB |
| **Disk** | 3 GB free | The native installer *fails* below 3 GB free on `/`. on container and binary installs `cb doctor` warns below 1 GiB free on the data directory |
| **Network** | Outbound internet access (to download the installer and image) | — |

Those are the floor for the smallest deployment. Resources per workload profile, database sizing and
every bound the software enforces: [Sizing profiles](../operations/sizing-profiles.md).

> **Docker not required to run Circuit Breaker natively.** The default install method runs Circuit Breaker directly as systemd units. The installer does install Docker CE if it is absent, so container telemetry works — that step is best-effort and the install continues normally if it fails.

---

## Deployment Modes

Three words describe how Circuit Breaker's processes are laid out on a host.
Every other page uses them with the meanings fixed here.

| Mode | What it means | 1.0.0 status |
|---|---|---|
| **Native** | The backend, the workers and nginx run as systemd units directly on the host; PostgreSQL and Redis are ordinary host services. No container runtime is needed to run Circuit Breaker. | **Ships.** The default and recommended install. |
| **Mono** | One image — `ghcr.io/blkleg/circuitbreaker`, built from `Dockerfile.mono` — runs PostgreSQL, PgBouncer, Redis, NATS, the backend, the workers and nginx together under supervisord. | **Ships.** Every container install on this page is this one image. |
| **Split** | Backend, frontend, database, Redis and NATS each in their own container, composed together. | **Does not ship in 1.0.0.** |

### Why there is no split mode

The repository's `docker-compose.yml` declares exactly one service,
`circuitbreaker`, built from `Dockerfile.mono` — that is mono. No Compose file
in the repository wires separate backend, frontend, database and Redis
containers together, so there is nothing to install, and nothing that CI builds,
scans or smoke-tests.

Two files look like a split stack and are not one:

- `docker-compose.deps.yml` starts PostgreSQL, Redis and NATS with development
  credentials for `make dev`. It starts no Circuit Breaker process at all — it
  is a developer dependency stack, not a deployment.
- `docker/backend.Dockerfile` and `docker/frontend.Dockerfile` are development
  images. No shipped Compose file references either one.

If another document tells you split Compose is a supported 1.0 channel, that
document is wrong — please open an issue.

### Single-node, and what that costs

Native and mono are two ways of laying out **one node**. The mono image is a
**single-node appliance**: PostgreSQL, PgBouncer, Redis, NATS, the backend, the six
workers and nginx run as twelve supervised programs in one container, sharing one
lifecycle. Restarting it restarts the database.

**High availability is [unsupported for 1.0.0](../release/1.0.0-support-contract.md#deployment-support-matrix)** —
one active application server, no clustering, no failover. Availability comes from
backups and maintenance windows instead. What that means operationally, and what happens
when the node goes away: [Single-node appliance and availability](../operations/appliance-and-availability.md).

---

## Method Comparison

| Method | Mode | Best for | Port | Effort |
|---|---|---|---|---|
| [Quick Install — native](quick-install.md#native-recommended) | Native | Most Linux users — fastest path, no containers to manage | 443 (8088 redirects to it) | Low |
| [Proxmox LXC](proxmox-lxc.md) | Native, inside an LXC the helper creates | Proxmox VE users — isolated container on the PVE host | 8088 (HTTPS) | Low |
| [Docker Compose](docker-compose.md) | Mono | Users who prefer a containerised deployment they can `compose up` | 80 / 443 | Low |
| [Single Docker Container](manual-docker.md) | Mono | One `docker run` behind your own reverse proxy | 8080 / 8443 (container) | Low |
| [From Source](docker-compose-source.md) | Mono | Developers building the image from the repository | 80 / 443 | Medium |

The last three rows are three ways to run the *same* mono image. They differ in
how the container is started, not in what runs inside it.

---

## Which Method Should I Choose?

**I want to get Circuit Breaker running as fast as possible on a Linux server.**
→ Use the [Quick Install script](quick-install.md). One command, no Docker required, under 2 minutes. This is native mode.

**I'm running Proxmox VE and want Circuit Breaker in an isolated LXC container.**
→ Use the [Proxmox LXC installer](proxmox-lxc.md). Runs on the PVE host, creates the container and installs natively inside it.

**I want to run Circuit Breaker as a container managed with Docker Compose.**
→ Use the [Docker Compose](docker-compose.md) method. It runs the mono image, which bundles Postgres, Redis, NATS, the backend, the workers and nginx.

**I want one container and my own reverse proxy in front of it.**
→ Use [Single Docker Container](manual-docker.md). Same mono image, started with `docker run`.

**I want to build the image from the repository.**
→ See [Docker Compose — From Source](docker-compose-source.md). It builds the same mono image.

**I want each service in its own container.**
→ Not available in 1.0.0. See [Why there is no split mode](#why-there-is-no-split-mode).

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
- [Single-node appliance and availability](../operations/appliance-and-availability.md)
- [Sizing profiles](../operations/sizing-profiles.md)
