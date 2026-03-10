# Topology Map

The Topology Map is your live visual workspace for understanding infrastructure relationships.

It combines inventory, dependencies, status, and editing tools in one place.

---

## What You See

- **Nodes** for hardware, compute, services, storage, networks, misc, clusters, and external/cloud systems.
- **Edges** for how things are connected.
- **Live status indicators** for monitored hardware.
- **Side panel details** for whichever node you select.

---

## Core Controls

### Filters and visibility

- Filter by **environment**.
- Filter by **tag**.
- Toggle which **node types** are shown.
- Filter hardware by role (for example UPS, PDU, AP, SBC).

### Layout and view

- Switch between traditional automated structures like **Dagre**, **Force**, and **Tree**.
- For advanced architectural needs, use the new intelligent layouts:
    - **Network-First Hierarchical**: Orders networks at the top, cascading down to hypervisors, compute nodes, and then services.
    - **Radial and Concentric**: Radiates service-centric views outwards—perfect for microservice and Docker service visualizations.
    - **Layered VLAN/Segment view**: Arranges components left-to-right (WAN, DMZ, LAN, Management, etc).
    - **Circular Cluster**: Designed specifically to showcase Proxmox virtualization pools or Docker overlays.
- Use **Cloud View** to simplify large mixed maps.
- Save current placement with **Save Positions** (all customized options, including groupings and layouts, adhere to this state when reloaded).
- Use **Refresh** to reload current data.

### Legend and navigation

- Open the **Legend** for connection, node, and status meaning.
- Use built-in map controls for zoom and centering.

---

## Editing Directly on the Map

### Node actions (right-click)

Depending on node type, you can:

- Link nodes
- Edit icon
- Update alias
- Update status
- Set hardware role
- Delete node
- Quick-create related items (service, compute, storage)

### Create from canvas

Right-click empty map space to create a new node at that position.

### Edge actions

- Drag to create a connection between nodes.
- Reconnect an existing edge to a different target.
- Choose connection type when connecting.
- Right-click an edge to adjust anchor sides or clear bend points.

---

## Boundaries and Labels

### Boundaries

- Use **Draw Boundary** and drag over map regions.
- Boundaries can be renamed.
- Boundaries are saved with your layout.

### Labels

- Add free labels with **Add Label**.
- Drag labels to reposition.
- Resize labels by editing.
- Change label color.
- Remove labels when no longer needed.

---

## Side Panel Details and Live Pulse Telemetry

Selecting a node opens details such as:

- Related nodes and relationship direction
- Key system details for that entity
- Effective status and source status signals
- **Live Pulse Metrics**: Host, VM, LXC, and service nodes stream inline metrics directly on hover via Pulse cards (e.g., showing CPU, memory, disk, and network stats updated live from backend poller jobs, like Proxmox). This keeps telemetry centralized without needing external dashboards.
- Uplink speed controls where supported
- Quick jump to full entity page

---

## Live Health and Status

Hardware with telemetry can show live status rings and updates directly on map nodes.

| Ring state | Meaning |
| --- | --- |
| 🟢 Pulsing green | All systems healthy |
| 🟡 Amber | Degraded — something needs attention |
| 🔴 Glowing red | Critical condition |
| *(no ring)* | Telemetry not configured for this device |

You can also override or reset statuses where supported.

---

## Discovery Tie-In

If there are pending discovery findings, the map shows a shortcut badge to the Discovery review queue.

---

## Best Practice Workflow

1. Filter to a single environment.
2. Toggle only relevant node types.
3. Confirm relationships and statuses.
4. Save positions after adjustments.
5. Use boundaries and labels for clearer communication.

See [Hardware](hardware.md), [Auto-Discovery (Beta)](discovery.md), and [Settings](settings.md) for related setup.
