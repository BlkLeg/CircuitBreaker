Here’s a structured plan that treats these as first-class features, not bolt-ons.

***

## 0. Guiding Principles

- Everything must plug into the **existing data model** (hardware, compute, services, networks, racks, settings).
- Map, rack simulator, and lists must **stay in sync**.
- Features should be extensible for future phases (e.g., WAN links, multi-site).

I’ll break the work into three coherent feature packages plus cross-cutting changes.

***

## 1. Map: Network Node Context Menu → Link to Hardware / Compute / Services

### 1.1 Data Model & API

You already have relationship tables:

- `compute_networks` (compute ↔ network)
- Services connect to networks via their compute units today (indirectly).

New behaviors are **UI shortcuts** that call existing APIs:

- Network → Compute:
  - Use `POST /api/v1/networks/{id}/members` with `{ compute_id, ip_address }`.
- Network → Hardware:
  - Two options:
    - **Option A (preferred)**: treat hardware as “implied” by its compute units, and **don’t create a new table**; the link to hardware is always via compute.
    - **Option B**: add `hardware_networks` table for explicit L2 connections.
- Network → Service:
  - Use existing relationships:
    - Map Service → Compute → Network chain; no new table needed.
  - Create a helper that:
    - Looks up compute of service.
    - Binds that compute to the network (if not already).

Implementation plan:

- **Short term**: network context menu options are thin wrappers:
  - Link to Hardware → choose a hardware → choose a compute on that hardware → create `compute_networks` row.
  - Link to Compute → same as existing network-membership workflow, but from map.
  - Link to Services → choose service → resolve compute → ensure compute_networks row exists.

- **Optional long term**: if you need a “hardware directly on network” concept (e.g., router, switch):
  - Add `hardware_networks` table and extend `/graph/topology` with those edges.

### 1.2 Frontend: Map Context Menu

For **Network nodes**, extend the context menu:

- Existing menu: Link to Compute, Link to Services, Edit Icon (already there per v2 roadmap).
- New structure:

```text
Right-click Network node:
├── Link to Hardware  ▶ (hardware list)
├── Link to Compute   ▶ (compute list)
├── Link to Services  ▶ (services list)
└── Edit Icon
```

Dropdown behavior:

- Searchable lists (name, tags).
- Show environment, current IPs, and hardware for context.
- Confirm action:
  - Hardware path: select hardware → then inner dropdown of compute units.
  - Service path: select service → confirm which network-level IP to use if multiple.

UX feedback:

- After linking:
  - Draw edge on map (`connects_to`, `runs`, `hosts` already used).
  - Toast notification.
  - Optionally show “New member added” in network detail HUD.

### 1.3 Graph & HUD Integration

- `/graph/topology` already emits `compute ↔ network` edges; ensure these new links are immediately reflected.
- Network detail HUD:
  - Members list is updated, with explicit mention when added via map.

***

## 2. Hardware “Clusters” – Accurate Model Representation

Goal: Group multiple hardware nodes into **logical clusters** that represent reality:

- Example: “Proxmox Cluster A” containing 3 SFF boxes.
- Clusters should show up:
  - In list views (filterable).
  - In topology (cluster node with member hardware).
  - In rack simulator (optional grouping).

### 2.1 Data Model

Introduce new entity: `hardware_cluster`.

Table:

```sql
CREATE TABLE hardware_clusters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    environment TEXT,          -- optional (prod/dev)
    location    TEXT,          -- optional (data center, office)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE hardware_cluster_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id  INTEGER NOT NULL,
    hardware_id INTEGER NOT NULL,
    role        TEXT,          -- optional: "primary", "node", "storage"
    UNIQUE (cluster_id, hardware_id),
    FOREIGN KEY (cluster_id) REFERENCES hardware_clusters(id),
    FOREIGN KEY (hardware_id) REFERENCES hardware(id)
);
```

API:

- CRUD for clusters:
  - `GET/POST/PATCH/DELETE /api/v1/hardware-clusters`
