```markdown
# Circuit Breaker — Prompt A: `install.sh` Native Installer

## Role
You are a senior Linux systems engineer. Your task is to write a single,
production-grade `install.sh` for Circuit Breaker. It must be the ONLY
file a user needs to run. Everything else is automated.

## Output
Single file: `install.sh` in the repo root.
Must be executable bash. Shebang: `#!/usr/bin/env bash`

---

## Non-Negotiable Rules

1. `set -euo pipefail` at the top — fail on any unhandled error
2. Every VERIFY step must FAIL the installer with a human-readable
   error message. Never silently continue past a broken service.
3. Idempotent — safe to run on an existing install (triggers upgrade mode)
4. All secret generation happens ONCE. If `/etc/circuitbreaker/.env`
   exists, NEVER regenerate secrets.
5. All config files written from heredocs inside the script — no
   external template files needed.
6. Secrets substituted into config files at WRITE TIME — no runtime
   env var expansion in service configs.
7. Every `apt install` / `dnf install` uses `-y -q` flags. No
   interactive prompts from package managers ever surface to the user.
8. The script installs the `cb` CLI at `/usr/local/bin/cb` at the end.
   Inline it as a heredoc — no second file needed.

---

## Flag Interface

```bash
bash install.sh [OPTIONS]

Options:
  --port       <number>   HTTP port (default: 80)
  --data-dir   <path>     Data directory (default: /var/lib/circuitbreaker)
  --no-tls                Skip TLS cert generation
  --branch     <name>     Git branch to install from (default: main)
  --unattended            Skip all prompts, use defaults (for Proxmox LXC)
  --upgrade               Force upgrade mode even if install not detected
  --help                  Show usage
```

---

## UI / Progress Display

Use these exact functions throughout the script for consistent output:

```bash
# Color codes
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)                   ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${RESET}"
}

cb_step()    { echo -e "  ${CYAN}▸${RESET} $1..."; }
cb_ok()      { echo -e "  ${GREEN}✓${RESET}  $1"; }
cb_warn()    { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
cb_fail()    { echo -e "\n  ${RED}✗  ERROR: $1${RESET}"; echo -e "  ${YELLOW}→  $2${RESET}\n"; exit 1; }
cb_section() { echo -e "\n  ${BOLD}$1${RESET}"; echo "  $(printf '─%.0s' {1..42})"; }
```

All internal command output goes to:
`/var/lib/circuitbreaker/logs/install.log`
NOT to the terminal. The user only sees the progress functions above.

---

## Stage 0 — Pre-flight

```bash
# 1. Root check
[[ $EUID -ne 0 ]] && cb_fail "Must run as root" "sudo bash install.sh"

# 2. OS Detection — set PKG_MGR, OS_ID, OS_VERSION
# Supported matrix:
#   ubuntu:22.04, ubuntu:24.04
#   debian:11, debian:12
#   fedora:39, fedora:40, fedora:41
#   rhel:9, rocky:9, almalinux:9
# Source /etc/os-release, check ID + VERSION_ID
# cb_fail with unsupported message if no match

# 3. Architecture — set ARCH for NATS binary download
# uname -m → x86_64=amd64 | aarch64=arm64 | armv7l=arm7

# 4. Resource checks
# Free disk: df -BG / | tail -1 | awk '{print $4}' | tr -d G
#   < 3GB → cb_fail "Insufficient disk space (need 3GB free)"
# RAM: free -m | awk '/^Mem/{print $2}'
#   < 1024 → cb_warn "Low RAM detected (< 1GB). Performance may be limited."
#   Don't fail on RAM — Raspberry Pi installs are valid.

# 5. Existing install detection
# Check: systemctl is-active circuitbreaker-backend 2>/dev/null
# Or:    test -f /etc/circuitbreaker/.env
# If found: UPGRADE_MODE=true
# --upgrade flag also forces UPGRADE_MODE=true

# 6. Interactive prompts (skip if --unattended)
# Only if not UPGRADE_MODE:
#   CB_PORT (default: 80)
#   CB_DATA_DIR (default: /var/lib/circuitbreaker)
# Use: read -p with timeout fallback to default after 10s
```

