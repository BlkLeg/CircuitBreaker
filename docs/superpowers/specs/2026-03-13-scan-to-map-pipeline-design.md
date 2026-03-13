# Spec: Intelligent Scan → Map Pipeline

**Date:** 2026-03-13
**Status:** Approved — ready for implementation planning
**Author:** CircuitBreaker team

---

## Context

CircuitBreaker's core value proposition is "scan a network, see it mapped." Today that pipeline
has a critical gap: scan results require the user to manually open each discovered device
one-by-one and click merge. On a 20-device network that's 20 individual actions. For home lab
users this friction defeats the purpose of auto-discovery.

This spec designs the end-to-end intelligent pipeline: scan completes → devices inferred →
user batch-reviews → map auto-populates grouped by subnet.

**Target users:** Home lab enthusiasts who want security, stability, reliability, and accuracy.

---

## User Flow (Target State)

```
User triggers scan (existing UI)
    ↓
Scan completes
    ↓
InferenceEngine annotates each result (vendor, role, icon)
    ↓
Map canvas shows banner: "🔍 20 devices discovered — Review →"
    ↓
User clicks banner → ScanImportModal opens
    ↓
Table shows all results, pre-checked, with inferred details:
  ☑ 192.168.1.1   Ubiquiti   router   (already on map — will update)
  ☑ 192.168.1.10  Dell       server   NEW
  ☐ 192.168.1.11  Unknown    ?        NEW  ← user unchecked unknown
    ↓
User clicks "Import selected (19)"
    ↓
Backend (single DB transaction): deduplicates by MAC > IP, upserts Hardware rows,
assigns subnet positions, persists layout
    ↓
19 nodes appear on map, grouped by /24 slice
Existing nodes silently get last_seen + changed fields updated
```

---

## Design

### 1. Inference Engine (Backend)

**New file:** `apps/backend/src/app/services/inference_service.py`

Annotates a `ScanResult` with inferred metadata using three signals (in priority order):

**Signal A — MAC OUI lookup**
- Bundle an offline OUI → vendor name table (IEEE data, ~50KB)
- `OUIResolver.lookup(mac) → vendor_name | None`
- Also maps vendor names to `vendor_icon_slug` using existing catalog mappings
- e.g. `DC:A6:32` → "Raspberry Pi Foundation" → icon slug `raspberrypi`
- Falls back gracefully when MAC is absent or OUI is unrecognised

**Signal B — Hostname substring matching**
- Case-insensitive substring match against `hostname` field:
  ```
  "pve" or "proxmox" → role=hypervisor, icon=proxmox
  "sw-" or "switch"  → role=switch
  "rt-" or "router"  → role=router
  "nas"              → role=storage
  "rpi" or "-pi-"    → role=sbc, vendor=Raspberry Pi   ← deliberate: avoid "pi" alone
  "ap-" or "unifi"   → role=access_point
  "ups"              → role=ups
  ```
- Short patterns (like bare "pi") intentionally avoided to prevent false positives on
  substrings like "opigee" or "pipeline". Patterns chosen to be distinctive.
- Hardcoded defaults in `inference_service.py` for v1; configurable rules deferred to
  a follow-up spec.

**Signal C — Open port fingerprinting**
- `open_ports_json` is stored as a JSON string; implementation must call
  `json.loads(open_ports_json or "[]")` before use.
- Stored format is `[{"port": 22, "protocol": "tcp", "state": "open"}, ...]`
  (nmap-parsed dicts). Port matching extracts the `"port"` key as an integer.
- Fingerprint rules:
  ```
  8006        → role=hypervisor (Proxmox web UI)
  22 + 443    → role=server (Linux with HTTPS)
  161         → SNMP-capable device
  554         → role=misc (RTSP camera/NVR)
  22 only     → role=server
  80 only     → role=misc (IoT/embedded)
  ```

**Output:** `InferredAnnotation` dataclass:
```python
@dataclass
class InferredAnnotation:
    vendor: str | None           # "Ubiquiti", "Dell", "Raspberry Pi"
    role: str | None             # "router", "server", "hypervisor", etc.
    vendor_icon_slug: str | None # "ubiquiti", "dell", "raspberrypi"
    confidence: float            # 0.0–1.0 (thresholds below)
    signals_used: list[str]      # ["mac_oui", "hostname"] for transparency
```

**Confidence scoring:**
```
OUI alone              → 0.40
hostname alone         → 0.50
port fingerprint alone → 0.30
any two signals agree  → 0.75
all three agree        → 1.00
no signals             → 0.00 (shown as "Unknown"; importable but unchecked by default)
```

UI indicator thresholds: ≥0.75 = ●●● (high), ≥0.40 = ●●○ (medium), >0 = ●○○ (low), 0 = ○○○.

