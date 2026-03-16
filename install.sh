#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker Native Installer
# Single-file production installer for Circuit Breaker on Linux

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Default values
CB_PORT=80
CB_DATA_DIR=/var/lib/circuitbreaker
CB_BRANCH=main
UNATTENDED=false
UPGRADE_MODE=false
NO_TLS=false
FORCE_DEPS=false

# UI Functions
cb_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "installing"
}

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)            ║"
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
  echo "  $(printf '─%.0s' {1..42})"
}

# Parse command-line arguments
show_help() {
  echo "Circuit Breaker Native Installer"
  echo ""
  echo "Usage: bash install.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --port <number>      HTTP port (default: 80)"
  echo "  --data-dir <path>    Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls             Skip TLS cert generation"
  echo "  --branch <name>      Git branch to install from (default: main)"
  echo "  --unattended         Skip all prompts, use defaults (for Proxmox LXC)"
  echo "  --upgrade            Force upgrade mode even if install not detected"
  echo "  --force-deps         Force reinstall dependencies in upgrade mode"
  echo "  --help               Show this help message"
  echo ""
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --port)
      CB_PORT="$2"
      shift 2
      ;;
    --data-dir)
      CB_DATA_DIR="$2"
      shift 2
      ;;
    --no-tls)
      NO_TLS=true
      shift
      ;;
    --branch)
      CB_BRANCH="$2"
      shift 2
      ;;
    --unattended)
      UNATTENDED=true
      shift
      ;;
    --upgrade)
      UPGRADE_MODE=true
      shift
      ;;
    --force-deps)
      FORCE_DEPS=true
      shift
      ;;
    --help)
      show_help
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run with --help for usage information"
      exit 1
      ;;
  esac
done

# Global vars set during execution
PKG_MGR=""
OS_ID=""
OS_VERSION=""
ARCH=""
LOG_FILE=""
PG_BIN_DIR=""

# ============================================================================
# STAGE 0: PRE-FLIGHT CHECKS
# ============================================================================

stage0_preflight() {
  cb_header
  cb_section "Pre-flight Checks"

  # Root check
  cb_step "Checking root privileges"
  [[ $EUID -ne 0 ]] && cb_fail "Must run as root" "sudo bash install.sh"
  cb_ok "Running as root"

  # OS Detection
  cb_step "Detecting operating system"
  if [[ ! -f /etc/os-release ]]; then
    cb_fail "Cannot detect OS" "/etc/os-release not found"
  fi
  
  source /etc/os-release
  OS_ID="$ID"
  OS_VERSION="${VERSION_ID:-unknown}"
  
  case "$OS_ID" in
    ubuntu)
      PKG_MGR="apt-get"
      case "$OS_VERSION" in
        22.04|24.04)
          cb_ok "Ubuntu $OS_VERSION detected"
          ;;
        *)
          cb_fail "Unsupported Ubuntu version: $OS_VERSION" "Supported: 22.04, 24.04"
          ;;
      esac
      ;;
    debian)
      PKG_MGR="apt-get"
      case "$OS_VERSION" in
        11|12)
          cb_ok "Debian $OS_VERSION detected"
          ;;
        *)
          cb_fail "Unsupported Debian version: $OS_VERSION" "Supported: 11, 12"
          ;;
      esac
      ;;
    fedora)
      PKG_MGR="dnf"
      case "$OS_VERSION" in
        39|40|41)
          cb_ok "Fedora $OS_VERSION detected"
          ;;
        *)
          cb_fail "Unsupported Fedora version: $OS_VERSION" "Supported: 39, 40, 41"
          ;;
      esac
      ;;
    rhel|rocky|almalinux)
      PKG_MGR="dnf"
      case "$OS_VERSION" in
        9|9.*)
          cb_ok "$OS_ID $OS_VERSION detected"
          ;;
        *)
          cb_fail "Unsupported $OS_ID version: $OS_VERSION" "Supported: 9.x"
          ;;
      esac
      ;;
    *)
      cb_fail "Unsupported OS: $OS_ID" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux"
      ;;
  esac

  # Architecture detection
  cb_step "Detecting architecture"
  case "$(uname -m)" in
    x86_64)
      ARCH="amd64"
      cb_ok "Architecture: x86_64 (amd64)"
      ;;
    aarch64)
      ARCH="arm64"
      cb_ok "Architecture: aarch64 (arm64)"
      ;;
    armv7l)
      ARCH="arm7"
      cb_ok "Architecture: armv7l (arm7)"
      ;;
    *)
      cb_fail "Unsupported architecture: $(uname -m)" "Supported: x86_64, aarch64, armv7l"
      ;;
  esac

  # Resource checks
  cb_step "Checking system resources"
  
  local free_disk_gb=$(df -BG / | tail -1 | awk '{print $4}' | tr -d G)
  if [[ "$free_disk_gb" -lt 3 ]]; then
    cb_fail "Insufficient disk space: ${free_disk_gb}GB free" "Need at least 3GB free"
  fi
  cb_ok "Disk space: ${free_disk_gb}GB free"
  
  local ram_mb=$(free -m | awk '/^Mem:/{print $2}')
  if [[ "$ram_mb" -lt 1024 ]]; then
    cb_warn "Low RAM detected: ${ram_mb}MB (< 1GB). Performance may be limited."
  else
    cb_ok "RAM: ${ram_mb}MB"
  fi

  # Existing install detection
  cb_step "Checking for existing installation"
  if systemctl is-active circuitbreaker-backend &>/dev/null || [[ -f /etc/circuitbreaker/.env ]]; then
    UPGRADE_MODE=true
    cb_ok "Existing installation detected — upgrade mode"
  else
    cb_ok "No existing installation — fresh install"
  fi

  # Initialize log directory early
  mkdir -p "${CB_DATA_DIR}/logs"
  LOG_FILE="${CB_DATA_DIR}/logs/install.log"
  echo "=== Circuit Breaker Installation Log ===" > "$LOG_FILE"
  echo "Started: $(date)" >> "$LOG_FILE"
  echo "OS: $OS_ID $OS_VERSION" >> "$LOG_FILE"
  echo "Arch: $ARCH" >> "$LOG_FILE"
  echo "" >> "$LOG_FILE"

  # Interactive prompts (skip if --unattended or UPGRADE_MODE)
  if [[ "$UNATTENDED" == "false" ]] && [[ "$UPGRADE_MODE" == "false" ]]; then
    cb_section "Configuration"
    
    echo -e "  ${CYAN}HTTP Port${RESET} (default: 80): "
    read -t 10 -r port_input || port_input=""
    if [[ -n "$port_input" ]]; then
      CB_PORT="$port_input"
    fi
    cb_ok "HTTP Port: $CB_PORT"
    
    echo -e "  ${CYAN}Data Directory${RESET} (default: /var/lib/circuitbreaker): "
    read -t 10 -r dir_input || dir_input=""
    if [[ -n "$dir_input" ]]; then
      CB_DATA_DIR="$dir_input"
    fi
    cb_ok "Data Directory: $CB_DATA_DIR"
  fi
}

