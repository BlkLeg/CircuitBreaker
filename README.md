# Circuit Breaker

![Circuit Breaker](screenshots/cb_night-full.webp)

**Circuit Breaker** is a self-hosted homelab visualization platform that maps your infrastructure—hardware, services, networks, and clusters—with interactive topology, live telemetry, and auto-discovery.

> **⚠️ Beta Security Notice**
> Not fully audited. Run on trusted LAN only. Do not expose publicly until v1.0.

📖 **[User Guide](https://circuitbreaker.shawnji.com)** | 🗣️ **[Discord](https://discord.gg/SBdBRfmD)** | 🐦 **[X/Twitter](https://x.com/TryHostingCB)**

---

## Screenshots

![Topology Map](screenshots/01-concentric-rings.webp)

📸 [Full Screenshot Gallery](docs/screenshots.md)

---

## Features

- **Auto-Discovery**: Scan LAN with nmap/SNMP/ARP. Auto-populate Proxmox VMs, TrueNAS pools, UniFi APs. Review & merge into topology.
- **Live Telemetry**: iDRAC/iLO/APC UPS/SNMP health badges update via WebSockets. Green/yellow/red health rings.
- **Proxmox Integration**: One-click cluster import — nodes, VMs, and health metrics visualized instantly.
- **Interactive Topology**: Hierarchical/cluster/radial layouts with live animations. Drag-to-save positions.
- **3D Rack Simulator**: U-height drag-drop, cable management, front/rear views, power modeling.
- **Vendor Catalog**: 100+ devices (Dell/HPE/Ubiquiti/Synology/APC). Freeform entry always works.
- **Audit Logs**: Tamper-evident SHA-256 hash chain. Every change tracked with actor, IP, and diff.

---

## Security

- **Authentication**: bcrypt passwords, TOTP MFA, OAuth/OIDC (GitHub, Google, Authentik, Keycloak), HttpOnly session cookies
- **RBAC**: 4 built-in roles (viewer/editor/admin/demo), granular scopes, admin masquerade with full audit trail
- **Secrets Vault**: Fernet encryption at rest for all credentials; auto-generated key, never stored in plaintext
- **Transport**: Automatic HTTPS via Caddy — Let's Encrypt for public domains, local self-signed CA for LAN
- **HTTP Hardening**: CSP, HSTS, X-Frame-Options, rate limiting, SSRF guard, and tamper-evident audit log

> See [Security & Deployment](docs/deployment-security.md) for full details.

---

## Quick Start

### One-line Install (Recommended — Native)

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

Installs natively via systemd — no Docker required. Opens the OOBE setup wizard at `http://<host>:8088` on completion.

**Upgrade:** `cb update` | **Uninstall:** `cb uninstall`

---

### Proxmox LXC (Proxmox Hosts)

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-deploy.sh)"
```

Runs on your PVE host: creates a Debian 12 LXC container, installs Circuit Breaker natively, and auto-configures Proxmox API integration. Interactive TUI guides you through setup, done in ~3 minutes.

---

### Docker Compose

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash -s -- --docker
```

Full stack with Caddy, NATS, and discovery workers. See [docs/installation/docker-compose.md](docs/installation/docker-compose.md) for env vars, persistence, ARP scan, and socket config.

---

## cb CLI

`cb` is installed automatically alongside Circuit Breaker.

| Command | Description |
|---------|-------------|
| `cb status` | Show service status |
| `cb logs [-f]` | Show logs (add `-f` to follow) |
| `cb restart` | Restart Circuit Breaker |
| `cb update` | Pull latest release and restart |
| `cb vault-recover` | Recover an uninitialized vault (edge cases only) |
| `cb version` | Show installed version |
| `cb uninstall` | Remove Circuit Breaker from this system |

---

## Documentation

- [Overview](docs/overview.md)
- [Getting Started](docs/getting-started.md)
- [Installation](docs/installation/index.md)
- [Backup & Restore](docs/backup-restore.md)
- [Roadmap](docs/roadmap.md)

---

## Community

Join [Discord](https://discord.gg/SBdBRfmD) for support and showcases. Follow [@TryHostingCB](https://x.com/TryHostingCB) on X/Twitter.