---

## Stage 1 — User & Directory Bootstrap

```bash
# Create system user (skip if exists)
id breaker &>/dev/null || useradd -r -u 999 -s /usr/sbin/nologin \
  -d /nonexistent -c "Circuit Breaker" breaker

# Directory tree — exact permissions matter
# postgres dir MUST be postgres:postgres 700 before initdb
declare -A DIRS=(
  ["/opt/circuitbreaker"]="root:root:755"
  ["/opt/circuitbreaker/backend"]="breaker:breaker:750"
  ["/opt/circuitbreaker/frontend"]="root:root:755"
  ["/opt/circuitbreaker/scripts"]="root:root:755"
  ["/opt/circuitbreaker/frontend/dist"]="root:root:755"
  ["${CB_DATA_DIR}"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/postgres"]="postgres:postgres:700"
  ["${CB_DATA_DIR}/nats"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/redis"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/uploads"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/tls"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/logs"]="breaker:breaker:750"
  ["${CB_DATA_DIR}/backups"]="breaker:breaker:750"
  ["/etc/circuitbreaker"]="root:breaker:750"
  ["/etc/nats"]="root:root:755"
)
# Loop: mkdir -p, chown, chmod for each entry

# Secret generation — ONLY if /etc/circuitbreaker/.env does not exist
# Generate all 5 secrets, write full .env file:
# /etc/circuitbreaker/.env contents:
# --- Secrets (auto-generated, never change manually) ---
#   CB_JWT_SECRET=<openssl rand -hex 64>
#   CB_VAULT_KEY=<python3.12 Fernet.generate_key()>
#   CB_DB_PASSWORD=<openssl rand -base64 32 | tr -d /+= | head -c 32>
#   CB_REDIS_PASS=<openssl rand -base64 32 | tr -d /+= | head -c 32>
#   NATS_AUTH_TOKEN=<openssl rand -base64 48 | tr -d /+=>
# --- Connection strings ---
#   CB_DB_URL=postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:6432/circuitbreaker
#   CB_REDIS_URL=redis://:${CB_REDIS_PASS}@127.0.0.1:6379/0
#   NATS_URL=nats://127.0.0.1:4222
# --- Paths ---
#   CB_DATA_DIR=<value>
#   UPLOADS_DIR=<value>/uploads
#   STATIC_DIR=/opt/circuitbreaker/frontend/dist
#   LOG_DIR=<value>/logs
# --- App ---
#   CB_PORT=<value>
#   CB_APP_URL=http://<detected-ip>
#   CB_AUTH_ENABLED=false
#   CB_ENV=production
# File permissions: chmod 640, chown root:breaker
# Source the file immediately after writing: source /etc/circuitbreaker/.env
```

---

## Stage 2 — Dependency Installation

Show one progress line per group. All output → install.log.

```bash
# GROUP 1: Base tools
# apt: curl jq openssl netcat-openbsd git wget gnupg2 ca-certificates lsb-release
# dnf: curl jq openssl nmap-ncat git wget gnupg2 ca-certificates

# GROUP 2: Network/discovery tools
# apt: nmap snmp ipmitool
# dnf: nmap net-snmp-utils ipmitool
# Warn (don't fail) if ipmitool unavailable on arm7

# GROUP 3: PostgreSQL 15 (PGDG repo — not distro default)
# Ubuntu/Debian:
#   curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc → apt-key
#   Write /etc/apt/sources.list.d/pgdg.list
#   apt install -y -q postgresql-15 postgresql-client-15
# Fedora/RHEL:
#   dnf install -y -q https://download.postgresql.org/pub/repos/yum/reporpms/...
#   dnf install -y -q postgresql15-server postgresql15
# VERIFY: pg_lsclusters or pg_ctl --version | grep " 15"
#   → cb_fail if not version 15

# GROUP 4: pgbouncer, Redis, nginx
# apt: pgbouncer redis-server nginx
# dnf: pgbouncer redis nginx
# VERIFY each binary exists after install

# GROUP 5: NATS Server (binary download)
# URL: https://github.com/nats-io/nats-server/releases/latest/download/
#      nats-server-v<VERSION>-linux-<ARCH>.tar.gz
# Get latest version: curl -s https://api.github.com/repos/nats-io/nats-server/releases/latest
#                     | jq -r '.tag_name' | tr -d v
# Download → extract → install /usr/local/bin/nats-server
# chmod 755, chown root:root
# VERIFY: nats-server --version → cb_fail if missing

# GROUP 6: Python 3.12
# Ubuntu 22.04 only: add-apt-repository ppa:deadsnakes/ppa first
# Then: apt/dnf install python3.12 python3.12-venv python3.12-dev
# VERIFY: python3.12 --version → cb_fail "Python 3.12 required"

# GROUP 7: Node 20 LTS (build only)
# Ubuntu/Debian: NodeSource setup_20.x script
# Fedora/RHEL:   NodeSource rpm setup
# VERIFY: node --version | grep -q "^v20"
#   → cb_fail "Node 20 required for frontend build"
```

