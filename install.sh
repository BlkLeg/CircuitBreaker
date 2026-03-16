#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Circuit Breaker — Native Installer
# https://github.com/BlkLeg/CircuitBreaker
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

CB_PORT=8088
CB_DATA_DIR=/var/lib/circuitbreaker
CB_BRANCH=main
CB_FQDN="circuitbreaker.lab"
CB_CERT_TYPE="self-signed"
CB_EMAIL=""
UNATTENDED=false
UPGRADE_MODE=false
NO_TLS=false
FORCE_DEPS=false

PKG_MGR=""
OS_ID=""
OS_VERSION=""
ARCH=""
LOG_FILE=""
PG_BIN_DIR=""

# =============================================================================
# UI FUNCTIONS
# =============================================================================

cb_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "installing"
}

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║              $(cb_version)                     ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${RESET}"
}

cb_step() {
  echo -e "  ${CYAN}▸${RESET} $1..."
}

cb_ok() {
  echo -e "  ${GREEN}✓${RESET}  $1"
}

cb_warn() {
  echo -e "  ${YELLOW}⚠${RESET}  $1"
}

cb_fail() {
  echo -e "\n  ${RED}✗  ERROR: $1${RESET}"
  echo -e "  ${YELLOW}→  $2${RESET}\n"
  exit 1
}

cb_section() {
  echo -e "\n  ${BOLD}$1${RESET}"
  echo "  $(printf '─%.0s' {1..44})"
}

log() {
  echo "$*" >> "$LOG_FILE" 2>&1
}

run() {
  "$@" >> "$LOG_FILE" 2>&1
}

# =============================================================================
# CLI ARGUMENT PARSING
# =============================================================================

show_help() {
  echo "Circuit Breaker Native Installer"
  echo ""
  echo "Usage: bash install.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --port <num>         HTTP port (default: 8088)"
  echo "  --fqdn <domain>      Fully qualified domain name (optional)"
  echo "  --cert-type <type>   self-signed or letsencrypt (default: self-signed)"
  echo "  --email <email>      Email for Let's Encrypt (required with letsencrypt)"
  echo "  --data-dir <path>    Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls             Skip TLS (HTTP only)"
  echo "  --branch <name>      Git branch to install from (default: main)"
  echo "  --unattended         Skip all prompts, use defaults"
  echo "  --upgrade            Force upgrade mode"
  echo "  --force-deps         Reinstall all dependencies in upgrade mode"
  echo "  --help               Show this help"
  echo ""
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --port)       CB_PORT="$2";      shift 2 ;;
    --fqdn)       CB_FQDN="$2";      shift 2 ;;
    --cert-type)  CB_CERT_TYPE="$2"; shift 2 ;;
    --email)      CB_EMAIL="$2";     shift 2 ;;
    --data-dir)   CB_DATA_DIR="$2";  shift 2 ;;
    --no-tls)     NO_TLS=true;       shift   ;;
    --branch)     CB_BRANCH="$2";    shift 2 ;;
    --unattended) UNATTENDED=true;   shift   ;;
    --upgrade)    UPGRADE_MODE=true; shift   ;;
    --force-deps) FORCE_DEPS=true;   shift   ;;
    --help)       show_help          ;;
    *) echo "Unknown option: $1"; echo "Run with --help for usage."; exit 1 ;;
  esac
done

# =============================================================================
# STAGE 0: PRE-FLIGHT
# =============================================================================

stage0_preflight() {
  cb_header
  cb_section "Pre-flight Checks"

  cb_step "Checking root privileges"
  [[ $EUID -ne 0 ]] && cb_fail "Must run as root" "sudo bash install.sh"
  cb_ok "Running as root"

  cb_step "Detecting operating system"
  [[ ! -f /etc/os-release ]] && cb_fail "Cannot detect OS" "/etc/os-release not found"
  source /etc/os-release
  OS_ID="$ID"
  OS_VERSION="${VERSION_ID:-unknown}"

  case "$OS_ID" in
    ubuntu)
      PKG_MGR="apt-get"
      case "$OS_VERSION" in
        22.04|24.04) cb_ok "Ubuntu $OS_VERSION detected" ;;
        *) cb_fail "Unsupported Ubuntu version: $OS_VERSION" "Supported: 22.04, 24.04" ;;
      esac
      ;;
    debian)
      PKG_MGR="apt-get"
      case "$OS_VERSION" in
        11|12) cb_ok "Debian $OS_VERSION detected" ;;
        *) cb_fail "Unsupported Debian version: $OS_VERSION" "Supported: 11, 12" ;;
      esac
      ;;
    fedora)
      PKG_MGR="dnf"
      case "$OS_VERSION" in
        39|40|41) cb_ok "Fedora $OS_VERSION detected" ;;
        *) cb_fail "Unsupported Fedora version: $OS_VERSION" "Supported: 39, 40, 41" ;;
      esac
      ;;
    rhel|rocky|almalinux)
      PKG_MGR="dnf"
      case "$OS_VERSION" in
        9|9.*) cb_ok "$OS_ID $OS_VERSION detected" ;;
        *) cb_fail "Unsupported $OS_ID version: $OS_VERSION" "Supported: 9.x" ;;
      esac
      ;;
    *)
      cb_fail "Unsupported OS: $OS_ID" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux"
      ;;
  esac

  cb_step "Detecting architecture"
  case "$(uname -m)" in
    x86_64)  ARCH="amd64"; cb_ok "Architecture: x86_64 (amd64)" ;;
    aarch64) ARCH="arm64"; cb_ok "Architecture: aarch64 (arm64)" ;;
    armv7l)  ARCH="arm7";  cb_ok "Architecture: armv7l (arm7)" ;;
    *) cb_fail "Unsupported architecture: $(uname -m)" "Supported: x86_64, aarch64, armv7l" ;;
  esac

  cb_step "Checking system resources"
  local free_disk_gb
  free_disk_gb=$(df -BG / | tail -1 | awk '{print $4}' | tr -d G)
  [[ "$free_disk_gb" -lt 3 ]] && \
    cb_fail "Insufficient disk: ${free_disk_gb}GB free" "Need at least 3GB"
  cb_ok "Disk: ${free_disk_gb}GB free"

  local ram_mb
  ram_mb=$(free -m | awk '/^Mem:/{print $2}')
  if [[ "$ram_mb" -lt 1024 ]]; then
    cb_warn "Low RAM: ${ram_mb}MB — performance may be limited"
  else
    cb_ok "RAM: ${ram_mb}MB"
  fi

  cb_step "Checking for existing installation"
  if systemctl is-active circuitbreaker-backend &>/dev/null || \
     [[ -f /etc/circuitbreaker/.env ]]; then
    UPGRADE_MODE=true
    cb_ok "Existing install detected — upgrade mode enabled"
  else
    cb_ok "No existing installation — fresh install"
  fi

  mkdir -p "${CB_DATA_DIR}/logs"
  LOG_FILE="${CB_DATA_DIR}/logs/install.log"
  {
    echo "=== Circuit Breaker Installation Log ==="
    echo "Started:  $(date)"
    echo "OS:       $OS_ID $OS_VERSION"
    echo "Arch:     $ARCH"
    echo "Branch:   $CB_BRANCH"
    echo ""
  } > "$LOG_FILE"

  if [[ "$UNATTENDED" == "false" ]] && [[ "$UPGRADE_MODE" == "false" ]]; then
    cb_section "Configuration"

    echo -e "  ${CYAN}HTTP Port${RESET} (default: ${CB_PORT}): \c"
    read -t 10 -r port_input || port_input=""
    [[ -n "$port_input" ]] && CB_PORT="$port_input"
    cb_ok "HTTP Port: $CB_PORT"

    echo -e "  ${CYAN}Data Directory${RESET} (default: ${CB_DATA_DIR}): \c"
    read -t 10 -r dir_input || dir_input=""
    [[ -n "$dir_input" ]] && CB_DATA_DIR="$dir_input"
    cb_ok "Data Directory: $CB_DATA_DIR"

    echo -e "  ${CYAN}Domain / FQDN${RESET} (optional, Enter to skip): \c"
    read -t 15 -r fqdn_input || fqdn_input=""
    if [[ -n "$fqdn_input" ]]; then
      CB_FQDN="$fqdn_input"
      cb_ok "Domain: $CB_FQDN"

      echo -e "  ${CYAN}TLS Certificate${RESET}"
      echo -e "    1) Self-signed (default)"
      echo -e "    2) Let's Encrypt (port 80 must be internet-accessible)"
      read -t 10 -r -p "  Choice [1-2]: " cert_choice || cert_choice="1"
      if [[ "$cert_choice" == "2" ]]; then
        CB_CERT_TYPE="letsencrypt"
        echo -e "  ${CYAN}Email for Let's Encrypt${RESET} (required): \c"
        read -t 15 -r email_input || email_input=""
        if [[ -z "$email_input" ]]; then
          cb_warn "Email required — falling back to self-signed"
          CB_CERT_TYPE="self-signed"
        else
          CB_EMAIL="$email_input"
          cb_ok "Certificate: Let's Encrypt ($CB_EMAIL)"
        fi
      else
        cb_ok "Certificate: Self-signed"
      fi
    else
      cb_ok "Domain: Not configured (using IP)"
    fi
  fi
}