---

### 2. Batch Import Endpoint (Backend)

**New endpoint:** `POST /api/v1/discovery/scans/{scan_id}/batch-import`

**Auth:** `require_write_auth` (editor/admin role required)

**Request:**
```json
{
  "items": [
    {
      "scan_result_id": 42,
      "overrides": {
        "name": "my-router",
        "role": "router",
        "vendor_icon_slug": "ubiquiti"
      }
    }
  ]
}
```

**Transaction isolation:** All upserts execute within a single `db.begin()` transaction.
Use PostgreSQL `INSERT ... ON CONFLICT (ip_address) DO UPDATE` (or explicit
`SELECT ... FOR UPDATE` on the MAC/IP lookup) to prevent duplicate creation under concurrent
imports of the same scan.

**Logic per item (within transaction):**
1. Lock candidate rows: `SELECT id FROM hardware WHERE ip_address=$ip OR mac_address=$mac FOR UPDATE`
2. Evaluate match priority: MAC match first, then IP match.
3. **MAC + IP resolve to the same row:** standard update path (silent).
4. **MAC match resolves to row A; IP match resolves to different row B:**
   This is a real conflict (device changed IP, or two devices share a MAC — rare but
   real with VMs/containers). Mark as `conflict` in response; do NOT auto-merge. Surface
   in UI as a warning row; user must resolve manually.
5. **If exists (single match):** update `last_seen=now`, `mac_address` if changed,
   `hostname` if changed, `open_ports_json` if changed. Do NOT overwrite user-set
   `name`, `role`, `vendor_icon_slug` unless `Hardware.source == "discovery"` (i.e.
   was originally set by a scan, not manually entered).
6. **If new:** create `Hardware` with `source="discovery"`, `discovered_at=now`,
   inferred fields from `InferredAnnotation` as defaults, apply `overrides`.
7. After all upserts: call `compute_subnet_layout()` for newly-created IDs **only**.
   Updated IDs are never repositioned — their existing canvas positions are preserved.
   Persist new positions via `graph/layout` **server-side** (the backend owns layout
   persistence here; the frontend does not make a second call).

**Idempotency:** Calling batch-import twice on the same scan is safe. The second call
will find all rows already exist and produce `updated` results with no duplicates.

**Response:**
```json
{
  "created": [{"id": 101, "ip": "192.168.1.10", "position": {"x": 350, "y": 200}}],
  "updated": [{"id": 5,   "ip": "192.168.1.1",  "position": null}],
  "conflicts": [{"scan_result_id": 44, "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF",
                 "reason": "mac_matches_id_7_ip_matches_id_12"}],
  "skipped": []
}
```

---

### 3. Enriched Results Endpoint (Backend)

**Modified endpoint:** `GET /api/v1/discovery/scans/{scan_id}/results?with_inference=true`

**New response schema `InferredScanResultOut`** (extends existing `ScanResultOut`):
```python
class InferredScanResultOut(ScanResultOut):
    inferred_vendor: str | None
    inferred_role: str | None
    inferred_icon_slug: str | None
    confidence: float
    signals_used: list[str]
    exists_in_hardware: bool       # True if IP or MAC already in hardware table
    existing_hardware_id: int | None  # id of the matching Hardware row if exists
    # Computed at request time (not from ScanJob.hosts_new which may be stale)
    is_new: bool  # True when exists_in_hardware is False
```

The banner count on the frontend uses `items.filter(r => r.is_new).length`, computed
fresh from this response — not from `ScanJob.hosts_new` which may be stale if a
partial import was done previously.

---

### 4. Subnet Grouping Layout (Backend)

**New function:** `compute_subnet_layout(hardware_ids: list[int], db: Session) → dict[int, dict]`
Location: `apps/backend/src/app/services/layout_service.py` (new file)

Algorithm:
1. Fetch `Hardware` rows for given IDs (IP addresses only; some may have no IP).
2. Group by /24 slice regardless of actual subnet prefix length. A home lab with a
   `/16` flat network is treated as multiple /24 groups — this ensures layout stays
   readable for any network size. Grid width capped at 5 nodes per row.
3. Sort groups by network address; assign canvas columns 600px apart.
4. Within each group: gateway/router candidate placed at top-center (lowest IP, or
   device with port 80/443 open). Remaining nodes in rows of 5, 200px spacing.
5. Nodes with no IP → placed in an overflow region at bottom-right.

Returns `dict[hardware_id, {"x": float, "y": float}]`.

Backend persists this by calling the existing `save_layout` service function internally.
Frontend does NOT need to make a separate layout save call.

---

### 5. Scan Notification Banner (Frontend)

