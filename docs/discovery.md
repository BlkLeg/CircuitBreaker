# Auto-Discovery (Beta)

Auto-Discovery helps you find devices and services in your network, then add them to Circuit Breaker with review and control.

> **Beta status:** Discovery is available now and actively improving. Use it with care in sensitive environments.

---

## What Discovery Does

- Scans selected network ranges.
- Finds hosts and service signals.
- Places findings into a review queue.
- Lets you approve and merge only what you want.

New devices require review by default. Findings that match existing devices can automatically fill missing details and refresh their last-seen time.
The one exception is opt-in: if you turn on **Auto-Merge New Hosts** under **Discovery → Scan Settings**, newly
discovered hosts are turned into hardware entities without review.

---

## Discovery UI (current)

The Discovery page has a **left sidebar** with a **New Scan** button, a **Discover Docker** button, a **Scans** list, and a **Configuration** group containing **Proxmox VE**, **OPNsense**, **Scan Profiles**, **Review Queue**, and **Scan Settings**. The "New Scan" view shows a **Scan from** selector, scan mode cards, **Target Scope** (Single CIDR or VLANs), **Scan Types** (e.g. SNMP, HTTP), and Start Scan / Cancel.

If you see a different layout, you are on an outdated frontend. Pull the current image and restart (`docker compose pull && docker compose up -d` in your install directory), then hard-refresh the browser (Ctrl+Shift+R).

**Scan reports 0 hosts:** This can happen if the scanner cannot reach the target network (e.g. the container runs on a Docker bridge and the target is 192.168.1.0/24 on the host LAN). Make sure the container has a route to the target CIDR, or run the scan from an agent that sits on that segment.

---

## Before Your First Scan

### Scan authorization

The first time you start a scan, a modal appears that cannot be dismissed by clicking away. It states that
network scanning may be illegal without explicit authorization from the network owner, and requires you to
tick **"I own or have explicit written authorization to scan this network"** before the scan runs. The
acknowledgment is recorded once per instance. An admin can clear it again under
**Discovery → Scan Settings → Legal → Scan Authorization**.

### Nmap Active Scanning

**Nmap Active Scanning** under **Discovery → Scan Settings → Scan Mode** is a persistent safety gate for
nmap-based scans. It is the prerequisite for the Full and Deep Dive modes — while it is off, both mode
cards are disabled. Keep it disabled until you have explicit authorization for the networks you intend
to scan.

---

## Discovery Workflow

### 1) Choose a Discovery Mode

Circuit Breaker allows you to balance discovery depth against network safety and isolation requirements:

- **Safe (default):** Ping plus TCP connect. No `NET_RAW` required, so it works in a stock container.
- **Full:** ARP sweep plus nmap OS fingerprint. Requires `NET_RAW`.
- **Deep Dive:** Full scan plus L0 fingerprinting (rDNS, NetBIOS, mDNS, SSDP, HTTP). Requires `NET_RAW`.
- **Docker:** Enumerates containers from the Docker socket. This is **opt-in** for security — by default the socket is not mounted. To enable it, run Compose with the socket override from the repo root: `docker compose -f docker-compose.yml -f docker/docker-compose.socket.yml up -d`. With the socket mounted, discovery can read container configuration, populate Docker network modes (bridges, overlays), and map container services to exposed ports. Turn on **Container Discovery** under **Settings → Integrations → Docker Integration**.
- **OPNsense:** Pulls DHCP leases and the ARP table directly from OPNsense — instant, with no subnet sweep. Configure the firewall under **Discovery → OPNsense**.

Full and Deep Dive are only selectable when **Nmap Active Scanning** is enabled (see above); with it off, both cards are disabled and the mode falls back to Safe.

### 2) Create a scan profile

Use **Scan Profiles** when you want a repeatable scan target.

A profile typically includes:

- A name
- Target range (CIDR)
- Scan method settings (Safe vs. Full)
- Schedule options

### 3) Run an ad-hoc scan

Use **Ad-hoc Scan** for one-time checks.

This is useful after changes like:

- New subnet rollout
- Device migration
- Service move

### 4) Review findings

Open the **Review Queue** to inspect discovered items before import.

Repeated observations of the same device share one pending review item within the same tenant and network scope. The other observations remain in scan history with a `duplicate` status. Different known MAC addresses at a shared IP and distinct conflicts remain separate for review. Docker and Proxmox retain their integration-specific identity handling.

On backend startup, existing pending duplicates are consolidated and older findings are checked against the current inventory. Accepting a finding also rechecks inventory, so accepting stale scan results does not create the same device again.

You can:

- Merge one result at a time
- Bulk merge selected results
- Skip items that are not needed

### 4) Track progress and history

Use **Scan History** to see completed, running, canceled, and failed jobs.

---

## Running a Scan from an Agent

