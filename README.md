# Circuit Breaker


![Circuit Breaker Logo](screenshots/cb_night-full.webp)

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

![Mobile View](screenshots/new_mobile_layout.jpg)

![Mobile View 2](screenshots/02-mobile.jpg)

### 🎨 Customizability

- Branding
- Logos
- Favicons
- Login background
- Map names

### 🔒 Security

Circuit Breaker is built security-first, with defense-in-depth applied across authentication, transport, secrets, and infrastructure layers.

#### Authentication & Identity

- **Local auth** — bcrypt-hashed passwords; salted HMAC-SHA256 API tokens stored only as hashes and shown exactly once
- **OAuth/OIDC** — GitHub, Google, and any generic OIDC provider (Authentik, Keycloak, etc.) with PKCE-compatible flows and time-limited state tokens
- **TOTP MFA** — per-user TOTP two-factor (RFC 6238) with a dedicated rate-limited verify endpoint
- **HttpOnly session cookies** — `SameSite=Strict; Secure; HttpOnly` so the session token is never readable by JavaScript
- **CSRF double-submit** — every mutating request (POST/PUT/DELETE/PATCH) requires a matching `X-CSRF-Token` header validated with `hmac.compare_digest`
- **Account lockout** — configurable failed-attempt threshold (default: 5 attempts → 15-minute lockout); admin unlock endpoint
- **Configurable session timeouts** — idle-session expiry set per deployment

#### Role-Based Access Control

- **4 built-in roles**: `viewer` (read-only), `editor` (write infrastructure), `admin` (full control), `demo` (read-only, auto-expiring)
- **Granular scopes**: `read:*`, `write:hardware`, `write:networks`, `delete:*`, `admin:*` and resource-specific variants
- **Role hierarchy** enforced server-side on every protected route; explicit per-user scope overrides for fine-grained delegation
- **Admin masquerade** — admins can issue 15-minute impersonation tokens for support workflows; fully audit-logged and globally disableable

#### Secrets Vault

- **Fernet encryption at rest** — SMTP credentials, Proxmox API tokens, SNMP community strings, and iDRAC/iLO credentials never touch the database in plaintext
- **Auto-generated key** during first-run OOBE; persisted to `/data/.env`; SHA-256 key hash stored in DB for verification without exposing the key
- **Key rotation** support; `cb vault-recover` CLI for edge-case recovery
- **Lazy vault initialization** — no silent ephemeral key generation; startup fails loudly if the key is missing

#### Transport Security

- **Automatic HTTPS** via Caddy — Let's Encrypt for public domains; local self-signed CA for LAN/`.local` deployments; one-click CA cert download from OOBE wizard
- **Native TLS modes** — `local` (generated CA + cert) or `provided` (bring-your-own cert) for native Linux installs
- **HSTS** (`max-age=63072000; includeSubDomains`) on all HTTPS responses
- **WSS enforcement** — production WebSocket auth flows over cookie (`cb_session`); `CB_WS_REQUIRE_WSS=true` rejects any plain `ws://` connection

#### HTTP Hardening

