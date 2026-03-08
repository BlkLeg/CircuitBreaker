# Circuit Breaker

![Circuit Breaker Logo](screenshots/cb_night-full.png)

**Circuit Breaker** is a self-hosted homelab visualization platform that maps your infrastructure—hardware, services, networks, clusters—with interactive topology, live telemetry, and auto-discovery. **Now PostgreSQL-powered for scalability!**

> **⚠️ Beta Security Notice**  
> Not fully audited. Run on trusted LAN only. Do not expose publicly until v1.0.

📖 **[User Guide](https://blkleg.github.io/CircuitBreaker)**

🗣️ **[Discord](https://discord.gg/SBdBRfmD)** | 🐦 **[X/Twitter](https://x.com/TryHostingCB)**

***

## 🚀 Standout Features (v0.2.0-beta)

- **Auto-Discovery Engine**: Scan LAN with nmap/SNMP/ARP. Auto-pop Proxmox VMs, TrueNAS pools, UniFi APs. Review & merge into topology!
- **Live Telemetry**: iDRAC/iLO/APC UPS/SNMP badges update via WebSockets. Health rings (green=healthy, red=critical).
- **Proxmox Integration**: One-click cluster import—nodes, VMs, health metrics visualized instantly!
- **Interactive Topology**: Hierarchical/cluster layouts. Drag/save positions. New mobile-responsive HUD!
- **3D Rack Simulator**: U-height drag-drop, cable mgmt, front/rear views, power modeling.
- **Vendor Catalog**: 100+ devices (Dell/HPE/Ubiquiti/Synology). Freeform always works.
- **Scan Dashboard**: Ad-hoc/recurring profiles. Bulk merge new hosts/services.
- **Rich Docs & Logs**: Markdown runbooks per entity. Audit trail for all changes.

![Proxmox Map]  
![Scan Page]  
![Mobile View]

### 🎨 Customizability

- Branding
- Logos
- Favicons
- Login background
- Map names

### 🔒 Security

- Built-in HTTPS
- OAuth/OIDC - GitHub, Google, generic OIDC providers
- MFA
- RBAC roles + scopes (viewer/editor/admin/demo)
- Fernet secured secrets management
- Audit logging for non-repudiation
- JWT 

### 🔌 Integrations

- Webhooks and notification routing for Slack, Discord, and custom endpoints

### ⚡ Speed

- Scans and maps Proxmox topology in under 60 seconds
- Scans subnet in under 2 minutes (depends on worker count)
- Loads quickly on low-resource devices like Pi and mini pcs

***

## Quick Start

### One-line Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

Open: <http://localhost:8080>

**Overrides**: `CB_PORT=9090 curl ... | bash`

**Uninstall**: `curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash`

### Docker Compose

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker/docker-compose.prebuilt.yml -o docker-compose.yml && docker compose up -d
```

Full `docker-compose.yml`:

```yaml
services:
  circuit-breaker:
    image: ghcr.io/blkleg/circuitbreaker:v0.2.0-beta  # Or :latest
    ports: ["127.0.0.1:8080:8080"]
    volumes: [circuit-breaker-data:/data]
    restart: unless-stopped
volumes:
  circuit-breaker-data:
```

Update: `docker compose pull && docker compose up -d`

***

## 🔄 v0.2.0 Migration Notes

**PostgreSQL Upgrade for Scale!**  
SQLite → PostgreSQL default (`DATABASE_URL=postgresql://...`). Handles 10k+ nodes effortlessly.  

**Breaking Changes (One-time)**:

- Backup `/data/app.db` (SQLite).  
- Set `DATABASE_URL` in env/compose. Init: auto-migrates schemas.  
- Data preserved via Alembic migrations. Test on staging first!  

Why? Explosive growth—Proxmox scans add 100s of VMs. PG scales infinitely.

***

## Build from Source

```bash
git clone https://github.com/BlkLeg/circuitbreaker.git && cd circuitbreaker
docker build -t circuit-breaker .
docker run -p 127.0.0.1:8080:8080 -v cb-data:/data circuit-breaker
```

***

## Documentation

- [Overview](docs/OVERVIEW.md)
- [Roadmap](docs/ROADMAP.md) – v0.3.0: VLANs, mobile polish.

## Community

Join [Discord](https://discord.gg/SBdBRfmD) for support/showcase. Follow [@TryHostingCB](https://x.com/TryHostingCB).

**Star on GitHub** ⭐ Questions? #support! 🖥️