The **Scan from** selector at the top of the New Scan view chooses where the scan executes:
**Circuit Breaker server** (the default) or one of your registered agents.

An agent runs a bounded connect-based sweep of its own segment and nothing else — it bundles no scanner.
Selecting an agent therefore forces the Safe mode and its fields: no nmap arguments, no SNMP community,
no Docker socket. Every other mode card is disabled while an agent is selected. Agents that cannot take
the scan are listed with the reason underneath the selector.

Use an agent when the target subnet is reachable from the agent but not from the Circuit Breaker server.

---

## Docker sources

Docker discovery is organised around **sources** rather than one anonymous scan. A source is a
configured daemon endpoint with a stable identity, its own history, and its own host association.
**Discovery → Docker** shows one card per source.

### What a sync establishes, and what it does not

Each sync records an outcome and a completeness flag, and the card reports them separately. This
matters because an empty result and a failed one used to look identical — a bare empty list — and
reconciliation could not tell "this host runs nothing" from "the daemon did not answer".

| Outcome | What it means | What reconciliation does |
|---|---|---|
| **Synced** | The daemon was reachable and its container list is complete | Containers that disappeared are marked stopped |
| **Partial sync** | Some containers were read; coverage is incomplete | Nothing is marked stopped — an unseen container is not a confirmed absent one |
| **Sync failed** / **interrupted** | Enumeration did not complete | Prior inventory and the last success timestamp are preserved untouched |
| **Never synced** | No attempt has completed | Nothing is inferred |

**Last attempt** and **last success** are shown as two separate values on purpose. A source whose
daemon has been down for a week still shows last week's success, and the card says plainly that
what you are looking at is the last good picture rather than the current one.

### Host association and manual overrides

A source's containers hang off its parent host. That parent is recorded with its provenance:

- **You set it** — the assignment is kept as-is, and rediscovery will not overwrite it.
- **Resolved automatically** — a later sync may replace it. Set it yourself to pin it.
- **Unresolved** — the containers have no parent until you assign one. The card says so.

Assigning a host sends the source revision you were looking at. If the source changed in the
meantime, the correction is refused rather than silently landing on top of someone else's — the
panel reloads and asks you to look again.

### Stopped and stale containers

A container marked **stopped** was observed absent by a *complete* enumeration. A container that
simply was not seen during a partial or failed sync is left exactly as it was: Circuit Breaker does
not infer that something is gone from a reading it knows to be incomplete.

Recreated containers are matched on their durable identity, not their display name, so restarting a
container does not produce a duplicate and a similarly named container on another host does not
absorb it.

## Safety and Good Practice

- Start with a small range first.
- Run scans during low-traffic windows.
- Review every merge carefully.
- Keep recurring scans targeted instead of broad.

If your environment has strict network controls, coordinate scanning windows before first use.

---

## ARP Scanning and Docker Desktop

Circuit Breaker has an ARP scan phase that resolves MAC addresses and improves host detection on local subnets. It needs two things: the `NET_RAW` capability, and Layer 2 adjacency to the subnet being scanned.

The shipped `docker-compose.yml` already grants `NET_RAW` to the `circuitbreaker` container — it drops all capabilities and adds back only the ones the container needs. It does **not** offer `NET_ADMIN` or `network_mode: host`, so the container reaches your network through the Docker bridge.

Layer 2 adjacency is the part Compose cannot grant. When the container sits on a Docker bridge and the target subnet is elsewhere on your LAN, ARP has nothing to resolve and Circuit Breaker falls back to nmap TCP/ICMP host detection, which:

- Works on all platforms and Docker environments.
- Finds hosts and open ports without MAC address resolution.
- Does not require Layer 2 adjacency.

All other scan phases (nmap, SNMP, HTTP probing) are fully functional either way.

**Docker Desktop** (macOS, or Docker Desktop for Linux) runs every container inside a lightweight VM, so the container is never adjacent to your real LAN and MAC resolution is not available there.

Admins can see exactly what the running instance can do with `GET /api/v1/discovery/readiness`, which reports the nmap binary, raw-socket privilege, ARP/MAC resolution, and LAN adjacency separately.

> **Security note:** `NET_RAW` allows the container to craft and send raw network packets. This is why the container is otherwise capability-stripped, read-only, and started with `no-new-privileges`.

---

## Troubleshooting Basics

- **No results:** verify target range and network reachability.
- **Too many results:** narrow CIDR scope and use more specific profiles.
- **Scan failed:** retry once, then check permissions and environment constraints.
- **Unexpected matches:** keep findings in queue and merge only confirmed assets.

---

## Related Guides

- [Settings](settings.md)
- [Topology Map](topology-map.md)
- [Audit Log](audit-log.md)

## Naming hints

Vendor and device-type identification draws on two operator-editable lookup
tables in addition to the curated device catalogue. See
[Knowledge Base](knowledge-base.md) for how learned entries accumulate and how
to correct them.
