# Compute

Compute entries represent the workloads running on your hardware, such as virtual machines and containers.

They connect your physical devices to the services users actually consume.

---

## Adding Compute

1. Open **Compute**.
2. Select **Add Compute**.
3. Fill in the core fields.
4. Save.

Recommended fields:

- **Name** for easy identification
- **Type** (VM or container)
- **Host hardware** where it runs
- **Resource notes** (CPU/memory summary)
- **Purpose** of the workload

---

## Proxmox Workloads & Clusters

If you configure a **Proxmox API Integration** within Settings, Circuit Breaker bridges the virtual-to-physical gap effortlessly. QEMU and LXC workloads discovered across the API are automatically mapped downward structurally to their respective host Hardware nodes.

Features unlocked during Proxmox Discovery include:

- **Per-VM & Container Pulse Stats:** Inline rendering of VM CPU/memory/disk performance dynamically syncing directly to the front-end map.
- **Run State Inference:** A transparent green/red halo indicating the live `running` or `stopped` condition of the workload directly over its topology icon.

---

## Why Compute Mapping Matters

With compute mapped correctly, you can quickly answer:

- Which services are affected if a host goes down?
- Where should a service be moved during maintenance?
- Which hosts are carrying the most critical workloads?

---

## Related Guides

- [Hardware](hardware.md)
- [Services](services.md)
- [Topology Map](topology-map.md)