# ============================================================================
# STAGE 1: USER & DIRECTORY BOOTSTRAP
# ============================================================================

stage1_bootstrap() {
  cb_section "User & Directory Setup"

  # Create breaker user
  cb_step "Creating system user 'breaker'"
  if id breaker &>/dev/null; then
    cb_ok "User 'breaker' already exists"
  else
    useradd -r -u 999 -s /usr/sbin/nologin -d /nonexistent -c "Circuit Breaker" breaker >> "$LOG_FILE" 2>&1
    cb_ok "User 'breaker' created"
  fi

  # Create directory tree with exact permissions
  cb_step "Creating directory structure"
  
  declare -A DIRS=(
    ["/opt/circuitbreaker"]="root:root:755"
    ["/opt/circuitbreaker/apps"]="root:root:755"
    ["/opt/circuitbreaker/apps/backend"]="breaker:breaker:750"
    ["/opt/circuitbreaker/apps/frontend"]="root:root:755"
    ["/opt/circuitbreaker/scripts"]="root:root:755"
    ["/opt/circuitbreaker/apps/frontend/dist"]="root:root:755"
    ["${CB_DATA_DIR}"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/nats"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/redis"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/uploads"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/tls"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/logs"]="breaker:breaker:750"
    ["${CB_DATA_DIR}/backups"]="breaker:breaker:750"
    ["/etc/circuitbreaker"]="root:breaker:750"
    ["/etc/nats"]="root:root:755"
    ["/etc/pgbouncer"]="root:root:755"
  )
  
  for dir in "${!DIRS[@]}"; do
    IFS=':' read -r owner group perms <<< "${DIRS[$dir]}"
    mkdir -p "$dir" >> "$LOG_FILE" 2>&1
    chown "$owner:$group" "$dir" >> "$LOG_FILE" 2>&1
    chmod "$perms" "$dir" >> "$LOG_FILE" 2>&1
  done
  
  cb_ok "Directory structure created"

  # Secret generation
  if [[ -f /etc/circuitbreaker/.env ]]; then
    cb_ok "Secrets already exist — preserving"
    source /etc/circuitbreaker/.env
  else
    cb_step "Generating secrets"
    
    local jwt_secret=$(openssl rand -hex 64)
    # Generate Fernet key: 32 random bytes, base64-encoded (URL-safe)
    local vault_key=$(openssl rand -base64 32 | tr '/+' '_-')
    local db_password=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    local redis_pass=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    local nats_token=$(openssl rand -base64 48 | tr -d '/+=' )
    
    local detected_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")
    
    cat > /etc/circuitbreaker/.env <<EOF
# Circuit Breaker Environment Configuration
# Generated by install.sh on $(date)
# DO NOT EDIT SECRETS MANUALLY — regeneration will break existing data

# ===== Secrets (auto-generated) =====
CB_JWT_SECRET=${jwt_secret}
CB_VAULT_KEY=${vault_key}
CB_DB_PASSWORD=${db_password}
CB_REDIS_PASS=${redis_pass}
NATS_AUTH_TOKEN=${nats_token}

# ===== Connection Strings =====
CB_DB_URL=postgresql://breaker:${db_password}@127.0.0.1:6432/circuitbreaker
CB_REDIS_URL=redis://:${redis_pass}@127.0.0.1:6379/0
NATS_URL=nats://127.0.0.1:4222

# ===== Paths =====
CB_DATA_DIR=${CB_DATA_DIR}
UPLOADS_DIR=${CB_DATA_DIR}/uploads
STATIC_DIR=/opt/circuitbreaker/apps/frontend/dist
LOG_DIR=${CB_DATA_DIR}/logs

# ===== Application =====
CB_PORT=${CB_PORT}
CB_APP_URL=http://${detected_ip}
CB_AUTH_ENABLED=false
CB_ENV=production
EOF
    
    chmod 640 /etc/circuitbreaker/.env
    chown root:breaker /etc/circuitbreaker/.env
    
    cb_ok "Secrets generated and saved"
    source /etc/circuitbreaker/.env
  fi
}

# ============================================================================
# STAGE 2: DEPENDENCY INSTALLATION
# ============================================================================

stage2_dependencies() {
  if [[ "$UPGRADE_MODE" == "true" ]] && [[ "$FORCE_DEPS" == "false" ]]; then
    cb_section "Dependencies"
    cb_ok "Skipping dependency installation (upgrade mode)"
    return
  fi

  cb_section "Installing Dependencies"

  # Group 1: Base tools
  cb_step "Installing base tools"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    $PKG_MGR update -y -q >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q curl jq openssl netcat-openbsd git wget gnupg2 ca-certificates lsb-release >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q curl jq openssl nmap-ncat git wget gnupg2 ca-certificates >> "$LOG_FILE" 2>&1
  fi
  cb_ok "Base tools installed"

  # Group 2: Network/discovery tools
  cb_step "Installing network discovery tools"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    $PKG_MGR install -y -q nmap snmp >> "$LOG_FILE" 2>&1
    if [[ "$ARCH" != "arm7" ]]; then
      $PKG_MGR install -y -q ipmitool >> "$LOG_FILE" 2>&1
    else
      cb_warn "Skipping ipmitool on arm7 (often unavailable)"
    fi
  else
    $PKG_MGR install -y -q nmap net-snmp-utils >> "$LOG_FILE" 2>&1
    if [[ "$ARCH" != "arm7" ]]; then
      $PKG_MGR install -y -q ipmitool >> "$LOG_FILE" 2>&1
    else
      cb_warn "Skipping ipmitool on arm7 (often unavailable)"
    fi
  fi
  cb_ok "Network tools installed"

  # Group 3: PostgreSQL 15 from PGDG
  cb_step "Installing PostgreSQL 15 from PGDG repository"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg >> "$LOG_FILE" 2>&1
    echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list
    $PKG_MGR update -y -q >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q postgresql-15 postgresql-client-15 >> "$LOG_FILE" 2>&1
    PG_BIN_DIR="/usr/lib/postgresql/15/bin"
  else
    local pg_repo_rpm=""
    case "$OS_ID" in
      fedora)
        pg_repo_rpm="https://download.postgresql.org/pub/repos/yum/reporpms/F-${OS_VERSION}-x86_64/pgdg-fedora-repo-latest.noarch.rpm"
        ;;
      rhel|rocky|almalinux)
        pg_repo_rpm="https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm"
        ;;
    esac
    $PKG_MGR install -y -q "$pg_repo_rpm" >> "$LOG_FILE" 2>&1 || true
    $PKG_MGR install -y -q postgresql15-server postgresql15 >> "$LOG_FILE" 2>&1
    PG_BIN_DIR="/usr/pgsql-15/bin"
  fi
  
  if ! "$PG_BIN_DIR/pg_ctl" --version 2>/dev/null | grep -q " 15"; then
    cb_fail "PostgreSQL 15 verification failed" "Check: $PG_BIN_DIR/pg_ctl --version"
  fi
  cb_ok "PostgreSQL 15 installed"

  # Group 4: pgbouncer, Redis, nginx
  cb_step "Installing pgbouncer, Redis, and nginx"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    $PKG_MGR install -y -q pgbouncer redis-server nginx >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q pgbouncer redis nginx >> "$LOG_FILE" 2>&1
  fi
  
  for bin in pgbouncer redis-server redis-cli nginx; do
    if ! command -v "$bin" &>/dev/null && ! command -v "${bin%-*}" &>/dev/null; then
      cb_fail "$bin not found after install" "Check: $PKG_MGR install logs"
    fi
  done
  cb_ok "pgbouncer, Redis, nginx installed"

  # Group 5: NATS Server binary
  cb_step "Installing NATS Server"
  local nats_version=$(curl -s https://api.github.com/repos/nats-io/nats-server/releases/latest | jq -r '.tag_name' | tr -d v)
  if [[ -z "$nats_version" ]] || [[ "$nats_version" == "null" ]]; then
    cb_fail "Failed to fetch NATS version from GitHub" "Check internet connectivity"
  fi
  
  local nats_tarball="nats-server-v${nats_version}-linux-${ARCH}.tar.gz"
  local nats_url="https://github.com/nats-io/nats-server/releases/download/v${nats_version}/${nats_tarball}"
  
  cd /tmp
  curl -fsSL -o "$nats_tarball" "$nats_url" >> "$LOG_FILE" 2>&1 || cb_fail "Failed to download NATS" "$nats_url"
  tar -xzf "$nats_tarball" >> "$LOG_FILE" 2>&1
  cp "nats-server-v${nats_version}-linux-${ARCH}/nats-server" /usr/local/bin/nats-server
  chmod 755 /usr/local/bin/nats-server
  chown root:root /usr/local/bin/nats-server
  rm -rf "$nats_tarball" "nats-server-v${nats_version}-linux-${ARCH}"
  
  if ! /usr/local/bin/nats-server --version &>/dev/null; then
    cb_fail "NATS Server verification failed" "Check: /usr/local/bin/nats-server --version"
  fi
  cb_ok "NATS Server ${nats_version} installed"

  # Group 6: Python 3.12
  cb_step "Installing Python 3.12"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    if [[ "$OS_ID" == "ubuntu" ]] && [[ "$OS_VERSION" == "22.04" ]]; then
      $PKG_MGR install -y -q software-properties-common >> "$LOG_FILE" 2>&1
      add-apt-repository -y ppa:deadsnakes/ppa >> "$LOG_FILE" 2>&1
      $PKG_MGR update -y -q >> "$LOG_FILE" 2>&1
    fi
    $PKG_MGR install -y -q python3.12 python3.12-venv python3.12-dev >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q python3.12 python3.12-devel >> "$LOG_FILE" 2>&1
  fi
  
  if ! python3.12 --version &>/dev/null; then
    cb_fail "Python 3.12 verification failed" "Check: python3.12 --version"
  fi
  cb_ok "Python 3.12 installed"

  # Group 7: Node 20 LTS
  cb_step "Installing Node.js 20 LTS"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q nodejs >> "$LOG_FILE" 2>&1
  else
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q nodejs >> "$LOG_FILE" 2>&1
  fi
  
  if ! node --version 2>/dev/null | grep -q "^v20"; then
    cb_fail "Node 20 verification failed" "Check: node --version"
  fi
  cb_ok "Node.js $(node --version) installed"
}

