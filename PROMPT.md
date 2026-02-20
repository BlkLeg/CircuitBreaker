**Prompt: Circuit Breaker v2 Phase 1 – Map Context Menu + Enhanced Hardware Info**

You are a senior Vite/React + FastAPI engineer.  
**Circuit Breaker v1** is complete and production-ready (CRUD, relationships, map, logs, settings, vendor icons).  

**Your task**: Implement **v2 Phase 1** focusing on **Map Context Menu** (right-click actions) and **Enhanced Hardware/Compute Information** (storage details). These are the highest-priority v2 features.

***

## Phase 1 Goals (from v2 roadmap)

### 1. Map Context Menu (Right-Click Actions)
**Right-click any node → rapid relationship creation** without leaving the map.

### 2. Enhanced Hardware/Compute Information
**Storage capacity and type** shown in node details, tooltips, and map badges.

***

## Backend Implementation

### 1. Enhanced Entity Schemas (Storage Summary)

**Extend existing schemas** to include storage information:

#### Hardware schema update
```python
# app/schemas/hardware.py - ADD these fields
class Hardware(HardwareBase):
    # ... existing fields ...
    storage_summary: Optional[dict] = None  # NEW
    # {
    #   "total_gb": 10000,
    #   "used_gb": 8000, 
    #   "types": ["ssd", "hdd", "zfs"],
    #   "primary_pool": "tank"
    # }
```

#### Compute schema update  
```python
# app/schemas/compute_units.py - ADD
class ComputeUnit(ComputeUnitBase):
    # ... existing fields ...
    storage_allocated: Optional[dict] = None  # NEW
    # {
    #   "disk_gb": 500,
    #   "storage_pools": ["tank/media"]
    # }
```

#### Graph endpoint enhancement
**Extend `/api/v1/graph/topology`** to include storage data:
```json
{
  "nodes": [
    {
      "id": "hw-1",
      "type": "hardware", 
      "ref_id": 1,
      "label": "Node-1",
      "tags": ["prod"],
      "storage_summary": {          // NEW
        "total_gb": 10000,
        "used_gb": 8000,
        "types": ["ssd", "zfs"],
        "primary_pool": "tank"
      }
    }
  ]
}
```

**Storage calculation logic** (simple aggregation):
- Hardware: sum storage pools attached to this hardware_id.
- Compute: sum disk_gb + storage pools via service relationships.

### 2. No new endpoints needed
- Reuse existing Phase 2 relationship APIs:
  - `POST /api/v1/services/{id}/storage`
  - `POST /api/v1/networks/{id}/members`
  - etc.

***

## Frontend Implementation (Map HUD)

### 1. Map Context Menu (Right-Click)

**Add right-click context menu** to Cytoscape.js (or your graph library):

#### Context menu structure:
```
Right-click SERVICE node:
├── 🔗 Link to Hardware     → dropdown(all hardware)
├── 🔗 Link to Compute      → dropdown(all compute units)  
├── 🔗 Link to Storage      → dropdown(all storage)
├── 🔗 Link to Network      → dropdown(all networks)
└── 🔗 Link to Misc         → dropdown(all misc items)

Right-click COMPUTE node:
├── 🔗 Link to Hardware     → dropdown(all hardware)
├── 🔗 Link to Services     → dropdown(all services)
└── 🔗 Link to Network      → dropdown(all networks)

Right-click HARDWARE node:
├── 🔗 Link to Compute      → dropdown(all compute units)
└── 🔗 Link to Storage      → dropdown(all storage)
```

#### Implementation:
```javascript
// Map HUD - right-click handler
cy.on('cxttap', 'node', (evt) => {
  const node = evt.target;
  const nodeType = node.data('type');
  const nodeId = node.data('id');
  
  showContextMenu({
    position: evt.position || evt.cyPosition,
    items: getContextMenuItems(nodeType, nodeId),  // context-aware
    onSelect: async (action, targetId) => {
      await createRelationship(nodeType, nodeId, action, targetId);
      refreshGraph();  // re-fetch /graph/topology
      showToast('Relationship created!');
    }
  });
});
```

**Dropdown features**:
- Searchable (type to filter by name/tags).
- Shows: name + tags + brief info.
- Loading state during API calls.
- Error handling with toast messages.

### 2. Enhanced Node Information (Storage)

#### Map node tooltips
```
Node-1 (Hardware)
10TB total (80% used)
Primary: tank (ZFS)
Tags: prod, hypervisor
```

#### Node badges (visual indicators)
- Small progress bar or disk icon with capacity %.
- Color-coded: green (low usage), yellow (medium), red (high).

#### Side panel enhancements
```
Hardware: Node-1
Role: hypervisor | Vendor: Dell ✓
Storage: 10TB total (8TB used)
├─ tank (ZFS): 8TB/10TB
└─ fast (SSD): 500GB/1TB
```

### 3. HUD Detail Panels

**Update entity HUDs** to show storage info:
- Hardware HUD: storage capacity breakdown chart.
- Compute HUD: allocated storage summary.
- Service HUD: storage pools it uses (via relationships).

***

## Command Palette Integration

Add new commands:
```
Map: Link selected node
Map: Show storage details  
Hardware: Filter by storage capacity
```

***

## Integration Points

1. **Settings**: Respect `map_default_filters` for initial graph load.
2. **Vendor icons**: Storage nodes show vendor icons if configured.
3. **Logs**: All context menu actions logged automatically.
4. **Theme**: Context menu uses current theme colors.

***

## Exit Criteria (MUST PASS)

### Map Context Menu
1. Right-click service node → "Link to Storage" → dropdown appears.
2. Type "tank" → filter storage → select → edge appears on graph.
3. Right-click compute → "Link to Network" → works.
4. Right-click hardware → "Link to Compute" → works.
5. Error cases show toast, menu stays open.

### Storage Information  
1. Hardware node tooltip shows "10TB (80% used, ZFS)".
2. Map badges show storage capacity visually.
3. Side panel shows detailed storage breakdown.
4. Graph endpoint includes `storage_summary` data.

### No regressions
1. All v1 features work unchanged.
2. Map pan/zoom/node selection unchanged.
3. Filters still work.

***

## Non-Goals (Phase 1)
- Authentication (Phase 2).
- Doc editor improvements (Phase 2). 
- Theming/branding (Phase 2).
- Advanced storage analytics.

***

## Output Format

When complete, respond with:

1. **Backend changes**: Updated schemas + graph endpoint storage logic.
2. **Context menu code**: Cytoscape event handler + dropdown implementation.
3. **Storage UI**: Tooltip + badge + side panel examples.
4. **Test workflow**: 5-step test proving right-click → link → edge appears.
5. **New commands**: Command palette entries added.

**Keep it focused**: Map context menu + storage info only. No feature creep.

---