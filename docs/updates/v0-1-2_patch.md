# Circuit Breaker v0.1.2-beta — Release Notes

**Released:** March 2, 2026
**Previous version:** v0.1.0-beta

***

## What's New

v0.1.2 is the biggest update since the initial beta launch. It expands hardware support significantly, brings live device health into the topology map, and delivers a round of quality-of-life improvements that make the app faster and more reliable to use day-to-day.

***

## Know Your Hardware Instantly

### Device Catalog with Smart Search

Start typing a device name in the hardware form — `R740`, `USW Pro`, `Pi 5` — and Circuit Breaker now suggests matching devices from a built-in catalog covering Dell, HPE, Ubiquiti, MikroTik, Synology, TrueNAS, APC, CyberPower, Raspberry Pi, Proxmox, pfSense, OPNsense, Cisco, Juniper, and more. Selecting a match automatically fills in the vendor, model, rack height, and device role. Your custom devices are always welcome too — a freeform option is always available at the bottom of every search result.

### Rack Position Tracking

Hardware nodes now have **Rack Height (U)** and **Rack Position (U)** fields. Set them on any device to start building out your rack layout data ahead of the upcoming rack simulator.

### New Hardware Roles

Four new device roles join the existing set, giving your topology map more precision:

| Role | What it represents |
|---|---|
| UPS | Uninterruptible power supplies |
| PDU | Power distribution units |
| Access Point | Wireless access points |
| SBC | Single-board computers (Raspberry Pi, etc.) |

***

## Live Device Health on the Map

### Telemetry Integration

Connect Circuit Breaker directly to your hardware's management interface and see live health data on the topology map. Supported integrations:

- **Dell iDRAC** (6/7/8/9) — CPU temp, fan speeds, PSU status, system power draw
- **HPE iLO** (4/5/6) — CPU temp, fan speeds, PSU watts, overall health
- **APC & CyberPower UPS** — battery level, estimated runtime, load %, input/output voltage, temperature
- **Generic SNMP** — bring your own OIDs for any SNMP-capable device

Configure a device by opening its detail panel and expanding the new **Telemetry** section. Set the connection details, hit **Test Connection** to verify it works, and Circuit Breaker handles the rest — polling automatically every 60 seconds in the background.

### Status Rings on the Map

Once telemetry is configured, every hardware node on the topology map shows a live status ring:

- 🟢 **Pulsing green** — all systems healthy
- 🟡 **Amber** — something needs attention
- 🔴 **Glowing red** — critical condition
- No ring — telemetry not configured

Key metrics like CPU temperature and power draw appear as a small badge directly on the node so you can see what matters at a glance.

### Credential Security

Management interface passwords are encrypted at rest. Set the `CB_VAULT_KEY` environment variable to keep credentials secure and persistent across container restarts.

***

## More Icons

### New Vendor Icons

APC, CyberPower, Raspberry Pi, Forgejo, and Cloudflare Workers icons have been added to the vendor library.

### Expanded Icon Picker

Over **130 new icons** are available in the icon picker across six new groups:

| Group | Icons added |
|---|---|
| Hardware | 26 |
| Network | 73 |
| Security | 21 |
| Cameras | 6 |
| Power / UPS | 3 |
| Other | 3 |

***

## Categories & Environments

### Inline-Creatable Categories

The category field on services is now a smart typeahead. Start typing to see your existing categories, or type a new name and select **Create "media"** to add it on the spot — no trip to Settings required. All categories are still manageable from the **Settings → Categories** page where you can rename, recolor, and delete them.

### Inline-Creatable Environments

The same treatment applies to environments across services, hardware, and compute units. Type `staging` and it's created immediately if it doesn't exist yet. Manage the full list from **Settings → Environments**. Existing environment values you've already entered are automatically migrated into the new system on first launch.

***

## IP & Port Conflict Detection

Assigning an IP address or port that's already in use now triggers an immediate warning. If you try to save a service or device with a conflicting address, Circuit Breaker tells you exactly what already has it — and gives you a direct link to open that entity. Conflicts are caught as you type, before you even hit Save.

***

## Real Timestamps & Timezone Support

### Accurate Log Times

Every action in the audit log now shows a real timestamp. Entries under an hour old display as relative time (`"4 minutes ago"`), while older entries show the full date and time. Hover any timestamp to see the exact moment it occurred.

### Your Timezone, Your Time

Circuit Breaker now asks for your timezone during first-time setup. All timestamps across the app — logs, telemetry readings, entity records — display in your local time. Change your timezone anytime from **Settings → General**.

***

## Audit Log

The logs panel has been rebuilt into a proper audit trail. Every meaningful action — creating a device, changing a service, saving the topology layout, a failed login attempt — now produces a structured log entry showing what changed, who did it, and where the request came from. Entries include a collapsible before/after view so you can see exactly what was modified. Filter by entity type, action, or severity, and search by name.

Log entries are permanent and append-only. Nothing in the audit trail can be edited or deleted.

***

## Bug Fixes

- Fixed an issue where selecting a custom icon for a network node would not persist after refreshing the topology map
- Fixed the icon picker appearing behind the right-click context menu on the topology map
- Fixed the context menu closing too early when selecting an icon, causing the icon change to silently fail
- Fixed custom icons not saving when creating a new network node
- Fixed the icon picker not highlighting the currently assigned icon when reopened

***

## Upgrading

No action required beyond pulling the latest image. All database changes apply automatically on startup and are fully backwards-compatible — your existing data is untouched.

```bash
# Prebuilt image
docker compose pull && docker compose up -d
```

If you plan to use telemetry integrations, set `CB_VAULT_KEY` in your environment before restarting to ensure credentials are encrypted and persist across future updates.