- Membership:
  - `GET /api/v1/hardware-clusters/{id}/members`
  - `POST /api/v1/hardware-clusters/{id}/members`
  - `DELETE /api/v1/hardware-clusters/{id}/members/{hardwareId}`

### 2.2 Frontend UX

#### a) Cluster Management (Settings or Hardware HUD)

- New “Clusters” management page:
  - List clusters, member counts, environment.
  - Create/edit cluster, assign hardware.

- Hardware table:
  - Column: `Cluster` (name or “—”).
  - Filter: by cluster.

- Hardware detail HUD:
  - Shows cluster membership with quick links.
  - Action: “Move to Cluster…” or “Add to Cluster…”.

#### b) Map Representation

- Add a new node type: **cluster**:

  - `/graph/topology`:
    - Emit `cluster` nodes if include contains `hardware` or new `clusters` type.
    - Edges:
      - Cluster → Hardware: `relation: "cluster_member"`.

- Map view:

  - Cluster nodes visually distinct:
    - Larger ring, label “Proxmox Cluster A”.
    - Hover/tooltip: summary of members (3 nodes, total CPU/RAM).
  - Clicking cluster:
    - Side panel with members list.
    - “Drill-down” action: focus only cluster members.

- Optional expansion:
  - Toggle “Expanded view”: automatically layout member hardware around cluster.

#### c) Rack Simulator Integration (optional for this phase)

- Racks: allow filtering/grouping by cluster, but actual modeling is per hardware.
- In rack inspector:
  - Show cluster membership.

***

## 3. Cloud Servers (VPS) & Their Interaction with the Local Network

Goal: Represent **non-local** infrastructure (cloud VPS, managed DB, SaaS endpoints) and **how they tie into the local lab**, without hacking around with fake hardware.

This needs to feel first-class and map into existing entities cleanly.

### 3.1 Data Model Options

We want:

- Distinct from on-prem hardware.
- Linkable to networks, services, misc.

Two approaches:

### Option A – Extend `hardware` with `kind`

- Add `kind` field to `hardware`:

  - `'physical' | 'cloud' | 'virtual_appliance' | ...`
- For cloud servers:
  - `kind = 'cloud'`.
  - `location = 'AWS us-west-2'`, etc.

Pros:

- Minimal DB changes.
- Reuses existing relationships (compute, services, racks if needed).

Cons:

- Might feel confusing when you expect “hardware” = physical box.

### Option B – New `external_node` entity

- `external_nodes` table:

  ```sql
  CREATE TABLE external_nodes (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      name        TEXT NOT NULL,
      provider    TEXT,      -- 'AWS', 'Linode', 'Hetzner', 'Cloudflare Tunnel'
      type        TEXT,      -- 'vps', 'managed_db', 'saas'
      region      TEXT,
      ip_address  TEXT,
      notes       TEXT,
      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL
  );
  ```

- Relationships:
  - `external_node_networks` for how they link in:
    - Which network/VPN/tunnel they belong to.
  - `service_external_nodes` for mapping local services to remote dependencies.

Pros:

- Clean separation; external nodes are explicit.
- Easier to render differently on map.

Cons:

- More tables and CRUD.

Given how rich the app already is, Option B is more in line with treating this as a **real feature**, not a hack.

### 3.2 APIs

- CRUD:
  - `GET/POST/PATCH/DELETE /api/v1/external-nodes`
- Relationships:
  - `POST /api/v1/networks/{id}/external-members`
    - Body: `{ external_node_id, ip_address }`
  - `POST /api/v1/services/{id}/external-dependency`
    - Body: `{ external_node_id, purpose }`

### 3.3 Frontend UX

#### a) External Nodes List / HUD

- New “Cloud & External” view or under “Network” or “Misc” section.
- Table columns:
  - Name, provider, type, region, IP, tags.
- Detail HUD:
  - Provider logo (if known).
  - Networks it participates in (VPN, WAN, VLAN).
  - Local services that depend on it.

#### b) Map Representation

- New node type: `external` or `cloud`:

  - Visual:
    - Cloud icon or hex “cloud” node.
    - Distinct color (e.g., purple/blue).
  - Edges:
    - External ↔ Network: `relation: "connects_to"` (via external_node_networks).
    - External ↔ Service: `relation: "depends_on"` or `relation: "external_dep"`.

