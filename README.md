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

After starting the compose stack, install the `cb` CLI tool so you have access to operational commands:

```bash
make install-cb
```

***

## cb — Command-Line Tool

`cb` is a small shell utility installed alongside Circuit Breaker. It gives you operational commands without needing to remember Docker flags.

| Command | Description |
|---------|-------------|
| `cb status` | Show container / service status |
| `cb logs [-f]` | Show logs (add `-f` to follow) |
| `cb restart` | Restart Circuit Breaker |
| `cb update` | Pull latest image and recreate the container *(Docker mode)* |
| `cb vault-recover` | Recover an uninitialized vault *(recovery path — not needed during normal setup)* |
| `cb version` | Show installed version |
| `cb uninstall` | Remove Circuit Breaker from this system |

**How `cb` is installed:**

- **`install.sh` (one-line install)** — installed automatically.
- **Docker Compose (from source)** — run `make install-cb` after `docker compose up`.
- **Manual** — `sudo install -Dm755 ./cb /usr/local/bin/cb` from the repo root.

> **Vault key**: no manual setup needed. The vault key is generated automatically when you complete the first-run setup wizard. `cb vault-recover` only exists for edge cases where the vault ends up uninitialized after a crash or a headless deploy.

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

## Docker Compose — Production Stack

The full stack (`docker/docker-compose.yml`) includes:

| Service | Role |
|---------|------|
| `caddy` | Reverse proxy — automatic HTTPS via local self-signed cert (`.local`) or ACME (public domain) |
| `backend` | FastAPI app + Alembic migrations |
| `frontend` | nginx serving the built React app |
| `worker` | Discovery worker (2 replicas) |
| `webhook-worker` | Webhook dispatch worker |
| `notification-worker` | Alert / notification worker |
| `nats` | Message bus (JetStream) |
| `postgres` _(optional)_ | PostgreSQL — only starts with `--profile pg` |

### Quick start

```bash
# Clone and start (builds from source):
git clone https://github.com/BlkLeg/circuitbreaker.git && cd circuitbreaker
docker compose -f docker/docker-compose.yml up -d
```

Access at `https://circuitbreaker.local` (default domain). See **Caddy HTTPS** below if your browser shows a certificate warning.

### Environment variables

Copy `docker/.env.example` to `docker/.env` and set as needed:

| Variable | Default | Notes |
|----------|---------|-------|
| `CB_DOMAIN` | `circuitbreaker.local` | Domain Caddy listens on. Use a public FQDN for automatic ACME certs. |
| `CB_TLS_EMAIL` | _(empty)_ | Required for Let's Encrypt on public domains. |
| `CB_LOCAL_CERTS` | `local_certs` | Set to empty string to use ACME on a public domain. |
| `CB_DB_URL` | SQLite | Override to `postgresql://breaker:pass@postgres:5432/circuitbreaker` to use the optional PG service. |
| `CB_VAULT_KEY` | _(auto)_ | Fernet key for secret encryption. Auto-generated during OOBE; persisted to `/data/.env` in the volume. |
| `CB_DB_PASSWORD` | `breaker` | PostgreSQL password (only used with `--profile pg`). |

### Caddy HTTPS — CA Certificate

Caddy issues a self-signed CA for `.local` / LAN domains.
Browsers won't trust it until you install the CA certificate.

**Download the cert** (available over HTTP before redirecting):

```
http://circuitbreaker.local/caddy-root-ca.crt
```

Or click the **Download CA Certificate** button shown in the first-run OOBE wizard.

**Install instructions:**

| OS | Steps |
|----|-------|
| **macOS** | Double-click `caddy-root-ca.crt` → Keychain Access → select *Always Trust* |
| **Windows** | Double-click → *Install Certificate* → *Local Machine* → *Trusted Root Certification Authorities* |
| **Linux (Debian/Ubuntu)** | `sudo cp caddy-root-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |
| **Firefox** | Settings → Privacy & Security → Certificates → *Import* |
| **Chrome/Edge** | Uses the OS trust store (macOS/Windows). On Linux: Settings → Security → *Manage Certificates* |

For a **public domain**, set `CB_DOMAIN=myserver.example.com` and `CB_TLS_EMAIL=admin@example.com`. Caddy will provision a trusted Let's Encrypt certificate automatically — no manual cert installation needed.

### ARP Scan / Full Discovery

By default, discovery uses nmap TCP/ICMP and works without elevated privileges. To enable ARP scanning (faster, more reliable on LAN):

> **Native Linux Docker only — not supported on Docker Desktop (macOS / Docker Desktop for Linux).**
> `network_mode: host` is required so the container can reach your LAN directly. Docker Desktop runs containers inside a VM, so host mode accesses the VM's network, not your LAN, and breaks the nginx → backend proxy.

1. In `docker/docker-compose.yml`, uncomment under the `backend` service:
   ```yaml
   cap_add:
     - NET_RAW
     - NET_ADMIN
   network_mode: "host"
   ```
2. Uncomment under the `frontend` service:
   ```yaml
   extra_hosts:
     - "backend:host-gateway"
   ```
3. Restart: `docker compose -f docker/docker-compose.yml up -d`

**Security note:** `NET_RAW` + `NET_ADMIN` allow the container to craft and send arbitrary raw packets. Only enable this on trusted, isolated homelab networks.

When `network_mode: host` is active, IPv6 sysctls cannot be set per-container (they share the host namespace). To disable IPv6 on the host instead:
```bash
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
```

---

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