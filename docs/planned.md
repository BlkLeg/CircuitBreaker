# Planned Features

Features planned for post-beta full release sprints. Items in the [v2 roadmap](v2-roadmap.md) cover the upcoming beta.

---

## Sprint A — IP & Network Intelligence

### A1 — IPAM (IP Address Management)

- Visual subnet map showing allocated vs. available IPs within each network's CIDR
- Highlight conflicts (same IP assigned to multiple entities)
- Quick "assign next free IP" helper on entity forms
- Built on top of the existing `networks`, `hardware_networks`, `compute_networks` tables — no new entities needed

### A2 — Port Conflict Detection

- Parse the `services.ports` free-text field and warn when two services on the same compute unit share a port
- Surface conflicts in the service detail HUD and as a badge on the map node

---

## Sprint B — Service Health & Alerting

### B1 — Status Change Webhooks

- When a service's `status` field changes, fire a configurable webhook payload
- Support Discord, Slack, and generic HTTP targets
- Store webhook configs in `app_settings` (JSON array of `{ label, url, events[] }`)
- Purely event-driven off existing CRUD — no external polling

### B2 — Status History Sparklines

- Lightweight `status_history` table: `(service_id, status, recorded_at)` — append-only, pruned after N days
- 30-day sparkline per service in the Services table and detail HUD

### B3 — Certificate Expiry Tracking

- Optional `cert_expiry` date field on `services`
- Background task scans services with URLs and checks TLS expiry
- Badge on service entities when expiry is <30 days; highlight on map nodes

---

## Sprint C — Asset & Hardware Lifecycle

### C1 — Custom Fields per Entity Type

- User-defined metadata fields (e.g. "Serial Number", "Purchase Date", "Asset Tag") stored as JSON
- Managed in Settings → Custom Fields; rendered in entity forms and detail panels
- Stored as a `custom_fields` JSON column added via migration — no schema redesign

### C2 — Hardware Lifecycle / Cost Center

- Add `purchase_date`, `warranty_expiry`, `purchase_price` fields to `hardware`
- Dashboard widget showing approaching warranty expirations
- Optional `monthly_cost` on services for tracking hybrid/cloud spend with budget totals

---

## Sprint D — Topology & Map Enhancements

### D1 — Map Zones / Visual Grouping

- Draw named zones on the topology map (e.g. DMZ, Management VLAN, Cloud)
- Zones stored as ReactFlow group nodes with color theming; persisted in `graph_layouts`
- Purely cosmetic/organizational — no new backend entities required

### D2 — Map Export

- Export the current map view as PNG or SVG for runbooks, architecture docs, or presentations
- ReactFlow supports this natively via `getNodes()` + html-to-image

### D3 — Dependency Blast Radius Analysis

- Leverage the existing `service_dependencies` table to answer "what breaks if X goes down?"
- Panel showing full upstream/downstream dependency chain for any service, with depth levels
- Highlight the affected subgraph directly on the map

---

## Sprint E — Collaboration & Access Control

### E1 — Role-Based Permissions

- Extend `users.is_admin` boolean into scoped roles: `admin`, `editor`, `viewer`
- Viewer role → read-only token, no CRUD
- Minimal backend surface area to change — middleware already structured for this

### E2 — Named API Key

- Multiple named API keys with scopes (`read`, `write`, `admin`) in an `api_keys` table
- Generate/revoke from Settings → Security
- Useful for CI pipelines, scripts, or monitoring agents

### E3 — Shareable Read-Only Map Links

- Signed short-lived (or permanent) URLs rendering a read-only, embed-safe topology view
- Useful for sharing with contractors or displaying on a wall dashboard without granting login

---

## Sprint F — Integrations & Portability

### F1 — CSV Bulk Import/Export

- Per-entity-type CSV import/export alongside the planned JSON backup
- Import wizard with column mapping and conflict resolution UI
- High value for users migrating from spreadsheets

### F2 — Homepage Dashboard Widget

- Lightweight `GET /api/v1/widgets/status-summary` endpoint returning service status counts
- Iframe-embeddable status badge page (`/embed/status`) compatible with Homarr, Heimdall, etc.

### F3 — Scheduled Maintenance Windows

- `maintenance_start` / `maintenance_end` timestamps on services
- Auto-set status to `maintenance` on window start; revert to prior status on end (background task)
- Countdown badge on map nodes and service table

---

## Sprint G — Physical Infrastructure

> Detailed specification: [server-sim.md](server-sim.md)

### G1 — Interactive Rack Layout

- `Rack` entity with `height_u`, `location`, `notes`; `RackPlacement` binding `hardware` → U position
- Drag-and-drop 2D front-elevation rack view
- Pre-built component library: 1U/2U servers, switches, NAS, PDUs, patch panels
- Linked to existing `hardware` entities — rack view *is* the hardware inventory, spatially arranged

### G2 — Power Budgeting

- `max_power_watts` on hardware and `power_draw_watts` on compute units
- Rack view shows total draw vs. PDU/UPS capacity with color-coded utilization bar

---

## Sprint H — Sysinfo Integrations

### H1 — Proxmox API Integration

- Pull VM/container inventory directly from a Proxmox node
- Auto-populate or sync `compute_units` from Proxmox guest list
- Store Proxmox host credentials in settings (encrypted)

### H2 — Netdata / Pulse API Integration

- Pull real-time CPU, memory, and disk metrics from Netdata or Pulse agents
- Display live gauges on hardware and compute detail HUDs
- No metric storage in Circuit Breaker — purely a live display proxy

---

## Prioritization

| Sprint | Feature | Effort | Impact |
|--------|---------|--------|--------|
| D2 | Map Export | Low | High |
| D3 | Blast Radius Analysis | Low | High |
| E2 | Named API Keys | Low | Medium |
| B1 | Status Webhooks | Medium | High |
| F1 | CSV Bulk Import | Medium | High |
| A1 | IPAM | Medium | High |
| C1 | Custom Fields | Medium | Medium |
| B3 | Cert Expiry Tracking | Medium | Medium |
| F2 | Dashboard Widget | Low | Medium |
| D1 | Map Zones | Medium | Medium |
| C2 | Hardware Lifecycle | Medium | Medium |
| E1 | Role-Based Permissions | Medium | Medium |
| G1 | Rack Layout | High | Very High |
| G2 | Power Budgeting | Medium | High |
| H1 | Proxmox Integration | High | High |

---
