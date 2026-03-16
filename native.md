# Circuit Breaker — Native Deployment Plan
## "3 minutes or less" -  Proxmox-ready -  Docker co-equal

***

## Guiding Principles

1. **One command installs everything.** The user never edits a config file.
2. **Smart defaults for everything.** Optional prompts only — never required.
3. **Fail loudly, explain clearly.** Every error tells the user exactly what to run next.
4. **Idempotent.** Running the installer twice doesn't break anything.
5. **Proxmox-first roadmap.** `install.sh` is the engine. The Proxmox script just wraps it.
6. **Docker stays co-equal.** Native and Docker produce identical behavior. Same env vars, same secrets format, same DB schema.

***

## Deliverables

| # | Artifact | Location | Purpose |
|---|---|---|---|
| A | `install.sh` | repo root | One-liner full installer |
| B | `cb` | `/usr/local/bin/cb` | Diagnostic + management CLI |
| C | `proxmox/create-lxc.sh` | repo | tteck-style LXC provisioner |

No other user-facing files. All complexity is internal.

***

## User Experience (What They See)

### Native
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh)
```

### Proxmox
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/proxmox/create-lxc.sh)
```

### What runs on screen
```
╔══════════════════════════════════════════╗
║         Circuit Breaker Installer        ║
║                 v0.2.2                   ║
╚══════════════════════════════════════════╝

  Detected:  Ubuntu 24.04 LTS  ✓
  Resources: 4 CPU / 8GB RAM   ✓
  Network:   192.168.1.50      ✓

  Port            (default: 80):   ↵
  Data directory  (default: /var/lib/circuitbreaker):   ↵

  ┌──────────────────────────────────────────┐
  │  Installing dependencies...    ✓  0:14   │
  │  Configuring services...       ✓  0:03   │
  │  Initializing database...      ✓  0:04   │
  │  Running migrations...         ✓  0:06   │
  │  Building frontend...          ✓  1:12   │
  │  Starting Circuit Breaker...   ✓  0:08   │
  │  Verifying health...           ✓  0:05   │
  └──────────────────────────────────────────┘

  ✓  Circuit Breaker is running!

  ┌──────────────────────────────────────────┐
  │  URL:   http://192.168.1.50              │
  │  Logs:  cb logs                          │
  │  Help:  cb doctor                        │
  └──────────────────────────────────────────┘
```

**Total: ~2.5 minutes on modern hardware. Zero manual steps.**

***

## Artifact A — `install.sh`

### What it does (internal — user never sees this complexity)

#### Stage 0 — Pre-flight
```
- Must run as root (fail immediately with clear message if not)
- Detect OS + version:
    Supported: Ubuntu 22.04, 24.04 | Debian 11, 12 | Fedora 39, 40, 41 | RHEL/Rocky 9
    Unsupported: print message + exit cleanly (no half-installs)
- Detect architecture: amd64, arm64, armv7
- Detect available RAM + disk:
    Warn (not fail) if < 1GB RAM
    Fail if < 3GB free disk
- Detect if already installed → switch to upgrade mode automatically
- Detect if Docker version is running → offer migration path (future)
- Parse optional flags:
    --port          (default: 80)
    --data-dir      (default: /var/lib/circuitbreaker)
    --no-tls        (skip self-signed cert generation)
    --branch        (default: main, for testing)
    --unattended    (no prompts at all, pure defaults)
```

#### Stage 1 — User & Directory Bootstrap
```
- Create system user: breaker (uid 999, no login shell, no home dir)
- Create directory tree with correct owners BEFORE any service starts:

  /opt/circuitbreaker/                → root:root       755
  /opt/circuitbreaker/backend/        → breaker:breaker 750
  /opt/circuitbreaker/frontend/       → root:root       755
  /opt/circuitbreaker/scripts/        → root:root       755
  /var/lib/circuitbreaker/            → breaker:breaker 750
  /var/lib/circuitbreaker/postgres/   → postgres:postgres 700  ← critical
  /var/lib/circuitbreaker/nats/       → breaker:breaker 750
  /var/lib/circuitbreaker/redis/      → breaker:breaker 750
  /var/lib/circuitbreaker/uploads/    → breaker:breaker 750
  /var/lib/circuitbreaker/tls/        → breaker:breaker 750
  /var/lib/circuitbreaker/logs/       → breaker:breaker 750
  /etc/circuitbreaker/                → root:breaker    750

- Generate all secrets ONCE, write to /etc/circuitbreaker/.env (640 root:breaker)
  If file already exists (upgrade), SKIP — never regenerate secrets
  
  CB_JWT_SECRET    = openssl rand -hex 64
  CB_VAULT_KEY     = python3 Fernet.generate_key()
  CB_DB_PASSWORD   = openssl rand -base64 32 (url-safe strip)
  CB_REDIS_PASS    = openssl rand -base64 32
  NATS_AUTH_TOKEN  = openssl rand -base64 48
  
  Also write all connection strings, paths, port, app URL to same file.
  Single source of truth — every service reads from here.
```

