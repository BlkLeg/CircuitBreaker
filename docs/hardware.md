# Hardware

Hardware represents the physical foundation of your lab — servers, switches, firewalls, NAS devices, UPS units, access points, and anything else you can physically touch.

---

## Adding Hardware

To add a new hardware component:

1. Navigate to **Hardware** using the sidebar.
2. Click **Add Hardware**.
3. Start typing a device name in the **search field** at the top of the form.

### Device Catalog Smart Search

Circuit Breaker includes a built-in device catalog. As you type — `R740`, `USW Pro`, `Pi 5` — matching devices are suggested automatically, covering vendors including:

> Dell · HPE · Ubiquiti · MikroTik · Synology · TrueNAS · APC · CyberPower · Raspberry Pi · Proxmox · pfSense · OPNsense · Cisco · Juniper · and more

Selecting a match automatically fills in the **vendor**, **model**, **rack height**, and **device role**. You can edit any pre-filled value after selecting.

If your device isn't in the catalog, a **freeform option** is always available at the bottom of every search result — just continue filling in fields manually.

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

The **Category** and **Environment** fields on hardware nodes are smart typeaheads. Start typing to see your existing values, or type a new name and select **Create "…"** to add it on the spot without leaving the form.

Manage the full list — rename, recolor, delete — from **Settings → Categories** and **Settings → Environments**.

---

## Rack Position

Two fields let you record where a device lives in your rack:

- **Rack Height (U)** — how many rack units the device occupies
- **Rack Position (U)** — which rack unit it starts at (counting from the top)

Fill these in now to build out your rack layout data ahead of the upcoming visual rack simulator.

---

## Telemetry

Circuit Breaker can connect directly to your hardware's management interface and display live health data on the topology map.

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

Circuit Breaker polls the device automatically every **60 seconds** in the background. No further configuration is required.

### Credential Security

Management interface passwords are **encrypted at rest** using AES-256. Set the `CB_VAULT_KEY` environment variable before restarting to ensure credentials are encrypted and persist across container updates.

```yaml
# docker-compose.yml
services:
  backend:
    environment:
      - CB_VAULT_KEY=your-secret-key-here
```

> See [Getting Started](getting-started.md) for full environment variable setup.

---

## Connecting Hardware

Hardware serves as the physical host for [Compute](compute.md) instances. You can also link [Storage](storage.md) directly to a hardware node to record where that storage physically resides.

_Pro-tip: Use tags like `cluster:proxmox` to group related nodes for filtering on the topology map._