- Context menu for external node:
  - Link to Network.
  - Link to Services.
  - Edit icon.

- For representing **internet / WAN**:
  - Reserve special external node “Internet” that can be connected to external or even local networks (for completeness).

#### c) How Interaction Is Modeled

Examples:

- A VPS with WireGuard to your lab:
  - External node “VPS-01 (Hetzner)”.
  - Linked to local `WG-Net` network.
- A cloud DB used by a local app:
  - External node “RDS-Prod”.
  - Linked as dependency to “App Service” local service.

***

## 4. Cross-Cutting Considerations

### 4.1 Graph Topology Endpoint

Extend `/api/v1/graph/topology` to include:

- Cluster nodes + edges.
- External nodes + edges.

New types:

- `cluster` for hardware clusters.
- `external` for cloud/external resources.

`nodes[]` entries:

```json
{
  "id": "cluster-1",
  "type": "cluster",
  "ref_id": 1,
  "label": "Proxmox Cluster A",
  "tags": ["prod"],
  "meta": { "members": 3 }
}
```

```json
{
  "id": "ext-5",
  "type": "external",
  "ref_id": 5,
  "label": "VPS-01 (Hetzner)",
  "tags": ["cloud", "prod"]
}
```

Edges:

- Cluster → Hardware: `relation: "cluster_member"`.
- External → Network: `relation: "connects_to"`.
- External → Service: `relation: "depends_on"`.

### 4.2 Permissions & Logs

- All new endpoints must:
  - Honor auth (JWT/api token).
  - Produce audit logs in the Logs HUD (already present).
- Map context actions (network linking, cluster linking, external dependencies) generate log entries.

### 4.3 Settings & Defaults

- Settings:
  - New filters: show/hide external nodes / cluster nodes on map.
  - Option to treat cloud/external as part of environment (e.g., `prod` vs `lab`).

***

## 5. Implementation Order

To keep risk manageable:

1. **Network context menu enhancements (map only)**:
   - No new tables if using existing compute/network/services.
   - Immediate UX win, minimal surface area.

2. **Hardware clusters**:
   - New tables, list views, and map integration.
   - Ties into existing hardware and racks.

3. **External/cloud nodes**:
   - New entities and map integration.
   - Use learnings from clusters/new node types.

Here’s an add-on plan you can append to your existing topology plan.

***

## 4. Topology Layout & Edge Rendering Adjustments

### 4.1 Auto-adjust Connections When Nodes Move

**Goal**: When the user drags nodes on the map, all associated edges should dynamically re-route so that:

- Lines originate/terminate at visually correct points on the node’s perimeter.
- The layout feels “aware” of node positions (no lines cutting through nodes unnecessarily).

**Plan**:

1. **Use library’s live edge routing**  
   - Ensure node drag events update node positions in the graph engine (Cytoscape / React Flow).
   - Edges should be bound to node positions so that when node coordinates change, edges redraw automatically (most libs do this; confirm and fix any manual overrides).

2. **Anchor edges to node perimeter**  
   - Configure edges to attach to node border, not center:
     - For Cytoscape:
       - Use `target-endpoint`, `source-endpoint`, or built‑in `curve-style: bezier / straight` with automatic perimeter anchoring.
     - For React Flow:
       - Use `position`, `sourcePosition`, `targetPosition` (top/bottom/left/right).
   - Determine `sourcePosition` / `targetPosition` based on relative node positions:
     - If target.x > source.x → sourcePosition = "right", targetPosition = "left".
     - If target.x < source.x → reverse; if mostly vertical → top/bottom.

3. **Recompute anchor hints on drag end**  
   - On node drag end:
     - For all edges touching that node:
       - Compare node center positions and set appropriate source/target side props.
   - Persist these anchor hints in local layout state (but not in DB; see 4.2 for explicit endpoint overrides).

***

### 4.2 User-adjustable Edge Endpoints (Per-edge Fine Tuning)

**Goal**: Let the user tweak exactly where edges connect to nodes, without changing underlying relationships.

