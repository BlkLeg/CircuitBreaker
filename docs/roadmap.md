# Product Roadmap

Circuit Breaker is actively evolving. This page shows what is already available and what is planned next.

---

## Available Now

- Full inventory tracking for hardware, compute, services, storage, and networks.
- Interactive topology map with multi-map support, dependency visibility, and live telemetry.
- Notes and runbooks attached to assets.
- Audit history with filters, search, and tamper-evident hash chain.
- Auto-Discovery (Beta) with safe mode (no NET_RAW required) and review-before-merge workflow.
- Backup export and restore import.
- **IPAM**: Unified 4-tab network management center — Networks, IP Addresses, VLANs, and Sites.
- **Certificates**: Track TLS/SSL certificate expiry across your homelab.
- **External / Cloud Nodes**: Document cloud VMs, managed databases, SaaS dependencies, and other external resources on the topology map.
- **Status Pages**: Create public-facing status boards backed by your Circuit Breaker monitors.
- **Interactive Rack Editor**: Drag-and-drop hardware placement, cable visualization, and U-slot management.
- **Native Monitoring**: Built-in ICMP ping, HTTP health check, and TCP port monitors — no external tool required.
- **Notifications Center**: Configure Slack, Discord, Teams, and email notification sinks with routing rules.
- **Tenant Management**: Isolate different environments within the same Circuit Breaker installation.
- **Proxmox Integration**: One-click cluster import with live telemetry for nodes, VMs, and LXC containers.

---

## Next Priorities

### 1) Discovery Maturity and Coverage

- Improve scan quality and result confidence.
- Expand service and device matching.
- Improve scheduling and operational visibility.

### 2) Physical Context Enhancements

- Expand rack-focused workflows and visuals.
- Improve planning views for hardware placement and capacity.

### 3) Topology Insights

- Better impact views for dependency chains.
- More visual controls for map readability and sharing.

---

## Planned Improvements

### Network and Address Management

- Richer IP visibility and conflict handling workflows.
- Easier network-level troubleshooting context.

### Health and Alerts

- Broader health status integrations.
- More alert and notification routing options.

### Collaboration and Access

- Better sharing and access controls for teams.
- Safer integration paths for external tools.

### Import and Interoperability

- Better migration helpers for existing inventories.
- Expanded integration options for common infrastructure ecosystems.

---

## Release Notes

For version-by-version changes, see the [Updates](updates/v0-1-4_release.md) section in the docs navigation.
