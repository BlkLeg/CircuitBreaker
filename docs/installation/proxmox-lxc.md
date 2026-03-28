# Proxmox LXC Installation

Install Circuit Breaker inside a new LXC container on your Proxmox VE host. The installer script runs on the **PVE host** and handles everything: creating the container, installing Circuit Breaker natively inside it, and optionally configuring the Proxmox API integration.

---

## Prerequisites

- **Proxmox VE 7 or later** on the host
- Outbound internet access from the PVE host (to reach GitHub and the Debian template mirror)
- A Proxmox API token if you want auto-discovery configured during install (see [Creating an API Token](#creating-a-proxmox-api-token) below)

---

## Run the Installer

Run this on your **Proxmox VE host** (not inside an existing container):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-deploy.sh)"
```

The script walks through an interactive TUI setup (~3 minutes total).

---

## What the Script Does

**Phase 1 — Preflight**

- Verifies it's running on a PVE host
- Checks internet connectivity
- Auto-selects the next available CTID (`pvesh get /cluster/nextid`)
- Auto-detects storage pool (prefers `local-lvm`, falls back to `local`)
- Prompts: **Hostname?** (default: `circuitbreaker`)

**Phase 2 — API Token (optional)**

- Prompts: **Configure Proxmox auto-discovery? [Y/n]**
  - If yes: **API Token ID?** (default: `circuitbreaker@pam!circuitbreaker`) and **API Token Secret** (hidden input)
  - If no: skips API configuration entirely

**Phase 3 — Create LXC**

- Downloads the latest Debian 12 template (or uses cached)
- Creates a container with: 2 cores, 4 GB RAM, 512 MB swap, 10 GB disk, bridge `vmbr0`, nesting enabled, onboot enabled
- Starts the container and waits for a DHCP address

**Phase 4 — Install Circuit Breaker**

- Runs the standard Circuit Breaker installer inside the container natively (no Docker)

**Phase 5 — Configure Integration**

- Waits for the Circuit Breaker API to become ready (up to 120 seconds)
- If API credentials were provided, registers the Proxmox integration automatically

---

## Container Specs

| Setting | Value |
|---|---|
| OS | Debian 12 |
| CPU | 2 cores |
| RAM | 4 GB |
| Swap | 512 MB |
| Disk | 10 GB |
| Network | `vmbr0`, DHCP |
| Nesting | Enabled |
| Start on boot | Yes |

> **Note:** The container runs in privileged mode with nesting enabled. This is required for the Circuit Breaker systemd service to function correctly inside the LXC.

---

## Access Circuit Breaker

After the script completes, a success banner shows the container IP:

```
  URL : https://<container-ip>:8088
```

Open that URL in your browser to complete the [First-Run Setup](first-run.md) wizard.

---

## Creating a Proxmox API Token

Create the token in the PVE UI **before** running the installer so you can enter the secret when prompted.

1. In the Proxmox web UI, go to **Datacenter → Permissions → API Tokens**
2. Click **Add**
3. Set:
   - **User:** `root@pam` (or a dedicated user)
   - **Token ID:** `circuitbreaker` (or any name you choose)
   - **Privilege Separation:** unchecked (required for full discovery)
4. Click **Add** — the token secret is shown **once**. Copy it immediately.

The default token ID the installer expects is `circuitbreaker@pam!circuitbreaker`. If you use a different user or token name, enter the full ID when prompted (format: `user@realm!tokenname`).

### Minimum required permissions

For full Proxmox discovery (VMs, nodes, storage), the token's user needs:

| Permission | Path |
|---|---|
| `VM.Audit` | `/vms` |
| `Sys.Audit` | `/nodes` |
| `Datastore.Audit` | `/storage` |

You can assign these via **Datacenter → Permissions → Add → API Token Permission**.

---

## After Install

1. Open `https://<container-ip>:8088` in your browser. Your browser will warn about the self-signed certificate — click **Advanced → Proceed** (Firefox) or **Advanced → Proceed anyway** (Chrome) to continue.
2. Complete the **[First-Run Setup](first-run.md)** wizard.
3. Back up your vault key — it is shown once at the end of the wizard.

If you skipped API configuration during install, you can set it up later at **Settings → Integrations → Proxmox**.

---

## Upgrading

SSH into the container and run:

```bash
cb update
```

Or from the PVE host:

```bash
pct exec <CTID> -- cb update
```

---

## Troubleshooting

**No DHCP address assigned** — Check that `vmbr0` is connected to a network with a DHCP server. Adjust `CT_BRIDGE` in the script if using a different bridge.

**API did not respond within 120s** — Check logs inside the container:

```bash
pct exec <CTID> -- journalctl -u circuitbreaker -n 50
```

**Token rejected / HTTP 401** — Verify the token ID format (`user@realm!tokenid`) and that privilege separation is disabled. Re-configure at **Settings → Integrations → Proxmox**.

**Container already exists with same hostname** — The script detects this and exits early. If Circuit Breaker is already running, use `cb update` inside the container to upgrade.