- `Content-Security-Policy` — strict directive set with `frame-ancestors 'none'`
- `X-Frame-Options: DENY` — clickjacking prevention
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` — camera, microphone, geolocation, payment, USB, and sensor APIs all disabled
- Applied by `SecurityHeadersMiddleware` on every HTTP response

#### Rate Limiting

- Per-IP rate limiting (slowapi) on auth, MFA verify, scans, telemetry, and general endpoints
- Three configurable profiles — **relaxed**, **normal** (default), **strict** — switchable live from Settings
- Profile cache with 5-minute TTL so changes propagate without restart

#### Tamper-Evident Audit Log

- Every significant action (login, settings change, certificate create, masquerade, CVE sync, etc.) is written as a structured log entry with IP, User-Agent, actor, role, and diff
- **SHA-256 hash chain** — each entry includes `log_hash = SHA256(payload)` and `previous_hash`; the chain can be verified end-to-end via `/admin/audit-log/verify-chain`
- **IP redaction** toggle — strip IP addresses from audit entries for privacy-conscious deployments
- Non-repudiation: who did what, from where, and when — queryable at `/logs?category=audit`

#### SSRF & Injection Prevention

- **SSRF guard** — webhook URLs and integration endpoints are resolved and checked against loopback, link-local, and (for webhooks) RFC 1918 ranges before any outbound request
- **Network ACL** — configurable per-deployment CIDR allowlist for scan targets; `CB_AIRGAP` / `airgap_mode` setting disables all outbound scanning entirely
- **File upload magic-byte validation** — MIME type is verified against actual file bytes (PNG, JPEG, GIF, WebP, ICO), not the declared `Content-Type`
- **SQL identifier hardening** — dynamic SQL identifiers (e.g. audit partition names) are regex-validated before use; ORM-parameterized queries everywhere else
- **Log redaction** — global log filter strips Bearer tokens, passwords, secrets, API keys, and URL-embedded credentials before they reach any log sink

#### Infrastructure Security

- **Docker network segmentation** — `cb_frontend`, `cb_backend`, and `cb_workers` are distinct networks; workers can only reach the NATS bus and Postgres, never the backend API or frontend
- **Optional NATS auth** — token or username/password auth plus TLS for the internal message bus
- **CVE tracking** — built-in NVD CVE feed sync with entity-level CVE association and a security findings dashboard
- **TLS certificate management** — track, create, renew, and audit-log TLS certificates from the admin UI
- **Security CI pipeline** — every push runs Bandit, Semgrep, Gitleaks, ESLint (security plugin), Hadolint, Checkov, Trivy (filesystem + image), and `npm audit`

> See [Deployment & Security](docs/deployment-security.md) for hardening checklists, NATS TLS configuration, WebSocket WSS setup, and network segmentation details.

### 🔌 Integrations

- Webhooks and notification routing for Slack, Discord, and custom endpoints

### ⚡ Speed

- Scans and maps Proxmox topology in under 60 seconds
- Scans subnet in under 2 minutes (depends on worker count)
- Loads quickly on low-resource devices like Pi and mini pcs

### Efficient

- Runs in under 500mb of RAM - Pi Ready!

***

### Multiple Topologies (w/ live animations)

![Concentric Rings](screenshots/01-concentric-rings.webp)

![Radial w/ Smooth connections](screenshots/01-heart-diagram.webp)

![Radial Bundled](screenshots/radial-bundled.webp)

![Subnet Separation](screenshots/01-subnet.webp)

### Floating HUD w/ live Telemtry

![Maintenance Status](screenshots/01-hud-maintenance.webp)

![HUD w/ Telemetry](screenshots/01-hud-2.webp)

### Non-Repudiation Audit Logs

![Audit Log](screenshots/01-secure-logging.webp)

## Quick Start

### One-line Install (Recommended)

The install script requires **curl or wget** on the host (e.g. Ubuntu: `sudo apt-get install -y curl` or `wget`).

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
```

The script downloads `docker-compose.yml`, generates `.env` with secrets if missing, and starts the stack. Full capability—discovery, webhooks, HTTPS—in under 60 seconds. No build required.

Open: **http://localhost** or **https://localhost** (or your host IP). On first run, the setup wizard creates your admin account.

**Overrides**: `CB_PORT=9090` or `CB_VERSION=v0.2.0` (pin image tag)

**Tagged deploy**: `CB_TAG=v1.2.0 curl ... | bash` (pin to a specific release)

**Upgrade**: `cb update` or `docker compose --project-directory ~/.circuitbreaker pull && docker compose --project-directory ~/.circuitbreaker up -d`

**Uninstall**: `cb uninstall` or `curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash`

### Native Packages

> **In testing:** Native (PyInstaller) builds are still in testing. Prefer Docker or the one-line install for production use.

Native release archives are standardized across supported platforms:

- Linux `amd64`: `circuit-breaker_<version>_linux_amd64.tar.gz`
- Linux `arm64`: `circuit-breaker_<version>_linux_arm64.tar.gz`
- macOS `arm64`: `circuit-breaker_<version>_macos_arm64.tar.gz`
- Windows `amd64`: `circuit-breaker_<version>_windows_amd64.zip`

The Linux native installer (`install.sh --mode binary`) consumes the same packaged archive format that GitHub Releases publishes, so branch/local packaging and release packaging now use the same artifact contract.

For native Linux installs, the installer supports two HTTPS modes:

- `local`: generate and optionally trust a local CA + server certificate
- `provided`: copy an existing certificate and key into the managed cert directory

macOS and Windows native archives are built in CI, but their install path is currently manual rather than `install.sh`.

### Docker Compose (single deployment file)

