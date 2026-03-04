# Welcome to Circuit Breaker

If you run a homelab, this is your command notebook.

Circuit Breaker helps you document what you built, where it runs, and what depends on what — so upgrades and outages are less stressful.

---

## What to Track in Here

Use this Docs page (and attached docs) to keep notes for:

- Hardware (hosts, NAS, switches, firewalls, UPS)
- Compute (VMs and containers)
- Services (apps like Jellyfin, AdGuard Home, Home Assistant)
- Networks (VLANs, subnets, gateways)
- Storage (pools, datasets, shares)
- Recovery steps and maintenance checklists

---

## Simple Homelab Workflow

When adding something new, this order keeps your map clean:

1. Add the physical **Hardware**
2. Add the **Compute** instance running on it
3. Add required **Network** and **Storage**
4. Add the **Service**
5. Attach/update docs with install + rollback notes

---

## App Example: Jellyfin on a Docker VM

Example topology chain:

- Hardware: `pve-node-01`
- Compute: `docker-host-01` (Ubuntu VM)
- Service: `Jellyfin`
- Storage dependency: `media-nfs-share`
- Network dependency: `VLAN30_SERVICES`

Suggested runbook sections:

1. Purpose
2. Access URL + auth notes
3. Update steps (`docker compose pull && docker compose up -d`)
4. Rollback steps
5. Backup/restore notes

---

## Network Example: Segmented VLAN Layout

Example network model:

- `VLAN10_MGMT` — Proxmox, switches, hypervisor admin IPs
- `VLAN20_CLIENTS` — laptops, phones, TVs
- `VLAN30_SERVICES` — self-hosted apps (Jellyfin, Home Assistant, Grafana)
- `VLAN40_IOT` — cameras, smart plugs, IoT devices

Document for each network:

- CIDR (example: `10.30.0.0/24`)
- Gateway/router interface
- DNS/NTP behavior
- Firewall policy summary (what is allowed to talk across VLANs)

---

## Map + Ops Tips

- Use the **Topology Map** as your day-to-day visual dashboard.
- Save layout changes (positions, boundaries, labels) after edits.
- Use icon picker uploads to make critical nodes stand out.
- Check the **Audit Log** when troubleshooting “what changed?” moments.

---

## Starter Template

```md
# Service Runbook: <service-name>

## Purpose

## Location
- Hardware:
- Compute:
- Network(s):
- Storage:

## Access
- URL:
- Port:

## Update Procedure
1.
2.
3.

## Rollback
1.
2.

## Notes
```

---

## First Task

Pick one service you rely on every week and document it fully today.

Future-you will thank you during the next outage or late-night upgrade.