# ============================================================================
# STAGE 4: SYSTEMD UNITS
# ============================================================================

stage4_write_systemd_units() {
  cb_section "Writing systemd Service Units"
  cb_step "Creating systemd unit files"

  # circuitbreaker-postgres.service
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
TimeoutSec=0
Restart=on-failure
RestartSec=5s
StartLimitBurst=3
StartLimitInterval=60s
NoNewPrivileges=yes
ProtectSystem=false
ReadWritePaths=${CB_DATA_DIR}/postgres
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-postgres

[Install]
WantedBy=multi-user.target
EOF

  # circuitbreaker-pgbouncer.service
  cat > /etc/systemd/system/circuitbreaker-pgbouncer.service <<EOF
[Unit]
Description=Circuit Breaker pgbouncer
After=circuitbreaker-postgres.service
Requires=circuitbreaker-postgres.service

[Service]
Type=simple
User=postgres
ExecStart=/usr/sbin/pgbouncer /etc/pgbouncer/pgbouncer.ini
ExecReload=/bin/kill -HUP \$MAINPID
RuntimeDirectory=pgbouncer
RuntimeDirectoryMode=0755
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-pgbouncer

[Install]
WantedBy=multi-user.target
EOF

  # circuitbreaker-redis.service
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
MemoryMax=256M
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-redis

[Install]
WantedBy=multi-user.target
EOF

  # circuitbreaker-nats.service
  cat > /etc/systemd/system/circuitbreaker-nats.service <<EOF
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
EOF

  # circuitbreaker-backend.service
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
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --no-access-log
Restart=on-failure
RestartSec=5s
StartLimitBurst=3
StartLimitInterval=60s
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

  # circuitbreaker-worker@.service (template)
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
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/python -m app.workers.main --type %i
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

  # circuitbreaker.target
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

  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker.target >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry" >> "$LOG_FILE" 2>&1
  
  cb_ok "Systemd units created and enabled"
}

