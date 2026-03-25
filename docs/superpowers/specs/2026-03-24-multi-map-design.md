# Multi-Map Support — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Feature branch target:** `hotfix/performance` → `dev`

---

## Problem

The Circuit Breaker map page has a single, shared view of all entities. Large networks with distinct subnets, locations, or hardware groups become cluttered and hard to navigate. There is no way to create a focused view for (e.g.) just the DMZ, the lab rack, or the off-site WAN links.

## Goal

Allow users to create up to 10 named maps, cycle between them via a compact dropdown in the toolbar, and assign entities to specific maps. The active map renders with full fidelity; inactive maps consume zero resources.

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend model | Activate existing `Topology` / `TopologyNode` tables | Already in the schema from migration 0026; purpose-built for per-map node membership and positions |
| Entity scope | Exclusive by default; can be pinned to all maps | Clean separation with an escape hatch for "core" devices |
| New entity default | Map 1 (default/first map) | Predictable; matches existing behavior |
| Tab UI | Dropdown pill in toolbar | Conserves vertical canvas space; fits CB's existing toolbar aesthetic |
| Assignment UI | Entity detail drawer + right-click context menu | Both deliberate (drawer) and quick (context menu) paths |
| Inactive map perf | Full unmount via React `key` | No timers, polling, WebSocket, or animation frames from inactive maps |

---

## Data Model

### Existing tables activated

**`topologies`** — one row per map:
- Existing: `id`, `name` (display name), `is_default`, `tenant_id`, `created_at`, `updated_at`
- **Added**: `sort_order INTEGER NOT NULL DEFAULT 0`

**`topology_nodes`** — entity membership per map:
- Existing: `id`, `topology_id`, `entity_type`, `entity_id`, `x`, `y`, `size`, `extra` (JSONB)
- No changes needed; presence of a row for `(topology_id, entity_type, entity_id)` = "entity is on this map"

**`graph_layouts`** — layout/visual JSONB blob per map:
- Existing: `id`, `name`, `context`, `layout_data` (JSONB), `updated_at`
- **Added**: `topology_id INTEGER REFERENCES topologies(id) ON DELETE CASCADE`

### New table

**`map_pinned_entities`** — entities that appear on every map:
```sql
CREATE TABLE map_pinned_entities (
    entity_type VARCHAR NOT NULL,
    entity_id   INTEGER NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);
```

### Migration: `0063_multi_map.py`

`upgrade()` steps:
1. Add `sort_order` to `topologies`
2. Add `topology_id` FK + index to `graph_layouts`
3. Create `map_pinned_entities`
4. Seed: insert one `Topology` row `{name: "Main", is_default: True, sort_order: 0}` using `ON CONFLICT DO NOTHING` (guard against existing installs that may already have a topology row), then set `graph_layouts.topology_id` for any existing row with `name='default'`

`downgrade()`: removes the above in reverse order.

---

## API

### New resource: `/api/v1/maps`

| Method | Path | Description |
|---|---|---|
| `GET` | `/maps` | List all maps sorted by `sort_order` |
| `POST` | `/maps` | Create map (max 10 enforced; 409 if at limit) |
| `PATCH` | `/maps/{id}` | Rename or reorder |
| `DELETE` | `/maps/{id}` | Delete map + cascade nodes + linked layout row |
| `POST` | `/maps/{id}/entities` | Assign entity `{entity_type, entity_id}` |
| `DELETE` | `/maps/{id}/entities/{type}/{entity_id}` | Remove entity from map |
| `POST` | `/maps/pin` | Pin entity to all maps |
| `DELETE` | `/maps/pin/{type}/{entity_id}` | Unpin entity |

**`GET /maps` response:**
```json
[
  {"id": 1, "name": "Main", "is_default": true, "sort_order": 0, "entity_count": 24},
  {"id": 2, "name": "DMZ",  "is_default": false, "sort_order": 1, "entity_count": 8}
]
```

**Max-map 409 body:**
```json
{"detail": "Map limit reached (10). Delete a map before creating a new one."}
```

### Updated existing endpoints

**`GET /graph/topology`**
- New optional query param: `map_id: int`
- When present: filter nodes to `topology_nodes WHERE topology_id=map_id` UNION `map_pinned_entities`
- When absent: return all entities (backward compat for existing API consumers)

**`GET /graph/layout`**
- New optional query param: `map_id: int`
- Fetches `graph_layouts WHERE topology_id=map_id`; falls back to `name='default'` when absent

**`POST /graph/layout`**
- New optional body field: `map_id: int`
- Writes to `graph_layouts WHERE topology_id=map_id`

---

## Frontend Architecture

### New files

| File | Purpose |
|---|---|
| `src/hooks/useMapTabs.js` | Map list state, CRUD, active map, localStorage persistence |
| `src/components/MapSwitcher.jsx` | Dropdown pill UI for switching/renaming/creating maps |
| `src/api/maps.js` | API client methods for `/maps` resource |

