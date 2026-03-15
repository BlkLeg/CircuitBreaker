#!/usr/bin/env bash
# deploy/native/install.sh — Circuit Breaker Native Linux Installer
# Usage: sudo bash deploy/native/install.sh
#        CB_INSTALL_MODE=native bash install.sh
set -euo pipefail

# ── Colors / helpers ─────────────────────────────────────────────────────────
RESET="\033[0m"; BOLD="\033[1m"; GREEN="\033[32m"
ORANGE="\033[33m"; RED="\033[31m"; DIM="\033[2m"; CYAN="\033[36m"

ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
info() { echo -e "  ${CYAN}→${RESET} $*"; }
warn() { echo -e "  ${ORANGE}⚠${RESET} $*"; }
die()  { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

step() {
  STEP_NUM=$((STEP_NUM + 1))
  echo
  echo -e "  ${BOLD}[${STEP_NUM}/18]${RESET} $*"
}

STEP_NUM=0

# ── Banner ───────────────────────────────────────────────────────────────────
clear
echo -e "${BOLD}${ORANGE}"
cat <<'BANNER'
   ___  _                   _ _   ___
  / __\(_)_ __ ___ _   _(_) |_  / __\_ __ ___  __ _| | _____ _ __
 / /   | | '__/ __| | | | | __| /__\// '__/ _ \/ _` | |/ / _ \ '__|
/ /____| | | | (__| |_| | | |_/ \/  \ | |  __/ (_| |   <  __/ |
\______|_|_|  \___|\__,_|_|\__\_____/_|  \___|\__,_|_|\_\___|_|
BANNER
echo -e "${RESET}"
echo -e "  ${BOLD}Native Linux Installer${RESET}  ${DIM}https://github.com/BlkLeg/CircuitBreaker${RESET}"
echo

# ── Constants ────────────────────────────────────────────────────────────────
CB_APP_ROOT="/opt/circuitbreaker"
CB_CONFIG_DIR="/etc/circuitbreaker"
CB_DATA_DIR="/var/lib/circuitbreaker"
CB_LOG_DIR="/var/log/circuitbreaker"
CB_USER="breaker"
NATS_VERSION="${NATS_VERSION:-2.10.24}"
NATS_ARCH="$(uname -m)"
case "$NATS_ARCH" in
  x86_64)  NATS_ARCH="amd64" ;;
  aarch64) NATS_ARCH="arm64" ;;
  armv7l)  NATS_ARCH="arm7"  ;;
esac

# ── Detect script location (repo checkout vs extracted archive) ──────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Walk up to find repo root: deploy/native/install.sh → repo root is ../../
if [ -f "$SCRIPT_DIR/../../apps/backend/pyproject.toml" ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
  SOURCE_MODE="repo"
elif [ -f "$SCRIPT_DIR/apps/backend/pyproject.toml" ]; then
  REPO_ROOT="$SCRIPT_DIR"
  SOURCE_MODE="archive"
else
  # Try current working directory
  if [ -f "./apps/backend/pyproject.toml" ]; then
    REPO_ROOT="$(pwd)"
    SOURCE_MODE="archive"
  else
    die "Cannot locate Circuit Breaker source files. Run this script from the repo root or extracted archive."
  fi
fi
info "Source: ${SOURCE_MODE} at ${REPO_ROOT}"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 1: Check root / sudo
# ═════════════════════════════════════════════════════════════════════════════
step "Checking privileges"

if [ "$(id -u)" -ne 0 ]; then
  die "This installer must be run as root. Try: sudo bash $0"
fi
ok "Running as root"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 2: Detect OS
# ═════════════════════════════════════════════════════════════════════════════
step "Detecting operating system"

OS_ID="unknown"
OS_VERSION_ID="0"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION_ID="${VERSION_ID:-0}"
fi

case "$OS_ID" in
  debian)
    if [ "${OS_VERSION_ID%%.*}" -ge 12 ] 2>/dev/null; then
      ok "Debian ${OS_VERSION_ID} detected (supported)"
    else
      warn "Debian ${OS_VERSION_ID} detected — Debian 12+ recommended"
    fi
    ;;
  ubuntu)
    UBUNTU_MAJOR="${OS_VERSION_ID%%.*}"
    if [ "$UBUNTU_MAJOR" -ge 22 ] 2>/dev/null; then
      ok "Ubuntu ${OS_VERSION_ID} detected (supported)"
    else
      warn "Ubuntu ${OS_VERSION_ID} detected — Ubuntu 22.04+ recommended"
    fi
    ;;
  *)
    warn "Unsupported OS: ${OS_ID} ${OS_VERSION_ID}. This installer targets Debian 12+ / Ubuntu 22.04+."
    warn "Proceeding anyway — some packages may need manual installation."
    ;;
esac

# ═════════════════════════════════════════════════════════════════════════════
#  Step 3: Clean up old (hyphenated) artifacts
# ═════════════════════════════════════════════════════════════════════════════
step "Cleaning up legacy artifacts"

# Stop and disable old hyphenated service names
systemctl disable --now circuit-breaker.service circuit-breaker-native.service 2>/dev/null || true

# Remove old unit files
OLD_UNITS=$(find /etc/systemd/system/ -name 'circuit-breaker*' -type f 2>/dev/null || true)
if [ -n "$OLD_UNITS" ]; then
  echo "$OLD_UNITS" | while read -r unit; do
    rm -f "$unit"
    info "Removed old unit: $(basename "$unit")"
  done
  systemctl daemon-reload
  ok "Old systemd units removed"
else
  ok "No legacy units found"
fi

# Migrate old config directory if it exists
if [ -d "/etc/circuit-breaker" ] && [ ! -d "$CB_CONFIG_DIR" ]; then
  info "Migrating /etc/circuit-breaker/ → ${CB_CONFIG_DIR}/"
  mkdir -p "$CB_CONFIG_DIR"
  cp -a /etc/circuit-breaker/. "$CB_CONFIG_DIR/"
  ok "Config migrated from /etc/circuit-breaker/"
elif [ -d "/etc/circuit-breaker" ]; then
  warn "/etc/circuit-breaker/ exists but ${CB_CONFIG_DIR}/ already present — skipping migration"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 4: Create service user
# ═════════════════════════════════════════════════════════════════════════════
step "Creating service user"

if id "$CB_USER" &>/dev/null; then
  ok "User '${CB_USER}' already exists"
else
  useradd -r -m -s /bin/bash "$CB_USER"
  ok "Created system user '${CB_USER}'"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 5: Install system packages
# ═════════════════════════════════════════════════════════════════════════════
step "Installing system packages"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Determine which PostgreSQL package is available
PG_PKG="postgresql"
if apt-cache show postgresql-15 &>/dev/null; then
  PG_PKG="postgresql-15"
fi

PACKAGES=(
  "$PG_PKG"
  pgbouncer
  redis-server
  nginx
  python3
  python3-venv
  python3-pip
  nodejs
  npm
  curl
  jq
  openssl
  nmap
  snmp
  ipmitool
  gettext-base   # for envsubst
)

info "Installing: ${PACKAGES[*]}"
apt-get install -y -qq "${PACKAGES[@]}" 2>&1 | tail -5
ok "System packages installed"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 6: Install NATS server
# ═════════════════════════════════════════════════════════════════════════════
step "Installing NATS server"

if command -v nats-server &>/dev/null; then
  NATS_CURRENT=$(nats-server --version 2>/dev/null | grep -oP 'v[\d.]+' | head -1 || echo "unknown")
  ok "nats-server already installed (${NATS_CURRENT})"
else
  info "Downloading nats-server v${NATS_VERSION} (${NATS_ARCH})..."
  NATS_URL="https://github.com/nats-io/nats-server/releases/download/v${NATS_VERSION}/nats-server-v${NATS_VERSION}-linux-${NATS_ARCH}.tar.gz"
  NATS_TMP=$(mktemp -d)
  curl -fsSL "$NATS_URL" -o "${NATS_TMP}/nats.tar.gz"
  tar -xzf "${NATS_TMP}/nats.tar.gz" -C "$NATS_TMP"
  install -m 755 "${NATS_TMP}"/nats-server-*/nats-server /usr/local/bin/nats-server
  rm -rf "$NATS_TMP"
  ok "nats-server v${NATS_VERSION} installed to /usr/local/bin/nats-server"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 7: Create directories
# ═════════════════════════════════════════════════════════════════════════════
step "Creating directory structure"

mkdir -p \
  "$CB_APP_ROOT" \
  "$CB_CONFIG_DIR" \
  "$CB_DATA_DIR"/{pgdata,uploads,nats,tls,certs,redis,run/postgresql,tmp,backups} \
  "$CB_LOG_DIR"

# Set ownership
chown -R "$CB_USER":"$CB_USER" "$CB_DATA_DIR" "$CB_LOG_DIR"
chmod 700 "$CB_DATA_DIR/pgdata"

ok "Directories created under ${CB_APP_ROOT}, ${CB_DATA_DIR}, ${CB_LOG_DIR}"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 8: Copy application files
# ═════════════════════════════════════════════════════════════════════════════
step "Copying application files"

# Use rsync if available, fall back to cp
if command -v rsync &>/dev/null; then
  rsync -a --delete \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    "$REPO_ROOT/" "$CB_APP_ROOT/"
else
  cp -a "$REPO_ROOT/." "$CB_APP_ROOT/"
  # Clean up unnecessary files in the copy
  rm -rf "$CB_APP_ROOT/.git" "$CB_APP_ROOT/apps/frontend/node_modules" "$CB_APP_ROOT/apps/backend/.venv"
fi

chown -R "$CB_USER":"$CB_USER" "$CB_APP_ROOT"

# Create convenience symlinks so systemd units and deploy scripts can reference
# /opt/circuitbreaker/backend and /opt/circuitbreaker/frontend without the apps/ prefix.
ln -sfn "$CB_APP_ROOT/apps/backend"  "$CB_APP_ROOT/backend"
ln -sfn "$CB_APP_ROOT/apps/frontend" "$CB_APP_ROOT/frontend"

ok "Application files copied to ${CB_APP_ROOT}"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 9: Create Python venv and install backend dependencies
# ═════════════════════════════════════════════════════════════════════════════
step "Setting up Python virtual environment"

BACKEND_DIR="${CB_APP_ROOT}/apps/backend"
VENV_DIR="${BACKEND_DIR}/.venv"

sudo -u "$CB_USER" python3 -m venv "$VENV_DIR"
info "Installing Python dependencies..."
sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip setuptools wheel

# Install from requirements.txt if it exists, otherwise from pyproject.toml
if [ -f "${BACKEND_DIR}/requirements.txt" ]; then
  sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet -r "${BACKEND_DIR}/requirements.txt"
elif [ -f "${BACKEND_DIR}/pyproject.toml" ]; then
  sudo -u "$CB_USER" "$VENV_DIR/bin/pip" install --quiet "${BACKEND_DIR}"
fi

ok "Python venv created at ${VENV_DIR}"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 10: Build frontend
# ═════════════════════════════════════════════════════════════════════════════
step "Building frontend"

FRONTEND_DIR="${CB_APP_ROOT}/apps/frontend"

info "Running npm ci..."
cd "$FRONTEND_DIR"
sudo -u "$CB_USER" npm ci --silent 2>&1 | tail -3

info "Running npm run build..."
sudo -u "$CB_USER" npm run build --silent 2>&1 | tail -3
cd /

if [ -d "${FRONTEND_DIR}/dist" ]; then
  ok "Frontend built at ${FRONTEND_DIR}/dist/"
else
  warn "Frontend build may have failed — dist/ directory not found"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 11: Generate config.env with secrets
# ═════════════════════════════════════════════════════════════════════════════
step "Generating configuration"

CONFIG_ENV="${CB_CONFIG_DIR}/config.env"

if [ -f "$CONFIG_ENV" ]; then
  ok "Config already exists at ${CONFIG_ENV} — preserving"
else
  info "Generating secrets..."

  # Generate secrets — prefer Python, fall back to openssl
  CB_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null \
    || openssl rand -hex 32)
  CB_VAULT_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
    || openssl rand -base64 32)
  CB_DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))" 2>/dev/null \
    || openssl rand -base64 18)
  NATS_AUTH_TOKEN=$(openssl rand -base64 32)

  cat > "$CONFIG_ENV" <<EOF
# Circuit Breaker — generated by native installer on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT SHARE this file. It contains your secrets.

CB_JWT_SECRET=${CB_JWT_SECRET}
CB_VAULT_KEY=${CB_VAULT_KEY}
CB_DB_PASSWORD=${CB_DB_PASSWORD}
NATS_AUTH_TOKEN=${NATS_AUTH_TOKEN}

CB_DATA_DIR=${CB_DATA_DIR}
CB_APP_ROOT=${CB_APP_ROOT}
CB_LOG_DIR=${CB_LOG_DIR}
CB_DEPLOY_MODE=native

CB_DB_NAME=circuitbreaker
CB_DB_USER=${CB_USER}
CB_DB_HOST=127.0.0.1
CB_DB_PORT=5432
CB_DB_URL=postgresql://${CB_USER}:\${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker

CB_REDIS_URL=redis://127.0.0.1:6379/0
CB_NATS_URL=nats://127.0.0.1:4222

CB_PORT=80
CB_SSL_PORT=443
CB_HEALTHCHECK_PORT=80
EOF

  chmod 600 "$CONFIG_ENV"
  chown "$CB_USER":"$CB_USER" "$CONFIG_ENV"
  ok "Config generated at ${CONFIG_ENV}"
fi

# Source config for remaining steps
set -a
# shellcheck disable=SC1090
source "$CONFIG_ENV"
set +a

# ═════════════════════════════════════════════════════════════════════════════
#  Step 12: Run vault-init
# ═════════════════════════════════════════════════════════════════════════════
step "Initializing vault key"

VAULT_SCRIPT="${CB_APP_ROOT}/deploy/common/30-vault-init.sh"
if [ -f "$VAULT_SCRIPT" ]; then
  export CB_DATA_DIR CB_VAULT_KEY
  bash "$VAULT_SCRIPT"
  ok "Vault key initialized"
else
  warn "Vault init script not found at ${VAULT_SCRIPT} — skipping"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 13: Install systemd units
# ═════════════════════════════════════════════════════════════════════════════
step "Installing systemd service units"

SYSTEMD_SRC="${CB_APP_ROOT}/deploy/native/systemd"
SYSTEMD_DST="/etc/systemd/system"

if [ -d "$SYSTEMD_SRC" ]; then
  for unit in "$SYSTEMD_SRC"/*; do
    cp "$unit" "$SYSTEMD_DST/"
    info "Installed $(basename "$unit")"
  done
  ok "Systemd units installed"
else
  die "Systemd unit directory not found at ${SYSTEMD_SRC}"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 14: Configure nginx
# ═════════════════════════════════════════════════════════════════════════════
step "Configuring nginx"

NGINX_TEMPLATE="${CB_APP_ROOT}/config/nginx/circuitbreaker.conf"
NGINX_DEST="${CB_CONFIG_DIR}/nginx.conf"

if [ -f "$NGINX_TEMPLATE" ]; then
  # Export variables needed by the template
  export CB_PORT="${CB_PORT:-80}"
  export CB_SSL_PORT="${CB_SSL_PORT:-443}"
  export CB_DATA_DIR CB_APP_ROOT

  envsubst '${CB_PORT} ${CB_SSL_PORT} ${CB_DATA_DIR} ${CB_APP_ROOT}' \
    < "$NGINX_TEMPLATE" \
    > "$NGINX_DEST"

  # Disable default nginx site if present
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

  ok "Nginx configured at ${NGINX_DEST}"
else
  warn "Nginx template not found at ${NGINX_TEMPLATE} — skipping"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 15: Configure pgbouncer
# ═════════════════════════════════════════════════════════════════════════════
step "Configuring pgbouncer"

PGB_TEMPLATE="${CB_APP_ROOT}/config/pgbouncer/pgbouncer.ini.template"
PGB_DEST="${CB_CONFIG_DIR}/pgbouncer.ini"

if [ -f "$PGB_TEMPLATE" ]; then
  export CB_DB_NAME="${CB_DB_NAME:-circuitbreaker}"

  envsubst '${CB_DB_NAME} ${CB_DATA_DIR}' \
    < "$PGB_TEMPLATE" \
    > "$PGB_DEST"

  chown "$CB_USER":"$CB_USER" "$PGB_DEST"
  ok "PgBouncer configured at ${PGB_DEST}"
else
  warn "PgBouncer template not found at ${PGB_TEMPLATE} — skipping"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 16: Initialize PostgreSQL
# ═════════════════════════════════════════════════════════════════════════════
step "Initializing PostgreSQL"

# Find the correct pg binaries
PG_BIN=""
for pg_dir in /usr/lib/postgresql/*/bin /usr/pgsql-*/bin; do
  if [ -x "${pg_dir}/initdb" ]; then
    PG_BIN="$pg_dir"
    break
  fi
done

if [ -z "$PG_BIN" ] && command -v initdb &>/dev/null; then
  PG_BIN="$(dirname "$(command -v initdb)")"
fi

if [ -z "$PG_BIN" ]; then
  die "Cannot find PostgreSQL binaries (initdb). Is postgresql installed?"
fi

info "Using PostgreSQL binaries from ${PG_BIN}"

PGDATA="${CB_DATA_DIR}/pgdata"

if [ -f "${PGDATA}/PG_VERSION" ]; then
  ok "PostgreSQL cluster already initialized at ${PGDATA}"
else
  info "Initializing PostgreSQL cluster..."

  # Create password file
  PG_PWFILE=$(mktemp)
  echo "${CB_DB_PASSWORD}" > "$PG_PWFILE"
  chmod 600 "$PG_PWFILE"
  chown "$CB_USER":"$CB_USER" "$PG_PWFILE"

  sudo -u "$CB_USER" "${PG_BIN}/initdb" \
    -D "$PGDATA" \
    --auth=md5 \
    --username="$CB_USER" \
    --pwfile="$PG_PWFILE" \
    --encoding=UTF8 \
    --locale=C \
    2>&1 | tail -3

  rm -f "$PG_PWFILE"

  # Configure postgresql.conf for socket directory
  cat >> "${PGDATA}/postgresql.conf" <<PGCONF

# Circuit Breaker overrides
listen_addresses = '127.0.0.1'
port = 5432
unix_socket_directories = '${CB_DATA_DIR}/run/postgresql'
log_directory = '${CB_LOG_DIR}'
log_filename = 'postgresql-%Y-%m-%d.log'
logging_collector = on
max_connections = 100
shared_buffers = 128MB
PGCONF

  # Configure pg_hba.conf
  cat > "${PGDATA}/pg_hba.conf" <<PGHBA
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             ${CB_USER}                              trust
host    all             ${CB_USER}      127.0.0.1/32            md5
host    all             ${CB_USER}      ::1/128                 md5
PGHBA

  chown -R "$CB_USER":"$CB_USER" "$PGDATA"
  ok "PostgreSQL cluster initialized"
fi

# Start Postgres temporarily to create the database
info "Starting PostgreSQL temporarily..."
sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" \
  -D "$PGDATA" \
  -l "${CB_LOG_DIR}/pg-init.log" \
  -o "-k ${CB_DATA_DIR}/run/postgresql" \
  start -w

# Wait for ready
TRIES=0
until sudo -u "$CB_USER" "${PG_BIN}/pg_isready" -h "${CB_DATA_DIR}/run/postgresql" -q 2>/dev/null; do
  TRIES=$((TRIES + 1))
  [ $TRIES -ge 15 ] && die "PostgreSQL failed to start. Check ${CB_LOG_DIR}/pg-init.log"
  sleep 1
done

# Create database if it doesn't exist
if sudo -u "$CB_USER" "${PG_BIN}/psql" -h "${CB_DATA_DIR}/run/postgresql" \
  -tc "SELECT 1 FROM pg_database WHERE datname='circuitbreaker'" | grep -q 1; then
  ok "Database 'circuitbreaker' already exists"
else
  sudo -u "$CB_USER" "${PG_BIN}/psql" -h "${CB_DATA_DIR}/run/postgresql" \
    -c "CREATE DATABASE circuitbreaker OWNER ${CB_USER};"
  ok "Database 'circuitbreaker' created"
fi

# Stop temp Postgres — systemd will manage it from now on
sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" -D "$PGDATA" stop -w
ok "PostgreSQL initialized and configured"

# ═════════════════════════════════════════════════════════════════════════════
#  Step 17: Run database migrations
# ═════════════════════════════════════════════════════════════════════════════
step "Running database migrations"

MIGRATE_SCRIPT="${CB_APP_ROOT}/deploy/common/20-migrate.sh"
if [ -f "$MIGRATE_SCRIPT" ]; then
  # Start Postgres again for migrations
  sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" \
    -D "$PGDATA" \
    -l "${CB_LOG_DIR}/pg-migrate.log" \
    -o "-k ${CB_DATA_DIR}/run/postgresql" \
    start -w

  TRIES=0
  until sudo -u "$CB_USER" "${PG_BIN}/pg_isready" -h "${CB_DATA_DIR}/run/postgresql" -q 2>/dev/null; do
    TRIES=$((TRIES + 1))
    [ $TRIES -ge 15 ] && die "PostgreSQL failed to start for migrations."
    sleep 1
  done

  export CB_DEPLOY_MODE=native
  export CB_DATA_DIR CB_APP_ROOT CB_DB_PASSWORD
  export APP_ROOT="$CB_APP_ROOT"
  export DATA_DIR="$CB_DATA_DIR"

  bash "$MIGRATE_SCRIPT" || warn "Migration script returned non-zero — check logs"

  sudo -u "$CB_USER" "${PG_BIN}/pg_ctl" -D "$PGDATA" stop -w
  ok "Migrations complete"
else
  warn "Migration script not found at ${MIGRATE_SCRIPT} — skipping"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  Step 18: Enable and start services
# ═════════════════════════════════════════════════════════════════════════════
step "Enabling and starting services"

# Disable system-level services that would conflict
systemctl disable --now postgresql pgbouncer redis-server nginx 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now circuitbreaker.target
ok "Services enabled and started"

# ── Healthcheck ──────────────────────────────────────────────────────────────
info "Waiting for Circuit Breaker to become healthy..."
sleep 3

TRIES=0
HEALTHY=false
until curl -sf "http://localhost:${CB_PORT:-80}/api/v1/health" 2>/dev/null | grep -q '"status"'; do
  TRIES=$((TRIES + 1))
  if [ $TRIES -ge 30 ]; then
    break
  fi
  sleep 2
done

if curl -sf "http://localhost:${CB_PORT:-80}/api/v1/health" 2>/dev/null | grep -q '"status"'; then
  HEALTHY=true
fi

# ── Get LAN IP ───────────────────────────────────────────────────────────────
LAN_IP=$(ip -4 addr show scope global 2>/dev/null \
  | awk '/inet/{print $2}' | cut -d/ -f1 | head -1 \
  || hostname -I 2>/dev/null | awk '{print $1}' \
  || echo "localhost")

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

if [ "$HEALTHY" = true ]; then
  echo -e "  ${BOLD}${GREEN}Circuit Breaker is running!${RESET}"
else
  echo -e "  ${BOLD}${ORANGE}Circuit Breaker installed but health check did not pass.${RESET}"
  echo -e "  ${DIM}Check logs: journalctl -u circuitbreaker-backend.service${RESET}"
fi

echo
echo -e "  ${BOLD}Open in your browser:${RESET}"
echo -e "    → http://${LAN_IP}"
echo -e "    → http://localhost"
echo
echo -e "  ${BOLD}Manage:${RESET}"
echo -e "    Status:   ${DIM}systemctl status circuitbreaker.target${RESET}"
echo -e "    Logs:     ${DIM}journalctl -u circuitbreaker-backend -f${RESET}"
echo -e "    Stop:     ${DIM}sudo systemctl stop circuitbreaker.target${RESET}"
echo -e "    Start:    ${DIM}sudo systemctl start circuitbreaker.target${RESET}"
echo -e "    Restart:  ${DIM}sudo systemctl restart circuitbreaker.target${RESET}"
echo
echo -e "  ${BOLD}Paths:${RESET}"
echo -e "    App:      ${DIM}${CB_APP_ROOT}${RESET}"
echo -e "    Config:   ${DIM}${CB_CONFIG_DIR}/config.env${RESET}"
echo -e "    Data:     ${DIM}${CB_DATA_DIR}${RESET}"
echo -e "    Logs:     ${DIM}${CB_LOG_DIR}${RESET}"
echo
echo -e "  ${DIM}First launch: the setup wizard will create your admin account.${RESET}"
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