# ============================================================================
# STAGE 3: SERVICE CONFIGURATION
# ============================================================================

stage3_configure_postgres() {
  cb_section "Configuring PostgreSQL 15"
  
  # Stop any existing postgres
  cb_step "Stopping existing PostgreSQL instances"
  systemctl stop postgresql 2>/dev/null || true
  systemctl stop circuitbreaker-postgres 2>/dev/null || true
  "$PG_BIN_DIR/pg_ctl" stop -D "${CB_DATA_DIR}/postgres" 2>/dev/null || true
  pkill -9 postgres 2>/dev/null || true
  sleep 2
  
  # Verify port 5432 is free
  if lsof -i :5432 &>/dev/null; then
    cb_warn "Port 5432 still in use, attempting to free it..."
    lsof -ti :5432 | xargs kill -9 2>/dev/null || true
    sleep 2
  fi
  cb_ok "Stopped existing instances"
  
  # Create postgres data directory with correct ownership (postgres user now exists)
  cb_step "Creating PostgreSQL data directory"
  mkdir -p "${CB_DATA_DIR}/postgres"
  chown postgres:postgres "${CB_DATA_DIR}/postgres"
  chmod 700 "${CB_DATA_DIR}/postgres"
  cb_ok "PostgreSQL data directory created"
  
  # Initialize database
  if [[ ! -f "${CB_DATA_DIR}/postgres/PG_VERSION" ]]; then
    cb_step "Initializing PostgreSQL database"
    if ! su -s /bin/sh postgres -c "$PG_BIN_DIR/initdb -D ${CB_DATA_DIR}/postgres --auth-local=peer --auth-host=md5 -U postgres" >> "$LOG_FILE" 2>&1; then
      echo ""
      echo "  Last 20 lines from install log:"
      tail -20 "$LOG_FILE" | sed 's/^/  /'
      cb_fail "PostgreSQL initialization failed" "Check: tail -50 ${LOG_FILE}"
    fi
    cb_ok "Database initialized"
  else
    cb_ok "Database already initialized"
  fi
  
  # Write postgresql.conf
  cb_step "Writing PostgreSQL configuration"
  cat >> "${CB_DATA_DIR}/postgres/postgresql.conf" <<EOF

# Circuit Breaker custom settings
listen_addresses = '127.0.0.1'
port = 5432
max_connections = 100
shared_buffers = 128MB
effective_cache_size = 512MB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 4MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 4MB
min_wal_size = 1GB
max_wal_size = 4GB
EOF
  
  cat > "${CB_DATA_DIR}/postgres/pg_hba.conf" <<EOF
# Circuit Breaker pg_hba.conf
local   all             postgres                                peer
local   all             all                                     peer
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
EOF
  
  chown postgres:postgres "${CB_DATA_DIR}/postgres/postgresql.conf"
  chown postgres:postgres "${CB_DATA_DIR}/postgres/pg_hba.conf"
  cb_ok "PostgreSQL configuration written"
  
  # Start PostgreSQL
  cb_step "Starting PostgreSQL"
  echo "  → systemctl start circuitbreaker-postgres"
  if ! timeout 15 systemctl start circuitbreaker-postgres 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status circuitbreaker-postgres --no-pager || true
    cb_fail "PostgreSQL failed to start" "Check: journalctl -u circuitbreaker-postgres -n 50"
  fi
  sleep 3
  
  if ! nc -z 127.0.0.1 5432 2>/dev/null; then
    echo ""
    echo "  Port 5432 not listening. Checking service status..."
    systemctl status circuitbreaker-postgres --no-pager || true
    cb_fail "PostgreSQL not listening on port 5432" "Check: journalctl -u circuitbreaker-postgres -n 50"
  fi
  cb_ok "PostgreSQL started"
  
  # Create user and database
  cb_step "Creating database user and database"
  su -s /bin/sh postgres -c "psql -c \"CREATE USER breaker WITH PASSWORD '${CB_DB_PASSWORD}';\"" >> "$LOG_FILE" 2>&1 || true
  su -s /bin/sh postgres -c "psql -c \"CREATE DATABASE circuitbreaker OWNER breaker;\"" >> "$LOG_FILE" 2>&1 || true
  su -s /bin/sh postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE circuitbreaker TO breaker;\"" >> "$LOG_FILE" 2>&1 || true
  cb_ok "Database user and database created"
  
  # Verify connection
  cb_step "Verifying PostgreSQL connection"
  if ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null; then
    cb_fail "PostgreSQL connection failed" "Check logs: journalctl -u circuitbreaker-postgres -n 50"
  fi
  cb_ok "PostgreSQL connection verified"
}