# =============================================================================
# STAGE 1: USER & DIRECTORY BOOTSTRAP
# =============================================================================

stage1_bootstrap() {
  cb_section "User & Directory Setup"

  cb_step "Creating system user 'breaker'"
  if id breaker &>/dev/null; then
    cb_ok "User 'breaker' already exists"
  else
    run useradd -r -u 999 -s /usr/sbin/nologin -d /nonexistent \
        -c "Circuit Breaker" breaker
    cb_ok "User 'breaker' created (uid 999)"
  fi

  cb_step "Creating directory structure"

  declare -A DIRS=(
    ["/opt/circuitbreaker"]="root:root:755"
    ["/opt/circuitbreaker/apps"]="root:root:755"
    ["/opt/circuitbreaker/apps/backend"]="breaker:breaker:750"
    ["/opt/circuitbreaker/apps/frontend"]="root:root:755"
    ["/opt/circuitbreaker/apps/frontend/dist"]="root:root:755"
    ["/opt/circuitbreaker/scripts"]="root:root:755"
    ["${CB_DATA_DIR}"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/nats"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/uploads"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/tls"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/logs"]="breaker:breaker:777"
    ["${CB_DATA_DIR}/backups"]="breaker:breaker:755"
    ["/etc/circuitbreaker"]="root:breaker:750"
    ["/etc/nats"]="root:root:755"
    ["/etc/pgbouncer"]="root:root:755"
  )

  for dir in "${!DIRS[@]}"; do
    IFS=':' read -r owner group perms <<< "${DIRS[$dir]}"
    mkdir -p "$dir"
    chown "$owner:$group" "$dir"
    chmod "$perms" "$dir"
  done
  cb_ok "Directory structure created"

  cb_step "Generating secrets"
  if [[ -f /etc/circuitbreaker/.env ]]; then
    cb_ok "Secrets already exist — preserving (upgrade safe)"
    # shellcheck disable=SC1091
    source /etc/circuitbreaker/.env
  else
    local jwt_secret db_password redis_pass nats_token vault_key detected_ip

    jwt_secret=$(openssl rand -hex 64)
    vault_key=$(python3 -c "
from base64 import urlsafe_b64encode
import os
key = urlsafe_b64encode(os.urandom(32))
print(key.decode())
" 2>/dev/null || openssl rand -base64 32 | tr '/+' '_-' | tr -d '=')
    db_password=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    redis_pass=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    nats_token=$(openssl rand -base64 48 | tr -d '/+=')
    detected_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")

    cat > /etc/circuitbreaker/.env <<EOF
# ── Circuit Breaker Environment ──────────────────────────────────────────────
# Auto-generated by install.sh on $(date)
# DO NOT edit secrets manually. DO NOT commit this file.

# Secrets
CB_JWT_SECRET=${jwt_secret}
CB_VAULT_KEY=${vault_key}
CB_DB_PASSWORD=${db_password}
CB_REDIS_PASS=${redis_pass}
NATS_AUTH_TOKEN=${nats_token}

# Database
CB_DB_URL=postgresql://breaker:${db_password}@127.0.0.1:6432/circuitbreaker
CB_DB_POOL_URL=postgresql://breaker:${db_password}@127.0.0.1:6432/circuitbreaker

# Redis
CB_REDIS_URL=redis://:${redis_pass}@127.0.0.1:6379/0

# NATS
NATS_URL=nats://127.0.0.1:4222

# Paths
CB_DATA_DIR=${CB_DATA_DIR}
UPLOADS_DIR=${CB_DATA_DIR}/uploads
STATIC_DIR=/opt/circuitbreaker/apps/frontend/dist
LOG_DIR=${CB_DATA_DIR}/logs

# App
CB_PORT=${CB_PORT}
CB_APP_URL=http://${detected_ip}
CB_AUTH_ENABLED=false
CB_ENV=production
CB_HOST_IP=${detected_ip}
EOF

    chmod 640 /etc/circuitbreaker/.env
    chown root:breaker /etc/circuitbreaker/.env

    # shellcheck disable=SC1091
    source /etc/circuitbreaker/.env
    cb_ok "Secrets generated and stored in /etc/circuitbreaker/.env"
  fi
}

# =============================================================================
# STAGE 2: DEPENDENCIES
# =============================================================================

stage2_dependencies() {
  cb_section "Installing Dependencies"

  if [[ "$PKG_MGR" == "apt-get" ]]; then
    cb_step "Updating package index"
    run apt-get update -qq
    cb_ok "Package index updated"
  fi

  # Group 1 — Base tools
  cb_step "Installing base tools"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    run apt-get install -y -q \
      curl jq openssl netcat-openbsd git wget gnupg2 \
      ca-certificates lsb-release software-properties-common \
      procps lsof
  else
    run dnf install -y -q \
      curl jq openssl nmap-ncat git wget gnupg2 \
      ca-certificates procps lsof
  fi
  cb_ok "Base tools installed"

  # Group 2 — Network/discovery tools
  cb_step "Installing network discovery tools"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    run apt-get install -y -q nmap snmp
    [[ "$ARCH" != "arm7" ]] && run apt-get install -y -q ipmitool || \
      cb_warn "Skipping ipmitool on arm7"
  else
    run dnf install -y -q nmap net-snmp-utils
    [[ "$ARCH" != "arm7" ]] && run dnf install -y -q ipmitool || \
      cb_warn "Skipping ipmitool on arm7"
  fi
  cb_ok "Network discovery tools installed"

  # Group 3 — PostgreSQL 15 from PGDG
  cb_step "Installing PostgreSQL 15 (PGDG)"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc 2>/dev/null \
      | gpg --yes --dearmor \
      -o /usr/share/keyrings/postgresql-archive-keyring.gpg 2>/dev/null
    echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] \
http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list
    run apt-get update -qq
    run apt-get install -y -q postgresql-15 postgresql-client-15
    PG_BIN_DIR="/usr/lib/postgresql/15/bin"
  else
    local pg_rpm="https://download.postgresql.org/pub/repos/yum/reporpms"
    case "$OS_ID" in
      fedora)
        run dnf install -y -q \
          "${pg_rpm}/F-${OS_VERSION}-x86_64/pgdg-fedora-repo-latest.noarch.rpm"
        ;;
      rhel|rocky|almalinux)
        run dnf install -y -q \
          "${pg_rpm}/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm"
        ;;
    esac
    run dnf install -y -q postgresql15-server postgresql15
    PG_BIN_DIR="/usr/pgsql-15/bin"
  fi
  "${PG_BIN_DIR}/pg_ctl" --version 2>/dev/null | grep -q " 15" || \
    cb_fail "PostgreSQL 15 not found" "Check: ${PG_BIN_DIR}/pg_ctl --version"
  cb_ok "PostgreSQL 15 installed (${PG_BIN_DIR})"

  # Group 4 — pgbouncer, Redis
  cb_step "Installing pgbouncer and Redis"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    run apt-get install -y -q pgbouncer redis-server
  else
    run dnf install -y -q pgbouncer redis
  fi
  cb_ok "pgbouncer and Redis installed"

  # Group 5 — Caddy
  cb_step "Installing Caddy"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    run apt-get install -y -q \
      debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      2>/dev/null \
      | gpg --yes --dearmor \
      -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf \
      'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      2>/dev/null \
      > /etc/apt/sources.list.d/caddy-stable.list
    run apt-get update -qq
    run apt-get install -y -q caddy
  else
    run dnf copr enable -y @caddy/caddy || true
    run dnf install -y -q caddy
  fi
  command -v caddy &>/dev/null || \
    cb_fail "Caddy not found after install" "Check: tail -50 $LOG_FILE"
  cb_ok "Caddy $(caddy version 2>/dev/null | head -1) installed"

  # Group 6 — NATS Server binary
  cb_step "Installing NATS Server"
  local nats_version
  nats_version=$(curl -sf \
    https://api.github.com/repos/nats-io/nats-server/releases/latest \
    | jq -r '.tag_name' | tr -d v 2>/dev/null || echo "")
  [[ -z "$nats_version" || "$nats_version" == "null" ]] && \
    cb_fail "Cannot fetch NATS version from GitHub" \
    "Check internet connectivity"

  local nats_archive="nats-server-v${nats_version}-linux-${ARCH}.tar.gz"
  local nats_url="https://github.com/nats-io/nats-server/releases/download/v${nats_version}/${nats_archive}"

  cd /tmp
  run curl -fsSL -o "$nats_archive" "$nats_url" || \
    cb_fail "Failed to download NATS" "$nats_url"
  run tar -xzf "$nats_archive"
  cp "nats-server-v${nats_version}-linux-${ARCH}/nats-server" \
    /usr/local/bin/nats-server
  chmod 755 /usr/local/bin/nats-server
  chown root:root /usr/local/bin/nats-server
  rm -rf "$nats_archive" "nats-server-v${nats_version}-linux-${ARCH}"
  cd - > /dev/null

  /usr/local/bin/nats-server --version &>/dev/null || \
    cb_fail "NATS binary failed verification" \
    "Check: /usr/local/bin/nats-server --version"
  cb_ok "NATS Server ${nats_version} installed"

  # Group 7 — Python 3.12
  cb_step "Installing Python 3.12"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    if [[ "$OS_ID" == "ubuntu" && "$OS_VERSION" == "22.04" ]]; then
      run add-apt-repository -y ppa:deadsnakes/ppa
      run apt-get update -qq
    fi
    run apt-get install -y -q python3.12 python3.12-venv python3.12-dev
  else
    run dnf install -y -q python3.12 python3.12-devel
  fi
  python3.12 --version &>/dev/null || \
    cb_fail "Python 3.12 not found" "Check: python3.12 --version"
  cb_ok "Python $(python3.12 --version 2>&1) installed"

  # Group 8 — Node 20 LTS (frontend build only)
  cb_step "Installing Node.js 20 LTS"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x \
      2>/dev/null | bash - >> "$LOG_FILE" 2>&1
    run apt-get install -y -q nodejs
  else
    curl -fsSL https://rpm.nodesource.com/setup_20.x \
      2>/dev/null | bash - >> "$LOG_FILE" 2>&1
    run dnf install -y -q nodejs
  fi
  node --version 2>/dev/null | grep -q "^v20" || \
    cb_fail "Node 20 not found" "Check: node --version"
  cb_ok "Node.js $(node --version) installed"
}

