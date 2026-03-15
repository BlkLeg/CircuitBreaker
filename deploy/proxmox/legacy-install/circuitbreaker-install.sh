#!/usr/bin/env bash
# Circuit Breaker — Native LXC Install
# Python 3.11 + Postgres 15 + PgBouncer + NATS + Redis + nginx — zero Docker
set -euo pipefail

CB_VERSION="${CB_VERSION:-0.2.2}"
CB_PORT_INTERNAL="8000"     # uvicorn binds here (localhost only)
CB_PORT_PUBLIC="80"         # nginx HTTP (redirect to HTTPS)
CB_PORT_HTTPS="443"         # nginx HTTPS
CB_USER="breaker"
CB_GROUP="breaker"
CB_UID="1000"
CB_GID="1000"
CB_DIR="/opt/circuitbreaker"
CB_DATA_DIR="/var/lib/circuitbreaker"
CB_LOG_DIR="/var/log/circuitbreaker"
CB_REPO="https://github.com/BlkLeg/CircuitBreaker"
CB_DB_NAME="circuitbreaker"
CB_DB_USER="cb"
NATS_VER="2.10.24"

RESET="\033[0m"; GREEN="\033[32m"; DIM="\033[2m"; ORANGE="\033[33m"
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
info() { echo -e "  ${DIM}→${RESET} $*"; }
warn() { echo -e "  ${ORANGE}!${RESET} $*"; }

export DEBIAN_FRONTEND=noninteractive

# ── 1. System packages ────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    postgresql \
    postgresql-client \
    pgbouncer \
    redis-server \
    nginx \
    curl \
    wget \
    git \
    ca-certificates \
    openssl \
    jq \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    nmap \
    snmp \
    ipmitool \
    libmagic1
ok "System packages installed"

# ── 2. Install NATS server ───────────────────────────────────
info "Installing NATS server v${NATS_VER}..."
ARCH=$(dpkg --print-architecture)
wget -qO /tmp/nats.tar.gz \
    "https://github.com/nats-io/nats-server/releases/download/v${NATS_VER}/nats-server-v${NATS_VER}-linux-${ARCH}.tar.gz"
tar -xzf /tmp/nats.tar.gz -C /tmp
install -m 755 "/tmp/nats-server-v${NATS_VER}-linux-${ARCH}/nats-server" /usr/local/bin/
rm -rf /tmp/nats*
ok "NATS server installed"

# ── 3. Create service user ────────────────────────────────────
info "Creating service user breaker:${CB_UID}..."
groupadd --gid "$CB_GID" "$CB_GROUP" 2>/dev/null || true
useradd \
    --uid "$CB_UID" \
    --gid "$CB_GID" \
    --no-create-home \
    --shell /sbin/nologin \
    --comment "Circuit Breaker service account" \
    "$CB_USER" 2>/dev/null || true
ok "User breaker:1000 created"

# ── 4. Create directories ─────────────────────────────────────
info "Creating directories..."
mkdir -p \
    "${CB_DIR}" \
    "${CB_DATA_DIR}" \
    "${CB_DATA_DIR}/uploads" \
    "${CB_DATA_DIR}/vault" \
    "${CB_DATA_DIR}/nats" \
    "${CB_DATA_DIR}/redis" \
    "${CB_DATA_DIR}/tls" \
    "${CB_DATA_DIR}/pgdata" \
    "${CB_LOG_DIR}"

chown -R "${CB_USER}:${CB_GROUP}" \
    "${CB_DATA_DIR}" \
    "${CB_LOG_DIR}"
chmod 750 "${CB_DATA_DIR}" "${CB_LOG_DIR}"
ok "Directories created"

# ── 5. Clone repository ───────────────────────────────────────
info "Cloning Circuit Breaker v${CB_VERSION}..."
if [[ -d "${CB_DIR}/.git" ]]; then
    git -C "${CB_DIR}" fetch --tags -q
    git -C "${CB_DIR}" checkout "v${CB_VERSION}" -q 2>/dev/null \
        || git -C "${CB_DIR}" checkout main -q