#### Stage 2 — Dependency Installation
```
Package manager detection: apt (Debian/Ubuntu) | dnf (Fedora/RHEL)

Group 1 — Base tools (fast, always needed):
  curl, jq, openssl, netcat/ncat, git, wget, gnupg2, ca-certificates

Group 2 — Network/discovery tools:
  nmap, snmp, ipmitool
  Note: on RHEL/Fedora, snmp = net-snmp-utils

Group 3 — PostgreSQL 15 (from PGDG official repo):
  Ubuntu/Debian: Add pgdg.list + pgdg.asc, then apt install postgresql-15
  Fedora/RHEL:   Add pgdg-redhat-repo, then dnf install postgresql15-server
  Why PGDG: Ubuntu 22.04 defaults to PG14, Debian 11 defaults to PG13
  Verify: pg_config --version | grep " 15"  → FAIL if wrong version

Group 4 — pgbouncer, Redis, nginx:
  All from distro repos (versions are fine for CB's needs)

Group 5 — NATS Server (binary, not distro repo):
  Distro repos are years behind
  Download from: github.com/nats-io/nats-server/releases/latest
  Architecture-aware: amd64/arm64/arm6
  Install to: /usr/local/bin/nats-server
  Create: /etc/nats/ directory
  Verify: nats-server --version

Group 6 — Python 3.12:
  Ubuntu 22.04: deadsnakes PPA (ppa:deadsnakes/ppa)
  Ubuntu 24.04: python3.12 in main repo
  Debian 12:    python3.12 in main repo
  Fedora 39+:   python3.12 in main repo
  RHEL 9:       python3.12 from EPEL or SCL
  Verify: python3.12 --version → FAIL if not 3.12.x
  Also install: python3.12-venv, python3.12-dev

Group 7 — Node 20 LTS (for frontend build only):
  From NodeSource official setup script
  Not needed at runtime — only for the build step
  Verify: node --version | grep "^v20"

All installs:
  - Silent output (--quiet / -q flags)
  - Retry once on failure before failing installer
  - Log full output to /var/lib/circuitbreaker/logs/install.log
  - Progress indicator updates after each group completes
```

#### Stage 3 — Service Configuration
```
All config files written from heredocs inside the script.
Secrets substituted at write time from .env — no runtime env var expansion needed.

PostgreSQL:
  - initdb at /var/lib/circuitbreaker/postgres/
  - Write postgresql.conf:
      listen_addresses = 'localhost'
      port = 5432
      data_directory = /var/lib/circuitbreaker/postgres
      max_connections = 50
      log_directory = /var/lib/circuitbreaker/logs
      logging_collector = on
      log_filename = 'postgresql.log'
  - Write pg_hba.conf:
      local all         postgres             peer
      local circuitbreaker breaker          md5
      host  circuitbreaker breaker 127.0.0.1/32 md5
  - Start PostgreSQL (via pg_ctlcluster or pg_ctl)
  - Create user + database:
      CREATE USER breaker WITH PASSWORD '...'
      CREATE DATABASE circuitbreaker OWNER breaker
  - VERIFY: psql -U breaker -d circuitbreaker -c '\q'
    → FAIL HERE with clear message if this doesn't connect

pgbouncer:
  - Write /etc/pgbouncer/pgbouncer.ini (transaction mode, localhost:6432)
  - Generate /etc/pgbouncer/userlist.txt:
      md5 hash = md5(password + username) — compute in script
      "breaker" "md5<32-char-hex>"
      This is the #1 silent failure from the last attempt
  - VERIFY: psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q'
    → FAIL HERE if not working

Redis:
  - Write /etc/redis/redis.conf:
      bind 127.0.0.1
      port 6379
      requirepass <CB_REDIS_PASS>
      maxmemory 128mb
      maxmemory-policy allkeys-lru
      save ""
      dir /var/lib/circuitbreaker/redis
  - VERIFY: redis-cli -a $CB_REDIS_PASS PING → must return PONG
    → FAIL HERE if not PONG

NATS:
  - Write /etc/nats/nats.conf with token substituted at write time:
      port: 4222
      monitor_port: 8222
      authorization { token: "<actual-token-value>" }
      jetstream {
        store_dir: "/var/lib/circuitbreaker/nats"
        max_memory_store: 256MB
        max_file_store: 1GB
      }
  - VERIFY: nc -z 127.0.0.1 4222
    → FAIL HERE if port not open

nginx:
  - Write /etc/nginx/sites-available/circuitbreaker
  - Symlink to sites-enabled
  - Remove default site
  - Config includes:
      Static: serve /opt/circuitbreaker/frontend/dist
      API proxy: /api/ → http://127.0.0.1:8000
      WebSocket: /ws/ → http://127.0.0.1:8000 (upgrade headers)
      Gzip compression for assets
      Cache headers for static files
  - If --no-tls not set: generate self-signed cert to /var/lib/circuitbreaker/tls/
  - VERIFY: nginx -t → FAIL if config test fails
```