# =============================================================================
# STAGE 3: SERVICE CONFIGURATION
# =============================================================================

stage3_configure_postgres() {
  cb_section "Configuring PostgreSQL 15"

  cb_step "Stopping any existing PostgreSQL processes"
  systemctl stop postgresql 2>/dev/null || true
  systemctl stop circuitbreaker-postgres 2>/dev/null || true
  "${PG_BIN_DIR}/pg_ctl" stop -D "${CB_DATA_DIR}/postgres" 2>/dev/null || true
  pkill -9 postgres 2>/dev/null || true
  sleep 2
  cb_ok "Existing processes cleared"

  cb_step "Preparing PostgreSQL data directory"
  mkdir -p "${CB_DATA_DIR}/postgres"
  chown postgres:postgres "${CB_DATA_DIR}/postgres"
  chmod 700 "${CB_DATA_DIR}/postgres"
  cb_ok "Data directory: ${CB_DATA_DIR}/postgres (postgres:postgres 700)"

  if [[ ! -f "${CB_DATA_DIR}/postgres/PG_VERSION" ]]; then
    cb_step "Initializing database cluster"
    if ! su -s /bin/sh postgres -c \
        "${PG_BIN_DIR}/initdb -D ${CB_DATA_DIR}/postgres \
         --auth-local=peer --auth-host=md5 -U postgres" \
        >> "$LOG_FILE" 2>&1; then
      cb_fail "PostgreSQL initdb failed" "Check: tail -50 $LOG_FILE"
    fi
    cb_ok "Database cluster initialized"
  else
    cb_ok "Database cluster already initialized"
  fi

  cb_step "Writing PostgreSQL configuration"
  cat >> "${CB_DATA_DIR}/postgres/postgresql.conf" <<PGCONF

# Circuit Breaker settings
listen_addresses = 'localhost'
port = 5432
max_connections = 50
logging_collector = on
log_directory = '${CB_DATA_DIR}/logs'
log_filename = 'postgresql.log'
log_min_messages = warning
PGCONF

  cat > "${CB_DATA_DIR}/postgres/pg_hba.conf" <<PGHBA
# Circuit Breaker pg_hba.conf
local   all             postgres                                peer
local   circuitbreaker  breaker                                 md5
host    circuitbreaker  breaker         127.0.0.1/32            md5
host    all             all             127.0.0.1/32            reject
PGHBA

  chown postgres:postgres "${CB_DATA_DIR}/postgres/pg_hba.conf"
  cb_ok "PostgreSQL configuration written"

  cb_step "Starting PostgreSQL"
  systemctl start circuitbreaker-postgres >> "$LOG_FILE" 2>&1 || \
    cb_fail "PostgreSQL failed to start" \
    "Check: journalctl -u circuitbreaker-postgres -n 50"
  sleep 3
  nc -z 127.0.0.1 5432 2>/dev/null || \
    cb_fail "PostgreSQL not listening on 5432" \
    "Check: journalctl -u circuitbreaker-postgres -n 50"
  cb_ok "PostgreSQL started"

  cb_step "Creating database user and database"
  su -s /bin/sh postgres -c \
    "psql -c \"CREATE USER breaker WITH PASSWORD '${CB_DB_PASSWORD}';\"" \
    >> "$LOG_FILE" 2>&1 || true
  su -s /bin/sh postgres -c \
    "psql -c \"CREATE DATABASE circuitbreaker OWNER breaker;\"" \
    >> "$LOG_FILE" 2>&1 || true
  su -s /bin/sh postgres -c \
    "psql -c \"GRANT ALL PRIVILEGES ON DATABASE circuitbreaker TO breaker;\"" \
    >> "$LOG_FILE" 2>&1 || true
  cb_ok "Database 'circuitbreaker' and user 'breaker' ready"

  cb_step "Verifying direct PostgreSQL connection"
  PGPASSWORD="$CB_DB_PASSWORD" psql \
    -h 127.0.0.1 -p 5432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null || \
    cb_fail "PostgreSQL direct connection failed" \
    "Check: journalctl -u circuitbreaker-postgres -n 50"
  cb_ok "Direct PostgreSQL connection verified"
}