else
    git clone --depth 1 --branch "v${CB_VERSION}" \
        "$CB_REPO" "${CB_DIR}" -q 2>/dev/null \
        || git clone --depth 1 "$CB_REPO" "${CB_DIR}" -q
fi
chown -R root:root "${CB_DIR}"   # app source owned by root — not writable by breaker
ok "Repository at ${CB_DIR}"

# ── 6. Python virtualenv + dependencies ──────────────────────
info "Creating Python virtualenv..."
python3 -m venv "${CB_DIR}/.venv"
"${CB_DIR}/.venv/bin/pip" install --upgrade pip wheel -q
"${CB_DIR}/.venv/bin/pip" install \
    -r "${CB_DIR}/apps/backend/requirements.txt" \
    -r "${CB_DIR}/apps/backend/requirements-pg.txt" \
    -q
ok "Python dependencies installed"

# ── 7. Build frontend ─────────────────────────────────────────
info "Building frontend..."
STATIC_DIR="${CB_DIR}/apps/frontend/dist"
if [[ -d "${STATIC_DIR}" ]]; then
    ok "Pre-built frontend found"
else
    if ! command -v node >/dev/null 2>&1; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
        apt-get install -y -qq nodejs
    fi
    cd "${CB_DIR}/apps/frontend"
    npm ci --silent
    npm run build --silent
    cd /
    ok "Frontend built from source"
fi

# ── 8. PostgreSQL setup ───────────────────────────────────────
info "Configuring PostgreSQL..."
systemctl enable --now postgresql
TRIES=0
until pg_isready -q; do
    TRIES=$((TRIES+1)); [[ $TRIES -ge 20 ]] && { echo "Postgres failed to start"; exit 1; }
    sleep 1
done

CB_DB_PASS=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 32)

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${CB_DB_USER}') THEN
        CREATE ROLE ${CB_DB_USER} WITH LOGIN PASSWORD '${CB_DB_PASS}';
    ELSE
        ALTER ROLE ${CB_DB_USER} WITH PASSWORD '${CB_DB_PASS}';
    END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${CB_DB_NAME}' WHERE NOT EXISTS
    (SELECT FROM pg_database WHERE datname = '${CB_DB_NAME}')\gexec
GRANT ALL PRIVILEGES ON DATABASE ${CB_DB_NAME} TO ${CB_DB_USER};
SQL
ok "PostgreSQL configured"

# ── 9. Generate app secrets ───────────────────────────────────
info "Generating secrets..."
JWT_SECRET=$(openssl rand -hex 32)
VAULT_KEY=$(python3 -c \
    "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
NATS_TOKEN=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
REDIS_PASS=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)

# Persist Redis password for service use
printf '%s' "$REDIS_PASS" > "${CB_DATA_DIR}/.redis_pass"
chmod 600 "${CB_DATA_DIR}/.redis_pass"
chown ${CB_USER}:${CB_GROUP} "${CB_DATA_DIR}/.redis_pass"

# Write env file — readable only by root and breaker group
cat > /etc/circuitbreaker.env <<EOF
# Circuit Breaker environment — $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Generated at install. Do not share this file.

CB_DATA_DIR=${CB_DATA_DIR}
CB_DB_URL=postgresql://${CB_DB_USER}:${CB_DB_PASS}@localhost:5432/${CB_DB_NAME}
CB_DB_POOL_URL=postgresql://${CB_DB_USER}:${CB_DB_PASS}@127.0.0.1:6432/${CB_DB_NAME}
CB_JWT_SECRET=${JWT_SECRET}
CB_VAULT_KEY=${VAULT_KEY}
CB_ENVIRONMENT=production
CB_APP_URL=https://$(hostname -I | awk '{print $1}')
NATS_AUTH_TOKEN=${NATS_TOKEN}
NATS_URL=nats://127.0.0.1:4222
CB_REDIS_URL=redis://:${REDIS_PASS}@127.0.0.1:6379/0
PYTHONPATH=${CB_DIR}/apps/backend/src
CB_ALEMBIC_INI=${CB_DIR}/apps/backend/alembic.ini
ALEMBIC_CONFIG=${CB_DIR}/apps/backend/alembic.ini
STATIC_DIR=${STATIC_DIR}
UPLOADS_DIR=${CB_DATA_DIR}/uploads
PYTHONDONTWRITEBYTECODE=1
EOF
chown root:"${CB_GROUP}" /etc/circuitbreaker.env
chmod 640 /etc/circuitbreaker.env
ok "Secrets written to /etc/circuitbreaker.env"

