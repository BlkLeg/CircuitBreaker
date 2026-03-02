# Topology Map

The Topology Map is the core "at-a-glance" visualizer for Circuit Breaker. Once you have entered your Hardware, Compute, Services, Storage, and Networks, the Map automatically renders their relationships.

## How to Read the Map

The map generates a visual layout based on the connections you defined:

- **Hardware Nodes**: Usually form the base or outer layer of the map. They indicate the physical constraints of your lab.
- **Compute Instances**: Appear connected directly to the hardware hosting them.
- **Services**: Float above or attach directly to their respective compute endpoints.
- **Shared Resources**: Storage and Networks are depicted as interconnected nodes that multiple services or hardware items link into.

## Interacting with the Map

- **Pan & Zoom**: Click and drag empty space to pan. Use your mouse wheel or trackpad to zoom in and out.
- **Node Details**: Clicking on any node in the map will open a side panel (or detail page) showing its configuration, assigned IP addresses, current capacity (for storage), and attached notes.
- **Right-click context menu**: Right-click any node to link or unlink relationships, or select **Edit Icon** to open the icon picker and reassign the node's icon.
- **Filtering**: Use the search and filter tools to declutter the map. For example, search for the `prod` tag to hide development services, or filter specifically for `Storage` nodes.

---

## Live Device Health

Hardware nodes with [telemetry configured](hardware.md#telemetry) display a **live status ring** directly on the map:

| Ring state | Meaning |
| --- | --- |
| 🟢 Pulsing green | All systems healthy |
| 🟡 Amber | Degraded — something needs attention |
| 🔴 Glowing red | Critical condition |
| *(no ring)* | Telemetry not configured for this device |

Key metrics such as CPU temperature and power draw appear as a small badge on the node so you can assess device health without opening the detail panel.

See [Hardware → Telemetry](hardware.md#telemetry) to configure integrations.