**Single source of truth:** [`docker-compose.yml`](docker-compose.yml) at repo root. The [one-line install](#one-line-install-recommended) downloads this file and runs the **mono** image (PostgreSQL, NATS, Redis, backend, workers, nginx in one container).

```bash
make setup-buildx
make docker-publish-prod TAG=v0.2.0-2-beta
```

Manual run from repo (same file the installer uses):

```bash
# Recommended: use the installer (it downloads docker-compose.prod.yml for you)
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
# Choose option 2 (Compose stack)
```

Manual run from repo (same file the installer uses):

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker-compose.yml -o docker-compose.yml
# cp .env.example .env and set CB_DB_PASSWORD, CB_VAULT_KEY, CB_JWT_SECRET, NATS_AUTH_TOKEN; then:
docker compose up -d
```

Single-container image only (minimal—no discovery workers):

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/docker-compose.yml -o docker-compose.yml && cp .env.example .env && docker compose up -d
```

### Mono Image (Single Container, Postgres + NATS + Workers)

For a self-contained, single-container deployment that bundles PostgreSQL, NATS JetStream, the backend API, workers, and the frontend behind nginx, use the **mono** image:

```bash
curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | \
  CB_TAG=v0.2.0 CB_DB_PASSWORD='strongpass123' \
  CB_VAULT_KEY="$(openssl rand -base64 32)" bash
```

This starts:

- `ghcr.io/blkleg/circuitbreaker:mono-v0.2.0`
- Ports: `80` (HTTP) and optionally `443` (HTTPS, when `CB_ENABLE_TLS=1` and certs are mounted)
- Volume: `./circuitbreaker-data:/data`

To run manually:

```bash
docker run -d --name circuitbreaker \
  -p 8080:80 \
  -v "$(pwd)/circuitbreaker-data:/data" \
  -e CB_DB_PASSWORD=strongpass123 \
  -e CB_VAULT_KEY="$(openssl rand -base64 32)" \
  ghcr.io/blkleg/circuitbreaker:mono-v0.2.0
```

TLS is terminated inside the container by nginx. Mount your certificates into `/data/tls`:

```bash
mkdir -p circuitbreaker-data/tls
cp fullchain.pem circuitbreaker-data/tls/fullchain.pem
cp privkey.pem circuitbreaker-data/tls/privkey.pem

CB_ENABLE_TLS=1 CB_DB_PASSWORD=... CB_VAULT_KEY=... \
docker run -d --name circuitbreaker \
  -p 80:80 -p 443:443 \
  -v "$(pwd)/circuitbreaker-data:/data" \
  ghcr.io/blkleg/circuitbreaker:mono-v0.2.0
```

For advanced ARP discovery on native Linux Docker, you can add:

```bash
--cap-add NET_RAW --cap-add NET_ADMIN --network host
```

to the `docker run` command (trusted homelab networks only). See [docs/discovery.md](docs/discovery.md#arp-scanning-and-docker-desktop) for details.

**Build from source** (for development): see [docs/installation/docker-compose-source.md](docs/installation/docker-compose-source.md)

Single-container `docker-compose.yml`:

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

For **production (prebuilt images)**, use **[`docker-compose.yml`](docker-compose.yml)** — the same file the [one-line install](#one-line-install-recommended) uses. The full stack includes:

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

**Prebuilt (recommended):** use the [installer](#one-line-install-recommended) or run `docker-compose.yml` (repo root) as in the Quick Start section.

**Build from source:**

```bash
git clone https://github.com/BlkLeg/circuitbreaker.git && cd circuitbreaker
docker compose up -d
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
| `DB_POOL_SIZE` | `10` | PostgreSQL connection pool size. On Raspberry Pi or low-memory hosts, set to `3`–`5` to reduce memory. |
| `DB_MAX_OVERFLOW` | `10` | Extra connections allowed beyond the pool. On Pi, set to `2`–`3`. |
| `NATS_AUTH_TOKEN` | _(empty)_ | Optional. When set, NATS server and backend/workers use token auth. See [Deployment & Security](docs/deployment-security.md). |
| `NATS_TLS` | _(empty)_ | Optional. Set to `true` to connect to NATS over TLS. Server must be configured for TLS separately. |

### Persistence Layout

The root `docker-compose.yml` uses a **bind mount** (managed by Docker) and **bind mounts** (specific host folders). These are the important ones:

| Mount | Type | Container path | What it stores | Notes |
|------|------|----------------|----------------|-------|
| `backend-data` | Named volume | `/app/data` | SQLite DB, vault key file, encrypted credentials metadata, generated runtime data | This is the most important persistence mount |
| `../data/uploads/icons` | Bind mount | `/app/data/uploads/icons` | Custom uploaded icons | Lets you inspect/back up icons directly on the host |
| `../data/uploads/branding` | Bind mount | `/app/data/uploads/branding` | Branding assets, login background, logos | Safe to back up independently |
| `caddy_data` | Named volume | `/data` in `cb-caddy` | Local CA, certificates, ACME state | Required for HTTPS continuity across restarts |
| `caddy_config` | Named volume | `/config` in `cb-caddy` | Caddy autosave/config state | Usually leave this alone |
| `nats_data` | Named volume | `/data/nats` | NATS / JetStream state | Needed for durable worker messaging |
| `postgres_data` | Named volume | `/var/lib/postgresql/data` | PostgreSQL data | Only used when `--profile pg` is enabled |

Important paths inside the backend data volume:

- `/app/data/app.db`: default SQLite database
- `/app/data/.env`: persisted `CB_VAULT_KEY` written during OOBE
- `/app/data/uploads/`: runtime uploads and derived assets

Example: mount specific host folders instead of Docker-managed named volumes

```yaml
services:
  backend:
    volumes:
      - ./data/backend:/app/data
      - ./data/icons:/app/data/uploads/icons
      - ./data/branding:/app/data/uploads/branding

  caddy:
    volumes:
      - ./data/caddy:/data
      - ./data/caddy-config:/config

  nats:
    volumes:
      - ./data/nats:/data/nats
```

If you switch to host folders, keep those directories backed up together. The most critical pair is the backend data directory and the Caddy data directory.

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

1. In `docker-compose.yml`, uncomment under the `circuitbreaker` service:
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
3. Restart: `docker compose up -d`

**Security note:** `NET_RAW` + `NET_ADMIN` allow the container to craft and send arbitrary raw packets. Only enable this on trusted, isolated homelab networks.

### Docker socket (Docker-aware discovery)

The Docker socket is **not** mounted by default. To enable Docker-aware discovery (container/network enumeration), use the optional override so the backend can read the socket read-only:

```bash
# Development
docker compose -f docker-compose.yml -f docker/docker-compose.socket.yml up -d

# Production (prebuilt images)
docker compose -f docker-compose.yml -f docker/docker-compose.socket.yml up -d
```

Then enable "Docker Container Discovery" in **Settings → Discovery**. See [docs/discovery.md](docs/discovery.md).

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

## Troubleshooting

### Poetry install: DBusErrorResponse / SecretServiceNotAvailableException

If `poetry install` (or `poetry lock && poetry install`) in `apps/backend` fails with `DBusErrorResponse` or `SecretServiceNotAvailableException` (e.g. "Remote peer disconnected" in `secretstorage`), Poetry is trying to use the system keyring (Secret Service over D-Bus), which can be unavailable in headless or locked-session environments.

- **Project fix**: This repo disables keyring for the backend via [`apps/backend/poetry.toml`](apps/backend/poetry.toml) (`keyring.enabled = false`). Ensure you run Poetry from the backend directory: `cd apps/backend && poetry install`.
- **Global fallback**: Run once: `poetry config keyring.enabled false`.
- **Per-invocation**: `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry install`.

In CI, either rely on the project `poetry.toml` or set `POETRY_KEYRING_ENABLED=false` (or the env var above) so installs do not touch the keyring.

### Backend venv: use a stable Python (3.11–3.13)

The backend supports Python `>=3.11,<4`. If you are on Python 3.14 (or another very new interpreter) and see install or runtime issues, use a stable 3.11–3.13 interpreter for the Poetry venv:

```bash
cd apps/backend
poetry env use python3.12   # or python3.11 / python3.13
poetry install
```

A `.python-version` file in `apps/backend` is set to `3.12` for pyenv users so the default interpreter in that directory is a stable version.

### Security and lint (local + CI)

Run the full security and lint suite locally to catch issues before pushing (saves CI minutes): `make security-scan`. This runs Bandit, Semgrep, Gitleaks, ESLint (with security plugin), Hadolint, Checkov, Trivy (filesystem + config), and npm audit. The same tools run in CI via [`.github/workflows/security.yml`](.github/workflows/security.yml). For editor support, install the recommended VS Code extensions from `.vscode/extensions.json` (ESLint, Ruff, Mypy, Hadolint, Trivy, Checkov, Semgrep).

### Old Discovery UI (bottom nav, "Ad-hoc Scan", PROGRESS/LIVE RESULTS)

The current Discovery UI has a **left sidebar** (New Scan, All Scans, Proxmox VE, Scan Profiles, Review Queue, History) and a "New Scan" page with Safe/Full/Docker mode cards and TARGET SCOPE. If you see an older layout (bottom nav only, "• Ad-hoc Scan" title, NMAP SCAN PROFILE dropdown, Launch Scan, PROGRESS/LIVE RESULTS), the frontend image in use is outdated.

- **Compose install:** In your install directory (e.g. `~/.circuit-breaker`), re-pull with an explicit current tag and restart, then hard-refresh the browser (Ctrl+Shift+R or Cmd+Shift+R):

  ```bash
  CB_TAG=v0.2.0 docker compose pull
  docker compose up -d
  ```

  Use the tag that matches your release (e.g. `v0.2.0` or the version shown in Settings). After each release, `frontend-latest` and `backend-latest` are updated, so future installs with the default script will get the current UI.

***

## Documentation

- [Overview](docs/OVERVIEW.md)
- [Roadmap](docs/ROADMAP.md) – v0.3.0: VLANs, mobile polish.

## Community

Join [Discord](https://discord.gg/SBdBRfmD) for support/showcase. Follow [@TryHostingCB](https://x.com/TryHostingCB).

**Star on GitHub** ⭐ Questions? #support! 🖥️