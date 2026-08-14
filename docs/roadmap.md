# Product Roadmap

Circuit Breaker is actively evolving. This page shows what is already available and what is planned next.

---

## Available Now

- Full inventory tracking for hardware, compute, services, storage, and networks.
- Interactive topology map with dependency visibility.
- Notes and runbooks attached to assets.
- Audit history with filters and search.
- Auto-Discovery (Beta) with review-before-merge workflow.
- Backup export and restore import.
- **Monitoring**: native check engine (ICMP, TCP, HTTP, DNS) at `/monitors` with live status, uptime and latency history, and one-click monitoring on hardware, compute units, and services.
- Remote probe agents: enroll and approve agents, then run checks and discovery from other network segments.
- Interactive rack editor with cable overlay.
- IPAM center for IP addresses, subnets, VLANs, and sites, with per-network IP scanning.
- Multiple saved topology maps with a map switcher.
- Certificate manager for tracking certificates and triggering renewals.

---

## Next Priorities

### 1) Discovery Maturity and Coverage

- Improve scan quality and result confidence.
- Expand service and device matching.
- Improve scheduling and operational visibility.

### 2) Physical Context Enhancements

- Improve planning views for hardware placement and capacity.

### 3) Topology Insights

- Better impact views for dependency chains.

---

## Planned Improvements

### Network and Address Management

- IP conflict handling workflows.
- Easier network-level troubleshooting context.

### Health and Alerts

- More check types (push, database, message-queue probes) and maintenance windows.
- Broader health status integrations.
- More alert and notification options.

### Collaboration and Access

- Better sharing and access controls for teams.
- Safer integration paths for external tools.
- True multi-tenancy for MSP, consultant, community lab, hosted, or strict multi-team deployments.
  For v1, use separate Circuit Breaker deployments for separate trust boundaries.

### Import and Interoperability

- Better migration helpers for existing inventories.
- Expanded integration options for common infrastructure ecosystems.

---

## Release Notes

For version-by-version changes, see the [Updates](updates/v0.3.3_release.md) section in the docs navigation.
