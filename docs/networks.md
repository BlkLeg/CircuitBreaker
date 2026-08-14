# Networks (IPAM)

Networks help you document segmentation and connectivity in your environment.

Use them to track VLANs, subnets, and gateway context.

Networks live on the **IPAM** page, which needs the `editor` role or higher. (`/networks` redirects there.)
IPAM has four tabs: **Networks**, **IP Addresses**, **VLANs**, and **Sites**.

---

## Documenting Networks

1. Open **IPAM** and stay on the **Networks** tab.
2. Select **Add Network**.
3. Enter network details and save.

Fields:

- **Name** (for example: Trusted LAN, IoT VLAN, DMZ)
- **CIDR** (for example: `192.168.10.0/24`)
- **VLAN ID**
- **Gateway IP** — plain text, for example `10.10.10.1`
- **Gateway Hardware** — the hardware node acting as the gateway
- **Description**
- **Site**
- **Tags**

The Networks list also shows utilization and the IP count for each network.

---

## Linking Networks

Link networks to services and other entities that rely on them.

This gives you a quick answer to:

- Which services are on which segment?
- What could be affected by network changes?
- Where should security boundaries be reviewed?

---

## Related Guides

- [Services](services.md)
- [Topology Map](topology-map.md)