---

## Stage 3 — Service Configuration

Each service configured, started, and VERIFIED before moving to next.
Use `>> /var/lib/circuitbreaker/logs/install.log 2>&1` on all commands.

### PostgreSQL
```bash
# 1. Stop any running postgres first (idempotent)
# Ubuntu/Debian: pg_lsclusters, pg_dropcluster if exists at CB_DATA_DIR
# All: pg_ctl stop -D ${CB_DATA_DIR}/postgres || true

# 2. initdb
# Ubuntu/Debian: /usr/lib/postgresql/15/bin/initdb
#                -D ${CB_DATA_DIR}/postgres
#                --auth-local=peer --auth-host=md5
#                -U postgres
# Fedora/RHEL:   /usr/pgsql-15/bin/initdb ...
# Run as postgres user: su -s /bin/sh postgres -c "initdb ..."

# 3. Write postgresql.conf as heredoc (append/overwrite key lines)
# 4. Write pg_hba.conf as heredoc

# 5. Start PostgreSQL
# Create /etc/systemd/system/circuitbreaker-postgres.service HERE
# (see Stage 4 for full unit spec)
# systemctl enable + start circuitbreaker-postgres
# Sleep 3 then verify port 5432 listening: nc -z 127.0.0.1 5432

# 6. Create DB user and database
# Run as postgres: createuser / createdb
# su -s /bin/sh postgres -c "psql -c \"CREATE USER breaker...\""
# Handle already-exists gracefully (|| true with specific error check)

# VERIFY (hard fail):
# PGPASSWORD=$CB_DB_PASSWORD psql -h 127.0.0.1 -p 5432 \
#   -U breaker -d circuitbreaker -c '\q' 2>/dev/null
# || cb_fail "PostgreSQL connection failed" \
#            "Check logs: journalctl -u circuitbreaker-postgres -n 50"
```

### pgbouncer
```bash
# 1. Compute MD5 hash for userlist.txt
#    FORMAT: md5(password + username) — this is POSTGRESQL's md5 auth format
#    NOT just md5(password)
#    BASH: echo -n "${CB_DB_PASSWORD}breaker" | md5sum | cut -d' ' -f1
#    Result stored as: PGBOUNCER_HASH
#    Written as: "breaker" "md5${PGBOUNCER_HASH}"
#    This is the #1 silent failure point — get this exactly right.

# 2. Write /etc/pgbouncer/pgbouncer.ini as heredoc:
[databases]
circuitbreaker = host=127.0.0.1 port=5432 dbname=circuitbreaker

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 100
default_pool_size = 20
server_reset_query = DISCARD ALL
ignore_startup_parameters = extra_float_digits
logfile = ${CB_DATA_DIR}/logs/pgbouncer.log
pidfile = /run/pgbouncer/pgbouncer.pid

# 3. Write /etc/pgbouncer/userlist.txt
# 4. chown postgres:postgres /etc/pgbouncer/userlist.txt
# 5. Start pgbouncer (systemd unit — see Stage 4)

# VERIFY (hard fail — different port than postgres):
# PGPASSWORD=$CB_DB_PASSWORD psql -h 127.0.0.1 -p 6432 \
#   -U breaker -d circuitbreaker -c '\q' 2>/dev/null
# || cb_fail "pgbouncer connection failed" \
#            "Check userlist.txt hash. Run: cb doctor"
```