**Concept**: Each edge keeps its logical relation (e.g., `hosts`, `runs`, `connects_to`), but can store optional **endpoint overrides**:

- `source_side`: `'top' | 'right' | 'bottom' | 'left' | null`
- `target_side`: `'top' | 'right' | 'bottom' | 'left' | null`

If null, auto-logic from 4.1 applies. If set, user preference takes precedence.

**Data Model**:

- Extend your existing “saved positions” entity (where you store node positions) to also include per-edge overrides.

Example (for layout storage table or JSON):

```json
{
  "environment": "prod",
  "layout_mode": "manual",
  "nodes": {
    "hw-1": { "x": 100, "y": 200 },
    "svc-5": { "x": 400, "y": 260 }
  },
  "edges": {
    "edge-17": { "source_side": "right", "target_side": "left" }
  }
}
```

- Backend:
  - Extend layout schema / endpoint:
    - `GET/PUT /api/v1/graph/layout` to include optional `edges` map.
- Frontend:
  - When loading manual layout, set `sourcePosition` / `targetPosition` for edges from this map.

**UX – Editing endpoints**:

- Edge handle mode:
  - When user hovers an edge near a node endpoint, show a small handle on the node border (4 positions).
  - Clicking a side handle pins that endpoint to that side:
    - Updates in-memory override.
- Alternatively, edge context menu:
  - “Anchor to top/left/right/bottom of source/target”.
- Persist changes on “Save Positions” (existing control).

***

### 4.3 Straight-line vs Curved Connections

**Goal**: Provide a **global layout option** to render edges either as:

- Curved (current behavior), or
- Straight (no curves).

**Settings & Controls**:

1. **Settings → Map**:
   - Add a toggle:
     - `Edge style: (o) Curved  ( ) Straight`
   - Stored in settings under a map config, e.g.:

     ```json
     "map": {
       "edge_style": "curved" | "straight"
     }
     ```

2. **Map toolbar**:
   - Optional quick toggle icon to switch edge style per session; respects global default.

**Implementation**:

- Frontend:
  - Pass `edgeStyle` into graph renderer:
    - For Cytoscape:
      - `curve-style: 'bezier'` for curved, `'straight'` for straight.
    - For React Flow:
      - Use different `edgeTypes`:
        - `smoothstep` or `bezier` vs `straight` / `simple`.
  - When toggled:
    - Re-render edges with the new type; node positions remain unchanged.
- Backend:
  - Just stores the preference in settings (no schema changes to core entities).

**Interaction with 4.2**:

- Endpoint overrides (top/right/bottom/left) must work regardless of curved vs straight:
  - Straight lines: connect side to side directly.
  - Curved: curve control points still based on those sides but styled aesthetically.

***

### 4.4 Persistence and Existing “Save Positions” Behavior

You already have a “Save Positions” button. Extend its semantics to include:

- Node positions (existing).
- Edge endpoint overrides (4.2).
- Still independent of edge style (curved/straight is a global setting, not per-layout).

Flow:

1. User moves nodes and edits endpoints.
2. Clicks “Save Positions”.
3. App sends updated layout JSON (nodes + edges overrides) to backend.
4. On reload:
   - Load saved layout.
   - Apply node positions.
   - Apply endpoint overrides.
   - Use current edge style setting for final rendering.

***

### 4.5 Exit Criteria for This Topology Adjustment

1. **Auto anchor behavior**:
   - Dragging a node causes connected edges to re-attach to the most logically appropriate side (based on relative position) without overlapping nodes.

2. **User-adjustable endpoints**:
   - User can fix an edge’s connection point to a specific side of a node.
   - Overrides persist after refresh (via Save Positions).
   - Changing nodes’ positions maintains those chosen sides.

3. **Straight-line option**:
   - Switching between Curved and Straight in settings updates the map instantly.
   - Choice persists across sessions.
   - Both styles respect endpoint overrides.

4. **No impact on relationships**:
   - All tweaks are purely visual; underlying `nodes[]` / `edges[]` IDs and relations from `/graph/topology` remain unchanged.
