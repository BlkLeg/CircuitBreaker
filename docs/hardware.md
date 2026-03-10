# Hardware

Hardware is the physical layer of your environment: servers, switches, firewalls, storage appliances, UPS units, and more.

---

## Adding Hardware

1. Open **Hardware**.
2. Select **Add Hardware**.
3. Enter device details and save.
### Proxmox Clusters

When leveraging the **Proxmox Integration** from the Settings menu, Proxmox host nodes discovered organically via the virtualization API are automatically populated into the Hardware index as `Hypervisor` roles. Their attached telemetry (CPU utilization, memory usage) will immediately stream directly via the backend poller.
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

Each hardware node has a **Role** that describes its primary function. Choose the role that best fits the device:

| Role | What it represents |
| --- | --- |
| Server | General-purpose compute host |
| Switch | Layer 2 / Layer 3 network switch |
| Router | Routing and WAN gateway device |
| Firewall | Network security / firewall appliance (e.g., pfSense, OPNsense) |
| NAS | Network-attached storage device |
| Hypervisor | Dedicated virtualization host (e.g., Proxmox, ESXi) |
| **UPS** | Uninterruptible power supply |
| **PDU** | Power distribution unit |
| **Access Point** | Wireless access point |
| **SBC** | Single-board computer (e.g., Raspberry Pi, Radxa) |

---

## Categories & Environments

Category and Environment fields support quick type-ahead entry.

You can choose existing values or create new ones directly while editing hardware.

---

## Rack Position

Use these fields to record physical placement:

- **Rack Height (U)** — how many rack units the device occupies
- **Rack Position (U)** — which rack unit it starts at (counting from the top)

This helps with planning and maintenance work.

---

## Telemetry

You can connect supported hardware telemetry to show live health indicators on the topology map.

### Supported Integrations

| Integration | Metrics available |
| --- | --- |
| **Dell iDRAC** 6 / 7 / 8 / 9 | CPU temp, fan speeds, PSU status, system power draw |
| **HPE iLO** 4 / 5 / 6 | CPU temp, fan speeds, PSU watts, overall health status |
| **APC & CyberPower UPS** | Battery %, estimated runtime, load %, input/output voltage, temperature |
| **Generic SNMP** | Any SNMP-capable device using custom OIDs |

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