### Redis
```bash
# 1. Write /etc/redis/redis.conf as heredoc
#    Substitute $CB_REDIS_PASS at write time (not as env var)
# 2. chown redis:redis /etc/redis/redis.conf (or distro equivalent)
# 3. Start redis (systemd unit — see Stage 4)

# VERIFY (hard fail):
# redis-cli -a "$CB_REDIS_PASS" PING 2>/dev/null | grep -q PONG
# || cb_fail "Redis not responding" \
#            "Check: journalctl -u circuitbreaker-redis -n 50"
```

### NATS
```bash
# 1. Write /etc/nats/nats.conf as heredoc
#    Substitute actual $NATS_AUTH_TOKEN value — no env var in file
# 2. Create nats system user if not exists (for systemd unit)
# 3. Start nats (systemd unit — see Stage 4)

# VERIFY (hard fail):
# nc -z 127.0.0.1 4222 2>/dev/null
# || cb_fail "NATS not listening on 4222" \
#            "Check: journalctl -u circuitbreaker-nats -n 50"
```

### nginx
```bash
# 1. Write /etc/nginx/sites-available/circuitbreaker as heredoc:
#    - server_name _;
#    - listen $CB_PORT;
#    - root /opt/circuitbreaker/frontend/dist;
#    - try_files $uri $uri/ /index.html;  ← React SPA routing
#    - location /api/ { proxy_pass http://127.0.0.1:8000; ... }
#    - location /ws/  { proxy_pass http://127.0.0.1:8000;
#                       proxy_http_version 1.1;
#                       proxy_set_header Upgrade $http_upgrade;
#                       proxy_set_header Connection "upgrade"; }
#    - gzip on; gzip_types text/css application/javascript application/json;
#    - client_max_body_size 50M;  ← for icon uploads

# 2. Ubuntu/Debian: ln -sf .../sites-available/... sites-enabled/
#    rm -f /etc/nginx/sites-enabled/default
#    Fedora/RHEL: write directly to /etc/nginx/conf.d/circuitbreaker.conf
#    rm -f /etc/nginx/conf.d/default.conf

# 3. TLS (unless --no-tls):
#    openssl req -x509 -newkey rsa:4096 -nodes -days 3650
#      -keyout ${CB_DATA_DIR}/tls/privkey.pem
#      -out    ${CB_DATA_DIR}/tls/fullchain.pem
#      -subj "/CN=circuitbreaker/O=CircuitBreaker"
#    Add HTTPS server block on port 443 to nginx config

# 4. VERIFY config: nginx -t 2>/dev/null
#    || cb_fail "nginx config invalid" "Check: nginx -t"
# Note: Don't start nginx yet — frontend not built yet
```

---

## Stage 4 — All Systemd Units

Write all units in one function. Call before starting any service.

