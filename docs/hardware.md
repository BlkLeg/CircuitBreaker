# Hardware

Hardware represents the physical foundation of your lab. This includes the servers, switches, routers, and NAS devices you can physically touch.

## Adding Hardware

To add a new hardware component:

1. Navigate to **Hardware** using the sidebar.
2. Click **Add Hardware**.
3. Fill in the details:
   - **Name**: A recognizable name (e.g., `pve-node-01`, `unifi-switch-24`).
   - **Role**: Describe its primary use (e.g., `Proxmox Host`, `Core Router`).
   - **Specs**: A brief summary of its capabilities (e.g., `Ryzen 5, 64GB RAM, 2TB NVMe`).
   - **Tags**: Add relevant tags for filtering (e.g., `prod`, `lab`, `network`).

## Connecting Hardware

Currently, hardware primarily serves as the host for **Compute** instances. However, you can also link **Storage** (like physical disks or NAS arrays) directly to a Hardware node to indicate where that storage physically resides.

_Pro-tip: If you have a cluster of nodes, use tags like `cluster:proxmox` to group them visually on the map later._
