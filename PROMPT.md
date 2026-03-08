```
Circuit Breaker v0.2.x: Multi‑VLAN Scan & Profiles Expansion

Goal: Expand Scan + Scan Profile capabilities to treat **VLANs as first-class citizens** while keeping the UX intuitive and visually beautiful. Users should be able to define multiple VLANs per scan/profile, understand what will be probed at a glance, and see clear logical relationships between VLANs, networks, and discovered devices.

Use the attached UI references for visual tone and layout. [image:14] [image:15]

---

## Overview

You will:

1. Extend the **data model** so Scan Profiles and Ad‑Hoc Scans can target:
   - One or more **VLANs** (linked to existing `networks` rows).
   - One or more **CIDR ranges** (for non‑modeled networks).
2. Add rich **UI flows** for:
   - Selecting VLANs via beautiful chips/pills.
   - Showing VLAN → subnet mappings and which profiles touch which VLANs.
3. Keep the experience simple:
   - Everyday users pick a VLAN name (e.g., “Lab / VLAN 20”) and hit **Create Profile**.
   - Power users can still type raw CIDRs or mix VLAN + CIDR.
4. Update the **scan engine** so it:
   - Resolves VLAN selections into CIDR lists.
   - Stores relationships for topology use (which VLAN discovered which node).

Follow Persona + Space standards (no placeholders, production‑ready code).

---

## Backend

### 1. Schema Changes

Update existing discovery schema (see V1_PUSH.md) to add VLAN awareness.

**Tables**:

```sql
-- networks table already contains VLAN info; ensure this column exists
ALTER TABLE networks ADD COLUMN IF NOT EXISTS vlan_id INTEGER;      -- e.g. 10, 20, 30

-- discoveryprofiles: add VLAN linkage
ALTER TABLE discoveryprofiles ADD COLUMN IF NOT EXISTS vlan_ids TEXT; 
-- JSON array of VLAN ints, e.g. "" [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/155797712/dc8e925f-30b4-48d5-9845-39f6cc8ead60/image.jpg)

-- scanjobs: store resolved VLANs and networks
ALTER TABLE scanjobs ADD COLUMN IF NOT EXISTS vlan_ids TEXT;        -- JSON array
ALTER TABLE scanjobs ADD COLUMN IF NOT EXISTS network_ids TEXT;     -- JSON array of networks.id

-- scanresults: record primary VLAN + network
ALTER TABLE scanresults ADD COLUMN IF NOT EXISTS vlan_id INTEGER;
ALTER TABLE scanresults ADD COLUMN IF NOT EXISTS network_id INTEGER;
```

### 2. Pydantic Schemas

```python
class DiscoveryProfileBase(BaseModel):
    name: str
    target_cidr: Optional[str] = None
    vlan_ids: List[int] = []           # NEW: VLANs bound to this profile
    scan_types: List[str]              # ["nmap", "snmp", "arp", "http"]
    # existing fields: snmp community, schedule_cron, etc.

class ScanJobOut(BaseModel):
    id: int
    profile_id: Optional[int]
    target_cidr: Optional[str]
    vlan_ids: List[int]                 # Resolved from profile or ad‑hoc
    network_ids: List[int]              # networks table ids
    # ...
```

### 3. VLAN Resolution Logic

New helper in `discoveryservice.py`:

```python
async def resolve_vlans_to_cidrs(db: Session, vlan_ids: List[int]) -> tuple[list[str], list[int]]:
    """
    Given a list of VLAN IDs, return (cidrs, network_ids).
    Each VLAN may have multiple networks; de‑duplicate CIDRs.
    """
    if not vlan_ids:
        return [], []
    nets = (
        db.query(Network)
        .filter(Network.vlan_id.in_(vlan_ids))
        .all()
    )
    cidrs = sorted({n.cidr for n in nets if n.cidr})
    network_ids = [n.id for n in nets]
    return cidrs, network_ids