### Unit: `circuitbreaker-postgres.service`
```ini
[Unit]
Description=Circuit Breaker PostgreSQL 15
After=network.target
Before=circuitbreaker-pgbouncer.service

[Service]
Type=notify
User=postgres
Group=postgres
Environment=PGDATA=${CB_DATA_DIR}/postgres
ExecStart=/usr/lib/postgresql/15/bin/postgres -D ${CB_DATA_DIR}/postgres
# Fedora/RHEL: /usr/pgsql-15/bin/postgres
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGINT
TimeoutSec=0
Restart=on-failure
RestartSec=5s
StartLimitBurst=3
StartLimitIntervalSec=60s
NoNewPrivileges=yes
ProtectSystem=false
ReadWritePaths=${CB_DATA_DIR}/postgres
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-postgres

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker-pgbouncer.service`
```ini
[Unit]
Description=Circuit Breaker pgbouncer
After=circuitbreaker-postgres.service
Requires=circuitbreaker-postgres.service

[Service]
Type=forking
User=postgres
ExecStart=/usr/sbin/pgbouncer -d /etc/pgbouncer/pgbouncer.ini
ExecReload=/bin/kill -HUP $MAINPID
PIDFile=/run/pgbouncer/pgbouncer.pid
RuntimeDirectory=pgbouncer
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-pgbouncer

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker-redis.service`
```ini
[Unit]
Description=Circuit Breaker Redis
After=network.target

[Service]
Type=notify
User=redis
ExecStart=/usr/bin/redis-server /etc/redis/redis.conf
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
ReadWritePaths=${CB_DATA_DIR}/redis
MemoryMax=256M
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-redis

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker-nats.service`
```ini
[Unit]
Description=Circuit Breaker NATS JetStream
After=network.target

[Service]
Type=simple
User=breaker
ExecStart=/usr/local/bin/nats-server -c /etc/nats/nats.conf
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
ReadWritePaths=${CB_DATA_DIR}/nats
MemoryMax=512M
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-nats

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker-backend.service`
```ini
[Unit]
Description=Circuit Breaker Backend API
After=circuitbreaker-pgbouncer.service circuitbreaker-redis.service circuitbreaker-nats.service
Requires=circuitbreaker-pgbouncer.service circuitbreaker-redis.service circuitbreaker-nats.service

[Service]
Type=exec
User=breaker
Group=breaker
WorkingDirectory=/opt/circuitbreaker/backend
EnvironmentFile=/etc/circuitbreaker/.env
ExecStartPre=/opt/circuitbreaker/scripts/wait-for-services.sh
ExecStart=/opt/circuitbreaker/backend/venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 2 \
  --no-access-log
Restart=on-failure
RestartSec=5s
StartLimitBurst=3
StartLimitIntervalSec=60s
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${CB_DATA_DIR}
MemoryMax=1G
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-backend

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker-worker@.service` (template)
```ini
[Unit]
Description=Circuit Breaker Worker (%i)
After=circuitbreaker-backend.service
Requires=circuitbreaker-backend.service

[Service]
Type=simple
User=breaker
Group=breaker
WorkingDirectory=/opt/circuitbreaker/backend
EnvironmentFile=/etc/circuitbreaker/.env
ExecStart=/opt/circuitbreaker/backend/venv/bin/python -m app.workers.main --type %i
Restart=on-failure
RestartSec=10s
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${CB_DATA_DIR}
MemoryMax=512M
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-worker-%i

[Install]
WantedBy=multi-user.target
```

### Unit: `circuitbreaker.target`
```ini
[Unit]
Description=Circuit Breaker (all services)
Wants=circuitbreaker-postgres.service
Wants=circuitbreaker-pgbouncer.service
Wants=circuitbreaker-redis.service
Wants=circuitbreaker-nats.service
Wants=circuitbreaker-backend.service
Wants=circuitbreaker-worker@discovery.service
Wants=circuitbreaker-worker@webhook.service
Wants=circuitbreaker-worker@notification.service
Wants=circuitbreaker-worker@telemetry.service
After=circuitbreaker-postgres.service
After=circuitbreaker-pgbouncer.service
After=circuitbreaker-redis.service
After=circuitbreaker-nats.service
After=circuitbreaker-backend.service

[Install]
WantedBy=multi-user.target
```

After writing all units:
```bash
systemctl daemon-reload
# Enable but don't start yet — services are started individually
# with verification in Stage 3
systemctl enable circuitbreaker.target
systemctl enable circuitbreaker-postgres circuitbreaker-pgbouncer \
  circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
  "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
  "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry"
```

---

## `wait-for-services.sh`

Write to `/opt/circuitbreaker/scripts/wait-for-services.sh`
`chmod 755`, `chown root:root`

```bash
#!/usr/bin/env bash
set -euo pipefail
source /etc/circuitbreaker/.env

MAX_WAIT=60
INTERVAL=2

wait_port() {
  local name=$1 host=$2 port=$3 elapsed=0
  while ! nc -z "$host" "$port" 2>/dev/null; do
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    [[ $elapsed -ge $MAX_WAIT ]] && {
      echo "FATAL: $name did not start within ${MAX_WAIT}s" >&2
      echo "Run: cb doctor" >&2
      exit 1
    }
  done
}

wait_port "pgbouncer"  127.0.0.1 6432
wait_port "redis"      127.0.0.1 6379
wait_port "nats"       127.0.0.1 4222

# Actual DB connection test — port open ≠ DB accepting connections
PGPASSWORD="$CB_DB_PASSWORD" psql \
  -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null \
  || { echo "FATAL: Cannot connect to DB through pgbouncer" >&2; exit 1; }
```

