# Storage

Storage entries track where your data lives and who depends on it.

Use this section for pools, volumes, disks, and shared storage.

---

## Adding Storage

1. Open **Storage**.
2. Select **Add Storage**.
3. Enter storage details.
4. Save.

Common fields:

- **Name**
- **Type**
- **Capacity**

### Virtualized & Proxmox Storage

Storage entries can also be created dynamically. If a **Proxmox Cluster** is integrated within Settings, Circuit Breaker will detect and populate virtualized storage pools (ZFS, directory mounts, logical LVM block devices) directly as distinct infrastructure nodes on the Map. Every node automatically establishes ownership lines to their backing hardware host.

---

## Linking Storage

Connect storage in two ways:

1. **Physical location:** Link storage to the hardware that hosts it.
2. **Service usage:** Link storage to services that read or write to it.

This makes it easier to answer impact questions during maintenance and outages.

---

## Why It Matters

- See which services depend on each storage resource.
- Plan migrations and maintenance with less risk.
- Spot high-impact storage points in the topology map.

---

## Related Guides

- [Hardware](hardware.md)
- [Services](services.md)
- [Topology Map](topology-map.md)