stage3_configure_pgbouncer() {
  cb_section "Configuring pgbouncer"

  cb_step "Stopping any existing pgbouncer"
  systemctl stop circuitbreaker-pgbouncer 2>/dev/null || true
  pkill -9 pgbouncer 2>/dev/null || true
  sleep 1
  cb_ok "Cleared existing pgbouncer"

  cb_step "Configuring pgbouncer connection pooler"
  # CRITICAL: format is md5(password + username) — not md5(password)
  local pgbouncer_hash
  pgbouncer_hash=$(echo -n "${CB_DB_PASSWORD}breaker" | md5sum | cut -d' ' -f1)

  mkdir -p /etc/pgbouncer

  cat > /etc/pgbouncer/userlist.txt <<EOF
"breaker" "md5${pgbouncer_hash}"
EOF

  cat > /etc/pgbouncer/pgbouncer.ini <<EOF
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
EOF

  chown postgres:postgres /etc/pgbouncer/userlist.txt
  chown postgres:postgres /etc/pgbouncer/pgbouncer.ini
  chmod 640 /etc/pgbouncer/userlist.txt
  chmod 640 /etc/pgbouncer/pgbouncer.ini
  mkdir -p /run/pgbouncer
  chown postgres:postgres /run/pgbouncer
  cb_ok "pgbouncer configuration written"

  cb_step "Starting pgbouncer"
  systemctl start circuitbreaker-pgbouncer >> "$LOG_FILE" 2>&1 || \
    cb_fail "pgbouncer failed to start" \
    "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  sleep 2
  nc -z 127.0.0.1 6432 2>/dev/null || \
    cb_fail "pgbouncer not listening on 6432" \
    "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  cb_ok "pgbouncer started"

  cb_step "Verifying pgbouncer connection"
  PGPASSWORD="$CB_DB_PASSWORD" psql \
    -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' \
    >> "$LOG_FILE" 2>&1 || \
    cb_fail "pgbouncer connection failed — check userlist.txt hash" \
    "Run: cb doctor"
  cb_ok "pgbouncer connection verified (pool: 127.0.0.1:6432)"
}

stage3_configure_redis() {
  cb_section "Configuring Redis"

  cb_step "Stopping any existing Redis"
  systemctl stop redis 2>/dev/null || true
  systemctl stop redis-server 2>/dev/null || true
  systemctl stop circuitbreaker-redis 2>/dev/null || true
  pkill -9 redis-server 2>/dev/null || true
  sleep 1
  cb_ok "Cleared existing Redis"

  local redis_user="redis"
  id redis &>/dev/null || redis_user="root"

  mkdir -p "${CB_DATA_DIR}/redis"
  chown "${redis_user}:${redis_user}" "${CB_DATA_DIR}/redis" 2>/dev/null || true
  chmod 755 "${CB_DATA_DIR}/redis"

  cb_step "Writing Redis configuration"
  cat > /etc/redis/redis.conf <<EOF
bind 127.0.0.1
port 6379
requirepass ${CB_REDIS_PASS}
maxmemory 256mb
maxmemory-policy allkeys-lru
dir ${CB_DATA_DIR}/redis
save ""
loglevel warning
EOF

  chown "${redis_user}:${redis_user}" /etc/redis/redis.conf 2>/dev/null || true
  chmod 640 /etc/redis/redis.conf
  cb_ok "Redis configuration written"

  cb_step "Starting Redis"
  systemctl start circuitbreaker-redis >> "$LOG_FILE" 2>&1 || \
    cb_fail "Redis failed to start" \
    "Check: journalctl -u circuitbreaker-redis -n 50"
  sleep 2
  nc -z 127.0.0.1 6379 2>/dev/null || \
    cb_fail "Redis not listening on 6379" \
    "Check: journalctl -u circuitbreaker-redis -n 50"

  cb_step "Verifying Redis connection"
  redis-cli -a "$CB_REDIS_PASS" PING 2>/dev/null | grep -q PONG || \
    cb_fail "Redis not responding to PING" \
    "Check: journalctl -u circuitbreaker-redis -n 50"
  cb_ok "Redis verified (PONG received)"
}

stage3_configure_nats() {
  cb_section "Configuring NATS JetStream"

  cb_step "Stopping any existing NATS"
  systemctl stop circuitbreaker-nats 2>/dev/null || true
  pkill -9 nats-server 2>/dev/null || true
  sleep 1
  cb_ok "Cleared existing NATS"

  cb_step "Writing NATS configuration"
  cat > /etc/nats/nats.conf <<EOF
port: 4222
monitor_port: 8222

authorization {
  token: "${NATS_AUTH_TOKEN}"
}

jetstream {
  store_dir: "${CB_DATA_DIR}/nats"
  max_memory_store: 256MB
  max_file_store: 1GB
}
EOF
  chmod 644 /etc/nats/nats.conf
  cb_ok "NATS configuration written"

  cb_step "Starting NATS"
  systemctl start circuitbreaker-nats >> "$LOG_FILE" 2>&1 || \
    cb_fail "NATS failed to start" \
    "Check: journalctl -u circuitbreaker-nats -n 50"
  sleep 2
  nc -z 127.0.0.1 4222 2>/dev/null || \
    cb_fail "NATS not listening on 4222" \
    "Check: journalctl -u circuitbreaker-nats -n 50"
  cb_ok "NATS started (JetStream enabled)"
}