---

## Stage 5 — Code Deployment

```bash
# Clone or update repo
if [[ -d /opt/circuitbreaker/.git ]]; then
  git -C /opt/circuitbreaker fetch origin
  git -C /opt/circuitbreaker checkout "$CB_BRANCH"
  git -C /opt/circuitbreaker pull origin "$CB_BRANCH"
else
  git clone --branch "$CB_BRANCH" --depth 1 \
    https://github.com/BlkLeg/circuitbreaker.git \
    /opt/circuitbreaker
fi

chown -R breaker:breaker /opt/circuitbreaker/backend
chown -R root:root /opt/circuitbreaker/frontend
```

---

## Stage 6 — Python Setup & Migrations

```bash
# Create venv
python3.12 -m venv /opt/circuitbreaker/backend/venv

# Install dependencies as breaker user
su -s /bin/sh breaker -c "
  source /opt/circuitbreaker/backend/venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r /opt/circuitbreaker/backend/requirements.txt
  pip install --quiet -e /opt/circuitbreaker/backend
"

# Run migrations (source .env first for DB URL)
source /etc/circuitbreaker/.env
su -s /bin/sh breaker -c "
  source /etc/circuitbreaker/.env
  cd /opt/circuitbreaker/backend
  /opt/circuitbreaker/backend/venv/bin/alembic upgrade head
" >> "${CB_DATA_DIR}/logs/install.log" 2>&1

# VERIFY migrations ran
MIGRATION_COUNT=$(PGPASSWORD="$CB_DB_PASSWORD" psql \
  -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -tAc \
  "SELECT COUNT(*) FROM alembic_version" 2>/dev/null || echo "0")

[[ "$MIGRATION_COUNT" -gt 0 ]] \
  || cb_fail "Database migrations did not run" \
             "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
```

---

## Stage 7 — Frontend Build

```bash
cd /opt/circuitbreaker/apps/frontend   # adjust to actual path

npm ci --silent >> "${CB_DATA_DIR}/logs/install.log" 2>&1 \
  || cb_fail "npm install failed" \
             "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"

npm run build --silent >> "${CB_DATA_DIR}/logs/install.log" 2>&1 \
  || cb_fail "Frontend build failed" \
             "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"

# VERIFY
[[ -f /opt/circuitbreaker/apps/frontend/dist/index.html ]] \
  || cb_fail "Frontend build produced no output" \
             "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"

# Fix permissions
chown -R root:root /opt/circuitbreaker/apps/frontend/dist
chmod -R 755 /opt/circuitbreaker/apps/frontend/dist

# Update nginx static path if different from plan
# Update STATIC_DIR in .env
```

---

## Stage 8 — Start Everything & Final Verify

```bash
# Start backend (postgres/pgbouncer/redis/nats already running from Stage 3)
systemctl start circuitbreaker-backend

# Wait for backend health endpoint
MAX_WAIT=30; elapsed=0
until curl -sf http://127.0.0.1:8000/api/v1/health | grep -q '"status"'; do
  sleep 2; elapsed=$((elapsed + 2))
  [[ $elapsed -ge $MAX_WAIT ]] && \
    cb_fail "Backend API did not start" "Run: cb doctor"
done

# Start workers
systemctl start "circuitbreaker-worker@discovery"
systemctl start "circuitbreaker-worker@webhook"
systemctl start "circuitbreaker-worker@notification"
systemctl start "circuitbreaker-worker@telemetry"

# Start nginx
systemctl start nginx

# Detect primary IP
CB_IP=$(ip route get 1.1.1.1 2>/dev/null \
  | grep -oP 'src \K[^ ]+' || echo "localhost")

# Write IP to .env for cb CLI
echo "CB_HOST_IP=$CB_IP" >> /etc/circuitbreaker/.env
```

