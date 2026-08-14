# Proxmox LXC Installation

Install Circuit Breaker inside a new LXC container on your Proxmox VE host. The installer script runs on the **PVE host** and handles everything: creating the container and installing Circuit Breaker natively inside it.

---

## Prerequisites

- **Proxmox VE 7 or later** on the host
- Outbound internet access from the PVE host (to reach GitHub and the Debian template mirror)

---

## Run the Installer

Run this on your **Proxmox VE host** (not inside an existing container):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-deploy.sh)"
```

The script opens a whiptail menu (~3 minutes total for a default install):

| Menu entry | What it does |
|---|---|
| **Default Install** | Creates the container with the defaults below; prompts only for a root password and storage |
| **Advanced Settings** | Walks every setting — container type, CTID, hostname, disk/cores/RAM, network bridge and addressing, features, storage |
| **User Defaults** | Saves and reuses your own default answers |
| **Settings** | Installer options, including the install URL |
| **Uninstall Container** | Stops and destroys a container (`pct destroy --purge`) |
| **Update Circuit Breaker** | Re-runs the installer inside an existing container with `--unattended --upgrade` |
| **View Logs** | Tails the installer log |
| **Exit** | Quits |

---

## What Default Install Does

- Verifies it is running on a PVE host and checks internet connectivity
- Auto-selects the next available CTID (`pvesh get /cluster/nextid`)
- Prompts for a **root password** and for the **template and container storage**
- Downloads the Debian 12 template if it is not cached
- Creates and starts the container, then waits for a DHCP address
- Downloads the Circuit Breaker release bundle on the PVE host, pushes it into the container, and runs `install.sh --unattended` inside it
- Waits up to 120 seconds for the API health check, then patches the container's nginx so port 8088 serves HTTPS directly
- Prints a success banner with the container's URL

Nothing about the Proxmox API is configured during install — set that up afterwards, see [Creating a Proxmox API Token](#creating-a-proxmox-api-token).

---

## Container Specs

| Setting | Value |
|---|---|
| OS | Debian 12 |
| Container type | Unprivileged |
| Hostname | `cb` |
| CPU | 2 cores |
| RAM | 4 GB |
| Swap | 512 MB |
| Disk | 20 GB |
| Network | `vmbr0`, DHCP |
| Nesting | Enabled |
| Start on boot | Yes |

> **Note:** All of these can be changed from **Advanced Settings** in the menu. The disk size prompt is labelled "min 10", but the input is not validated against that floor — a smaller value is accepted, so set at least 10 GB yourself.

---

## Access Circuit Breaker

After the script completes, a success banner shows the container IP:

```
  URL : https://<container-ip>:8088
```

Open that URL in your browser to complete the [First-Run Setup](first-run.md) wizard.

---

## Creating a Proxmox API Token

The installer does not ask for Proxmox credentials. Create the token in the PVE UI after the install, then add it in Circuit Breaker under **Discovery → Proxmox VE**.

1. In the Proxmox web UI, go to **Datacenter → Permissions → API Tokens**
2. Click **Add**
3. Set:
   - **User:** `root@pam` (or a dedicated user)
   - **Token ID:** `circuitbreaker` (or any name you choose)
   - **Privilege Separation:** unchecked (required for full discovery)
4. Click **Add** — the token secret is shown **once**. Copy it immediately.

Enter the full token ID in the format `user@realm!tokenname`.

### Minimum required permissions

For full Proxmox discovery (VMs, nodes, storage), the token's user needs:

| Permission | Path |
|---|---|
| `VM.Audit` | `/vms` |
| `Sys.Audit` | `/nodes` |
| `Datastore.Audit` | `/storage` |

Since Privilege Separation is unchecked (step 3 above), the token inherits the **user's** permissions — grants made to the token itself are ignored. Assign these via **Datacenter → Permissions → Add → User Permission** (User = the user you created the token under, e.g. `root@pam`), not "API Token Permission" (that only applies when Privilege Separation is checked).

---

## After Install

1. Open `https://<container-ip>:8088` in your browser. Your browser will warn about the self-signed certificate — click **Advanced → Proceed** (Firefox) or **Advanced → Proceed anyway** (Chrome) to continue.
2. Complete the **[First-Run Setup](first-run.md)** wizard.
3. Back up your vault key — it is shown once at the end of the wizard.
4. To let Circuit Breaker discover your Proxmox nodes and VMs, add a Proxmox API token at **Discovery → Proxmox VE**.

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

**No DHCP address assigned** — Check that `vmbr0` is connected to a network with a DHCP server. To use a different bridge, pick it from **Advanced Settings → Network Bridge** instead of the default install.

**API did not respond within 120s** — Check logs inside the container:

```bash
pct exec <CTID> -- journalctl -u 'circuitbreaker-*' --no-pager -n 50
```

Or run the built-in health check inside the container:

```bash
pct exec <CTID> -- cb doctor
```

**Token rejected / HTTP 401** — Verify the token ID format (`user@realm!tokenid`) and that privilege separation is disabled. Re-configure at **Discovery → Proxmox VE**.

**`pct create` failed** — The most common cause is a CTID that is already taken or a storage pool that cannot hold the rootfs. The script prints the `pct` error and suggests `pvesm status` and `journalctl -u pvedaemon -n 20`. If Circuit Breaker is already running in a container, use **Update Circuit Breaker** from the menu, or `cb update` inside the container, instead of creating a new one.

**Removing the container** — See [Uninstalling](uninstalling.md#proxmox-lxc).