ensure_hosts_entry() {
  local fqdn="${CB_FQDN:-}"
  [[ -z "$fqdn" ]] && return 0
  if grep -qF "$fqdn" /etc/hosts 2>/dev/null; then
    cb_ok "/etc/hosts entry for $fqdn already present"
    return 0
  fi
  cb_step "Adding $fqdn to /etc/hosts"
  echo "127.0.0.1 $fqdn" >> /etc/hosts
  cb_ok "$fqdn → 127.0.0.1 added to /etc/hosts"
}

stage3_configure_caddy() {
  cb_section "Configuring Caddy"

  local tls_line=""
  local site_address

  if [[ "$NO_TLS" == "false" ]]; then
    if [[ "$CB_CERT_TYPE" == "letsencrypt" && \
          -n "$CB_FQDN" && -n "$CB_EMAIL" ]]; then
      cb_step "Validating Let's Encrypt prerequisites"
      local fqdn_ip server_ip
      fqdn_ip=$(dig +short "$CB_FQDN" 2>/dev/null | tail -n1 || echo "")
      server_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+')

      if [[ -z "$fqdn_ip" ]]; then
        cb_warn "DNS lookup failed for $CB_FQDN — falling back to self-signed"
        CB_CERT_TYPE="self-signed"
      elif [[ "$fqdn_ip" != "$server_ip" ]]; then
        cb_warn "DNS mismatch: $CB_FQDN → $fqdn_ip, server is $server_ip"
        cb_warn "Falling back to self-signed"
        CB_CERT_TYPE="self-signed"
      else
        cb_ok "DNS validated — Caddy will manage Let's Encrypt automatically"
        tls_line="tls ${CB_EMAIL}"
      fi
    fi

    if [[ "$CB_CERT_TYPE" == "self-signed" ]]; then
      cb_step "Generating self-signed TLS certificate (4096-bit, 10yr)"
      local cert_cn="${CB_FQDN:-circuitbreaker}"
      openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
        -keyout "${CB_DATA_DIR}/tls/privkey.pem" \
        -out    "${CB_DATA_DIR}/tls/fullchain.pem" \
        -subj   "/CN=${cert_cn}/O=CircuitBreaker" >> "$LOG_FILE" 2>&1
      chown breaker:breaker "${CB_DATA_DIR}/tls"/*.pem
      chmod 640 "${CB_DATA_DIR}/tls"/*.pem
      tls_line="tls ${CB_DATA_DIR}/tls/fullchain.pem ${CB_DATA_DIR}/tls/privkey.pem"
      cb_ok "Self-signed certificate generated"
    fi

    site_address="${CB_FQDN:-circuitbreaker.lab}"
  else
    site_address="http://:${CB_PORT}"
  fi

  cb_step "Writing Caddyfile"
  mkdir -p /etc/caddy
  cat > /etc/caddy/Caddyfile <<EOF
{
  admin off
  log {
    output file ${CB_DATA_DIR}/logs/caddy.log
    level  WARN
  }
}

${site_address} {
  ${tls_line}

  root * /opt/circuitbreaker/apps/frontend/dist
  encode gzip

  handle /api/* {
    reverse_proxy 127.0.0.1:8000 {
      header_up Host {host}
      header_up X-Real-IP {remote_host}
    }
  }

  handle /ws/* {
    reverse_proxy 127.0.0.1:8000 {
      header_up Host {host}
      header_up Upgrade {>Upgrade}
      header_up Connection {>Connection}
    }
  }

  handle {
    try_files {path} /index.html
    file_server
  }
}
EOF
  chmod 644 /etc/caddy/Caddyfile

  caddy validate --config /etc/caddy/Caddyfile >> "$LOG_FILE" 2>&1 || \
    cb_fail "Caddyfile is invalid" \
    "Check: caddy validate --config /etc/caddy/Caddyfile"
  cb_ok "Caddyfile validated"

  ensure_hosts_entry
  cb_ok "Caddy configured (starts after frontend build)"
}

# =============================================================================
# WAIT-FOR-SERVICES SCRIPT
# =============================================================================

write_wait_for_services() {
  cb_section "Creating Service Health Check Script"
  cb_step "Writing wait-for-services.sh"

  mkdir -p /opt/circuitbreaker/scripts

  cat > /opt/circuitbreaker/scripts/wait-for-services.sh <<'WAIT'
#!/usr/bin/env bash
set -euo pipefail

set -a
# shellcheck disable=SC1091
source /etc/circuitbreaker/.env
set +a

MAX_WAIT=60
INTERVAL=2

wait_port() {
  local name=$1 host=$2 port=$3 elapsed=0
  while ! nc -z "$host" "$port" 2>/dev/null; do
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      echo "FATAL: $name did not start within ${MAX_WAIT}s" >&2
      echo "Run: cb doctor" >&2
      exit 1
    fi
  done
  echo "$name ready (${elapsed}s)"
}

wait_port "pgbouncer" 127.0.0.1 6432
wait_port "redis"     127.0.0.1 6379
wait_port "nats"      127.0.0.1 4222

# Verify actual DB connection, not just port open
PGPASSWORD="$CB_DB_PASSWORD" psql \
  -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null || {
  echo "FATAL: Cannot connect to DB through pgbouncer" >&2
  echo "Run: cb doctor" >&2
  exit 1
}

echo "All services ready."
WAIT

  chmod 755 /opt/circuitbreaker/scripts/wait-for-services.sh
  chown root:root /opt/circuitbreaker/scripts/wait-for-services.sh
  cb_ok "wait-for-services.sh created"
}

# =============================================================================
# STAGE 4: SYSTEMD UNITS
# =============================================================================

stage4_write_systemd_units() {
  cb_section "Writing systemd Service Units"
  cb_step "Writing all unit files"

  # ── circuitbreaker-postgres.service ───────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-postgres.service <<EOF
[Unit]
Description=Circuit Breaker PostgreSQL 15
After=network.target
Before=circuitbreaker-pgbouncer.service

[Service]
Type=notify
User=postgres
Group=postgres
Environment=PGDATA=${CB_DATA_DIR}/postgres
ExecStart=${PG_BIN_DIR}/postgres -D ${CB_DATA_DIR}/postgres
ExecReload=/bin/kill -HUP \$MAINPID
KillMode=mixed
KillSignal=SIGINT
TimeoutSec=120
Restart=on-failure
RestartSec=5s
StartLimitBurst=3
StartLimitIntervalSec=60s
NoNewPrivileges=yes
ReadWritePaths=${CB_DATA_DIR}/postgres
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-postgres

[Install]
WantedBy=multi-user.target
EOF

  # ── circuitbreaker-pgbouncer.service ──────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-pgbouncer.service <<EOF
[Unit]
Description=Circuit Breaker pgbouncer
After=circuitbreaker-postgres.service
Requires=circuitbreaker-postgres.service

[Service]
Type=forking
User=postgres
ExecStart=/usr/sbin/pgbouncer -d /etc/pgbouncer/pgbouncer.ini
ExecReload=/bin/kill -HUP \$MAINPID
PIDFile=/run/pgbouncer/pgbouncer.pid
RuntimeDirectory=pgbouncer
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
ReadWritePaths=${CB_DATA_DIR}/logs
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-pgbouncer

[Install]
WantedBy=multi-user.target
EOF

  # ── circuitbreaker-redis.service ──────────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-redis.service <<EOF
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
MemoryMax=384M
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-redis

[Install]
WantedBy=multi-user.target
EOF

  # ── circuitbreaker-nats.service ───────────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-nats.service <<EOF
[Unit]
Description=Circuit Breaker NATS JetStream
After=network.target

[Service]
Type=simple
User=breaker
Group=breaker
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
EOF

  # ── circuitbreaker-backend.service ────────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-backend.service <<EOF
[Unit]
Description=Circuit Breaker Backend API
After=circuitbreaker-pgbouncer.service circuitbreaker-redis.service circuitbreaker-nats.service
Requires=circuitbreaker-pgbouncer.service circuitbreaker-redis.service circuitbreaker-nats.service

[Service]
Type=exec
User=breaker
Group=breaker
WorkingDirectory=/opt/circuitbreaker/apps/backend
EnvironmentFile=/etc/circuitbreaker/.env
ExecStartPre=/opt/circuitbreaker/scripts/wait-for-services.sh
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/uvicorn app.main:app \\
  --host 127.0.0.1 \\
  --port 8000 \\
  --workers 2 \\
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
EOF

  # ── circuitbreaker-worker@.service (template) ─────────────────────────────
  cat > /etc/systemd/system/circuitbreaker-worker@.service <<EOF
[Unit]
Description=Circuit Breaker Worker (%i)
After=circuitbreaker-backend.service
Requires=circuitbreaker-backend.service

[Service]
Type=simple
User=breaker
Group=breaker
WorkingDirectory=/opt/circuitbreaker/apps/backend
EnvironmentFile=/etc/circuitbreaker/.env
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/python \\
  -m app.workers.main --type %i
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
EOF

  # ── circuitbreaker.target ──────────────────────────────────────────────────
  cat > /etc/systemd/system/circuitbreaker.target <<EOF
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
EOF

  systemctl daemon-reload
  systemctl enable circuitbreaker.target \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" \
    "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" \
    "circuitbreaker-worker@telemetry" \
    >> "$LOG_FILE" 2>&1

  cb_ok "All systemd units written and enabled"
}

# =============================================================================
# STAGE 5: CODE DEPLOYMENT
# =============================================================================

stage5_deploy_code() {
  cb_section "Deploying Application Code"

  if [[ -d /opt/circuitbreaker/.git ]]; then
    cb_step "Updating existing repository (branch: ${CB_BRANCH})"
    run git -C /opt/circuitbreaker fetch origin
    run git -C /opt/circuitbreaker checkout "$CB_BRANCH"
    run git -C /opt/circuitbreaker pull origin "$CB_BRANCH"
    cb_ok "Repository updated"
  else
    if [[ -d /opt/circuitbreaker ]] && \
       [[ ! -d /opt/circuitbreaker/.git ]]; then
      cb_step "Removing incomplete install directory"
      rm -rf /opt/circuitbreaker/apps /opt/circuitbreaker/scripts
      cb_ok "Cleaned up"
    fi

    cb_step "Cloning repository (branch: ${CB_BRANCH})"
    git clone --branch "$CB_BRANCH" --depth 1 \
      https://github.com/BlkLeg/CircuitBreaker.git \
      /opt/circuitbreaker >> "$LOG_FILE" 2>&1 || \
      cb_fail "Git clone failed" "Check: tail -50 $LOG_FILE"
    cb_ok "Repository cloned to /opt/circuitbreaker"
  fi

  chown -R breaker:breaker /opt/circuitbreaker/apps/backend
  chown -R root:root /opt/circuitbreaker/apps/frontend
  cb_ok "Ownership set correctly"
}

# =============================================================================
# STAGE 6: PYTHON VENV SETUP & MIGRATIONS
# =============================================================================

stage6_setup_python() {
  cb_section "Python Backend Setup"

  cb_step "Creating Python 3.12 virtual environment"
  python3.12 -m venv /opt/circuitbreaker/apps/backend/venv >> "$LOG_FILE" 2>&1
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend/venv
  cb_ok "venv created at /opt/circuitbreaker/apps/backend/venv"

  cb_step "Installing Python dependencies (~1-2 min)"
  echo "    Step 1/2: requirements.txt..."
  su -s /bin/bash breaker -c "
    /opt/circuitbreaker/apps/backend/venv/bin/pip install \
      --quiet --upgrade pip && \
    /opt/circuitbreaker/apps/backend/venv/bin/pip install \
      --quiet \
      -r /opt/circuitbreaker/apps/backend/requirements.txt
  " >> "$LOG_FILE" 2>&1 || \
    cb_fail "pip install failed (requirements.txt)" \
    "Check: tail -80 $LOG_FILE"

  echo "    Step 2/2: editable install (pyproject.toml)..."
  su -s /bin/bash breaker -c "
    /opt/circuitbreaker/apps/backend/venv/bin/pip install \
      --quiet \
      -e /opt/circuitbreaker/apps/backend/
  " >> "$LOG_FILE" 2>&1 || \
    cb_fail "pip install -e failed (pyproject.toml)" \
    "Check: tail -80 $LOG_FILE"
  cb_ok "Python dependencies installed"

  cb_step "Running database migrations (alembic upgrade head)"
  su -s /bin/bash breaker -c "
    set -a
    source /etc/circuitbreaker/.env
    set +a
    cd /opt/circuitbreaker/apps/backend
    /opt/circuitbreaker/apps/backend/venv/bin/alembic upgrade head
  " >> "$LOG_FILE" 2>&1 || \
    cb_fail "Alembic migrations failed" \
    "Check: tail -80 $LOG_FILE"

  local migration_count
  migration_count=$(PGPASSWORD="$CB_DB_PASSWORD" psql \
    -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -tAc \
    "SELECT COUNT(*) FROM alembic_version" 2>/dev/null || echo "0")

  [[ "$migration_count" -gt 0 ]] || \
    cb_fail "No rows in alembic_version after migration" \
    "Check: tail -80 $LOG_FILE"

  cb_ok "Database schema ready ($migration_count migration(s) applied)"
}

# =============================================================================
# STAGE 7: FRONTEND BUILD
# =============================================================================

stage7_build_frontend() {
  cb_section "Frontend Build (React + Vite)"

  cd /opt/circuitbreaker/apps/frontend

  cb_step "Installing Node dependencies (npm ci)"
  npm ci >> "$LOG_FILE" 2>&1 || \
    cb_fail "npm ci failed" "Check: tail -80 $LOG_FILE"
  cb_ok "Node dependencies installed"

  cb_step "Building frontend bundle (~1-2 min)"
  npm run build >> "$LOG_FILE" 2>&1 || \
    cb_fail "npm run build failed" "Check: tail -80 $LOG_FILE"

  [[ -f /opt/circuitbreaker/apps/frontend/dist/index.html ]] || \
    cb_fail "Build produced no dist/index.html" \
    "Check: tail -80 $LOG_FILE"

  chown -R root:root /opt/circuitbreaker/apps/frontend/dist
  chmod -R 755 /opt/circuitbreaker/apps/frontend/dist

  local dist_size
  dist_size=$(du -sh /opt/circuitbreaker/apps/frontend/dist | cut -f1)
  cb_ok "Frontend built (${dist_size} → dist/)"

  cd - > /dev/null
}

# =============================================================================
# STAGE 8: START EVERYTHING
# =============================================================================

stage8_start_services() {
  cb_section "Starting Application Services"

  cb_step "Starting backend API"
  systemctl start circuitbreaker-backend >> "$LOG_FILE" 2>&1 || \
    cb_fail "Backend failed to start" \
    "Check: journalctl -u circuitbreaker-backend -n 100"

  cb_step "Waiting for backend health endpoint"
  local max_wait=45 elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null \
        | grep -qE '"(status|ok)"'; do
    sleep 2
    elapsed=$((elapsed + 2))
    [[ $elapsed -ge $max_wait ]] && \
      cb_fail "Backend API did not become healthy in ${max_wait}s" \
      "Run: cb doctor"
  done
  cb_ok "Backend API healthy"

  cb_step "Starting background workers"
  systemctl start "circuitbreaker-worker@discovery"    >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@webhook"      >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@notification" >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@telemetry"    >> "$LOG_FILE" 2>&1
  sleep 2
  cb_ok "Workers started (discovery, webhook, notification, telemetry)"

  cb_step "Starting Caddy"
  if systemctl is-active caddy &>/dev/null; then
    systemctl reload caddy >> "$LOG_FILE" 2>&1 || \
      cb_fail "Caddy reload failed" \
      "Run: caddy validate --config /etc/caddy/Caddyfile"
  else
    systemctl start caddy >> "$LOG_FILE" 2>&1 || \
      cb_fail "Caddy failed to start" \
      "Check: journalctl -u caddy -n 50"
  fi
  sleep 1

  local caddy_port=443
  [[ "$NO_TLS" == "true" ]] && caddy_port="$CB_PORT"
  nc -z 127.0.0.1 "$caddy_port" 2>/dev/null || \
    cb_fail "Caddy not listening on port $caddy_port" \
    "Check: journalctl -u caddy -n 50"
  cb_ok "Caddy running on port $caddy_port"

  local detected_ip
  detected_ip=$(ip route get 1.1.1.1 2>/dev/null \
    | grep -oP 'src \K[^ ]+' || echo "localhost")
  grep -q "CB_HOST_IP=" /etc/circuitbreaker/.env 2>/dev/null || \
    echo "CB_HOST_IP=${detected_ip}" >> /etc/circuitbreaker/.env

  cb_ok "All services running"
}

# =============================================================================
# STAGE 9: cb CLI
# =============================================================================

stage9_install_cb_cli() {
  cb_section "Installing Management CLI"
  cb_step "Writing /usr/local/bin/cb"

  cat > /usr/local/bin/cb <<'CBCLI'
#!/usr/bin/env bash
# cb — Circuit Breaker management CLI

[[ -f /etc/circuitbreaker/.env ]] && source /etc/circuitbreaker/.env

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

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
  printf "  %-38s %-10s %s\n" "SERVICE" "STATUS" "SINCE"
  printf "  %-38s %-10s %s\n" \
    "──────────────────────────────────────" "──────────" "──────"
  for svc in "${SERVICES[@]}"; do
    active=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    since=$(systemctl show "$svc" --property=ActiveEnterTimestamp \
      --value 2>/dev/null \
      | xargs -I{} date -d{} "+%H:%M %b %d" 2>/dev/null || echo "—")
    color="$GREEN"; [[ "$active" != "active" ]] && color="$RED"
    printf "  %-38s ${color}%-10s${RESET} %s\n" "$svc" "$active" "$since"
  done
  echo ""
}

cmd_doctor() {
  echo ""
  echo -e "  ${BOLD}Circuit Breaker Health Check${RESET}"
  echo "  ──────────────────────────────────────────"
  FAILED=0

  check() {
    local name=$1 cmd=$2 hint=$3
    if eval "$cmd" &>/dev/null; then
      printf "  ${GREEN}✓${RESET}  %-24s OK\n" "$name"
    else
      printf "  ${RED}✗${RESET}  %-24s FAILED\n" "$name"
      echo "     → $hint"
      FAILED=$((FAILED + 1))
    fi
  }

  check "PostgreSQL (5432)" \
    "nc -z 127.0.0.1 5432" \
    "journalctl -u circuitbreaker-postgres -n 30"
  check "pgbouncer (6432)" \
    "nc -z 127.0.0.1 6432" \
    "journalctl -u circuitbreaker-pgbouncer -n 30"
  check "DB connection" \
    "PGPASSWORD=\"$CB_DB_PASSWORD\" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\\q'" \
    "Check /etc/pgbouncer/userlist.txt hash"
  check "Redis (6379)" \
    "redis-cli -a \"$CB_REDIS_PASS\" PING 2>/dev/null | grep -q PONG" \
    "journalctl -u circuitbreaker-redis -n 30"
  check "NATS (4222)" \
    "nc -z 127.0.0.1 4222" \
    "journalctl -u circuitbreaker-nats -n 30"
  check "Backend API (8000)" \
    "curl -sf http://127.0.0.1:8000/api/v1/health" \
    "journalctl -u circuitbreaker-backend -n 30"
  check "Caddy (443)" \
    "nc -z 127.0.0.1 443 || nc -z 127.0.0.1 80" \
    "caddy validate --config /etc/caddy/Caddyfile && journalctl -u caddy -n 30"

  echo ""
  if [[ $FAILED -eq 0 ]]; then
    echo -e "  ${GREEN}All systems operational.${RESET}"
  else
    echo -e "  ${RED}${FAILED} check(s) failed.${RESET}"
    echo    "  Fix top-down — each service depends on the one above."
  fi
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
    -u caddy
}

cmd_restart() {
  echo "Restarting Circuit Breaker..."
  systemctl stop circuitbreaker.target 2>/dev/null || true
  sleep 2
  systemctl start circuitbreaker.target
  sleep 3
  cmd_status
}

cmd_update() {
  echo "Updating Circuit Breaker..."
  bash <(curl -fsSL \
    https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh) \
    --upgrade
}

cmd_backup() {
  [[ -z "${CB_DATA_DIR:-}" ]] && CB_DATA_DIR="/var/lib/circuitbreaker"
  local ts file
  ts=$(date +%Y%m%d-%H%M%S)
  file="${CB_DATA_DIR}/backups/cb-backup-${ts}.sql"
  mkdir -p "${CB_DATA_DIR}/backups"
  echo "Backing up to $file..."
  PGPASSWORD="$CB_DB_PASSWORD" pg_dump \
    -h 127.0.0.1 -p 6432 -U breaker circuitbreaker > "$file"
  echo "Done: $file ($(du -sh "$file" | cut -f1))"
}

cmd_migrate() {
  echo "Running database migrations..."
  su -s /bin/bash breaker -c "
    set -a; source /etc/circuitbreaker/.env; set +a
    cd /opt/circuitbreaker/apps/backend
    /opt/circuitbreaker/apps/backend/venv/bin/alembic upgrade head
  "
  echo "Done."
}

cmd_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "unknown"
}

cmd_uninstall() {
  echo ""
  echo -e "  ${RED}WARNING: This removes Circuit Breaker and ALL data.${RESET}"
  echo ""
  read -rp "  Type 'yes' to confirm: " confirm
  [[ "$confirm" != "yes" ]] && echo "Cancelled." && exit 0

  echo "Stopping services..."
  systemctl stop \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats \
    circuitbreaker-backend \
    "circuitbreaker-worker@discovery" \
    "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" \
    "circuitbreaker-worker@telemetry" \
    caddy 2>/dev/null || true

  systemctl disable circuitbreaker.target \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats \
    circuitbreaker-backend \
    "circuitbreaker-worker@discovery" \
    "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" \
    "circuitbreaker-worker@telemetry" \
    2>/dev/null || true

  pkill -u breaker 2>/dev/null || true
  sleep 2
  pkill -9 -u breaker 2>/dev/null || true

  rm -f /etc/systemd/system/circuitbreaker-*.service
  rm -f /etc/systemd/system/circuitbreaker.target
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true

  rm -rf /opt/circuitbreaker /etc/circuitbreaker /etc/nats
  rm -rf "${CB_DATA_DIR:-/var/lib/circuitbreaker}"
  rm -f /etc/caddy/Caddyfile
  rm -f /usr/local/bin/nats-server
  rm -f /usr/local/bin/cb
  userdel breaker 2>/dev/null || true

  [[ -n "${CB_FQDN:-}" ]] && \
    sed -i "/[[:space:]]${CB_FQDN}$/d" /etc/hosts

  echo "Circuit Breaker fully removed."
}

case "${1:-help}" in
  status)    cmd_status    ;;
  doctor)    cmd_doctor    ;;
  logs)      cmd_logs      ;;
  restart)   cmd_restart   ;;
  update)    cmd_update    ;;
  backup)    cmd_backup    ;;
  migrate)   cmd_migrate   ;;
  version)   cmd_version   ;;
  uninstall) cmd_uninstall ;;
  *)
    echo ""
    echo -e "  ${BOLD}cb — Circuit Breaker CLI${RESET}"
    echo ""
    echo "  Commands:"
    echo "    cb status     Show all service statuses"
    echo "    cb doctor     Run health checks"
    echo "    cb logs       Tail all logs (live)"
    echo "    cb restart    Restart all services"
    echo "    cb update     Update to latest version"
    echo "    cb backup     Backup database"
    echo "    cb migrate    Run alembic migrations manually"
    echo "    cb version    Show installed version"
    echo "    cb uninstall  Remove Circuit Breaker"
    echo ""
    ;;
esac
CBCLI

  chmod 755 /usr/local/bin/cb
  chown root:root /usr/local/bin/cb
  cb_ok "cb CLI installed (/usr/local/bin/cb)"
}

# =============================================================================
# STAGE 10: FINAL OUTPUT
# =============================================================================

stage10_final_output() {
  source /etc/circuitbreaker/.env
  local detected_ip version
  detected_ip=$(ip route get 1.1.1.1 2>/dev/null \
    | grep -oP 'src \K[^ ]+' || echo "localhost")
  version=$(cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "unknown")

  cb_section "Circuit Breaker is Running!"
  echo ""
  echo -e "  ${BOLD}${GREEN}Access:${RESET}"

  if [[ "$NO_TLS" == "false" ]]; then
    [[ -n "$CB_FQDN" ]] && \
      echo -e "  ${GREEN}✓${RESET}  https://${CB_FQDN}/"
    echo -e "  ${GREEN}✓${RESET}  https://${detected_ip}/"
    if [[ "$CB_CERT_TYPE" == "self-signed" ]]; then
      echo -e "  ${YELLOW}   Self-signed cert — accept browser warning on first visit${RESET}"
    fi
  else
    [[ -n "$CB_FQDN" ]] && \
      echo -e "  ${GREEN}✓${RESET}  http://${CB_FQDN}:${CB_PORT}/"
    echo -e "  ${GREEN}✓${RESET}  http://${detected_ip}:${CB_PORT}/"
  fi

  echo ""
  echo "  ┌────────────────────────────────────────────┐"
  echo "  │  Version:  ${version}"
  [[ -n "$CB_FQDN" ]] && echo "  │  Domain:   ${CB_FQDN}"
  echo "  │  Data:     ${CB_DATA_DIR}"
  echo "  ├────────────────────────────────────────────┤"
  echo "  │  cb status    — service overview"
  echo "  │  cb doctor    — health checks"
  echo "  │  cb logs      — live log stream"
  echo "  │  cb restart   — restart everything"
  echo "  └────────────────────────────────────────────┘"
  echo ""
  echo -e "  ${GREEN}${BOLD}Installation complete!${RESET}"
  echo ""
}

# =============================================================================
# UPGRADE MODE
# =============================================================================

run_upgrade() {
  cb_header
  cb_section "Upgrade Mode"
  source /etc/circuitbreaker/.env

  cb_step "Creating pre-upgrade database backup"
  local backup_file="${CB_DATA_DIR}/backups/pre-upgrade-$(date +%Y%m%d-%H%M%S).sql"
  mkdir -p "${CB_DATA_DIR}/backups"
  if systemctl is-active circuitbreaker-pgbouncer &>/dev/null; then
    PGPASSWORD="$CB_DB_PASSWORD" pg_dump \
      -h 127.0.0.1 -p 6432 -U breaker circuitbreaker \
      > "$backup_file" 2>/dev/null || true
    cb_ok "Backup: $backup_file"
  else
    cb_warn "Database not running — skipping backup"
  fi

  cb_step "Stopping services"
  systemctl stop circuitbreaker.target >> "$LOG_FILE" 2>&1 || true
  sleep 2
  cb_ok "Services stopped"

  local old_head
  old_head=$(git -C /opt/circuitbreaker rev-parse HEAD 2>/dev/null \
    || echo "unknown")

  stage5_deploy_code
  write_wait_for_services

  if [[ "$old_head" != "unknown" ]]; then
    cb_section "Changes in This Update"
    git -C /opt/circuitbreaker log --oneline "${old_head}..HEAD" \
      2>/dev/null | sed 's/^/  /' || echo "  (changelog unavailable)"
  fi

  stage6_setup_python
  stage7_build_frontend

  cb_step "Restarting all services"
  systemctl start circuitbreaker.target >> "$LOG_FILE" 2>&1
  sleep 5

  local max_wait=45 elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null \
        | grep -qE '"(status|ok)"'; do
    sleep 2; elapsed=$((elapsed + 2))
    [[ $elapsed -ge $max_wait ]] && \
      cb_fail "Backend did not come up after upgrade" "Run: cb doctor"
  done
  cb_ok "Services restarted and healthy"

  stage9_install_cb_cli
  stage10_final_output
}

# =============================================================================
# MAIN
# =============================================================================

main() {
  stage0_preflight

  if [[ "$UPGRADE_MODE" == "true" ]]; then
    run_upgrade
    exit 0
  fi

  stage1_bootstrap
  stage2_dependencies
  stage4_write_systemd_units

  stage3_configure_postgres
  stage3_configure_pgbouncer
  stage3_configure_redis
  stage3_configure_nats
  stage3_configure_caddy

  stage5_deploy_code
  write_wait_for_services
  stage6_setup_python
  stage7_build_frontend

  stage8_start_services
  stage9_install_cb_cli
  stage10_final_output
}

main