stage3_configure_pgbouncer() {
  cb_section "Configuring pgbouncer"
  
  # Stop any existing pgbouncer processes
  cb_step "Stopping any existing pgbouncer processes"
  systemctl stop circuitbreaker-pgbouncer 2>/dev/null || true
  pkill -9 pgbouncer 2>/dev/null || true
  sleep 2
  
  # Verify port 6432 is free
  if lsof -i :6432 &>/dev/null; then
    cb_warn "Port 6432 still in use, attempting to free it..."
    lsof -ti :6432 | xargs kill -9 2>/dev/null || true
    sleep 2
  fi
  cb_ok "Cleaned up existing pgbouncer processes"
  
  # Compute MD5 hash - CRITICAL: format is md5(password+username)
  cb_step "Generating pgbouncer authentication hash"
  local pgbouncer_hash=$(echo -n "${CB_DB_PASSWORD}breaker" | md5sum | cut -d' ' -f1)
  
  mkdir -p /etc/pgbouncer
  
  # Write userlist.txt
  cat > /etc/pgbouncer/userlist.txt <<EOF
"breaker" "md5${pgbouncer_hash}"
EOF
  
  chown postgres:postgres /etc/pgbouncer/userlist.txt
  chmod 600 /etc/pgbouncer/userlist.txt
  
  # Write pgbouncer.ini
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
EOF
  
  chown postgres:postgres /etc/pgbouncer/pgbouncer.ini
  cb_ok "pgbouncer configuration written"
  
  # Start pgbouncer
  cb_step "Starting pgbouncer"
  echo "  → systemctl start circuitbreaker-pgbouncer"
  if ! timeout 10 systemctl start circuitbreaker-pgbouncer 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status circuitbreaker-pgbouncer --no-pager || true
    echo ""
    echo "  Last 30 lines from journal:"
    journalctl -u circuitbreaker-pgbouncer -n 30 --no-pager || true
    cb_fail "pgbouncer failed to start" "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 6432 2>/dev/null; then
    echo ""
    echo "  Port 6432 not listening. Checking service status..."
    systemctl status circuitbreaker-pgbouncer --no-pager || true
    echo ""
    echo "  Last 30 lines from journal:"
    journalctl -u circuitbreaker-pgbouncer -n 30 --no-pager || true
    cb_fail "pgbouncer not listening on port 6432" "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  fi
  cb_ok "pgbouncer started"
  
  # Verify connection through pgbouncer
  cb_step "Verifying pgbouncer connection"
  echo "  → Attempting connection: psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker"
  if ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Connection failed. Debugging information:"
    echo "  → Checking userlist.txt:"
    cat /etc/pgbouncer/userlist.txt
    echo ""
    echo "  → Expected MD5 format: \"breaker\" \"md5<hash>\""
    echo "  → Hash should be md5(password+username)"
    echo ""
    echo "  → Checking pgbouncer status:"
    systemctl status circuitbreaker-pgbouncer --no-pager || true
    echo ""
    echo "  → Last 30 lines from pgbouncer journal:"
    journalctl -u circuitbreaker-pgbouncer -n 30 --no-pager || true
    echo ""
    echo "  → Testing direct PostgreSQL connection (port 5432):"
    PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U breaker -d circuitbreaker -c '\q' 2>&1 || true
    cb_fail "pgbouncer connection failed" "Check userlist.txt hash. Run: cb doctor"
  fi
  cb_ok "pgbouncer connection verified"
}

stage3_configure_redis() {
  cb_section "Configuring Redis"
  
  # Stop any existing Redis
  cb_step "Stopping existing Redis instances"
  systemctl stop redis 2>/dev/null || true
  systemctl stop redis-server 2>/dev/null || true
  systemctl stop circuitbreaker-redis 2>/dev/null || true
  pkill -9 redis-server 2>/dev/null || true
  sleep 1
  
  # Verify port 6379 is free
  if lsof -i :6379 &>/dev/null; then
    cb_warn "Port 6379 still in use, attempting to free it..."
    lsof -ti :6379 | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  cb_ok "Cleaned up existing Redis processes"
  
  cb_step "Writing Redis configuration"
  mkdir -p /etc/redis
  
  cat > /etc/redis/redis.conf <<EOF
bind 127.0.0.1
port 6379
protected-mode yes
requirepass ${CB_REDIS_PASS}
timeout 0
tcp-keepalive 300
daemonize no
supervised systemd
pidfile /var/run/redis/redis-server.pid
loglevel notice
logfile ${CB_DATA_DIR}/logs/redis.log
databases 16
save 900 1
save 300 10
save 60 10000
stop-writes-on-bgsave-error yes
rdbcompression yes
rdbchecksum yes
dbfilename dump.rdb
dir ${CB_DATA_DIR}/redis
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly no
EOF
  
  local redis_user="redis"
  if id redis &>/dev/null; then
    redis_user="redis"
  elif id _redis &>/dev/null; then
    redis_user="_redis"
  fi
  
  chown "${redis_user}:${redis_user}" /etc/redis/redis.conf
  chmod 640 /etc/redis/redis.conf
  cb_ok "Redis configuration written"
  
  # Start Redis
  cb_step "Starting Redis"
  echo "  → systemctl start circuitbreaker-redis"
  if ! timeout 10 systemctl start circuitbreaker-redis 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status circuitbreaker-redis --no-pager || true
    cb_fail "Redis failed to start" "Check: journalctl -u circuitbreaker-redis -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 6379 2>/dev/null; then
    echo ""
    echo "  Port 6379 not listening. Checking service status..."
    systemctl status circuitbreaker-redis --no-pager || true
    cb_fail "Redis not listening on port 6379" "Check: journalctl -u circuitbreaker-redis -n 50"
  fi
  cb_ok "Redis started"
  
  # Verify Redis
  cb_step "Verifying Redis connection"
  if ! redis-cli -a "$CB_REDIS_PASS" PING 2>/dev/null | grep -q PONG; then
    cb_fail "Redis not responding" "Check: journalctl -u circuitbreaker-redis -n 50"
  fi
  cb_ok "Redis connection verified"
}