# ── 10. PgBouncer setup ─────────────────────────────────────
info "Configuring PgBouncer..."
# Disable default pgbouncer instance
systemctl disable --now pgbouncer 2>/dev/null || true

cat > /etc/pgbouncer/circuitbreaker.ini <<EOF
[databases]
circuitbreaker = host=127.0.0.1 port=5432 dbname=circuitbreaker

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = scram-sha-256
auth_file = ${CB_DATA_DIR}/pgbouncer_userlist.txt
pool_mode = transaction
max_client_conn = 100
default_pool_size = 20
min_pool_size = 5
reserve_pool_size = 5
reserve_pool_timeout = 3
server_reset_query = DISCARD ALL
log_connections = 0
log_disconnections = 0
log_pooler_errors = 1
stats_period = 60
pidfile = /run/pgbouncer/pgbouncer.pid
logfile = ${CB_LOG_DIR}/pgbouncer.log
EOF

# PgBouncer with scram-sha-256 needs the SCRAM verifier from Postgres
PG_SCRAM_VERIFIER=$(sudo -u postgres psql -tAc "SELECT rolpassword FROM pg_authid WHERE rolname='${CB_DB_USER}'")
printf '"cb" "%s"\n' "$PG_SCRAM_VERIFIER" > "${CB_DATA_DIR}/pgbouncer_userlist.txt"
chmod 640 "${CB_DATA_DIR}/pgbouncer_userlist.txt"
chown ${CB_USER}:${CB_GROUP} "${CB_DATA_DIR}/pgbouncer_userlist.txt"
ok "PgBouncer configured"

# ── 11. Redis setup ──────────────────────────────────────────
info "Configuring Redis..."
# Disable default redis instance
systemctl disable --now redis-server 2>/dev/null || true

cat > /etc/redis/circuitbreaker.conf <<EOF
bind 127.0.0.1
port 6379
daemonize no
dir ${CB_DATA_DIR}/redis
maxmemory 128mb
maxmemory-policy allkeys-lru
requirepass ${REDIS_PASS}
save ""
protected-mode yes
logfile ""
EOF
chown redis:redis /etc/redis/circuitbreaker.conf
ok "Redis configured"

# ── 12. NATS config ──────────────────────────────────────────
info "Configuring NATS..."
mkdir -p "${CB_DATA_DIR}/nats"
chown ${CB_USER}:${CB_GROUP} "${CB_DATA_DIR}/nats"
ok "NATS data directory ready"

# ── 13. TLS certificate ─────────────────────────────────────
info "Generating self-signed TLS certificate..."
openssl req -x509 -nodes -days 365 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "${CB_DATA_DIR}/tls/privkey.pem" \
    -out "${CB_DATA_DIR}/tls/fullchain.pem" \
    -subj "/CN=$(hostname -I | awk '{print $1}')" 2>/dev/null
chown ${CB_USER}:${CB_GROUP} "${CB_DATA_DIR}/tls/"*
chmod 600 "${CB_DATA_DIR}/tls/privkey.pem"
ok "Self-signed TLS certificate generated"

# ── 14. Run DB migrations ──────────────────────────────────────
info "Running database migrations..."
sudo -u "${CB_USER}" \
    env $(grep -v '^#' /etc/circuitbreaker.env | grep -v '^$' | xargs) \
    "${CB_DIR}/.venv/bin/alembic" \
    --config "${CB_DIR}/apps/backend/alembic.ini" \
    upgrade head
ok "Migrations complete"

