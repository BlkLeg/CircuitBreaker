# Network Intelligence — Router-Level Visibility Design Spec

**Date:** 2026-03-25
**Status:** Approved for implementation planning

---

## Problem

Circuit Breaker is a network visualization app, but it lacks the observability that any managed network device provides by default:

- Topology links are drawn manually — there is no way to know what is physically connected to what without a human entering it.
- There is no per-link bandwidth visibility — you cannot tell if an uplink is saturated without logging into the device.
- IPAM is entirely manual — there is no way to know who actually holds each IP address without hand-entering every record.

Users running OPNsense/pfSense firewalls and Unifi/Cisco managed switches have all of this data available natively, but Circuit Breaker cannot access it.

---

## Goal

Add three capabilities that bring Circuit Breaker to feature parity with what you'd see on a managed switch or firewall dashboard:

1. **LLDP auto-topology** — auto-wire the topology map from LLDP neighbor data polled from managed switches
2. **Interface bandwidth monitoring** — per-interface in/out rates, surfaced as a hover tooltip on map links and a new Interfaces tab in the hardware detail drawer
3. **ARP/DHCP sync** — auto-populate IPAM from OPNsense/pfSense REST API; hardware linkages set automatically

---

## Non-Goals

- BGP/OSPF routing table visualization (not in scope for this release)
- Firewall rule visualization (not in scope)
- NetFlow/sFlow traffic capture (not in scope)
- Support for MikroTik, VyOS, or RouterOS (next iteration)
- Generic SNMP devices beyond managed switches (can be added later with same plugin pattern)

---

## Scope

**Target device types:**
- OPNsense / pfSense firewalls — via REST API (richer than SNMP for ARP/DHCP)
- Unifi / Cisco managed switches — via SNMP IF-MIB + LLDP-MIB table walks

---

## Architecture

Two new integration plugins feed a shared `NetworkInterface` model. Both run on schedule via the existing `integration_sync_worker`.

```
OPNsense/pfSense REST API  ─┐
                             ├─► OPNsensePlugin   ─┐
Unifi/Cisco SNMP             │                     ├─► network_interfaces (upsert)
  IF-MIB + LLDP-MIB    ─────┘   SNMPSwitchPlugin ─┤
                                                    ├─► hardware_connections (LLDP auto-wire)
                                                    ├─► ip_addresses (ARP/DHCP source)
                                                    └─► TelemetryTimeseries (counter history)
```

**Surfaces in the UI:**
- Topology map: hover any link → bandwidth tooltip (↑ Mbps / ↓ Mbps / utilization %); LLDP-discovered links show a small `LLDP` badge
- Hardware detail drawer: new **Interfaces** tab listing per-interface status, speed, live rates
- IPAM IP Addresses tab: `arp` / `dhcp` source badges; Discovered filter chip populated automatically

---

## Data Model

### New table: `network_interfaces`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| hardware_id | Integer FK→hardware | CASCADE delete |
| ifindex | Integer nullable | SNMP ifIndex; null for REST-sourced rows |
| name | String | e.g. "eth0", "ge-0/0/1", "Port 3" |
| mac_address | String nullable | Used for ARP correlation |
| speed_mbps | Integer nullable | ifSpeed ÷ 1,000,000 |
| mtu | Integer nullable | |
| admin_status | String nullable | "up" \| "down" \| "testing" |
| oper_status | String nullable | "up" \| "down" \| "dormant" |
| description | Text nullable | ifAlias or OPNsense description |
| last_in_bps | Float nullable | Computed from counter delta |
| last_out_bps | Float nullable | Computed from counter delta |
| last_in_errors | Integer nullable | Cumulative error counter |
| last_out_errors | Integer nullable | Cumulative error counter |
| last_polled_at | DateTime(tz) nullable | |

**Upsert key:** `(hardware_id, name)` — both plugins converge on the same row.

### Amended: `hardware_connections`

Four new nullable columns:

| Column | Type | Notes |
|--------|------|-------|
| source_interface_id | Integer FK→network_interfaces nullable | SET NULL on delete |
| target_interface_id | Integer FK→network_interfaces nullable | SET NULL on delete |
| lldp_discovered | Boolean default false | True for auto-wired LLDP links |
| last_lldp_seen_at | DateTime(tz) nullable | Updated each poll cycle |

