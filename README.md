# Circuit Breaker

![Circuit Breaker Logo](screenshots/cb_night-full.png)

> **⚠️ SECURITY WARNING (BETA RELEASE v0.1.0):**  
> This application is currently in beta. It has not yet undergone a full security audit. Please run this application strictly on a secure, local network (e.g., your homelab or a private intranet). **Do not expose it directly to the public internet.** Ensure you take your own precautions for securing the app and safeguarding your data until the full production release.

The **Circuit Breaker** (formerly Service Layout Mapper) is a tool designed to help you easily document, track, and visualize your homelab or small business network topology.

## Quick Start

You can run Circuit Breaker either as a **single container** (fastest local setup) or with **Docker Compose** (split frontend/backend services).

### Option A — Single Image (`docker run`)

```bash
# 1) Build the image
docker build -t circuit-breaker:beta .

# 2a) Run with localhost-only binding (recommended for homelab / beta):
docker run --rm -p 127.0.0.1:8080:8080 -v circuit-breaker-data:/data circuit-breaker:beta

# 2b) Run bound to all host interfaces (only if your router/firewall controls external access):
docker run --rm -p 8080:8080 -v circuit-breaker-data:/data circuit-breaker:beta
```

Open: [http://localhost:8080](http://localhost:8080)

> **Note:** Option 2a binds the port exclusively to `127.0.0.1` so only the local machine can reach it. Option 2b binds to `0.0.0.0`, exposing the port on every host interface including any public-facing ones. Use 2b only if you are behind a firewall or intentionally serving your LAN.

### Option B — Docker Compose (`docker/docker-compose.yml`)

```bash
# Build and start both services (frontend + backend)
docker compose -f docker/docker-compose.yml up -d --build
```

> **Note:** The default Compose file exposes port 8080 on all interfaces. For local-only access, edit `docker/docker-compose.yml` and change `"8080:8080"` to `"127.0.0.1:8080:8080"` before starting.

Open: [http://localhost:8080](http://localhost:8080)

### First-run OOBE / reset data

- On a fresh database, the app opens the first-run OOBE wizard to create the initial admin account.
- To reset to a fresh state:

```bash
# Single-image volume reset
docker volume rm -f circuit-breaker-data

# Compose stack + volume reset
docker compose -f docker/docker-compose.yml down -v
```

## Screenshots

### Login Screen

![Login Screen](screenshots/01-Login.png)

### Cluster-Centric Topology View

![Cluster-Centric Topology View](screenshots/01-cluster.png)

### Custom Layout Example

![Custom Layout Example](screenshots/01-custom-layout.png)

### Hardware Inventory Page

![Hardware Inventory Page](screenshots/01-hardware-page.png)

### Top-Down Topology Layout

![Top-Down Topology Layout](screenshots/01-top-down.png)

## Documentation

For more information on using the tool and our upcoming plans, please refer to:

- [Architecture & Overview](docs/OVERVIEW.md)
- [Project Roadmap](docs/ROADMAP.md)
- [Beta Pre-Flight Checklist](PRE_PKG.md)

Build docs locally with Zensical:

```bash
source .venv/bin/activate
make docs-build
make docs
```

## Inspiration

Netbox was my first attempt at IPAM. I only have two quarrels with it as a first time user back then:

1. It was too complex to navigate quickly and consistently.
2. There was no visual aspect that represents my lab. In their defense, it took me quite some time to come to that realization for myself.

At the time, I also had a lesser understanding of various aspects of IT and server documentation in generation. There's a very good chance I could feel differently now. To each their own.

### Disclaimer

This app was vibe coded from the ground up with a twist. I spent a week in the planning phase, simply listing the features and workflow I wanted to see in Notion. Then, each phase of the program was designed and tested in phases. At no point was any large element of this app built in "one shot". To keep the code honest, I use a combination of Dependabot, SonarQube, Snyk, and sentry to monitor for CVEs and bugs. Before the deployment of the BETA, all crictical and high risk vulnerabilities were patched.

As we move closer to v1, the code itself will become increasingly optimized for stability and maintainability. This will include things like having code that has low cognitive complexity, is self-explanatory with minimal help from comments, 

### Promises

1. I will never charge for this app. As such, no paid contributors will be working on this app. Donations are always welcome, but don't feel obligated.
2. O
