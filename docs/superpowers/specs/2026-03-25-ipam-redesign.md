# IPAM Redesign — Design Spec

**Status:** Approved
**Date:** 2026-03-25
**Mockup:** `.superpowers/brainstorm/859151-1774464203/ipam-layout.html`

---

## Problem

The IPAM page is a manual-entry tool with three tabs (IP Addresses, VLANs, Sites) and a manual network scanner. It doesn't reflect the live network — discovery results aren't visible alongside manual entries, there's no subnet utilization, and network management lives on a separate Networks page. This creates two overlapping infrastructure views with no cross-entity linking.

---

## Solution

Absorb the Networks page into IPAM as a first tab. Add discovery integration inline in IP Addresses. Add subnet utilization to the Networks tab. Add cross-entity backreferences in VLANs and Sites. Deprecate and redirect the Networks page.

---

## Tab Structure

| # | Tab | Status |
|---|-----|--------|
| 1 | **Networks** | NEW — absorbs NetworksPage |
| 2 | **IP Addresses** | Enhanced: discovery + notes + hardware link |
| 3 | **VLANs** | Enhanced: Referenced Networks backref panel |
| 4 | **Sites** | Enhanced: Networks at this site backref panel |

---

## Decisions Log

| Question | Decision |
|----------|----------|
| Discovery integration style | Inline — discovered hosts shown alongside manual entries with MANUAL/DISCOVERED badge and filter chips |
| Hardware link | Discovered IPs link to their Hardware entity; click opens HardwareDetail drawer |
| Notes scope | `notes TEXT` added to `ip_addresses` only; VLAN keeps `description`, Site keeps `notes` |
| Missing value | Subnet utilization + cross-entity linking (VLAN→Networks, Site→Networks) |
| Networks page | Absorbed into IPAM Networks tab; `/networks` redirects to `/ipam`; nav entry removed |

---

## Database Changes

### Migration `0066_ipam_notes_network_site.py`

```sql
-- A: notes on ip_addresses
ALTER TABLE ip_addresses ADD COLUMN notes TEXT;

-- B: site FK on networks (enables Site → Networks backref)
ALTER TABLE networks ADD COLUMN site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL;
CREATE INDEX ix_networks_site_id ON networks(site_id);
```

---

## Backend

### Models (`apps/backend/src/app/db/models.py`)

- `IPAddress` — add `notes: Mapped[str | None] = mapped_column(Text, nullable=True)`
- `Network` — add `site_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True)` + `site` relationship

### Schemas

- `apps/backend/src/app/schemas/ipam.py`
  - `IPAddressBase`: add `notes: str | None = None`
  - `IPAddressRead`: add `source: Literal["manual", "discovered"] = "manual"` (computed, not stored)
- `apps/backend/src/app/schemas/networks.py`
  - `NetworkBase`: add `site_id: int | None = None`
  - `NetworkRead`: add `allocated_count: int = 0`, `total_count: int = 0`

### API: `apps/backend/src/app/api/ipam.py`

- `GET /api/v1/ipam?include_discovered=true` — merge discovered hosts from the discovery result table (joined to Hardware), deduplicated against manual `IPAddress` records (manual takes precedence on address collision).

  Response shape:
  ```json
  [
    {"source": "manual",     "id": 1,    "address": "192.168.1.10", "hardware_id": 5,  "notes": "Primary hypervisor"},
    {"source": "discovered", "id": null, "address": "192.168.1.42", "hardware_id": 12, "notes": null}
  ]
  ```
  Discovered entries have `id: null` and are read-only in the frontend.

- `POST /api/v1/ipam`, `PATCH /api/v1/ipam/{id}` — pass through `notes` field.

### API: `apps/backend/src/app/api/networks.py`

- `GET /api/v1/networks` / `GET /api/v1/networks/{id}` — include `site_id`, `allocated_count`, `total_count` in response.
  - `allocated_count`: `COUNT(ip_addresses WHERE network_id=X AND status='allocated')`
  - `total_count`: derived from CIDR prefix length (e.g. `/24` → 254 usable)
- `PATCH /api/v1/networks/{id}` — accept `site_id` in update payload.

---

## Frontend

### `apps/frontend/src/pages/IPAMPage.jsx`
- Reorder tabs: Networks, IP Addresses, VLANs, Sites
- Add import + render of `NetworksTab`
- Remove `FutureFeatureBanner` (feature is no longer "early rollout")

### `apps/frontend/src/components/ipam/NetworksTab.jsx` ← NEW
- Port content from `NetworksPage.jsx` (table, FormModal, ConfirmDialog, NetworkDetail drawer)
- Remove standalone page wrapper (`page`, `page-header` divs)
- Add **Utilization** column: `<progress>` bar styled with CSS vars + `X / Y` label
- Add **Site** column (optional dropdown filter, populated from sites list)
- Keep `NetworkDetail` drawer unchanged

### `apps/frontend/src/components/ipam/IPAddressesTab.jsx`
- Add filter chips row: **All / Manual / Discovered** (local state)
- Add **Source** column first: `<span>` badge styled with CSS vars (no hardcoded colors)
- Add **Hardware** column: link text → opens `HardwareDetail` drawer
- Add **Notes** column: truncated inline text, editable on row click for manual records
- Discovered rows: no edit/delete action buttons; subtle `var(--color-surface)` background
- Fetch from `ipamApi.listIPs({ include_discovered: true })`

### `apps/frontend/src/components/ipam/VLANsTab.jsx`
- Add **Referenced Networks** section in VLAN row expand/drawer
- Source: filter `networks` (from `useIPAMData`) where `network.vlan_id === vlan.vlan_id`
- No API change needed — networks already in hook state

### `apps/frontend/src/components/ipam/SitesTab.jsx`
- Fix column: `notes` (not `description` — model uses `notes`)
- Add **Networks at this site** section in Site row expand/drawer
- Source: filter `networks` where `network.site_id === site.id`
- Add `site_id` optional field to Networks form (dropdown of sites)

### `apps/frontend/src/hooks/useIPAMData.js`
- Networks already fetched — no structural change needed
- Update `ipamApi.listIPs()` call to pass `{ include_discovered: true }`
- Add `createNetwork`, `updateNetwork`, `deleteNetwork` CRUD helpers (moved from NetworksPage local state)

### `apps/frontend/src/api/client.jsx`
- `ipamApi.listIPs(params)` — forward params to `GET /api/v1/ipam`

### `apps/frontend/src/data/navigation.js`
- Remove **Networks** nav entry

### `apps/frontend/src/App.jsx`
- Remove `NetworksPage` lazy import
- Replace `/networks` route with `<Navigate to="/ipam" replace />`

### `apps/frontend/src/pages/NetworksPage.jsx`
- Delete (route-level redirect handles any direct links)

---

## Verification Checklist

1. `make migrate` runs clean — both columns added
2. `/ipam` loads with Networks as first tab; existing networks appear with utilization bars
3. IP Addresses tab: "Discovered" filter chip shows discovered hosts with badge; hardware link opens drawer
4. VLANs tab: expanding a row shows "Referenced Networks" list
5. Sites tab: expanding a row shows "Networks at this site" list
6. `/networks` redirects to `/ipam`
7. Networks no longer appears in sidebar/dock
8. Create/edit an IP Address — `notes` field saves and displays correctly
9. Theme switch — all new elements use `var(--color-*)`, no hardcoded hex values