```

When creating a **scan job** (from profile or ad‑hoc):

```python
async def create_scan_job(db, profile: DiscoveryProfile, target_cidr: str | None, vlan_ids: list[int]):
    cidrs: list[str] = []
    network_ids: list[int] = []

    if vlan_ids:
        vlan_cidrs, n_ids = await resolve_vlans_to_cidrs(db, vlan_ids)
        cidrs.extend(vlan_cidrs)
        network_ids.extend(n_ids)

    if target_cidr:
        cidrs.append(target_cidr)

    cidrs = sorted(set(cidrs))

    job = ScanJob(
        profile_id=profile.id if profile else None,
        target_cidr=",".join(cidrs) or None,
        vlan_ids=json.dumps(vlan_ids),
        network_ids=json.dumps(network_ids),
        # ...
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
```

During scan result upsert, also set `vlan_id` / `network_id` by matching IP to the known `networks` table (reuse existing mapping logic).

---

## Frontend

### 1. Scan Profile Modal: Multi‑VLAN Selection

**Create/Update Profile UI** (based on screenshot):

- Add a **“Target Scope”** section under “TARGET CIDR”:

```
TARGET SCOPE
[ ] CIDR Range    [ 192.168.10.0/24           ]
[ ] VLANs
    [ + Add VLAN ]
    [ Lab / VLAN 20    x ]
    [ Main LAN / VLAN 10 x ]
    (Dropdown shows: “VLAN 10 – Main LAN – 192.168.10.0/24”, etc.)
```

Interaction:

- Users can:
  - Type a CIDR, or
  - Select one or multiple VLANs, or
  - Do both (advanced).
- VLANs appear as **pills/chips** with:
  - Badge: `VLAN 20`
  - Subtext: `192.168.20.0/24 • Lab`
- When hovering a VLAN, show a mini tooltip: “3 networks • 254 IPs”.

Implementation:

- Add `useNetworks()` hook to fetch `GET /api/v1/networks` (existing).
- Build `availableVlans` array from unique `vlan_id` + name, grouped by environment/tag.
- Save selected VLAN IDs to `profile.vlan_ids`.

### 2. Ad‑Hoc Scan: Multi‑VLAN Targeting

On the “New Scan” screen (second screenshot):

- Replace single “TARGET NETWORK” input with a **toggle group**:

```
TARGET
( ) Single CIDR
    [ 192.168.10.0/24           ]

( ) VLANs
    [ + Select VLANs ]
    [ VLAN 10 – Main LAN  x ]
    [ VLAN 20 – Lab       x ]
```

- When VLAN mode is active:
  - CIDR field disabled or treated as advanced override.
  - Below, show a summary line:

> Will scan 2 VLANs • 3 networks • ~508 IPs

### 3. Visual Relationships in Discovery UI

On Discovery → Scan Jobs / History:

- For each job card/row:
  - Show **pill icons** for VLANs:
    - Example: `[VLAN 10] [VLAN 20]`
  - Hover → show tooltip listing network CIDRs.

In the topology map:

- Optionally add a lightweight overlay:
  - Highlight nodes discovered by a specific VLAN scan:
    - Filter: “Highlight VLAN 10 results”.
  - Node badge: tiny label `V10` around telemetry ring.

---

## UX & Visual Design

**Principles**:

- **Intuitive First**:
  - Default path: user sees only “Target CIDR” as today.
  - When **networks with vlan_id** exist, surface a subtle “Use VLANs instead” hint.
- **Freeform Friendly**:
  - Users can always type any CIDR—even if networks/VLANs aren’t modeled yet.
- **Beautiful, Minimal**:
  - VLAN chips use the existing tag styles (rounded pills, subtle glows).
  - Keep the modal uncluttered:
    - Group advanced settings under collapsible “Advanced VLAN Options”.

**Micro‑copy examples**:

- Under VLAN selection:
  > “Pick one or more VLANs to scan. Circuit Breaker will resolve all associated subnets for you.”
- Under CIDR:
  > “Prefer manual? Enter a CIDR range instead.”

---

## API & Contracts

### New/Updated Fields

**DiscoveryProfileCreate/Update**:
```json
{
  "name": "Home LAN",
  "target_cidr": "192.168.10.0/24",
  "vlan_ids":, [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/155797712/dc8e925f-30b4-48d5-9845-39f6cc8ead60/image.jpg)
  "scan_types": ["nmap", "snmp"],
  ...
}
```

**ScanJobOut**:
```json
{
  "id": 13,
  "profile_id": 2,
  "target_cidr": "192.168.10.0/24,192.168.20.0/24",
  "vlan_ids":, [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/images/155797712/dc8e925f-30b4-48d5-9845-39f6cc8ead60/image.jpg)
  "network_ids":, [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/collection_fd11e377-1bb9-49cf-9e9f-fe81afe63231/c1224fd1-2a31-4044-9ef4-73320cd2b983/V1_PUSH.md)
  "hosts_found": 74,
  ...
}
```

---

## Testing & Exit Criteria

### Backend

- Unit:
  - `resolve_vlans_to_cidrs()` returns correct CIDR list and network IDs.
  - Job creation with:
    - VLANs only,
    - CIDR only,
    - Both.
  - Scan result mapping sets `vlan_id` correctly for discovered IPs.

- Integration:
  - Create profile with VLANs → trigger scan → verify:
    - `scanjobs.vlan_ids` and `network_ids` populated.
    - `scanresults.vlan_id`/`network_id` correct for each host.

### Frontend

- Unit/Component:
  - VLAN selector renders correct chips.
  - Selecting/removing VLAN updates `vlan_ids` payload.

- E2E:
  - User creates profile “Lab VLANs” selecting VLAN 10 & 20.
  - Runs scan from profile.
  - History shows VLAN tags on job row.
  - Topology filter “Highlight VLAN 10” works.

### Exit Criteria

- Users can define scans/profiles by single or multiple VLANs without touching raw CIDRs.
- Profiles clearly show which VLANs they target.
- Discovery history visually communicates VLAN scope.
- Topology and discovery views stay clean, readable, and aligned with current visual style.

Use this spec as the implementation brief for the coding agent. Implement backend first (schema, services, API), then frontend (VLAN‑aware forms and visuals), then tests.```