stage3_configure_nats() {
  cb_section "Configuring NATS"
  
  # Stop any existing NATS
  cb_step "Stopping existing NATS instances"
  systemctl stop circuitbreaker-nats 2>/dev/null || true
  pkill -9 nats-server 2>/dev/null || true
  sleep 1
  
  # Verify port 4222 is free
  if lsof -i :4222 &>/dev/null; then
    cb_warn "Port 4222 still in use, attempting to free it..."
    lsof -ti :4222 | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  cb_ok "Cleaned up existing NATS processes"
  
  cb_step "Writing NATS configuration"
  cat > /etc/nats/nats.conf <<EOF
# Circuit Breaker NATS Configuration
port: 4222
http_port: 8222

authorization {
  token: "${NATS_AUTH_TOKEN}"
}

jetstream {
  store_dir: "${CB_DATA_DIR}/nats"
  max_memory_store: 256MB
  max_file_store: 2GB
}

max_payload: 8MB
max_connections: 1000
ping_interval: 30s
ping_max: 3

log_file: "${CB_DATA_DIR}/logs/nats.log"
EOF
  
  chown breaker:breaker /etc/nats/nats.conf
  chmod 640 /etc/nats/nats.conf
  cb_ok "NATS configuration written"
  
  # Start NATS
  cb_step "Starting NATS"
  echo "  → systemctl start circuitbreaker-nats"
  if ! timeout 10 systemctl start circuitbreaker-nats 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status circuitbreaker-nats --no-pager || true
    cb_fail "NATS failed to start" "Check: journalctl -u circuitbreaker-nats -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 4222 2>/dev/null; then
    echo ""
    echo "  Port 4222 not listening. Checking service status..."
    systemctl status circuitbreaker-nats --no-pager || true
    cb_fail "NATS not listening on port 4222" "Check: journalctl -u circuitbreaker-nats -n 50"
  fi
  cb_ok "NATS started"
  
  cb_step "Verifying NATS connection"
  if ! nc -z 127.0.0.1 4222 2>/dev/null; then
    cb_fail "NATS connection failed" "Check: journalctl -u circuitbreaker-nats -n 50"
  fi
  cb_ok "NATS connection verified"
}

