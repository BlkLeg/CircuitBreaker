# Telemetry

Circuit Breaker can poll live health data from supported hardware — servers, UPS units, and SNMP devices — and display the results as color-coded health rings on the topology map.

---

## Overview

When telemetry is configured on a hardware node, Circuit Breaker polls it on that node's own poll interval (**60 seconds** by default) and updates the node's health ring on the topology map:

| Ring color | Meaning |
|---|---|
| Green (pulse) | All metrics healthy |
| Yellow | Warning threshold exceeded (e.g., high temperature, low battery) |
| Red | Critical condition or unreachable |
| Grey (no ring) | Telemetry not configured |

---

## Supported Integrations

| Integration | Metrics | Protocol |
|---|---|---|
| **Dell iDRAC** 6 / 7 / 8 / 9 | CPU temp, fan speeds, PSU status, system power draw | SNMP |
| **HPE iLO** 4 / 5 / 6 | CPU temp, fan speeds, PSU watts, overall health | Redfish (HTTP) |
| **APC / CyberPower UPS** | Battery %, estimated runtime, load %, input/output voltage, temperature | SNMP |
| **Generic SNMP** | Arbitrary OIDs supplied per device | SNMP |
| **IPMI / Generic** | Same client as Generic SNMP; fallback for IPMI-style boards (Supermicro, MikroTik) | SNMP |
| **Network Device (SNMP)** | Uptime, CPU, memory, per-interface traffic | SNMP |

---

## Configuring Telemetry

1. Open the **Hardware** page and select a device.
2. In the detail panel, expand the **Telemetry** section.
3. Select the **Integration type** from the dropdown.
4. Enter the connection details for that integration (see below).
5. Click **Test Connection** to verify the credentials before saving.

After saving, Circuit Breaker begins polling on that device's next due cycle. The collector wakes every `CB_TELEMETRY_POLL_SECONDS` (default 30, minimum 10) and polls whichever devices are due.

---

## Per-Integration Setup

### Dell iDRAC (6 / 7 / 8 / 9)

Protocol: SNMP v2c — polls always use `-v2c`.

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the iDRAC interface |
| **SNMP Community** | Community string (default: `public`) |
| **Poll Interval (s)** | How often this device is polled (default: 60, minimum 10) |

Make sure SNMP is enabled in the iDRAC web UI under **iDRAC Settings → Network → Services → SNMP**.

---

### HPE iLO (4 / 5 / 6)

Protocol: Redfish (HTTPS)

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the iLO interface |
| **Username** | iLO user with read access |
| **Password** | iLO user password |

Redfish is enabled by default on iLO 4 and later. iLO TLS certificates are verified against the system CA store, so a self-signed iLO certificate must be added to that trust store or polling fails with a connection error.

---

### APC / CyberPower UPS

Protocol: SNMP v2c

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the UPS network card / management interface |
| **SNMP Community** | Community string (default: `public`) |
| **Integration type** | Select `apc_ups` or `cyberpower_ups` to match your device |

For APC units, SNMP is typically enabled via the **Network Management Card** (NMC) web interface.

---

### Generic SNMP / IPMI

For any SNMP-capable device not covered by the specific integrations above. **IPMI / Generic** uses the same client and the same fields.

| Field | Description |
|---|---|
| **Host** | IP address or hostname |
| **SNMP Community** | Community string |
| **Poll Interval (s)** | How often this device is polled (default: 60, minimum 10) |

These two profiles poll only the OIDs supplied in the device's `custom_oids` config. The Telemetry
panel has no field for them today, so a device saved from the UI with one of these profiles reports
status `unknown` until OIDs are set on its telemetry config directly.

---

### Network Device (SNMP)

For switches, routers, firewalls, and access points. This profile is pre-selected automatically when
the hardware node's role is `switch`, `router`, `firewall`, or `access_point`. It collects system
uptime, CPU and memory usage, and per-interface traffic counters.

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the device's management interface |
| **SNMP Community** | Community string |
| **Poll Interval (s)** | How often this device is polled (default: 60, minimum 10) |

---

## Credential Security

Telemetry passwords and SNMP community strings are encrypted using a **Fernet vault** before being stored in the database.

In production, set `CB_VAULT_KEY` in your environment to ensure credentials are persistently encrypted:

```bash
# Generate a vault key
openssl rand -base64 32
```

If `CB_VAULT_KEY` is not set, Circuit Breaker auto-generates a key during the OOBE wizard and stores it locally. That key must be preserved to decrypt stored credentials after a reinstall or migration.

→ See [Deployment & Security](deployment-security.md) for vault key management guidance.

---

## Topology Map Indicators

The topology map shows health rings on hardware nodes where telemetry is configured. Hover over a node to see the last-polled metrics in the detail tooltip.

The last successful poll time is shown in the hardware detail panel under **Telemetry → Last Polled**.

---

## Troubleshooting

**Test Connection fails with "Connection refused" or timeout**
- Confirm the host IP is correct and reachable from the Circuit Breaker server.
- For SNMP: verify SNMP is enabled on the device and the community string matches.
- For iLO: verify Redfish is enabled in iLO settings.

**SNMP returns no data**
- Check that the community string has read access to the required OIDs.
- Try `snmpwalk -v2c -c <community> <host> .1.3.6.1` to test from the command line.

**Ring stays grey after configuring**
- Wait one full poll cycle for that device (its **Poll Interval (s)** value, 60 seconds by default) after saving.
- Check `cb logs -f` for polling errors.

**Credentials lost after reinstall**
- Vault key mismatch. Restore your vault key backup and restart, or re-enter credentials manually.
  See [Backup & Restore](backup-restore.md).