**Modify:** `apps/frontend/src/hooks/useMapRealTimeUpdates.js`
- When a scan transitions to `status=done`: fetch enriched results
  (`GET .../results?with_inference=true`) and compute `newCount = items.filter(r => r.is_new).length`
- If `newCount > 0`: dispatch `scan:import-ready` custom event with
  `{scan_id, new_count: newCount, scan_cidr}`

**Modify:** `apps/frontend/src/pages/MapPage.jsx`
- Subscribe to `scan:import-ready` event
- Render dismissible banner at top of canvas:
  ```
  🔍  20 new devices found on 192.168.1.0/24 — Review & Import →   [×]
  ```
- Banner stores `{scan_id, new_count}` in state
- Clicking "Review & Import →" opens `ScanImportModal` with `scanId` prop
- Auto-dismisses after successful import or `[×]` click

---

### 6. ScanImportModal Component (Frontend)

**New file:** `apps/frontend/src/components/ScanImportModal.jsx`

Data source: `GET /api/v1/discovery/scans/{scan_id}/results?with_inference=true`
(data already fetched by banner trigger; pass as prop to avoid double-fetch)

**Table columns:**

| ☑ | IP Address | Hostname | Vendor | Role | Status | Confidence |
|---|------------|----------|--------|------|--------|------------|
| ☑ | 192.168.1.1 | router.local | Ubiquiti | router | EXISTS | ●●● |
| ☑ | 192.168.1.10 | dell-r720 | Dell | server | NEW | ●●○ |
| ☐ | 192.168.1.11 | — | Unknown | ? | NEW | ○○○ |

**Default selection logic:**
- Pre-check all rows where `confidence > 0` (known devices)
- Leave unchecked rows where `confidence == 0` AND `is_new == true` (truly unknown)
- Always pre-check EXISTS rows (safe: update is non-destructive)

**Interactions:**
- Per-row checkbox toggle
- "Select all" / "Select new only" quick actions
- Inline role dropdown override (does not require re-fetching)
- Conflict rows shown in amber with warning icon; cannot be imported without manual resolution
- `[Import selected (N)]` → `POST .../batch-import` with selected IDs + overrides
- On success: modal closes, parent calls `fetchData()` to refresh topology + `fitView()`
- Toast: "19 devices added to map. 1 updated." (from response counts)

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `apps/backend/src/app/services/inference_service.py` | **New** — OUI resolver, hostname rules, port fingerprinting, confidence scoring |
| `apps/backend/src/app/services/layout_service.py` | **New** — subnet grouping layout algorithm |
| `apps/backend/src/app/api/discovery.py` | Enrich `GET .../results`, add `POST .../batch-import` |
| `apps/frontend/src/hooks/useMapRealTimeUpdates.js` | Dispatch `scan:import-ready` on scan completion |
| `apps/frontend/src/pages/MapPage.jsx` | Discovery banner + modal integration |
| `apps/frontend/src/components/ScanImportModal.jsx` | **New** — batch confirm table UI |
| `apps/frontend/src/api/client.jsx` | Add `discoveryApi.getResultsWithInference(scanId)` and `discoveryApi.batchImport(scanId, items)` |

---

## Security

- Batch import requires `require_write_auth` (editor/admin role)
- CSRF token injected by existing axios interceptor — no changes needed
- OUI table bundled offline — zero external DNS/HTTP calls during inference
- Inference rules hardcoded in service — no user-editable attack surface in v1
- `overrides` validated against existing `HardwareCreate` Pydantic validators
- Transaction isolation prevents duplicate-creation race conditions

---

## Out of Scope (This Spec)

- OOBE guided wizard (separate spec)
- Configurable inference rules UI (deferred to follow-up)
- Telemetry auto-configuration after import
- VLAN-aware grouping beyond /24 slicing

---

## Verification Checklist

- [ ] Scan completes → banner shows correct `is_new` count (fresh, not stale from ScanJob)
- [ ] Modal: inference shows vendor/role for common devices (Ubiquiti, Dell, RPi, Proxmox)
- [ ] Confidence ●●● for MAC+hostname match; ●●○ for one signal; ○○○ for no signals
- [ ] Unknown devices (confidence=0) pre-unchecked by default
- [ ] EXISTS badge + pre-checked for devices already in hardware table
- [ ] Import 19 of 20 → 19 nodes on map, grouped by /24 slice
- [ ] Re-import same scan → no duplicates, `last_seen` updated, idempotent
- [ ] MAC+IP conflict → amber row, not importable, warning shown
- [ ] Viewer role → 403 on batch-import
- [ ] All mutating requests carry `X-CSRF-Token` header
- [ ] Layout positions persisted server-side; frontend only calls `fetchData()` + `fitView()`
