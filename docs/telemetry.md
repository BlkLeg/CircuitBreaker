# Telemetry

Circuit Breaker can poll live health data from supported hardware — servers, UPS units, and SNMP devices — and display the results as color-coded health rings on the topology map.

---

## Overview

When telemetry is configured on a hardware node, Circuit Breaker polls it every **60 seconds** and updates the node's health ring on the topology map:

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
| **Generic SNMP** | Any SNMP-capable device using custom OIDs | SNMP |

---

## Configuring Telemetry

1. Open the **Hardware** page and select a device.
2. In the detail panel, expand the **Telemetry** section.
3. Select the **Integration type** from the dropdown.
4. Enter the connection details for that integration (see below).
5. Click **Test Connection** to verify the credentials before saving.

After saving, Circuit Breaker begins polling on the next 60-second cycle.

---

## Per-Integration Setup

### Dell iDRAC (6 / 7 / 8 / 9)

Protocol: SNMP v1/v2c

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the iDRAC interface |
| **SNMP Community** | Community string (default: `public`) |
| **SNMP Version** | v1 or v2c |

Make sure SNMP is enabled in the iDRAC web UI under **iDRAC Settings → Network → Services → SNMP**.

---

### HPE iLO (4 / 5 / 6)

Protocol: Redfish (HTTPS)

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the iLO interface |
| **Username** | iLO user with read access |
| **Password** | iLO user password |

Redfish is enabled by default on iLO 4 and later. If using a self-signed iLO certificate, Circuit Breaker skips certificate verification automatically.

---

### APC / CyberPower UPS

Protocol: SNMP v1/v2c

| Field | Description |
|---|---|
| **Host** | IP address or hostname of the UPS network card / management interface |
| **SNMP Community** | Community string (default: `public`) |
| **Integration type** | Select `apc_ups` or `cyberpower_ups` to match your device |

For APC units, SNMP is typically enabled via the **Network Management Card** (NMC) web interface.

---

### Generic SNMP

For any SNMP-capable device not covered by the specific integrations above.

| Field | Description |
|---|---|
| **Host** | IP address or hostname |
| **SNMP Community** | Community string |
| **OIDs** | Comma-separated list of OIDs to poll |

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

Poll interval: 60 seconds. The last successful poll time is shown in the hardware detail panel under **Telemetry → Last Polled**.

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
- Wait one full poll cycle (up to 60 seconds) after saving.
- Check `cb logs -f` for polling errors.

**Credentials lost after reinstall**
- Vault key mismatch. Restore your vault key backup and restart, or re-enter credentials manually.
  See [Backup & Restore](backup-restore.md).