### Modified files

| File | Change |
|---|---|
| `src/pages/MapPage.jsx` | Consume `useMapTabs`; key `<ReactFlowProvider>` on `activeMapId`; pass `mapId` to hooks |
| `src/components/MapToolbar.jsx` | Render `<MapSwitcher>` left of existing controls |
| `src/hooks/useMapDataLoad.js` | Append `?map_id=X` to topology API call |
| `src/hooks/useMapMutations.js` | Include `map_id` in layout save payload |
| `src/hooks/useMapRealTimeUpdates.js` | Only run when `mapId` matches active map (effectively gated by React key unmount) |
| `src/components/details/HardwareDetail.jsx` | Add "Map" field + "Show on all maps" toggle |
| `src/components/details/NetworkDetail.jsx` | Add "Map" field + "Show on all maps" toggle |
| `src/components/details/ClusterDetail.jsx` | Add "Map" field + "Show on all maps" toggle |
| `src/components/details/ComputeDetail.jsx` | Add "Map" field + "Show on all maps" toggle |
| `src/components/details/ServiceDetail.jsx` | Add "Map" field + "Show on all maps" toggle |
| Node right-click menu | Add "Move to map ›" submenu + "Pin to all maps" |

### `useMapTabs` hook

```js
const { maps, activeMapId, switchMap, createMap, renameMap, deleteMap } = useMapTabs();
```

- Fetches `GET /maps` on mount
- Reads `cb_active_map_id` from `localStorage`, defaults to `maps[0].id`
- `switchMap(id)` → saves to `localStorage`, re-triggers topology fetch
- First-use seed: if `GET /maps` returns `[]`, auto-calls `POST /maps {name: "Main"}`

### `MapSwitcher` component

```jsx
<MapSwitcher
  maps={maps}
  activeMapId={activeMapId}
  onSwitch={switchMap}
  onCreate={createMap}
  onRename={renameMap}
  onDelete={deleteMap}
/>
```

Renders a pill button (`[⬡ Main Network ▾]`) that opens a dropdown on click:
- Each row: map name + pencil icon (click pencil → inline text input, confirm on Enter or blur)
- "+ New map…" at the bottom (disabled when `maps.length >= 10`)
- Closes on outside click

### Performance — inactive map isolation

Keying the React Flow provider on `activeMapId`:

```jsx
<ReactFlowProvider key={activeMapId}>
  <MapInternal mapId={activeMapId} ... />
</ReactFlowProvider>
```

When `activeMapId` changes, React unmounts the entire subtree and mounts a fresh one for the new map. This naturally terminates all `useEffect` cleanup, animation frames, `setInterval` timers, and WebSocket subscriptions from the previous map — no explicit pause/resume logic required.

### Entity assignment UX

**Entity detail drawers** (add to each of: `HardwareDetail.jsx`, `NetworkDetail.jsx`, `ClusterDetail.jsx`, `ComputeDetail.jsx`, `ServiceDetail.jsx`):
- "Map" section showing current map name (determined by which `topology_nodes` row this entity appears in)
- Dropdown to reassign: fires `DELETE .../entities` on the old map then `POST .../entities` on the new map
- "Show on all maps" toggle: fires `POST /maps/pin` or `DELETE /maps/pin/...`

**Right-click context menu on node:**
- "Move to map ›" → submenu listing all map names (click to reassign)
- "Pin to all maps" toggle

---

## Backward Compatibility

- Existing installs: migration 0063 seeds one `Topology("Main")` and links the existing layout — no data loss
- API callers omitting `map_id` continue to get the full unfiltered topology
- The `graph_layouts.name='default'` row is preserved and linked, not replaced

---

## Constraints

- Maximum 10 maps per tenant (enforced server-side with 409)
- Map names: 1–64 characters
- Deleting the last map is prevented server-side (must always have at least 1)
- Deleting a non-default map re-assigns its exclusive entities to the default map. The `DELETE /maps/{id}` handler must: (1) query all `topology_nodes WHERE topology_id=deleted_id`, (2) exclude any whose `(entity_type, entity_id)` also appears in `map_pinned_entities`, (3) upsert the remainder into the default map's `topology_nodes` (insert if not already present). FK cascade then cleans up the deleted map's own `topology_nodes` rows.

---

## Verification Checklist

1. `make migrate` completes cleanly; one `Topology("Main")` row exists
2. `GET /api/v1/maps` returns the default map
3. Create a second map via `POST /api/v1/maps`; switch to it in the UI
4. Assign a hardware node to the new map; it disappears from Map 1, appears in Map 2
5. Pin a node to all maps; it appears in both
6. Rename a map via the pencil icon; name updates in real time
7. Delete a map; its exclusive entities move to the default map
8. Create maps until count = 10; "+ New map…" is greyed out
9. Switch maps rapidly; no stale polling, no double WebSocket connections
10. Refresh the page; active map is restored from `localStorage`
