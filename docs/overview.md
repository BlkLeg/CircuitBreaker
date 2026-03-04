# Circuit Breaker Overview

Circuit Breaker helps you keep your infrastructure understandable, searchable, and change-ready.

Use it to document what you run, where it runs, and what depends on what—then view everything in one live map.

---

## What You Can Manage

- **Hardware:** Physical devices like servers, switches, firewalls, NAS, and UPS.
- **Compute:** VMs and containers that run on your hardware.
- **Services:** Apps and workloads, including URLs, ports, and ownership.
- **Storage:** Shared and local storage resources.
- **Networks:** VLANs, subnets, and connectivity context.
- **Notes & Runbooks:** Markdown notes attached to real assets.

---

## How the App Helps Day-to-Day

### Keep relationships clear

Follow service dependencies from app → compute → hardware → storage/network.

### Move faster during maintenance

Before touching a host, quickly see what services and dependencies are affected.

### Keep your team aligned

Store runbooks and operational notes right on the assets they belong to.

### Review recent changes

Use audit history and recent activity to understand what changed and when.

---

## Visual Topology Map

The topology map gives you an at-a-glance view of your environment.

- Pan and zoom through your infrastructure.
- Open entities directly from the map.
- Track live health indicators on supported hardware when telemetry is configured.

---

## Discovery (Beta)

Circuit Breaker includes **Auto-Discovery (Beta)** to help you find devices and services faster.

- Create scan profiles for recurring scans.
- Run one-time ad-hoc scans.
- Review findings before they are merged.
- Keep control: nothing is added automatically without approval.

See [Auto-Discovery (Beta)](discovery.md).

---

## Configuration and Operations

- **Settings:** Language, timezone, visuals, map defaults, and system behavior.
- **Backup & Restore:** Export and restore inventory snapshots.
- **Deployment & Security:** Start quickly for lab use, then harden as needed.

See [Settings](settings.md), [Backup & Restore](backup-restore.md), and [Deployment & Security](deployment-security.md).