LLDP links auto-expire: if `last_lldp_seen_at` exceeds 3× the integration's poll interval, the connection row is deleted. Manual connections (`lldp_discovered=false`) are never auto-expired.

### Amended: `ip_addresses`

One new column:

| Column | Type | Notes |
|--------|------|-------|
| source | String default "manual" | "manual" \| "arp" \| "dhcp" |

Used by the Discovered filter chip in the IPAM IP Addresses tab.

### Migration

`apps/backend/migrations/versions/0066_network_interfaces.py`
- `down_revision = "0065_multi_map"`
- Creates `network_interfaces` table
- Adds 4 columns to `hardware_connections`
- Adds `source` column to `ip_addresses`

---

## Integration Plugins

### OPNsensePlugin (`apps/backend/src/app/integrations/opnsense.py`)

```
TYPE = "opnsense"
DISPLAY_NAME = "OPNsense / pfSense"
CONFIG_FIELDS = [api_key, api_secret, base_url]
```

**`sync()` behaviour:**

1. `GET /api/diagnostics/interface/getifconfig` → upsert `network_interfaces` rows; write counter deltas to `TelemetryTimeseries`
2. `GET /api/diagnostics/interface/getarp` → for each ARP entry: find or create `IPAddress(address=ip, source="arp")`; set `hardware_id` by matching MAC against `network_interfaces.mac_address`
3. `GET /api/dhcpv4/leases/searchLease` → for each active lease: find or create `IPAddress`; set `source="dhcp"`, `hostname` from lease data
4. For existing `hardware_connections` where both endpoints are this hardware's interfaces: populate `source_interface_id` / `target_interface_id`

**Auth:** HTTP Basic with API key + secret (OPNsense standard). 5s timeout per request.

**`test_connection()`:** `GET /api/core/system/systemInformation` — returns (True, version) or (False, error).

---

### SNMPSwitchPlugin (`apps/backend/src/app/integrations/snmp_switch.py`)

```
TYPE = "snmp_switch"
DISPLAY_NAME = "Managed Switch (SNMP)"
CONFIG_FIELDS = [host, community, port=161, version="2c"]
```

**`sync()` behaviour:**

1. **IF-MIB table walk** (`1.3.6.1.2.1.2.2`) → upsert `network_interfaces` for each ifIndex; compute bps deltas from previous poll's octet counters (stored in integration config JSON); write to `TelemetryTimeseries`
2. **LLDP-MIB table walk** (`1.0.8802.1.1.2.1.4`) → for each neighbor entry:
   - Resolve `lldpRemSysName` to an existing `Hardware` row by name match
   - If match found: upsert `HardwareConnection(lldp_discovered=True, last_lldp_seen_at=now)`; populate `source_interface_id` / `target_interface_id`
   - If no match: log unresolved neighbor name for manual linkage
3. **LLDP expiry**: delete `HardwareConnection` rows where `lldp_discovered=True` and `last_lldp_seen_at < now - 3×interval`

