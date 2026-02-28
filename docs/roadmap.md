# Product Roadmap

Circuit Breaker is actively evolving. Our primary focus right now is reaching the **V1 Full Release**, which will introduce major capabilities to transition the tool from a purely manual documentation system into an intelligent infrastructure hub.

Below is a high-level overview of our current priorities and the features planned for the road ahead.

---

## 🚀 The Road to V1: Top Priorities

The V1 release is centered around two massive, highly-requested features designed to save you time and provide deeper physical context to your infrastructure.

### 1. Auto-Discovery

Say goodbye to entirely manual data entry. We are building a robust, agentless discovery engine that will optionally scan your networks to find devices and services automatically.

- **Network Probing:** Utilize Nmap, SNMP, and ARP scans to discover active hosts.
- **Intelligent Matching:** The system will identify OS families, vendors, and open ports, suggesting the correct hardware and service entities.
- **Review Queue:** You remain in control. Discovered items go into a pending queue where you can review, edit, and approve them before they are merged into your topology.
- **Scheduled Scans:** Set up recurring discovery jobs to catch new devices as they join your network.

### 2. Interactive Rack Map (Simulator)

Visualizing logical connections is great, but physical context is just as important. The Rack Map will allow you to build digital twins of your server racks.

- **Drag-and-Drop Elevation:** Position your 1U/2U servers, switches, and patch panels within standard rack enclosures.
- **Spatially Aware Inventory:** The rack view _is_ your hardware inventory. Moving a server in the rack updates its location metadata instantly.
- **Power Budgeting:** Track power draw across the rack to ensure you aren't overloading your UPS or PDU circuits.

---

## 🗺️ Planned Features (Post-Beta & Beyond)

As we work towards V1, several other major feature sprints are planned to round out the Circuit Breaker experience.

### IP & Network Intelligence

- **Visual IPAM:** See exactly which IP addresses are allocated, available, or generating conflicts within your defined subnets.
- **Port Conflict Warnings:** Receive immediate alerts if multiple services on the same compute unit attempt to bind to the same network port.

### Service Health & Alerting

- **Status Webhooks:** Push notifications to Discord, Slack, or custom endpoints whenever a service goes up or down.
- **Certificate Tracking:** Automatically monitor TLS certificates for your documented services and get warned before they expire.
- **Uptime Sparklines:** Visual, 30-day historical graphs of service status changes.

### Topology Enhancements

- **Map Zones:** Draw colored, named zones directly on the topology map (e.g., "DMZ", "Management VLAN") to grouped related infrastructure visually.
- **Blast Radius Analysis:** Select a core switch or hypervisor and instantly highlight the full downstream dependency chain to see exactly what goes offline if that node fails.
- **High-Res Export:** Export your fully rendered map to PNG or SVG for easy inclusion in runbooks or presentations.

### Collaboration & Access

- **Role-Based Access Control (RBAC):** Restrict accounts to Admin, Editor, or read-only Viewer roles.
- **Named API Keys:** Generate scoped tokens for integrating external scripts or CI/CD pipelines.
- **Shareable Dashboard Links:** Generate secure, read-only URLs to share a live view of your topology on a wallboard or with contractors, without requiring them to log in.

### Hardware Lifecycle Management

- **Custom Fields:** Define your own metadata fields (e.g., Asset Tags, Purchase Dates) to track the exact information that matters to your business.
- **Warranty Tracking:** Dashboard widgets highlighting hardware approaching the end of its warranty or support lifecycle.

### Integrations

- **Proxmox Sync:** Automatically pull VM and container inventory directly from your Proxmox clusters.
- **Live Metrics Display:** Integrate with Netdata or Pulse to display live CPU and memory utilization gauges directly on your hardware nodes within Circuit Breaker.
- **CSV Bulk Operations:** Robust import/export wizards for users migrating from existing spreadsheet trackers.
