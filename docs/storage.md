# Storage

Storage items in Circuit Breaker document the disks, pools, volumes, and network shares used by your lab. This could be a physical hard drive in a server, a ZFS pool, or an NFS share hosted on a separate NAS.

## Adding Storage

To add a new storage resource:

1. Navigate to **Storage** using the sidebar.
2. Click **Add Storage**.
3. Fill in the required details:
   - **Name**: A descriptive name (e.g., `ZFS-Tank`, `NFS-Media-Share`).
   - **Type**: The kind of storage (e.g., `ZFS Pool`, `EXT4 Drive`, `NFS Share`).
   - **Capacity**: Total size or current usage (e.g., `12TB`).

## Linking Storage

Storage items can be connected in two ways:

1. **Physical Location**: Link a storage item to the **Hardware** it physically resides on (e.g., `ZFS-Tank` on `pve-node-01`).
2. **Usage**: Link a storage item to the **Services** that utilize it (e.g., the `Plex` service uses the `NFS-Media-Share`).

These connections are crucial for understanding which applications might fail if a specific array goes down or a volume becomes full.