#### Stage 4 — Systemd Units
```
Written to /etc/systemd/system/circuitbreaker-*.service
systemctl daemon-reload after all are written

Startup dependency chain (enforced via After= and Requires=):

  circuitbreaker-postgres.service
    After: network.target
    User: postgres
    
  circuitbreaker-pgbouncer.service
    After + Requires: circuitbreaker-postgres.service
    
  circuitbreaker-redis.service
    After: network.target
    
  circuitbreaker-nats.service
    After: network.target
    EnvironmentFile: /etc/circuitbreaker/.env
    
  circuitbreaker-backend.service
    After + Requires: pgbouncer + redis + nats
    ExecStartPre: /opt/circuitbreaker/scripts/wait-for-services.sh
    User: breaker
    EnvironmentFile: /etc/circuitbreaker/.env
    ExecStart: /opt/circuitbreaker/backend/venv/bin/uvicorn app.main:app
               --host 127.0.0.1 --port 8000 --workers 2
    
  circuitbreaker-worker@.service  (template)
    After + Requires: circuitbreaker-backend.service
    User: breaker
    ExecStart: /opt/circuitbreaker/backend/venv/bin/python -m app.workers.main
               --type %i
    Instances: discovery, webhook, notification, telemetry
    
  circuitbreaker-nginx.service
    After + Requires: circuitbreaker-backend.service
    (uses system nginx, just ensures ordering)
    
  circuitbreaker.target
    Wants: all 7 units above
    (enable this target = enable everything)

All units include:
  Restart=on-failure
  RestartSec=5s
  StartLimitBurst=3 / StartLimitIntervalSec=60s
  NoNewPrivileges=yes
  StandardOutput=journal
  StandardError=journal
  SyslogIdentifier=cb-<name>
  MemoryMax= (per-service limits)
```

#### Stage 5 — `wait-for-services.sh`
```
/opt/circuitbreaker/scripts/wait-for-services.sh
Runs as ExecStartPre before backend starts.
Max wait: 60 seconds per service.
Checks (in order):
  1. nc -z 127.0.0.1 6432  (pgbouncer port open)
  2. nc -z 127.0.0.1 6379  (redis port open)
  3. nc -z 127.0.0.1 4222  (nats port open)
  4. psql $CB_DB_URL -c '\q'  (actual DB connection, not just port)
  5. redis-cli -a $CB_REDIS_PASS PING  (actual Redis, not just port)
Fails with clear message if any check times out.
This replaces Docker's depends_on: condition: service_healthy.
```

#### Stage 6 — Python App + Migrations
```
- python3.12 -m venv /opt/circuitbreaker/backend/venv
- /opt/.../venv/bin/pip install --quiet -r requirements.txt -r requirements-pg.txt
- /opt/.../venv/bin/pip install --quiet -e .
- Source /etc/circuitbreaker/.env
- /opt/.../venv/bin/alembic upgrade head
- VERIFY: psql $CB_DB_URL -c "SELECT version_num FROM alembic_version"
    → FAIL if no rows (migrations didn't run)
- Check if bootstrap needed:
    psql ... -c "SELECT is_initialized FROM app_settings LIMIT 1"
    → set CB_FIRST_RUN=true in .env if not initialized
      (OOBE wizard handles the rest on first browser visit)
```

#### Stage 7 — Frontend Build
```
- cd /opt/circuitbreaker/frontend
- /usr/bin/node (node 20) npm ci --silent
- npm run build --silent
- Output: /opt/circuitbreaker/frontend/dist/
- chown -R root:root dist/
- chmod -R 755 dist/
- VERIFY: test -f dist/index.html → FAIL if missing
- Optional: remove node_modules after build to save ~300MB disk
  (node only needed for rebuilds, cb update reinstalls it)
```