# OOBE marker — parity with docker/30-oobe.sh
touch "${CB_DATA_DIR}/.oobe-complete"
chown ${CB_USER}:${CB_GROUP} "${CB_DATA_DIR}/.oobe-complete"

# ── 15. systemd: NATS server ────────────────────────────────
info "Installing systemd services..."
cat > /etc/systemd/system/nats-server.service <<EOF
[Unit]
Description=NATS Server (Circuit Breaker)
After=network.target

[Service]
Type=simple
User=${CB_USER}
Group=${CB_GROUP}
EnvironmentFile=/etc/circuitbreaker.env
ExecStart=/usr/local/bin/nats-server --jetstream --store_dir ${CB_DATA_DIR}/nats --auth \${NATS_AUTH_TOKEN}
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# ── 16. systemd: Redis ──────────────────────────────────────
cat > /etc/systemd/system/cb-redis.service <<EOF
[Unit]
Description=Redis (Circuit Breaker)
After=network.target

[Service]
Type=simple
User=redis
Group=redis
ExecStart=/usr/bin/redis-server /etc/redis/circuitbreaker.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── 17. systemd: PgBouncer ──────────────────────────────────
cat > /etc/systemd/system/cb-pgbouncer.service <<EOF
[Unit]
Description=PgBouncer (Circuit Breaker)
After=postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=${CB_USER}
Group=${CB_GROUP}
RuntimeDirectory=pgbouncer
ExecStart=/usr/sbin/pgbouncer /etc/pgbouncer/circuitbreaker.ini
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ── 18. systemd: Circuit Breaker API ────────────────────────
cat > /etc/systemd/system/circuitbreaker.service <<EOF
[Unit]
Description=Circuit Breaker — Homelab Topology Manager
Documentation=https://github.com/BlkLeg/CircuitBreaker
After=network.target postgresql.service cb-pgbouncer.service nats-server.service cb-redis.service
Requires=postgresql.service

[Service]
Type=exec
User=${CB_USER}
Group=${CB_GROUP}
WorkingDirectory=${CB_DIR}/apps/backend/src
EnvironmentFile=/etc/circuitbreaker.env
# Vault key auto-sync — if the app rotates CB_VAULT_KEY it writes to
# the data-dir .env; this overlay takes precedence over the base config
# (parity with docker/entrypoint-mono.sh lines 204-211).
EnvironmentFile=-${CB_DATA_DIR}/.env

ExecStart=${CB_DIR}/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 \
    --port ${CB_PORT_INTERNAL} \
    --workers 2 \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips=127.0.0.1

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${CB_DATA_DIR} ${CB_LOG_DIR}
CapabilityBoundingSet=

Restart=always
RestartSec=5
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=circuitbreaker

[Install]
WantedBy=multi-user.target
EOF

# ── 19. systemd: Workers ────────────────────────────────────
cat > /etc/systemd/system/circuitbreaker-worker@.service <<EOF
[Unit]
Description=Circuit Breaker Worker %i
After=circuitbreaker.service postgresql.service nats-server.service cb-redis.service
Requires=postgresql.service

[Service]
Type=simple
User=${CB_USER}
Group=${CB_GROUP}
WorkingDirectory=${CB_DIR}/apps/backend/src
EnvironmentFile=/etc/circuitbreaker.env
EnvironmentFile=-${CB_DATA_DIR}/.env
ExecStart=${CB_DIR}/.venv/bin/python -m app.workers.main --type=%i

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${CB_DATA_DIR} ${CB_LOG_DIR}

Restart=on-failure
RestartSec=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-worker-%i

[Install]
WantedBy=multi-user.target
EOF
ok "Systemd services installed"

# ── 20. nginx reverse proxy ───────────────────────────────────
info "Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/circuitbreaker <<'NGINXEOF'
# Gzip compression — parity with Docker mono nginx.mono.conf
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_min_length 1024;
gzip_types text/plain text/css text/javascript application/javascript
           application/json application/xml image/svg+xml font/woff2;

