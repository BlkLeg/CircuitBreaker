```markdown
# server-sim.md – Circuit Breaker Rack Simulator (v2+ Feature)

## 1. Vision

Circuit Breaker will include a **lightweight server rack simulator** that lets users design, visualize, and understand their homelab hardware layout as if they were looking at a physical rack.

The simulator is:

- **Interactive**: Users choose rack size and drag components into slots.
- **Data-driven**: Integrates with the existing Circuit Breaker database and backend.
- **Informative**: Clicking any component reveals and edits its specs (CPU, RAM, storage, etc.).
- **Lightweight**: Implemented in JavaScript (frontend) with Python/FastAPI (backend) to keep deployment simple.

The long-term goal is a **visual digital twin** of the homelab: the rack view becomes the “bread and butter” for understanding where everything physically lives.

---

## 2. Core Concepts

### 2.1 Rack Model

A rack is a configurable vertical layout of **units** (U):

- User-configurable:
  - Total height: 8U–48U (homelab-friendly).
  - Optional sections (upper/lower racks, half-depth shelves later).
- Internal representation:
  - `Rack` entity:
    - `id`
    - `name`
    - `height_u` (int)
    - `location` (string, optional)
    - `notes`
  - `RackSlot` model (virtual; stored as part of device positioning):
    - `rack_id`
    - `start_u` (topmost U occupied by the device)
    - `height_u` (how many U consumed)
    - `depth` (front-only, rear-only, or full — v2+)

The rack is rendered as a **2D or pseudo-3D front elevation** with clearly marked U positions. Each slot can contain one “rack device” placeholder, which may represent:

- Rackmounted devices (1U/2U/etc).
- Shelves that hold smaller items (mini-PCs, Pis).
- “Floating” items overlaid without strict U alignment (optional later).

### 2.2 Component Library

The simulator provides a **library of homelab components**, such as:

- Router / Firewall (e.g., OPNsense box).
- Desktop PC / tower.
- Mini-PC / NUC.
- Raspberry Pi / SBC.
- 1U/2U servers.
- Switches (24/48-port).
- NAS / storage devices.
- Shelves / trays.
- PDUs (future).

Each library entry has:

- `id` (component type id)
- `name` (e.g., “1U Server”, “Mini-PC”)
- `category` (`router`, `switch`, `server`, `mini_pc`, `pi`, `shelf`, `nas`, `other`)
- `default_height_u` (1 for 1U devices, 0 for non-rackmount like mini-PCs on shelves)
- `default_color` / visual style
- `default_icon` / SVG sprite
- `capability_hints`: allows mapping to existing entities:
  - `hardware_compatible` – can be bound to a `hardware` record
  - `compute_compatible` – can be bound to a `compute_unit`
  - `service_highlight` – highlight that this device runs key services

These define **visual behavior**; actual configuration is driven by binding to real database entities.

### 2.3 Placements and Bindings

When a user drags an item from the library into the rack:

- A **RackPlacement** record is created:
  - `id`
  - `rack_id`
  - `component_type_id`
  - `start_u` and `height_u`
  - `position` (front/back, left/right for shelves, future)
  - `bound_hardware_id` (optional)
  - `bound_compute_id` (optional)
  - `label` (optional override)
  - `color_override` (optional)
- The placement may be **bound** to existing Circuit Breaker entities:
  - Hardware: physical machine or NAS.
  - Compute units: a particular VM host or host node.
  - Services: indirectly via that hardware/compute.

Binding strategies:

- **One-to-one**: Each hardware entity can be associated with zero or one RackPlacement.
- **Many-to-one**: Shelves can contain multiple mini devices (v2+ extension).

---

## 3. User Experience

### 3.1 Rack Creation Flow

1. Open **Rack Simulator** from HUD/Dock (e.g., “Racks” or “Server View” tab).
2. Click **“Create Rack”**:
   - Enter:
     - Rack name.
     - Height (U).
     - Location (optional).
3. A new empty rack grid is generated:
   - U positions labeled along the left.
   - Optional guides for power zones (top/mid/bottom).

### 3.2 Drag-and-Drop Placement

- Left side: **Component Library panel** with draggable items.
- Center: **Rack canvas** (vertical front view).
- Right side: **Details / Inspector panel**.

Interactions:

- Drag a component from the library onto a U position in the rack.
- Snap to the nearest U; if the component’s height exceeds free space, show an error.
- Allow repositioning by dragging existing placements up/down.
- Support keyboard shortcuts for nudge (Up/Down arrow).

Constraints:

- Non-overlap of U ranges for front-mounted devices.
- Optionally allow:
  - “Loose” items on shelves (two mini-PCs on one shelf) as children in v2+.

### 3.3 Component Inspector

Clicking a placed component opens the **Inspector**:

- **General**:
  - Name / label (editable).
  - Type (from library).
  - Rack: name and U position.
- **Hardware binding**:
  - Dropdown to bind to existing `hardware` entity:
    - Filtered by tags or vendor (e.g., “Dell”, “HP”).
  - If bound:
    - Show summary: CPU, RAM, storage, vendor.
    - One-click “Open hardware HUD”.
- **Compute binding** (optional):
  - Bind to a `compute_unit` record (e.g., the Proxmox node).
- **Specs** (local to the simulator, with defaults from binding):
  - CPU model.
  - RAM (GB).
  - Storage (size, type).
  - NIC count/ports.
  - Notes.
- **Visuals**:
  - Color / accent.
  - Icon variant (e.g., different server bezel styles).

Data precedence:

- If bound to hardware, specs are pre-filled from DB but can be overridden for rack-only representation.
- Updates to bound hardware in main app should be reflected, but local overrides can be preserved.

---

## 4. Integration with Existing Circuit Breaker Data

### 4.1 Hardware Integration

- Mapping:
  - Each `hardware` can appear as a rack device.
  - A bound rack device is the **visual representation** of a hardware record.
- UI:
  - Option on Hardware HUD: “Place in Rack”.
    - Opens rack selector and U position chooser.
    - Creates a RackPlacement associated with that hardware.

### 4.2 Compute and Services

- Compute:
  - Rack placements can optionally link to compute units (e.g., a Proxmox node).
  - Hovering the rack item can show:
    - “Hosts 6 VMs / 4 LXCs”.
- Services:
  - Indirect: clicking through to hardware/compute HUD shows services.
  - Future: overlay icons or badges for key services (e.g., Plex, NAS, Router).

### 4.3 Graph and Map Synergy

- The rack simulator provides a **physical view**, while the existing map shows **logical topology**.
- For a given hardware node:
  - Map view: where it connects (networks, services).
  - Rack view: where it lives physically (which U in which rack).
- Cross-links:
  - From Map node → “Show in Rack” (if bound).
  - From Rack item → “Show in Map” (focus that node in topology).

---

## 5. Architecture

### 5.1 Backend (Python / FastAPI)

New entities:

- `Rack` table:
  ```sql
  CREATE TABLE racks (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      name        TEXT NOT NULL,
      height_u    INTEGER NOT NULL,
      location    TEXT,
      notes       TEXT,
      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL
  );
  ```

- `RackPlacement` table:
  ```sql
  CREATE TABLE rack_placements (
      id                  INTEGER PRIMARY KEY AUTOINCREMENT,
      rack_id             INTEGER NOT NULL,
      component_type_id   TEXT NOT NULL,     -- references library component key
      start_u             INTEGER NOT NULL,
      height_u            INTEGER NOT NULL,
      position            TEXT,              -- 'front', 'rear', 'shelf' (future)
      bound_hardware_id   INTEGER,           -- nullable
      bound_compute_id    INTEGER,           -- nullable
      label               TEXT,
      color_override      TEXT,
      specs_json          TEXT,              -- JSON for CPU/RAM/storage/etc.
      created_at          TEXT NOT NULL,
      updated_at          TEXT NOT NULL,
      FOREIGN KEY (rack_id) REFERENCES racks(id),
      FOREIGN KEY (bound_hardware_id) REFERENCES hardware(id),
      FOREIGN KEY (bound_compute_id) REFERENCES compute_units(id)
  );
  ```

Endpoints (v1 of simulator):

- Racks:
  - `GET /api/v1/racks`
  - `POST /api/v1/racks`
  - `GET /api/v1/racks/{id}`
  - `PATCH /api/v1/racks/{id}`
  - `DELETE /api/v1/racks/{id}`

- Rack placements:
  - `GET /api/v1/racks/{id}/placements`
  - `POST /api/v1/racks/{id}/placements`
  - `PATCH /api/v1/rack-placements/{id}`
  - `DELETE /api/v1/rack-placements/{id}`

- Component library:
  - Static JSON served from `/api/v1/rack-components` or embedded in frontend config.

Validation:

- Ensure `start_u + height_u - 1` does not collide with existing placements in that rack/position.
- Enforce 1-based U numbering from top to bottom (or bottom to top, but be consistent).

### 5.2 Frontend (JS / Vite / React)

New main view:

- `RackSimulatorPage` or `RacksHUD`:
  - Canvas for rack rendering.
  - Drag-and-drop from library.
  - Inspector panel.

Rendering:

- 2D representation using:
  - Canvas/SVG (e.g., via plain SVG + React).
  - Optional 3D-like styling (shadows, gradients).
- Each rack:
  - Vertical stack of slots.
  - Placed components drawn as rounded rectangles with labels and icons.

State:

- `racks`: list of racks from API.
- `selectedRackId`.
- `placements` for selected rack.
- `dragState` for drag-and-drop interactions.
- `selectedPlacement` for inspector.

Interactions:

- Changing rack height adjusts grid and validates placements.
- Dragging within rack updates placements via API.
- Undo/redo (optional later via client-side history).

---

## 6. Future Enhancements (Beyond Initial Version)

Not required in initial server-sim implementation but worth noting:

- **Cabling**:
  - Visual patch cables between devices (switch to server).
- **Power / thermal visualization**:
  - Show power draw and heat zones per rack.
- **Rear rack view**:
  - Separate layout for rear devices (PDUs, cable management).
- **Templates**:
  - Save and reuse common rack layouts.
- **Export**:
  - Export rack view as PNG/SVG or JSON.

---

## 7. Success Criteria

The server rack simulator is considered successful when:

1. Users can create one or more racks with configurable heights.
2. Users can drag components (routers, switches, servers, etc.) into racks and reposition them without overlap.
3. Clicking any placed component opens an inspector where users can:
   - Bind the placement to existing hardware/compute entities.
   - Edit CPU, RAM, storage, and notes.
4. Bound placements show live hardware summary (CPU/RAM/storage) from the main DB.
5. From a hardware or compute HUD, users can quickly jump to its rack position (“Show in Rack”).
6. From a rack item, users can jump to the corresponding hardware/compute HUD.
7. All data (racks + placements) persist across reloads and are accessible via API for future features (e.g., export, cabling, power modeling).

This document should guide the first implementation phase of **Circuit Breaker’s Rack Simulator**, ensuring it ties cleanly into the existing data model while remaining approachable for homelab users.
```