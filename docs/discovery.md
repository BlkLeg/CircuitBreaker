# Auto-Discovery (Beta)

Auto-Discovery helps you find devices and services in your network, then add them to Circuit Breaker with review and control.

> **Beta status:** Discovery is available now and actively improving. Use it with care in sensitive environments.

---

## What Discovery Does

- Scans selected network ranges.
- Finds hosts and service signals.
- Places findings into a review queue.
- Lets you approve and merge only what you want.

Nothing is added automatically without your approval.

---

## Discovery Workflow

### 1) Create a scan profile

Use **Scan Profiles** when you want a repeatable scan target.

A profile typically includes:

- A name
- Target range (CIDR)
- Scan method settings
- Schedule options

### 2) Run an ad-hoc scan

Use **Ad-hoc Scan** for one-time checks.

This is useful after changes like:

- New subnet rollout
- Device migration
- Service move

### 3) Review findings

Open the **Review Queue** to inspect discovered items before import.

You can:

- Merge one result at a time
- Bulk merge selected results
- Skip items that are not needed

### 4) Track progress and history

Use **Scan History** to see completed, running, canceled, and failed jobs.

---

## Safety and Good Practice

- Start with a small range first.
- Run scans during low-traffic windows.
- Review every merge carefully.
- Keep recurring scans targeted instead of broad.

If your environment has strict network controls, coordinate scanning windows before first use.

---

## ARP Scanning and Docker Desktop

Circuit Breaker supports an ARP scan phase that resolves MAC addresses and improves host detection reliability on local subnets. This phase requires elevated Linux capabilities (`NET_RAW`, `NET_ADMIN`) and the container must run with `network_mode: host` to reach your LAN directly.

**This configuration is incompatible with Docker Desktop** (macOS or Docker Desktop for Linux). Docker Desktop runs all containers inside a lightweight VM, so `network_mode: host` attaches the container to the VM's network rather than your actual LAN. It also breaks the nginx → backend proxy that the frontend relies on, resulting in a 502 error on every page load.

### Default behavior (Docker Desktop and all platforms)

ARP scanning is disabled by default. Circuit Breaker automatically falls back to nmap TCP/ICMP host detection, which:

- Works on all platforms and Docker environments.
- Finds hosts and open ports without MAC address resolution.
- Does not require any special Linux capabilities.

All other scan phases (nmap, SNMP, HTTP probing) are fully functional.

### Enabling ARP scanning (native Linux Docker only)

If you are running native Docker on Linux (not Docker Desktop), you can enable the ARP scan phase for MAC address resolution and more reliable LAN discovery:

1. Open `docker/docker-compose.yml`.
2. In the `backend` service, uncomment the `cap_add` and `network_mode` blocks:
   ```yaml
   cap_add:
     - NET_RAW
     - NET_ADMIN
   network_mode: "host"
   ```
3. In the `frontend` service, uncomment the `extra_hosts` block:
   ```yaml
   extra_hosts:
     - "backend:host-gateway"
   ```
4. Run `make compose-up` to rebuild and restart the stack.

> **Security note:** `NET_RAW` and `NET_ADMIN` allow the container to craft and send arbitrary raw network packets. Only enable this on trusted, isolated homelab networks.

> **Docker Desktop users:** A workaround for enabling ARP scanning under Docker Desktop is being investigated. Track progress in the project issue tracker.

---

## Troubleshooting Basics

- **No results:** verify target range and network reachability.
- **Too many results:** narrow CIDR scope and use more specific profiles.
- **Scan failed:** retry once, then check permissions and environment constraints.
- **Unexpected matches:** keep findings in queue and merge only confirmed assets.
- **502 error on page load:** this is caused by `network_mode: host` being enabled while running Docker Desktop. Comment out the `cap_add`, `network_mode`, and `extra_hosts` blocks in `docker/docker-compose.yml` and run `make compose-up` again.

---

## Related Guides

- [Settings](settings.md)
- [Topology Map](topology-map.md)
- [Audit Log](audit-log.md)