#### Stage 8 — Start Everything & Final Health Check
```
- systemctl daemon-reload
- systemctl enable circuitbreaker.target
- systemctl start circuitbreaker.target
- Wait for backend health endpoint:
    Poll http://127.0.0.1:8000/api/v1/health every 2s, max 30s
    → FAIL with "cb doctor" hint if doesn't come up
- systemctl start circuitbreaker-nginx.service
- Detect primary IP for access URL:
    ip route get 1.1.1.1 | grep -oP 'src \K[^ ]+'
- Print success box with URL, logs command, doctor command
```

#### Stage 9 — Upgrade Mode
```
Triggered when existing install detected.
- Stop services: systemctl stop circuitbreaker.target
- Backup DB: pg_dump circuitbreaker → /var/lib/circuitbreaker/backups/pre-upgrade-<date>.sql
- git pull (or re-download tarball for non-git installs)
- pip install (new deps)
- alembic upgrade head (new migrations)
- npm ci + npm run build (new frontend)
- Restart services
- Verify health
- Print what changed (git log --oneline OLD_HEAD..HEAD)
```

***

## Artifact B — `cb` CLI

Installed to `/usr/local/bin/cb` during install. Single bash script.

```bash
cb status       # Pretty table of all 7 services: name | status | uptime | memory
cb logs         # tail -f all CB journal logs multiplexed with service labels
cb doctor       # Run all health checks, print exactly what's wrong
cb restart      # Stop all → wait → start all in correct order
cb update       # Upgrade to latest (runs upgrade flow from Stage 9)
cb migrate      # Run alembic upgrade head manually (for manual DB changes)
cb backup       # pg_dump to /var/lib/circuitbreaker/backups/
cb uninstall    # Remove everything cleanly (prompts for confirmation)
cb version      # Show installed version + git commit
```

### `cb doctor` output (example)
```
Circuit Breaker Health Check
─────────────────────────────────────────
PostgreSQL   ✓  Running  (port 5432)
pgbouncer    ✓  Running  (port 6432)  connection pool OK
Redis        ✓  Running  (port 6379)  PONG received
NATS         ✗  FAILED   (port 4222)  
  → journalctl -u circuitbreaker-nats -n 50
  → Check /etc/nats/nats.conf for syntax errors
Backend API  -  Waiting  (port 8000)  blocked on NATS
Workers      -  Waiting              blocked on backend
nginx        ✓  Running  (port 80)

1 service failed. Fix NATS first — others will follow.
```

***

## Artifact C — `proxmox/create-lxc.sh`

The tteck-style wrapper. After `install.sh` is rock solid, this is written last.

```
User runs on Proxmox host:
bash <(curl -fsSL .../proxmox/create-lxc.sh)

whiptail TUI prompts (all have defaults):
  - CT ID:          (next available)
  - Hostname:       circuitbreaker
  - RAM:            2048 MB
  - Disk:           10 GB
  - CPU cores:      2
  - Network bridge: vmbr0
  - VLAN tag:       (none)
  - IP:             DHCP (or static)
  - Start on boot:  yes

Then automatically:
  1. Download Debian 12 template if not cached
  2. pct create <id> with all options
  3. pct set <id> features=nesting=1,keyctl=1
     (needed for Docker-in-LXC if user later wants Docker)
  4. pct start <id>
  5. Wait for container to be ready
  6. pct exec <id> -- bash <(curl -fsSL .../install.sh) --unattended
  7. Print CT IP + access URL + cb commands

Total user interaction: ~60 seconds of answering whiptail prompts
Total install time: ~3 minutes
```

***

## Port Map (Unchanged, for Reference)

| Service | Port | Exposed |
|---|---|---|
| PostgreSQL | 5432 | Localhost only |
| pgbouncer | 6432 | Localhost only |
| NATS | 4222 | Localhost only |
| Redis | 6379 | Localhost only |
| Backend API | 8000 | Localhost only |
| nginx | 80 / 443 | Public |

***

## Prompt Sequence

| Prompt | Output | Test before next |
|---|---|---|
| **A** | `install.sh` complete | Run on clean Ubuntu 24.04 VM, verify app opens in browser |
| **B** | `cb` CLI | Run `cb doctor`, `cb status`, `cb logs` on installed instance |
| **C** | `proxmox/create-lxc.sh` | Run on Proxmox, verify LXC created + app running |

***

## What Docker Keeps

Docker deployment is untouched. Native and Docker stay co-equal:
- Same `/etc/circuitbreaker/.env` format
- Same secrets naming
- Same DB schema (Alembic)
- Same `VERSION` file
- Docker image continues to be built and published to GHCR
- `docker-compose.yml` stays in repo root

The only thing that changes is there's now a second equally-valid path to production.