# Hardware

Hardware is the physical layer of your environment: servers, switches, firewalls, storage appliances, UPS units, and more.

---

## Adding Hardware

1. Open **Hardware**.
2. Select **Add Hardware**.
3. Enter device details and save.
### Proxmox Clusters

When leveraging the **Proxmox Integration** from **Discovery → Proxmox VE**, Proxmox host nodes discovered organically via the virtualization API are automatically populated into the Hardware index as `Hypervisor` roles. Their attached telemetry (CPU utilization, memory usage) will immediately stream directly via the backend poller.
---

### Device Catalog Smart Search

As you type a model name, Circuit Breaker suggests matching hardware from the built-in catalog.

When you pick a match, key fields are filled automatically:

- Vendor
- Model
- Rack height
- Device role

If your device is not listed, use manual entry.

---

## Device Roles

Each hardware node has a **Role** that describes its primary function. Roles are a catalog, not a fixed list:
Circuit Breaker seeds 29 built-in roles and you can add, rename or re-rank them under **Settings → Device Roles**.
The rank also drives how the topology map orders devices.

Some of the most common built-ins:

| Role | What it represents |
| --- | --- |
| Server | General-purpose compute host |
| Network Switch | Layer 2 / Layer 3 network switch |
| Router | Routing and WAN gateway device |
| Firewall | Network security / firewall appliance (e.g., pfSense, OPNsense) |
| NAS | Network-attached storage device |
| Hypervisor | Dedicated virtualization host (e.g., Proxmox, ESXi) |
| UPS | Uninterruptible power supply |
| PDU | Power distribution unit |
| WiFi AP | Wireless access point |
| Single Board Computer | Single-board computer (e.g., Raspberry Pi, Radxa) |

The rest of the catalog covers desktops, workstations, mini PCs, laptops, IP cameras, phones, tablets, smart TVs,
thermostats, printers, gaming consoles, VoIP phones, IoT devices, VMs, LXC containers, storage, compute and misc.

---

## Categories & Environments

Category and Environment fields support quick type-ahead entry.

You can choose existing values or create new ones directly while editing hardware.

---

## Telemetry

You can connect supported hardware telemetry to show live health indicators on the topology map.

### Supported Integrations

The transport matters, because it decides which credentials the panel asks for: SNMP profiles ask for an
SNMP community, Redfish profiles ask for a username and password.

| Integration | Transport | Metrics available |
| --- | --- | --- |
| **Dell iDRAC** 6 / 7 / 8 / 9 | SNMP | CPU temp, fan speeds, PSU status, system power draw |
| **HPE iLO** 4 / 5 / 6 | Redfish | CPU temp, fan speeds, PSU watts, overall health status |
| **APC & CyberPower UPS** | SNMP | Battery %, estimated runtime, load %, input/output voltage, temperature |
| **Generic SNMP** | SNMP | Any SNMP-capable device. Custom OIDs are supplied through the integration config/API — the Telemetry panel has no OID field |
| **IPMI / Generic** | SNMP | Generic fallback for IPMI-style BMCs (Supermicro and similar); polled with the generic SNMP client |
| **Network Device (SNMP)** | SNMP | Switches, routers and firewalls: system name/description, uptime, CPU %, memory %, and per-interface counters |

### Configuring Telemetry

1. Open any hardware node's **detail panel**.
2. Expand the **Telemetry** section.
3. Select the integration type and enter the connection details.
4. Click **Test Connection** to verify the credentials work.

After setup, Circuit Breaker checks telemetry automatically.

### Credential Security

Use a vault key in your deployment to protect stored management credentials.

See [Deployment & Security](deployment-security.md) for setup guidance.

---

## Connecting Hardware

Hardware is usually linked to:

- [Compute](compute.md) that runs on it
- [Storage](storage.md) attached to it
- [Services](services.md) that depend on it indirectly

These links make impact analysis easier on the topology map.