# HTTP — health check exempt from redirect, everything else → HTTPS
server {
    listen 80;
    server_name _;

    location @backend_warming_up {
        default_type application/json;
        add_header   Retry-After 5 always;
        return 503 '{"status":"warming_up","message":"Service is starting up, please retry in a few seconds."}';
    }

    set $backend "http://127.0.0.1:8000";

    location = /api/v1/health {
        proxy_connect_timeout  5s;
        proxy_next_upstream    error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 1;
        error_page 502 503 504 = @backend_warming_up;

        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS — main application server
server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate     /var/lib/circuitbreaker/tls/fullchain.pem;
    ssl_certificate_key /var/lib/circuitbreaker/tls/privkey.pem;

    root   /opt/circuitbreaker/apps/frontend/dist;
    index  index.html;
    client_max_body_size 32m;

    # Security headers
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'strict-dynamic'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://www.gravatar.com; connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; frame-ancestors 'none';" always;
    add_header X-Content-Type-Options  "nosniff"                          always;
    add_header X-Frame-Options         "DENY"                             always;
    add_header Referrer-Policy         "strict-origin-when-cross-origin"  always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()" always;

    location @backend_warming_up {
        default_type application/json;
        add_header   Retry-After 5 always;
        return 503 '{"status":"warming_up","message":"Service is starting up, please retry in a few seconds."}';
    }

    # Long-term caching for hashed static assets
    location ~* \.(js|css|woff2?|ttf|eot|png|jpg|jpeg|gif|svg|ico|webp)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    set $backend "http://127.0.0.1:8000";

    # WebSocket / SSE streaming endpoints
    location = /api/v1/discovery/stream {
        proxy_pass         $backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Authorization     $http_authorization;
        proxy_read_timeout 3600s;
        proxy_buffering    off;
    }

    location = /api/v1/topology/stream {
        proxy_pass         $backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Authorization     $http_authorization;
        proxy_read_timeout 3600s;
        proxy_buffering    off;
    }

    location = /api/v1/status/stream {
        proxy_pass         $backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Authorization     $http_authorization;
        proxy_read_timeout 3600s;
        proxy_buffering    off;
    }

    location = /api/v1/telemetry/stream {
        proxy_pass         $backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Authorization     $http_authorization;
        proxy_read_timeout 3600s;
        proxy_buffering    off;
    }

    location = /api/v1/events/stream {
        proxy_pass         $backend;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   Authorization     $http_authorization;
        proxy_set_header   Upgrade           "";
        proxy_set_header   Connection        "";
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
    }

    # Backend API proxy
    location ^~ /api/ {
        proxy_connect_timeout  5s;
        proxy_next_upstream    error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 1;
        error_page 502 503 504 = @backend_warming_up;

        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization     $http_authorization;
        proxy_set_header Upgrade           "";
        proxy_set_header Connection        "";
        proxy_read_timeout 30s;
    }

    # User-uploaded content proxied to backend
    location ^~ /user-icons/ {
        proxy_connect_timeout  5s;
        proxy_next_upstream    error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 1;
        error_page 502 503 504 = @backend_warming_up;

        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location ^~ /branding/ {
        proxy_connect_timeout  5s;
        proxy_next_upstream    error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 1;
        error_page 502 503 504 = @backend_warming_up;

        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location ^~ /uploads/ {
        proxy_connect_timeout  5s;
        proxy_next_upstream    error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 1;
        error_page 502 503 504 = @backend_warming_up;

        proxy_pass $backend;
        proxy_http_version 1.1;
        proxy_set_header Host            $host;
        proxy_set_header X-Real-IP       $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # React SPA catch-all
    location / {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        try_files $uri $uri/ /index.html;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/circuitbreaker \
       /etc/nginx/sites-enabled/circuitbreaker
ok "nginx configured"

# ── 21. Start services in dependency order ───────────────────
info "Starting services..."
systemctl daemon-reload

# Priority 10 — database
systemctl enable --now postgresql
ok "postgresql started"

# Priority 15 — connection pool
systemctl enable --now cb-pgbouncer
ok "cb-pgbouncer started"

# Priority 20 — event bus
systemctl enable --now nats-server
ok "nats-server started"

# Priority 25 — cache
systemctl enable --now cb-redis
ok "cb-redis started"

# Priority 30 — API + workers
systemctl enable --now circuitbreaker
systemctl enable --now circuitbreaker-worker@0
systemctl enable --now circuitbreaker-worker@1
systemctl enable --now circuitbreaker-worker@2
systemctl enable --now circuitbreaker-worker@3
ok "circuitbreaker + 4 workers started"

# Priority 40 — reverse proxy
nginx -t 2>/dev/null
systemctl enable --now nginx
systemctl reload nginx
ok "nginx started"

# ── 22. Wait for health ───────────────────────────────────────
info "Waiting for health check..."
TRIES=0
until curl -sf "http://127.0.0.1:${CB_PORT_INTERNAL}/api/v1/health" >/dev/null 2>&1; do
    TRIES=$((TRIES+1)); [[ $TRIES -ge 30 ]] && {
        warn "Health check timed out — dumping journal:"
        journalctl -u circuitbreaker --no-pager -n 20
        exit 1
    }
    sleep 2
done
ok "Circuit Breaker healthy"

# ── 23. cb-update command ─────────────────────────────────────
cat > /usr/local/bin/cb-update <<'SCRIPT'
#!/usr/bin/env bash
# Update Circuit Breaker to latest release
set -euo pipefail
CB_DIR="/opt/circuitbreaker"

echo "→ Fetching latest..."
git -C "$CB_DIR" fetch --tags -q
LATEST=$(git -C "$CB_DIR" describe --tags "$(git -C "$CB_DIR" rev-list --tags --max-count=1)")
echo "→ Updating to ${LATEST}..."
git -C "$CB_DIR" checkout "$LATEST" -q

echo "→ Installing dependencies..."
"${CB_DIR}/.venv/bin/pip" install \
    -r "${CB_DIR}/apps/backend/requirements.txt" \
    -r "${CB_DIR}/apps/backend/requirements-pg.txt" \
    -q

echo "→ Building frontend..."
if command -v node >/dev/null 2>&1; then
    cd "${CB_DIR}/apps/frontend"
    npm ci --silent
    npm run build --silent
    cd /
fi

echo "→ Running migrations..."
sudo -u breaker \
    env $(grep -v '^#' /etc/circuitbreaker.env | grep -v '^$' | xargs) \
    "${CB_DIR}/.venv/bin/alembic" \
    --config "${CB_DIR}/apps/backend/alembic.ini" \
    upgrade head

echo "→ Restarting services..."
systemctl restart cb-pgbouncer nats-server cb-redis circuitbreaker \
    circuitbreaker-worker@{0,1,2,3} nginx
sleep 3
curl -sf http://127.0.0.1:8000/api/v1/health | jq .
echo "✓ Updated to ${LATEST}"
SCRIPT
chmod +x /usr/local/bin/cb-update
ok "cb-update command installed"

# ── 24. MOTD ──────────────────────────────────────────────────
LAN_IP=$(hostname -I | awk '{print $1}')
cat > /etc/motd <<EOF

  ╔══════════════════════════════════════════════════════════╗
  ║   Circuit Breaker v${CB_VERSION}                               ║
  ║   Native LXC — Python + Postgres + nginx (no Docker)    ║
  ╚══════════════════════════════════════════════════════════╝

  Web UI  : https://${LAN_IP}
  Health  : curl -k https://${LAN_IP}/api/v1/health

  Services:
    systemctl status circuitbreaker
    systemctl status circuitbreaker-worker@{0,1,2,3}
    systemctl status postgresql cb-pgbouncer nats-server cb-redis nginx

  Logs    : journalctl -u circuitbreaker -f
  Update  : cb-update
  Config  : /etc/circuitbreaker.env
  Data    : /var/lib/circuitbreaker
  TLS     : /var/lib/circuitbreaker/tls/

EOF
ok "Install complete — Circuit Breaker v${CB_VERSION}"