---

## Stage 9 — Inline `cb` CLI

Write as heredoc to `/usr/local/bin/cb`, `chmod 755`:

```bash
#!/usr/bin/env bash
# cb — Circuit Breaker management CLI
# Installed by install.sh

[[ -f /etc/circuitbreaker/.env ]] && source /etc/circuitbreaker/.env

SERVICES=(
  "circuitbreaker-postgres"
  "circuitbreaker-pgbouncer"
  "circuitbreaker-redis"
  "circuitbreaker-nats"
  "circuitbreaker-backend"
  "circuitbreaker-worker@discovery"
  "circuitbreaker-worker@webhook"
  "circuitbreaker-worker@notification"
  "circuitbreaker-worker@telemetry"
)

cmd_status() {
  echo ""
  printf "  %-36s %-12s %s\n" "SERVICE" "STATUS" "UPTIME"
  printf "  %-36s %-12s %s\n" "─────────────────────────────────" "──────────" "──────"
  for svc in "${SERVICES[@]}"; do
    active=$(systemctl is-active "$svc" 2>/dev/null)
    uptime=$(systemctl show "$svc" --property=ActiveEnterTimestamp \
      --value 2>/dev/null | xargs -I{} date -d{} "+%H:%M %b %d" 2>/dev/null || echo "—")
    color="\033[0;32m"; [[ "$active" != "active" ]] && color="\033[0;31m"
    printf "  %-36s ${color}%-12s\033[0m %s\n" "$svc" "$active" "$uptime"
  done
  echo ""
}

cmd_doctor() {
  echo ""
  echo "  Circuit Breaker Health Check"
  echo "  ─────────────────────────────────────────"
  FAILED=0
  check() {
    local name=$1 cmd=$2 hint=$3
    if eval "$cmd" &>/dev/null; then
      printf "  \033[0;32m✓\033[0m  %-20s OK\n" "$name"
    else
      printf "  \033[0;31m✗\033[0m  %-20s FAILED\n" "$name"
      echo "     → $hint"
      FAILED=$((FAILED + 1))
    fi
  }
  check "PostgreSQL (5432)"  "nc -z 127.0.0.1 5432"           "journalctl -u circuitbreaker-postgres -n 30"
  check "pgbouncer (6432)"   "nc -z 127.0.0.1 6432"           "journalctl -u circuitbreaker-pgbouncer -n 30"
  check "DB connection"      "PGPASSWORD=\"$CB_DB_PASSWORD\" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q'" "Check pgbouncer userlist.txt hash"
  check "Redis (6379)"       "redis-cli -a \"$CB_REDIS_PASS\" PING | grep -q PONG" "journalctl -u circuitbreaker-redis -n 30"
  check "NATS (4222)"        "nc -z 127.0.0.1 4222"           "journalctl -u circuitbreaker-nats -n 30"
  check "Backend API (8000)" "curl -sf http://127.0.0.1:8000/api/v1/health" "journalctl -u circuitbreaker-backend -n 30"
  check "nginx (${CB_PORT})" "nc -z 127.0.0.1 ${CB_PORT:-80}" "nginx -t && journalctl -u nginx -n 30"
  echo ""
  [[ $FAILED -eq 0 ]] && echo "  All systems operational." \
                       || echo "  $FAILED check(s) failed. Fix top-down — each service depends on the one above."
  echo ""
}

cmd_logs() {
  journalctl -f \
    -u circuitbreaker-postgres \
    -u circuitbreaker-pgbouncer \
    -u circuitbreaker-redis \
    -u circuitbreaker-nats \
    -u circuitbreaker-backend \
    -u "circuitbreaker-worker@*" \
    -u nginx
}

cmd_restart() {
  echo "Restarting Circuit Breaker..."
  systemctl restart circuitbreaker.target
  sleep 3
  cmd_status
}

cmd_update() {
  echo "Updating Circuit Breaker..."
  bash <(curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh) --upgrade
}

cmd_backup() {
  TS=$(date +%Y%m%d-%H%M%S)
  FILE="${CB_DATA_DIR}/backups/cb-backup-${TS}.sql"
  echo "Backing up to $FILE..."
  PGPASSWORD="$CB_DB_PASSWORD" pg_dump \
    -h 127.0.0.1 -p 6432 -U breaker circuitbreaker > "$FILE"
  echo "Done: $FILE"
}

cmd_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "unknown"
}

cmd_uninstall() {
  read -rp "  Remove Circuit Breaker and ALL data? [y/N]: " confirm
  [[ "$confirm" != "y" ]] && echo "Cancelled." && exit 0
  systemctl stop circuitbreaker.target nginx 2>/dev/null || true
  systemctl disable circuitbreaker.target 2>/dev/null || true
  rm -f /etc/systemd/system/circuitbreaker-*.service
  rm -f /etc/systemd/system/circuitbreaker.target
  systemctl daemon-reload
  rm -rf /opt/circuitbreaker /etc/circuitbreaker /etc/nats
  rm -rf "${CB_DATA_DIR}"
  userdel breaker 2>/dev/null || true
  rm -f /usr/local/bin/cb
  echo "Circuit Breaker removed."
}

case "${1:-help}" in
  status)    cmd_status    ;;
  doctor)    cmd_doctor    ;;
  logs)      cmd_logs      ;;
  restart)   cmd_restart   ;;
  update)    cmd_update    ;;
  backup)    cmd_backup    ;;
  version)   cmd_version   ;;
  uninstall) cmd_uninstall ;;
  *)
    echo ""
    echo "  cb — Circuit Breaker CLI"
    echo ""
    echo "  Commands:"
    echo "    cb status     Show all service statuses"
    echo "    cb doctor     Run health checks and diagnose issues"
    echo "    cb logs       Tail all logs (live)"
    echo "    cb restart    Restart all services"
    echo "    cb update     Update to latest version"
    echo "    cb backup     Backup database"
    echo "    cb version    Show installed version"
    echo "    cb uninstall  Remove Circuit Breaker"
    echo ""
    ;;
esac
```