stage3_configure_nginx() {
  cb_section "Configuring nginx"
  
  # TLS certificate generation
  if [[ "$NO_TLS" == "false" ]]; then
    cb_step "Generating self-signed TLS certificate"
    openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
      -keyout "${CB_DATA_DIR}/tls/privkey.pem" \
      -out "${CB_DATA_DIR}/tls/fullchain.pem" \
      -subj "/CN=circuitbreaker/O=CircuitBreaker" >> "$LOG_FILE" 2>&1
    chown breaker:breaker "${CB_DATA_DIR}/tls"/*.pem
    chmod 640 "${CB_DATA_DIR}/tls"/*.pem
    cb_ok "TLS certificate generated"
  fi
  
  # Write nginx configuration
  cb_step "Writing nginx configuration"
  
  local nginx_config=""
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    nginx_config="/etc/nginx/sites-available/circuitbreaker"
  else
    nginx_config="/etc/nginx/conf.d/circuitbreaker.conf"
  fi
  
  cat > "$nginx_config" <<EOF
server {
    listen ${CB_PORT} default_server;
    server_name _;
    
    root /opt/circuitbreaker/apps/frontend/dist;
    index index.html;
    
    client_max_body_size 50M;
    
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_vary on;
    
    # SPA routing - serve index.html for all routes
    location / {
        try_files \$uri \$uri/ /index.html;
    }
    
    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # WebSocket proxy
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
    
    # Static assets
    location /user-icons/ {
        proxy_pass http://127.0.0.1:8000;
    }
    
    location /branding/ {
        proxy_pass http://127.0.0.1:8000;
    }
    
    location /uploads/ {
        proxy_pass http://127.0.0.1:8000;
    }
}
EOF
  
  # Add HTTPS server block if TLS enabled
  if [[ "$NO_TLS" == "false" ]]; then
    cat >> "$nginx_config" <<EOF

server {
    listen 443 ssl http2;
    server_name _;
    
    ssl_certificate ${CB_DATA_DIR}/tls/fullchain.pem;
    ssl_certificate_key ${CB_DATA_DIR}/tls/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    root /opt/circuitbreaker/apps/frontend/dist;
    index index.html;
    
    client_max_body_size 50M;
    
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_vary on;
    
    location / {
        try_files \$uri \$uri/ /index.html;
    }
    
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /user-icons/ {
        proxy_pass http://127.0.0.1:8000;
    }
    
    location /branding/ {
        proxy_pass http://127.0.0.1:8000;
    }
    
    location /uploads/ {
        proxy_pass http://127.0.0.1:8000;
    }
}
EOF
  fi
  
  # Enable site on Debian/Ubuntu
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    ln -sf /etc/nginx/sites-available/circuitbreaker /etc/nginx/sites-enabled/circuitbreaker
    rm -f /etc/nginx/sites-enabled/default
  else
    rm -f /etc/nginx/conf.d/default.conf
  fi
  
  cb_ok "nginx configuration written"
  
  # Verify nginx configuration
  cb_step "Verifying nginx configuration"
  if ! nginx -t 2>/dev/null; then
    cb_fail "nginx config invalid" "Check: nginx -t"
  fi
  cb_ok "nginx configuration verified"
  
  cb_ok "nginx configured (will start after frontend build)"
}

# ============================================================================
# WAIT-FOR-SERVICES SCRIPT
# ============================================================================

write_wait_for_services_script() {
  cb_section "Creating Service Health Check Script"
  cb_step "Writing wait-for-services.sh"
  
  mkdir -p /opt/circuitbreaker/scripts
  
  cat > /opt/circuitbreaker/scripts/wait-for-services.sh <<'EOF'
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
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      echo "FATAL: $name did not start within ${MAX_WAIT}s" >&2
      echo "Run: cb doctor" >&2
      exit 1
    fi
  done
}

wait_port "pgbouncer"  127.0.0.1 6432
wait_port "redis"      127.0.0.1 6379
wait_port "nats"       127.0.0.1 4222

# Actual DB connection test - port open ≠ DB accepting connections
PGPASSWORD="$CB_DB_PASSWORD" psql \
  -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null \
  || { echo "FATAL: Cannot connect to DB through pgbouncer" >&2; exit 1; }
EOF
  
  chmod 755 /opt/circuitbreaker/scripts/wait-for-services.sh
  chown root:root /opt/circuitbreaker/scripts/wait-for-services.sh
  
  cb_ok "wait-for-services.sh created"
}

# ============================================================================
# STAGE 5: CODE DEPLOYMENT
# ============================================================================

stage5_deploy_code() {
  cb_section "Deploying Code"
  
  if [[ -d /opt/circuitbreaker/.git ]]; then
    cb_step "Updating existing repository"
    echo "  → git fetch origin"
    git -C /opt/circuitbreaker fetch origin 2>&1 | tee -a "$LOG_FILE"
    echo "  → git checkout $CB_BRANCH"
    git -C /opt/circuitbreaker checkout "$CB_BRANCH" 2>&1 | tee -a "$LOG_FILE"
    echo "  → git pull origin $CB_BRANCH"
    git -C /opt/circuitbreaker pull origin "$CB_BRANCH" 2>&1 | tee -a "$LOG_FILE"
    cb_ok "Repository updated to branch: $CB_BRANCH"
  else
    cb_step "Cloning repository"
    echo "  → git clone --branch $CB_BRANCH --depth 1"
    echo "     https://github.com/BlkLeg/CircuitBreaker.git"
    if ! git clone --branch "$CB_BRANCH" --depth 1 \
      https://github.com/BlkLeg/CircuitBreaker.git \
      /opt/circuitbreaker 2>&1 | tee -a "$LOG_FILE"; then
      cb_fail "Git clone failed" "Check: tail -50 ${LOG_FILE}"
    fi
    cb_ok "Repository cloned from branch: $CB_BRANCH"
  fi
  
  # Fix ownership
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend
  chown -R root:root /opt/circuitbreaker/apps/frontend
  
  cb_ok "Code deployed"
}

# ============================================================================
# STAGE 6: PYTHON SETUP & MIGRATIONS
# ============================================================================

stage6_setup_python() {
  cb_section "Python Backend Setup"
  
  # Create virtual environment
  cb_step "Creating Python virtual environment"
  python3.12 -m venv /opt/circuitbreaker/apps/backend/venv >> "$LOG_FILE" 2>&1
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend/venv
  cb_ok "Virtual environment created"
  
  # Install dependencies as breaker user
  cb_step "Installing Python dependencies"
  echo "  → pip install (this may take a few minutes...)"
  if ! su -s /bin/sh breaker -c "
    source /opt/circuitbreaker/apps/backend/venv/bin/activate
    pip install --upgrade pip
    pip install -r /opt/circuitbreaker/apps/backend/requirements.txt
    pip install -e /opt/circuitbreaker/apps/backend/
  " 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Last 30 lines from install log:"
    tail -30 "$LOG_FILE" | sed 's/^/  /'
    cb_fail "Python dependencies installation failed" "Check: tail -100 ${LOG_FILE}"
  fi
  cb_ok "Python dependencies installed"
  
  # Run database migrations
  cb_step "Running database migrations"
  echo "  → alembic upgrade head"
  source /etc/circuitbreaker/.env
  if ! su -s /bin/sh breaker -c "
    source /etc/circuitbreaker/.env
    cd /opt/circuitbreaker/apps/backend
    /opt/circuitbreaker/apps/backend/venv/bin/alembic upgrade head
  " 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Last 30 lines from install log:"
    tail -30 "$LOG_FILE" | sed 's/^/  /'
    cb_fail "Database migrations failed" "Check: tail -100 ${LOG_FILE}"
  fi
  
  # Verify migrations ran
  local migration_count=$(PGPASSWORD="$CB_DB_PASSWORD" psql \
    -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -tAc \
    "SELECT COUNT(*) FROM alembic_version" 2>/dev/null || echo "0")
  
  if [[ "$migration_count" -gt 0 ]]; then
    cb_ok "Database migrations completed ($migration_count applied)"
  else
    cb_fail "Database migrations did not run" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
}

# ============================================================================
# STAGE 7: FRONTEND BUILD
# ============================================================================

stage7_build_frontend() {
  cb_section "Frontend Build"
  
  cb_step "Installing Node.js dependencies"
  cd /opt/circuitbreaker/apps/frontend
  echo "  → npm ci (this may take a few minutes...)"
  if ! npm ci 2>&1 | tee -a "${CB_DATA_DIR}/logs/install.log"; then
    echo ""
    echo "  Last 30 lines from install log:"
    tail -30 "${CB_DATA_DIR}/logs/install.log" | sed 's/^/  /'
    cb_fail "npm install failed" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  cb_ok "Node dependencies installed"
  
  cb_step "Building frontend application"
  echo "  → npm run build (this may take a few minutes...)"
  if ! npm run build 2>&1 | tee -a "${CB_DATA_DIR}/logs/install.log"; then
    echo ""
    echo "  Last 30 lines from install log:"
    tail -30 "${CB_DATA_DIR}/logs/install.log" | sed 's/^/  /'
    cb_fail "Frontend build failed" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  
  # Verify build output
  if [[ ! -f /opt/circuitbreaker/apps/frontend/dist/index.html ]]; then
    cb_fail "Frontend build produced no output" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  cb_ok "Frontend built successfully"
  
  # Fix permissions
  chown -R root:root /opt/circuitbreaker/apps/frontend/dist
  chmod -R 755 /opt/circuitbreaker/apps/frontend/dist
  
  cb_ok "Frontend ready to serve"
}

# ============================================================================
# STAGE 8: START EVERYTHING & FINAL VERIFY
# ============================================================================

stage8_start_services() {
  cb_section "Starting Application Services"
  
  # Start backend
  cb_step "Starting backend API"
  echo "  → systemctl start circuitbreaker-backend"
  if ! timeout 30 systemctl start circuitbreaker-backend 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status circuitbreaker-backend --no-pager || true
    echo ""
    echo "  Last 50 lines from journal:"
    journalctl -u circuitbreaker-backend -n 50 --no-pager || true
    cb_fail "Backend failed to start" "Check: journalctl -u circuitbreaker-backend -n 100"
  fi
  
  # Wait for backend health endpoint
  local max_wait=30
  local elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null | grep -q '"status"'; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [[ $elapsed -ge $max_wait ]]; then
      cb_fail "Backend API did not start" "Run: cb doctor"
    fi
  done
  cb_ok "Backend API started"
  
  # Start workers
  cb_step "Starting worker processes"
  for worker in discovery webhook notification telemetry; do
    echo "  → Starting worker: $worker"
    systemctl start "circuitbreaker-worker@${worker}" 2>&1 | tee -a "$LOG_FILE" || true
  done
  sleep 2
  cb_ok "Workers started"
  
  # Start nginx
  cb_step "Starting nginx"
  echo "  → systemctl start nginx"
  if ! timeout 10 systemctl start nginx 2>&1 | tee -a "$LOG_FILE"; then
    echo ""
    echo "  Startup failed or timed out. Checking status..."
    systemctl status nginx --no-pager || true
    cb_fail "nginx failed to start" "Check: journalctl -u nginx -n 50"
  fi
  sleep 1
  
  if ! nc -z 127.0.0.1 "$CB_PORT" 2>/dev/null; then
    echo ""
    echo "  Port $CB_PORT not listening. Checking service status..."
    systemctl status nginx --no-pager || true
    cb_fail "nginx not listening on port $CB_PORT" "Check: journalctl -u nginx -n 50"
  fi
  cb_ok "nginx started"
  
  # Detect primary IP and update .env
  local detected_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")
  if ! grep -q "CB_HOST_IP=" /etc/circuitbreaker/.env 2>/dev/null; then
    echo "CB_HOST_IP=$detected_ip" >> /etc/circuitbreaker/.env
  fi
  
  cb_ok "All services running"
}

# ============================================================================
# STAGE 9: CB CLI
# ============================================================================

stage9_install_cb_cli() {
  cb_section "Installing CB CLI"
  cb_step "Writing /usr/local/bin/cb"
  
  cat > /usr/local/bin/cb <<'EOF'
#!/usr/bin/env bash
# cb - Circuit Breaker management CLI

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
  printf "  %-36s %-12s %s\n" "────────────────────────────────────" "──────────" "──────"
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
  bash <(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh) --upgrade
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
    echo "  cb - Circuit Breaker CLI"
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
EOF
  
  chmod 755 /usr/local/bin/cb
  chown root:root /usr/local/bin/cb
  
  cb_ok "CB CLI installed"
}

# ============================================================================
# STAGE 10: FINAL OUTPUT
# ============================================================================

stage10_final_output() {
  local detected_ip=$(grep CB_HOST_IP /etc/circuitbreaker/.env 2>/dev/null | cut -d= -f2 || echo "localhost")
  local version=$(cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "unknown")
  
  cb_section "Circuit Breaker is running!"
  echo ""
  echo -e "  ┌──────────────────────────────────────────────┐"
  echo -e "  │  URL:      http://${detected_ip}:${CB_PORT}"
  if [[ "$NO_TLS" == "false" ]]; then
    echo -e "  │            https://${detected_ip}:443"
  fi
  echo -e "  │  Logs:     cb logs"
  echo -e "  │  Status:   cb status"
  echo -e "  │  Help:     cb doctor"
  echo -e "  │  Version:  ${version}"
  echo -e "  └──────────────────────────────────────────────┘"
  echo ""
  echo -e "  First run? Open the URL above to complete setup."
  echo ""
}

# ============================================================================
# UPGRADE MODE
# ============================================================================

run_upgrade() {
  cb_header
  cb_section "Upgrade Mode"
  cb_ok "Detected existing installation"
  
  # Source environment variables
  source /etc/circuitbreaker/.env
  
  # Backup before upgrade (while services are still running)
  cb_step "Creating pre-upgrade backup"
  local backup_file="${CB_DATA_DIR}/backups/pre-upgrade-$(date +%Y%m%d-%H%M%S).sql"
  if systemctl is-active circuitbreaker-pgbouncer &>/dev/null; then
    PGPASSWORD="$CB_DB_PASSWORD" pg_dump \
      -h 127.0.0.1 -p 6432 -U breaker circuitbreaker > "$backup_file" 2>/dev/null || true
    cb_ok "Backup saved: $backup_file"
  else
    cb_warn "Database not running - skipping backup"
  fi
  
  # Stop services after backup
  cb_step "Stopping services"
  systemctl stop circuitbreaker.target >> "$LOG_FILE" 2>&1 || true
  sleep 2
  cb_ok "Services stopped"
  
  # Record current HEAD for changelog
  local old_head=$(git -C /opt/circuitbreaker rev-parse HEAD 2>/dev/null || echo "unknown")
  
  # Deploy code
  stage5_deploy_code
  
  # Show changelog
  if [[ "$old_head" != "unknown" ]]; then
    cb_section "Changes in this update"
    git -C /opt/circuitbreaker log --oneline "${old_head}..HEAD" 2>/dev/null || echo "  (changelog unavailable)"
  fi
  
  # Update Python dependencies
  stage6_setup_python
  
  # Rebuild frontend
  stage7_build_frontend
  
  # Restart services
  cb_step "Restarting all services"
  systemctl start circuitbreaker.target >> "$LOG_FILE" 2>&1
  sleep 5
  
  # Wait for backend
  local max_wait=30
  local elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null | grep -q '"status"'; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [[ $elapsed -ge $max_wait ]]; then
      cb_fail "Backend did not start after upgrade" "Run: cb doctor"
    fi
  done
  cb_ok "Services restarted"
  
  stage10_final_output
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
  # Stage 0: Pre-flight
  stage0_preflight
  
  # Check if upgrade mode
  if [[ "$UPGRADE_MODE" == "true" ]]; then
    run_upgrade
    exit 0
  fi
  
  # Fresh install flow
  stage1_bootstrap
  stage2_dependencies
  stage4_write_systemd_units
  write_wait_for_services_script
  
  # Configure services
  stage3_configure_postgres
  stage3_configure_pgbouncer
  stage3_configure_redis
  stage3_configure_nats
  stage3_configure_nginx
  
  # Deploy and build
  stage5_deploy_code
  stage6_setup_python
  stage7_build_frontend
  
  # Start everything
  stage8_start_services
  stage9_install_cb_cli
  
  # Final output
  stage10_final_output
}

# Run main
main