**SNMP implementation:** Use `pysnmp` (add to `pyproject.toml`) for table walks rather than subprocess. Falls back gracefully if LLDP-MIB walk returns empty (device doesn't support LLDP).

**`test_connection()`:** SNMP GET on `sysDescr` (1.3.6.1.2.1.1.1.0).

---

## API

### New endpoint

`GET /api/v1/hardware/{hardware_id}/interfaces`

Returns list of `NetworkInterfaceRead`:
```json
[
  {
    "id": 1,
    "hardware_id": 42,
    "name": "eth0",
    "ifindex": 2,
    "mac_address": "00:1a:4b:c3:2f:01",
    "speed_mbps": 1000,
    "admin_status": "up",
    "oper_status": "up",
    "description": "WAN",
    "last_in_bps": 432000000.0,
    "last_out_bps": 39800000.0,
    "last_in_errors": 0,
    "last_out_errors": 0,
    "last_polled_at": "2026-03-25T18:00:42Z"
  }
]
```

### Amended graph endpoint

`GET /api/v1/graph` — hardware edges that are `HardwareConnection` rows now include:
```json
{
  "lldp_discovered": true,
  "last_in_bps": 432000000.0,
  "last_out_bps": 39800000.0,
  "source_interface_name": "eth1",
  "target_interface_name": "ge-0/0/0"
}
```
These fields are used by the topology map link tooltip.

---

## Frontend Changes

### New files

| File | Purpose |
|------|---------|
| `apps/frontend/src/components/details/InterfacesTab.jsx` | Per-interface table: status dot, name, MAC, speed, live ↑/↓ rates, "polled Xs ago" footer |
| `apps/frontend/src/api/interfaces.js` | `interfacesApi.list(hardwareId)` |

### Modified files

| File | Change |
|------|--------|
| `apps/frontend/src/components/details/HardwareDetail.jsx` | Add Interfaces tab (conditionally shown when `interfaces.length > 0`) |
| `apps/frontend/src/components/map/linkMutations.js` | Add `onEdgeMouseEnter` / `onEdgeMouseLeave` handler rendering bandwidth tooltip; render `LLDP` badge on `lldp_discovered` edges |
| `apps/frontend/src/pages/IPAMPage.jsx` | Add `arp` / `dhcp` source badges to IP rows; wire Discovered filter chip to `source !== "manual"` query |
| `apps/frontend/src/hooks/useMapDataLoad.js` | Pass through `lldp_discovered`, `last_in_bps`, `last_out_bps`, `source_interface_name`, `target_interface_name` on edge data |

---

## Existing Patterns to Reuse

| Pattern | File |
|---------|------|
| IntegrationPlugin base class | `apps/backend/src/app/integrations/base.py` |
| Integration sync worker (advisory lock, upsert monitors) | `apps/backend/src/app/workers/integration_sync_worker.py` |
| SNMPGenericClient (community string validation, timeout) | `apps/backend/src/app/integrations/proxmox_client.py` (similar pattern) |
| TelemetryTimeseries write pattern | `apps/backend/src/app/services/proxmox_telemetry.py` |
| HardwareConnection model | `apps/backend/src/app/db/models.py` |
| IPAddress upsert in IPAM | `apps/backend/src/app/api/ipam.py` |
| Hardware detail drawer tab pattern | `apps/frontend/src/components/details/HardwareDetail.jsx` |

---

## UI Behaviour Details

### Interfaces tab
- Shown on all hardware roles; tab is hidden if the integration hasn't polled yet (no `network_interfaces` rows for this hardware_id)
- Status dot: green pulse = oper_status "up"; red = "down"; grey = unknown
- Rates displayed as `Mbps` if ≥ 1 Mbps, `Kbps` otherwise
- Footer: `{n} interfaces · {up} up · {down} down · polled {Xs} ago`

### Link bandwidth tooltip
- Trigger: `onMouseEnter` on React Flow edge
- Content: `{source_interface_name} → {target_interface_name}`, `↑ {out_mbps} Mbps`, `↓ {in_mbps} Mbps · {utilization}%`
- Utilization = `max(last_in_bps, last_out_bps) / (speed_mbps × 1,000,000) × 100`; omitted if speed unknown
- `LLDP` badge: small pill rendered on the edge path midpoint when `lldp_discovered=true`
- Tooltip is suppressed if neither `last_in_bps` nor `last_out_bps` is populated

### IPAM Discovered filter
- Filter chips: All | Manual | Discovered
- Discovered = `source IN ("arp", "dhcp")`
- Source badge: `arp` (teal) / `dhcp` (amber) displayed inline on each row

---

## Verification

| Test | Expected |
|------|---------|
| OPNsense plugin `test_connection()` | Returns `(True, version_string)` for valid credentials |
| OPNsense ARP sync | `IPAddress.hardware_id` populated where MAC matches `network_interfaces.mac_address` |
| OPNsense DHCP sync | New `IPAddress` rows with `source="dhcp"` appear in IPAM Discovered filter |
| SNMP IF-MIB walk | `network_interfaces` rows created with correct speed/status; `last_in_bps` computed from two successive polls |
| SNMP LLDP walk | `HardwareConnection` created with `lldp_discovered=True`; appears as edge on topology map |
| LLDP expiry | Stop LLDP poll; connection row deleted after 3× interval |
| Interfaces tab | Visible on hardware detail drawer for device with polled interfaces; hidden for devices with none |
| Link tooltip | Hover LLDP-discovered edge; tooltip shows port names + Mbps; `LLDP` badge visible on edge |
| IPAM filter | Discovered filter shows only `source=arp/dhcp` rows; Manual shows only `source=manual` |
| Backward compat | Existing manual `HardwareConnection` rows unaffected; `lldp_discovered` defaults to false |
| Migration rollback | `downgrade()` cleanly removes all new columns and the `network_interfaces` table |