---

## Stage 10 — Final Output

```bash
cb_section "Circuit Breaker is running!"
echo ""
echo -e "  ┌──────────────────────────────────────────────┐"
echo -e "  │  URL:      http://${CB_HOST_IP}:${CB_PORT}"
echo -e "  │  Logs:     cb logs"
echo -e "  │  Status:   cb status"
echo -e "  │  Help:     cb doctor"
echo -e "  │  Version:  $(cat /opt/circuitbreaker/VERSION 2>/dev/null || echo 'unknown')"
echo -e "  └──────────────────────────────────────────────┘"
echo ""
echo -e "  First run? Open the URL above to complete setup."
echo ""
```

---

## Upgrade Mode Differences

When `UPGRADE_MODE=true`, the script:
1. Stops `circuitbreaker.target` first
2. Skips user/dir creation (idempotent mkdir -p handles it)
3. Skips secret generation (`.env` exists → skip)
4. Skips all dependency installs unless `--force-deps` passed
5. Runs backup BEFORE pulling new code (Stage 5)
6. Runs `git pull` instead of `git clone`
7. Runs `pip install` for new deps
8. Runs `alembic upgrade head` for new migrations
9. Runs `npm ci && npm run build` for new frontend
10. Restarts all services
11. Shows git changelog: `git log --oneline $OLD_HEAD..HEAD`

---

## Acceptance Criteria

- [ ] Running on fresh Ubuntu 24.04 VM installs fully with no manual steps
- [ ] Running on fresh Debian 12 installs fully with no manual steps
- [ ] Running on fresh Fedora 40 installs fully with no manual steps
- [ ] App opens in browser at displayed URL after script completes
- [ ] `cb status` shows all services green
- [ ] `cb doctor` passes all checks
- [ ] `cb logs` shows live log output
- [ ] Running install.sh again on existing install triggers upgrade mode
- [ ] All secrets are in `/etc/circuitbreaker/.env`, nowhere else
- [ ] No secrets ever print to terminal
- [ ] Full install completes in under 3 minutes on a 4-core VM
- [ ] Script fails with human-readable error if any VERIFY step fails
- [ ] `--unattended` flag completes with zero prompts
```