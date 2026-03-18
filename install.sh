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
DIM='\033[2m'
RESET='\033[0m'

# Default values
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
DOCKER_AVAILABLE=false
INSTALL_DOCKER=false

# UI Functions
cb_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "installing"
}

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)              ║"
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
  echo "  --port <number>      HTTP port (default: 8088)"
  echo "  --fqdn <domain>      Fully qualified domain name (optional)"
  echo "  --cert-type <type>   Certificate type: self-signed or letsencrypt (default: self-signed)"
  echo "  --email <address>    Email for Let's Encrypt notifications (required if --cert-type letsencrypt)"
  echo "  --data-dir <path>    Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls             Skip TLS cert generation"
  echo "  --branch <name>      Git branch to install from (default: main)"
  echo "  --unattended         Skip all prompts, use defaults (for Proxmox LXC)"
  echo "  --upgrade            Force upgrade mode even if install not detected"
  echo "  --force-deps         Force reinstall dependencies in upgrade mode"
  echo "  --docker             Install Docker CE and enable container telemetry proxy"
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
    --fqdn)
      CB_FQDN="$2"
      shift 2
      ;;
    --cert-type)
      CB_CERT_TYPE="$2"
      shift 2
      ;;
    --email)
      CB_EMAIL="$2"
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
    --docker)
      INSTALL_DOCKER=true
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
    arch)
      OS_NAME="Arch Linux"
      PKG_MGR="pacman"
      PG_BIN_DIR="/usr/bin"
      cb_ok "Arch Linux detected"
      ;;
    *)
      cb_fail "Unsupported OS: $OS_ID" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux, Arch"
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
    
    echo -e "  ${CYAN}HTTP Port${RESET} (default: 8088): "
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
    
    echo -e "  ${CYAN}Domain (FQDN)${RESET} (optional, press Enter to skip): "
    read -t 15 -r fqdn_input || fqdn_input=""
    if [[ -n "$fqdn_input" ]]; then
      CB_FQDN="$fqdn_input"
      cb_ok "Domain: $CB_FQDN"
      
      echo -e "  ${CYAN}TLS Certificate${RESET}"
      echo -e "    1) Self-signed (default)"
      echo -e "    2) Let's Encrypt (requires port 80 accessible from internet)"
      read -t 10 -r -p "  Choice [1-2]: " cert_choice || cert_choice="1"
      if [[ "$cert_choice" == "2" ]]; then
        CB_CERT_TYPE="letsencrypt"
        echo -e "  ${CYAN}Email for Let's Encrypt${RESET} (required): "
        read -t 15 -r email_input || email_input=""
        if [[ -z "$email_input" ]]; then
          cb_warn "Email required for Let's Encrypt, falling back to self-signed"
          CB_CERT_TYPE="self-signed"
        else
          CB_EMAIL="$email_input"
          cb_ok "Certificate: Let's Encrypt (email: $CB_EMAIL)"
        fi
      else
        cb_ok "Certificate: Self-signed"
      fi
    else
      cb_ok "Domain: Not configured (using IP)"
      cb_ok "Certificate: Self-signed"
    fi
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

  # Create directory structure
  cb_step "Creating directory structure"
  echo "    Application: /opt/circuitbreaker"
  echo "    Data: ${CB_DATA_DIR}"
  echo "    Config: /etc/circuitbreaker"
  
  declare -A DIRS=(
    ["/opt/circuitbreaker"]="root:root:755"
    ["/opt/circuitbreaker/apps"]="root:root:755"
    ["/opt/circuitbreaker/apps/backend"]="breaker:breaker:750"
    ["/opt/circuitbreaker/apps/frontend"]="root:root:755"
    ["/opt/circuitbreaker/scripts"]="root:root:755"
    ["/opt/circuitbreaker/apps/frontend/dist"]="root:root:755"
    ["${CB_DATA_DIR}"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/nats"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/uploads"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/tls"]="breaker:breaker:755"
    ["${CB_DATA_DIR}/logs"]="breaker:breaker:777"
    ["${CB_DATA_DIR}/backups"]="breaker:breaker:755"
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

  # File descriptor limits for the breaker user
  if ! grep -q "breaker.*nofile" /etc/security/limits.conf 2>/dev/null; then
    printf '\nbreaker soft nofile 65536\nbreaker hard nofile 65536\n' >> /etc/security/limits.conf
  fi

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
CB_DB_URL=postgresql://breaker:${db_password}@127.0.0.1:5432/circuitbreaker
CB_DB_POOL_URL=postgresql://breaker:${db_password}@127.0.0.1:6432/circuitbreaker
CB_REDIS_URL=redis://:${redis_pass}@127.0.0.1:6379/0
NATS_URL=nats://127.0.0.1:4222

# ===== Paths =====
CB_DATA_DIR=${CB_DATA_DIR}
UPLOADS_DIR=${CB_DATA_DIR}/uploads
STATIC_DIR=/opt/circuitbreaker/apps/frontend/dist
LOG_DIR=${CB_DATA_DIR}/logs

# ===== Application =====
CB_PORT=${CB_PORT}
CB_FQDN=${CB_FQDN}
CB_APP_URL=http://${CB_FQDN:-$detected_ip}
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
    $PKG_MGR install -y -q curl jq openssl netcat-openbsd git wget gnupg2 ca-certificates lsb-release libcap2-bin >> "$LOG_FILE" 2>&1
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -Sy --noconfirm --needed \
      curl jq openssl openbsd-netcat git wget gnupg ca-certificates libcap >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q curl jq openssl nmap-ncat git wget gnupg2 ca-certificates libcap >> "$LOG_FILE" 2>&1
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
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -S --noconfirm --needed nmap net-snmp >> "$LOG_FILE" 2>&1
    if [[ "$ARCH" != "arm7" ]]; then
      pacman -S --noconfirm --needed ipmitool >> "$LOG_FILE" 2>&1
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
  cb_step "Installing PostgreSQL 15 from official PGDG repository"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc 2>/dev/null | gpg --yes --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg 2>/dev/null
    echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list
    $PKG_MGR update -y -q >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q postgresql-15 postgresql-client-15 >> "$LOG_FILE" 2>&1
    PG_BIN_DIR="/usr/lib/postgresql/15/bin"
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -S --noconfirm --needed postgresql >> "$LOG_FILE" 2>&1
    # PG_BIN_DIR already set to /usr/bin in OS detection
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

  if [[ "$PKG_MGR" != "pacman" ]] && ! "$PG_BIN_DIR/pg_ctl" --version 2>/dev/null | grep -q " 15"; then
    cb_fail "PostgreSQL 15 verification failed" "Check: $PG_BIN_DIR/pg_ctl --version"
  fi
  local pg_version=$("$PG_BIN_DIR/pg_ctl" --version | grep -oP '\d+\.\d+' | head -1)
  echo "    Binary path: $PG_BIN_DIR"
  cb_ok "PostgreSQL ${pg_version} installed"

  # Group 4: pgbouncer, Redis, Caddy
  cb_step "Installing pgbouncer, Redis, and Caddy"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    # Add official Caddy stable APT repository
    $PKG_MGR install -y -q debian-keyring debian-archive-keyring apt-transport-https >> "$LOG_FILE" 2>&1
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' 2>/dev/null \
      | gpg --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' 2>/dev/null \
      > /etc/apt/sources.list.d/caddy-stable.list
    $PKG_MGR update -q >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q pgbouncer redis-server caddy >> "$LOG_FILE" 2>&1
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -S --noconfirm --needed pgbouncer redis caddy >> "$LOG_FILE" 2>&1
  else
    # Enable official Caddy COPR repository for RHEL/Fedora
    dnf copr enable -y @caddy/caddy >> "$LOG_FILE" 2>&1 || true
    $PKG_MGR install -y -q pgbouncer redis caddy >> "$LOG_FILE" 2>&1
  fi

  for bin in pgbouncer redis-server redis-cli caddy; do
    if ! command -v "$bin" &>/dev/null && ! command -v "${bin%-*}" &>/dev/null; then
      cb_fail "$bin not found after install" "Check: $PKG_MGR install logs"
    fi
  done
  cb_ok "pgbouncer, Redis, Caddy installed"

  # Group 5: NATS Server binary
  cb_step "Installing NATS Server (JetStream)"
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
  echo "    Install path: /usr/local/bin/nats-server"
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
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    # Arch ships Python 3.12+ as the default python package; venv module is included
    pacman -S --noconfirm --needed python python-pip >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q python3.12 python3.12-devel >> "$LOG_FILE" 2>&1
  fi
  
  if ! python3.12 --version &>/dev/null; then
    cb_fail "Python 3.12 verification failed" "Check: python3.12 --version"
  fi
  local py_version=$(python3.12 --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+')
  cb_ok "Python ${py_version} installed"

  # Group 7: Node 20 LTS
  cb_step "Installing Node.js 20 LTS"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q nodejs >> "$LOG_FILE" 2>&1
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    # Arch extra repo ships current Node (typically >= 20); NodeSource does not support Arch
    pacman -S --noconfirm --needed nodejs npm >> "$LOG_FILE" 2>&1
  else
    curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - >> "$LOG_FILE" 2>&1
    $PKG_MGR install -y -q nodejs >> "$LOG_FILE" 2>&1
  fi

  if ! node --version 2>/dev/null | grep -qE "^v(1[89]|[2-9][0-9])"; then
    cb_fail "Node 18+ verification failed" "Check: node --version (got: $(node --version 2>/dev/null || echo none))"
  fi
  cb_ok "Node.js $(node --version) installed"

  # Optionally install Docker CE when --docker flag is passed
  if [[ "$INSTALL_DOCKER" == "true" ]] && ! command -v docker &>/dev/null; then
    cb_step "Installing Docker CE"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg >> "$LOG_FILE" 2>&1
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -q >> "$LOG_FILE" 2>&1
      apt-get install -y -q docker-ce docker-ce-cli containerd.io >> "$LOG_FILE" 2>&1
    elif [[ "$PKG_MGR" == "pacman" ]]; then
      pacman -S --noconfirm --needed docker >> "$LOG_FILE" 2>&1
    else
      dnf config-manager --add-repo \
        https://download.docker.com/linux/fedora/docker-ce.repo >> "$LOG_FILE" 2>&1
      dnf install -y -q docker-ce docker-ce-cli containerd.io >> "$LOG_FILE" 2>&1
    fi
    systemctl enable --now docker >> "$LOG_FILE" 2>&1
    cb_ok "Docker CE installed"
  fi

  # Docker detection — enables container telemetry proxy when Docker is present
  cb_step "Checking for Docker daemon"
  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_AVAILABLE=true
    cb_ok "Docker detected — socket proxy will be configured"
  else
    DOCKER_AVAILABLE=false
    cb_warn "Docker not found — container telemetry will be unavailable"
  fi
}

# ============================================================================
# STAGE 4: SYSTEMD UNITS
# ============================================================================

stage4_write_systemd_units() {
  cb_section "Writing systemd Service Units"
  cb_step "Creating systemd unit files"
  echo "    All services will log to systemd journal"
  echo "    View with: journalctl -u circuitbreaker-<service>"

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
Slice=circuitbreaker.slice
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
Slice=circuitbreaker.slice
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
Slice=circuitbreaker.slice
ExecStart=/usr/local/bin/nats-server -c /etc/nats/nats.conf
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
ReadWritePaths=${CB_DATA_DIR}/nats
MemoryMax=512M
LimitNOFILE=65536
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
Slice=circuitbreaker.slice
WorkingDirectory=/opt/circuitbreaker/apps/backend
EnvironmentFile=/etc/circuitbreaker/.env
RuntimeDirectory=circuitbreaker
RuntimeDirectoryMode=0750
ExecStartPre=/bin/sh -c 'umask 077; grep -E "^CB_VAULT_KEY=" /etc/circuitbreaker/.env > /run/circuitbreaker/vault.env 2>/dev/null || true'
EnvironmentFile=-/run/circuitbreaker/vault.env
ExecStartPre=/opt/circuitbreaker/scripts/validate-secrets.sh
ExecStartPre=/opt/circuitbreaker/scripts/wait-for-services.sh
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
Restart=on-failure
RestartSec=10s
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${CB_DATA_DIR}
MemoryMax=1G
LimitNOFILE=65536
CPUQuota=200%
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
Slice=circuitbreaker.slice
WorkingDirectory=/opt/circuitbreaker/apps/backend
EnvironmentFile=/etc/circuitbreaker/.env
RuntimeDirectory=circuitbreaker
RuntimeDirectoryMode=0750
ExecStartPre=/bin/sh -c 'umask 077; grep -E "^CB_VAULT_KEY=" /etc/circuitbreaker/.env > /run/circuitbreaker/vault.env 2>/dev/null || true'
EnvironmentFile=-/run/circuitbreaker/vault.env
Environment="DB_POOL_SIZE=3"
Environment="DB_MAX_OVERFLOW=2"
ExecStart=/opt/circuitbreaker/apps/backend/venv/bin/python -m app.workers.main --type %i
Restart=on-failure
RestartSec=10s
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=${CB_DATA_DIR}
MemoryMax=512M
LimitNOFILE=65536
CPUQuota=50%
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
Wants=caddy.service
Wants=circuitbreaker-healthcheck.timer
After=circuitbreaker-postgres.service
After=circuitbreaker-pgbouncer.service
After=circuitbreaker-redis.service
After=circuitbreaker-nats.service
After=circuitbreaker-backend.service
After=caddy.service

[Install]
WantedBy=multi-user.target
EOF

  # Supporting scripts for systemd units
  mkdir -p /opt/circuitbreaker/scripts

  # healthcheck.sh — liveness probe called by circuitbreaker-healthcheck.timer
  cat > /opt/circuitbreaker/scripts/healthcheck.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/circuitbreaker/.env
set +a

LOCK_FILE="/run/cb-healthcheck.lock"
LOG_FILE="${CB_DATA_DIR}/logs/healthcheck.log"

# Rate-limit restarts: skip if a restart was triggered within the last 60s
if [[ -f "$LOCK_FILE" ]]; then
  last=$(cat "$LOCK_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if (( now - last < 60 )); then
    echo "$(date -Iseconds) restart already in progress — skipping" >> "$LOG_FILE"
    exit 0
  fi
fi

if curl -sf --max-time 5 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  exit 0
fi

echo "$(date -Iseconds) health check failed — restarting circuitbreaker-backend" >> "$LOG_FILE"
date +%s > "$LOCK_FILE"
systemctl restart circuitbreaker-backend
EOF
  chmod 700 /opt/circuitbreaker/scripts/healthcheck.sh
  chown root:root /opt/circuitbreaker/scripts/healthcheck.sh

  # validate-secrets.sh — pre-start guard called as ExecStartPre in backend.service
  cat > /opt/circuitbreaker/scripts/validate-secrets.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

set -a
source /etc/circuitbreaker/.env
set +a

fail() { echo "ERROR: $*" >&2; exit 1; }

PLACEHOLDERS="CHANGE_ME changeme placeholder todo test secret password"

check_secret() {
  local name="$1" value="$2" min_len="${3:-0}"
  [[ -z "$value" ]] && fail "$name is not set or empty"
  for p in $PLACEHOLDERS; do
    [[ "${value,,}" == "${p,,}" ]] && fail "$name contains placeholder value: $value"
  done
  if (( min_len > 0 )) && (( ${#value} < min_len )); then
    fail "$name is too short (${#value} chars, minimum $min_len)"
  fi
}

check_secret "CB_JWT_SECRET"   "${CB_JWT_SECRET:-}"   64
check_secret "CB_VAULT_KEY"    "${CB_VAULT_KEY:-}"    32
check_secret "NATS_AUTH_TOKEN" "${NATS_AUTH_TOKEN:-}"  0
check_secret "CB_DB_PASSWORD"  "${CB_DB_PASSWORD:-}"   0
EOF
  chmod 750 /opt/circuitbreaker/scripts/validate-secrets.sh
  chown root:breaker /opt/circuitbreaker/scripts/validate-secrets.sh

  # circuitbreaker-healthcheck.service
  cat > /etc/systemd/system/circuitbreaker-healthcheck.service <<EOF
[Unit]
Description=Circuit Breaker Liveness Check
After=circuitbreaker-backend.service

[Service]
Type=oneshot
ExecStart=/opt/circuitbreaker/scripts/healthcheck.sh
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-healthcheck
EOF

  # circuitbreaker-healthcheck.timer
  cat > /etc/systemd/system/circuitbreaker-healthcheck.timer <<EOF
[Unit]
Description=Circuit Breaker Liveness Check Timer
Requires=circuitbreaker-backend.service

[Timer]
OnBootSec=90s
OnUnitActiveSec=30s
AccuracySec=5s

[Install]
WantedBy=timers.target
EOF

  # circuitbreaker.slice — aggregate memory cap across all CB services
  cat > /etc/systemd/system/circuitbreaker.slice <<EOF
[Unit]
Description=Circuit Breaker Service Slice

[Slice]
MemoryMax=3G
MemoryHigh=2G
EOF

  # circuitbreaker-docker-proxy.service — only written when Docker is present
  # --privileged is required by tecnativa/docker-socket-proxy to bind to the Docker socket.
  # Port 2375 is bound to 127.0.0.1 only — never 0.0.0.0 (unauthenticated Docker API).
  if [[ "$DOCKER_AVAILABLE" == "true" ]]; then
    cat > /etc/systemd/system/circuitbreaker-docker-proxy.service <<'UNITEOF'
[Unit]
Description=Circuit Breaker Docker Socket Proxy
Documentation=https://github.com/Tecnativa/docker-socket-proxy
After=docker.service
Requires=docker.service
Before=circuitbreaker-backend.service

[Service]
Type=simple
User=root
Restart=on-failure
RestartSec=10s
LimitNOFILE=65536
Slice=circuitbreaker.slice
ExecStartPre=-/usr/bin/docker rm -f cb-docker-proxy
ExecStart=/usr/bin/docker run --rm --name cb-docker-proxy --privileged -p 127.0.0.1:2375:2375 -v /var/run/docker.sock:/var/run/docker.sock:ro --env-file /etc/circuitbreaker/docker-proxy.env tecnativa/docker-socket-proxy:latest
ExecStop=/usr/bin/docker stop cb-docker-proxy
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-docker-proxy

[Install]
WantedBy=multi-user.target
UNITEOF
  fi

  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker.target >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker.slice \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry" \
    circuitbreaker-healthcheck.timer \
    caddy >> "$LOG_FILE" 2>&1
  [[ "$DOCKER_AVAILABLE" == "true" ]] && \
    systemctl enable circuitbreaker-docker-proxy >> "$LOG_FILE" 2>&1 || true

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
  echo "    Data directory: ${CB_DATA_DIR}/postgres (postgres:postgres 700)"
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
  if ! systemctl start circuitbreaker-postgres >> "$LOG_FILE" 2>&1; then
    cb_fail "PostgreSQL failed to start" "Check: journalctl -u circuitbreaker-postgres -n 50"
  fi
  sleep 3
  
  if ! nc -z 127.0.0.1 5432 2>/dev/null; then
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
  cb_step "Configuring pgbouncer connection pooler"
  local pgbouncer_hash=$(echo -n "${CB_DB_PASSWORD}breaker" | md5sum | cut -d' ' -f1)
  echo "    Pool port: 6432, Backend: PostgreSQL 5432"
  
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
  chmod 640 /etc/pgbouncer/pgbouncer.ini
  cb_ok "Configuration written"
  
  # Start pgbouncer
  cb_step "Starting pgbouncer"
  if ! systemctl start circuitbreaker-pgbouncer >> "$LOG_FILE" 2>&1; then
    systemctl status circuitbreaker-pgbouncer --no-pager || true
    journalctl -u circuitbreaker-pgbouncer -n 20 --no-pager || true
    cb_fail "pgbouncer failed to start" "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 6432 2>/dev/null; then
    cb_fail "pgbouncer not listening on port 6432" "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
  fi
  cb_ok "pgbouncer started"
  
  # Verify connection through pgbouncer
  cb_step "Verifying pgbouncer connection"
  if ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' >> "$LOG_FILE" 2>&1; then
    cb_fail "pgbouncer connection failed" "Check: journalctl -u circuitbreaker-pgbouncer -n 50"
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

  local ram_mb
  ram_mb=$(free -m | awk '/^Mem:/{print $2}')
  local redis_maxmem="256mb"
  [[ "$ram_mb" -lt 2048 ]] && redis_maxmem="128mb"

  # Create Redis data directory with correct ownership
  local redis_user="redis"
  if id redis &>/dev/null; then
    redis_user="redis"
  elif id _redis &>/dev/null; then
    redis_user="_redis"
  fi
  
  mkdir -p "${CB_DATA_DIR}/redis"
  chown "${redis_user}:${redis_user}" "${CB_DATA_DIR}/redis"
  chmod 755 "${CB_DATA_DIR}/redis"
  echo "    Redis data: ${CB_DATA_DIR}/redis (${redis_user}:${redis_user})"
  
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
maxmemory ${redis_maxmem}
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
  echo "    Port: 6379, Max memory: 256MB, Policy: allkeys-lru"
  cb_ok "Configuration written"
  
  # Start Redis
  cb_step "Starting Redis"
  if ! systemctl start circuitbreaker-redis >> "$LOG_FILE" 2>&1; then
    cb_fail "Redis failed to start" "Check: journalctl -u circuitbreaker-redis -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 6379 2>/dev/null; then
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
http: 127.0.0.1:8222

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
  echo "    Port: 4222, Store: ${CB_DATA_DIR}/nats"
  cb_ok "Configuration written"
  
  # Start NATS
  cb_step "Starting NATS"
  if ! systemctl start circuitbreaker-nats >> "$LOG_FILE" 2>&1; then
    cb_fail "NATS failed to start" "Check: journalctl -u circuitbreaker-nats -n 50"
  fi
  sleep 2
  
  if ! nc -z 127.0.0.1 4222 2>/dev/null; then
    cb_fail "NATS not listening on port 4222" "Check: journalctl -u circuitbreaker-nats -n 50"
  fi
  cb_ok "NATS started"
  
  cb_ok "NATS connection verified"
}

ensure_hosts_entry() {
  local fqdn="${CB_FQDN:-}"
  [[ -z "$fqdn" ]] && return 0

  if grep -qF "$fqdn" /etc/hosts 2>/dev/null; then
    cb_ok "/etc/hosts entry for $fqdn already present"
    return 0
  fi

  cb_step "Adding $fqdn to /etc/hosts"
  echo "127.0.0.1  $fqdn" >> /etc/hosts
  cb_ok "$fqdn → 127.0.0.1 added to /etc/hosts"
}

stage3_configure_caddy() {
  cb_section "Configuring Caddy"

  local cert_path="${CB_DATA_DIR}/tls"
  local site_address
  local tls_line=""

  # TLS certificate generation / directive setup
  if [[ "$NO_TLS" == "false" ]]; then
    if [[ "$CB_CERT_TYPE" == "letsencrypt" ]]; then
      if [[ -n "$CB_FQDN" ]] && [[ -n "$CB_EMAIL" ]]; then
        cb_step "Validating Let's Encrypt prerequisites for $CB_FQDN"

        local fqdn_ip
        local server_ip
        fqdn_ip=$(dig +short "$CB_FQDN" 2>/dev/null | tail -n1)
        server_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+')

        if [[ -z "$fqdn_ip" ]]; then
          cb_warn "DNS lookup failed for $CB_FQDN, falling back to self-signed certificate"
          CB_CERT_TYPE="self-signed"
        elif [[ "$fqdn_ip" != "$server_ip" ]]; then
          cb_warn "DNS mismatch: $CB_FQDN resolves to $fqdn_ip but server IP is $server_ip"
          cb_warn "Let's Encrypt requires DNS to point to this server, falling back to self-signed"
          CB_CERT_TYPE="self-signed"
        else
          cb_ok "DNS validation passed — Caddy will obtain and renew the certificate automatically"
          tls_line="tls ${CB_EMAIL}"
        fi
      else
        cb_warn "Let's Encrypt requires both --fqdn and --email, falling back to self-signed"
        CB_CERT_TYPE="self-signed"
      fi
    fi

    # Generate self-signed certificate if Let's Encrypt is not in use
    if [[ "$CB_CERT_TYPE" == "self-signed" ]]; then
      cb_step "Generating self-signed TLS certificate"
      local cert_cn="${CB_FQDN:-circuitbreaker}"
      local cert_ip
      cert_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || true)
      local san="DNS:${cert_cn}"
      [[ -n "$cert_ip" ]] && san="${san},IP:${cert_ip}"
      openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
        -keyout "${CB_DATA_DIR}/tls/privkey.pem" \
        -out "${CB_DATA_DIR}/tls/fullchain.pem" \
        -subj "/CN=${cert_cn}/O=CircuitBreaker" \
        -addext "subjectAltName=${san}" >> "$LOG_FILE" 2>&1
      chown root:caddy "${CB_DATA_DIR}/tls"/*.pem
      chmod 640 "${CB_DATA_DIR}/tls"/*.pem
      tls_line="tls ${cert_path}/fullchain.pem ${cert_path}/privkey.pem"
      cb_ok "Self-signed TLS certificate generated"
    fi

    if [[ -n "${cert_ip:-}" ]]; then
      site_address="${CB_FQDN:-circuitbreaker.lab}, https://${cert_ip}"
    else
      site_address="${CB_FQDN:-circuitbreaker.lab}"
    fi
  else
    # Plain HTTP mode
    site_address="http://${CB_FQDN:-circuitbreaker.lab}:${CB_PORT}"
  fi

  # HSTS is only safe over HTTPS; omit it when NO_TLS=true
  local hsts_header=""
  [[ "$NO_TLS" == "false" ]] && hsts_header='Strict-Transport-Security "max-age=63072000; includeSubDomains"'

  # Write Caddyfile
  cb_step "Writing Caddy configuration"
  mkdir -p /etc/caddy

  cat > /etc/caddy/Caddyfile <<EOF
{
    admin off
}

${site_address} {
    ${tls_line}

    encode gzip

    # Security headers
    header {
        Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'strict-dynamic'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://www.gravatar.com https://secure.gravatar.com https://avatars.githubusercontent.com; connect-src 'self' ws: wss: https://geocoding-api.open-meteo.com https://api.open-meteo.com; frame-ancestors 'none';"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        ${hsts_header}
        Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
        -Server
    }

    # Long-term caching for hashed static assets
    @staticAssets path_regexp \.(js|css|woff2?|ttf|eot|png|jpg|jpeg|gif|svg|ico|webp)$
    header @staticAssets Cache-Control "public, max-age=31536000, immutable"
    header /index.html Cache-Control "no-cache, no-store, must-revalidate"

    # API + WebSocket streams
    # Caddy automatically handles WebSocket upgrades (Upgrade/Connection headers)
    # flush_interval -1 disables buffering for SSE (/api/v1/events/stream)
    handle /api/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up Host {host}
            header_up X-Real-IP {remote_host}
            flush_interval -1
            transport http {
                dial_timeout 5s
                response_header_timeout 0
                write_timeout 3600s
            }
        }
    }

    handle /user-icons/* {
        reverse_proxy localhost:8000
    }

    handle /branding/* {
        reverse_proxy localhost:8000
    }

    handle /uploads/* {
        reverse_proxy localhost:8000
    }

    # Frontend SPA — catch-all falls back to index.html for client-side routing
    handle {
        root * /opt/circuitbreaker/apps/frontend/dist
        try_files {path} /index.html
        file_server
    }
}
EOF

  cb_ok "Caddy configuration written"

  # Validate Caddyfile
  cb_step "Validating Caddy configuration"
  if ! caddy validate --config /etc/caddy/Caddyfile 2>/dev/null; then
    cb_fail "Caddy config invalid" "Check: caddy validate --config /etc/caddy/Caddyfile"
  fi
  cb_ok "Caddy configuration validated"

  ensure_hosts_entry

  cb_ok "Caddy configured (will start after frontend build)"
}

# ============================================================================
# STAGE 3: DOCKER SOCKET PROXY
# ============================================================================

stage3_configure_docker_proxy() {
  if [[ "$DOCKER_AVAILABLE" != "true" ]]; then
    cb_warn "Skipping Docker socket proxy (Docker not available)"
    # Ensure .env has DOCKER_PROXY_ENABLED=false for the CLI runtime check
    if ! grep -q "^DOCKER_PROXY_ENABLED=" /etc/circuitbreaker/.env; then
      printf '\n# ===== Docker socket proxy =====\nDOCKER_HOST=\nDOCKER_PROXY_ENABLED=false\n' \
        >> /etc/circuitbreaker/.env
    fi
    return
  fi

  cb_section "Configuring Docker Socket Proxy"

  # Pull the proxy image
  cb_step "Pulling docker-socket-proxy image"
  docker pull tecnativa/docker-socket-proxy:latest >> "$LOG_FILE" 2>&1 || \
    cb_fail "Failed to pull docker-socket-proxy image" \
            "Check: docker pull tecnativa/docker-socket-proxy"
  cb_ok "Image pulled"

  # Write proxy allowlist env file — only permits read-only telemetry endpoints
  cb_step "Writing Docker proxy allowlist"
  cat > /etc/circuitbreaker/docker-proxy.env <<'PROXYENV'
# Docker socket proxy allowlist — read-only telemetry endpoints only
# See: https://github.com/Tecnativa/docker-socket-proxy

# Permitted — endpoints the CB backend calls for container telemetry
CONTAINERS=1
INFO=1
VERSION=1
NETWORKS=1
VOLUMES=1
IMAGES=1
STATS=1

# Blocked — all write and privileged operations
AUTH=0
BUILD=0
COMMIT=0
CONFIGS=0
CONTAINERS_CREATE=0
CONTAINERS_DELETE=0
CONTAINERS_EXEC=0
CONTAINERS_KILL=0
CONTAINERS_PAUSE=0
CONTAINERS_RENAME=0
CONTAINERS_RESTART=0
CONTAINERS_START=0
CONTAINERS_STOP=0
CONTAINERS_UNPAUSE=0
CONTAINERS_UPDATE=0
EVENTS=0
EXEC=0
NODES=0
PLUGINS=0
POST=0
PRUNE=0
SECRETS=0
SERVICES=0
SESSION=0
SWARM=0
SYSTEM=0
TASKS=0
PROXYENV
  chmod 640 /etc/circuitbreaker/docker-proxy.env
  chown root:breaker /etc/circuitbreaker/docker-proxy.env
  cb_ok "Allowlist written to /etc/circuitbreaker/docker-proxy.env"

  # Inject DOCKER_HOST into .env (idempotent — skip if already present)
  if ! grep -q "^DOCKER_PROXY_ENABLED=" /etc/circuitbreaker/.env; then
    cat >> /etc/circuitbreaker/.env <<'ENVEOF'

# ===== Docker socket proxy =====
DOCKER_HOST=tcp://127.0.0.1:2375
DOCKER_PROXY_ENABLED=true
ENVEOF
    cb_ok "DOCKER_HOST injected into .env"
  else
    cb_ok "Docker env vars already present — skipping"
  fi

  cb_ok "Docker socket proxy configured"
}

# ============================================================================
# WAIT-FOR-SERVICES SCRIPT
# ============================================================================

write_wait_for_services_script() {
  cb_section "Creating Service Health Check Script"
  cb_step "Writing wait-for-services.sh"
  echo "    Location: /opt/circuitbreaker/scripts/wait-for-services.sh"
  echo "    Purpose: Pre-start verification for backend API"
  
  mkdir -p /opt/circuitbreaker/scripts
  
  cat > /opt/circuitbreaker/scripts/wait-for-services.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

set -a
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
}

wait_port "pgbouncer"  127.0.0.1 6432

# Redis: authenticated PING — port-open is not enough when requirepass is set
echo "Waiting for Redis to accept authenticated connections..."
elapsed=0
while ! redis-cli -h 127.0.0.1 -p 6379 -a "${CB_REDIS_PASS}" --no-auth-warning PING 2>/dev/null | grep -q PONG; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Redis did not accept authenticated connections within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# NATS: JetStream health endpoint — TCP-open does not mean JetStream is initialised
echo "Waiting for NATS JetStream to become ready..."
elapsed=0
while ! curl -sf http://127.0.0.1:8222/healthz >/dev/null 2>&1; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: NATS JetStream did not become ready within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# Actual DB connection test - port open ≠ DB accepting connections
echo "Waiting for DB to accept connections..."
elapsed=0
while ! PGPASSWORD="$CB_DB_PASSWORD" psql -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -c '\q' 2>/dev/null; do
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
  if [[ $elapsed -ge $MAX_WAIT ]]; then
    echo "FATAL: Cannot connect to DB through pgbouncer within ${MAX_WAIT}s" >&2
    exit 1
  fi
done

# Docker socket proxy — only check when Docker is enabled
if [[ "${DOCKER_PROXY_ENABLED:-false}" == "true" ]]; then
  echo "Waiting for Docker socket proxy..."
  elapsed=0
  while ! curl -sf http://127.0.0.1:2375/version &>/dev/null; do
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
    if [[ $elapsed -ge $MAX_WAIT ]]; then
      echo "FATAL: Docker socket proxy not responding within ${MAX_WAIT}s" >&2
      echo "Check: journalctl -u circuitbreaker-docker-proxy -n 30" >&2
      exit 1
    fi
  done
  echo "Docker proxy ready (${elapsed}s)"
fi
EOF
  
  chmod 755 /opt/circuitbreaker/scripts/wait-for-services.sh
  chown root:root /opt/circuitbreaker/scripts/wait-for-services.sh
  
  cb_ok "wait-for-services.sh created"
}

# ============================================================================
# STAGE 5: CODE DEPLOYMENT
# ============================================================================

stage5_deploy_code() {
  cb_section "Deploying Application Code"
  
  if [[ -d /opt/circuitbreaker/.git ]]; then
    cb_step "Updating existing repository"
    echo "    Branch: $CB_BRANCH"
    git -C /opt/circuitbreaker fetch origin >> "$LOG_FILE" 2>&1
    git -C /opt/circuitbreaker checkout "$CB_BRANCH" >> "$LOG_FILE" 2>&1
    git -C /opt/circuitbreaker pull origin "$CB_BRANCH" >> "$LOG_FILE" 2>&1
    cb_ok "Repository updated"
  else
    # Remove non-git directory if it exists
    if [[ -d /opt/circuitbreaker ]] && [[ ! -d /opt/circuitbreaker/.git ]]; then
      cb_step "Removing incomplete installation directory"
      rm -rf /opt/circuitbreaker/apps /opt/circuitbreaker/scripts
      cb_ok "Cleaned up"
    fi
    
    cb_step "Cloning repository from GitHub"
    echo "    Repo: github.com/BlkLeg/CircuitBreaker"
    echo "    Branch: $CB_BRANCH"
    echo "    Location: /opt/circuitbreaker"
    if ! git clone --branch "$CB_BRANCH" --depth 1 \
      https://github.com/BlkLeg/CircuitBreaker.git \
      /opt/circuitbreaker >> "$LOG_FILE" 2>&1; then
      cb_fail "Git clone failed" "Check: tail -50 ${LOG_FILE}"
    fi
    cb_ok "Repository cloned"
  fi
  
  # Fix ownership
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend
  chown -R root:root /opt/circuitbreaker/apps/frontend
  
  cb_ok "Code deployed to /opt/circuitbreaker"
}

# ============================================================================
# STAGE 6: PYTHON SETUP & MIGRATIONS
# ============================================================================

stage6_setup_python() {
  cb_section "Python Backend Setup"
  
  # Create virtual environment
  cb_step "Creating Python virtual environment"
  echo "    Location: /opt/circuitbreaker/apps/backend/venv"
  python3.12 -m venv /opt/circuitbreaker/apps/backend/venv >> "$LOG_FILE" 2>&1
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend/venv
  cb_ok "Virtual environment created"
  
  # Install dependencies as breaker user
  cb_step "Installing Python dependencies (may take 1-2 minutes)"
  echo "    Installing from: apps/backend/requirements.txt"
  su -s /bin/bash breaker -c "
    source /opt/circuitbreaker/apps/backend/venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r /opt/circuitbreaker/apps/backend/requirements.txt -r /opt/circuitbreaker/apps/backend/requirements-pg.txt
    pip install --quiet -e /opt/circuitbreaker/apps/backend/
  " >> "$LOG_FILE" 2>&1
  cb_ok "Python dependencies installed"
  
  # Run database migrations
  cb_step "Running database migrations (alembic upgrade head)"
  source /etc/circuitbreaker/.env
  echo "    Database: circuitbreaker@127.0.0.1:6432 (via pgbouncer)"
  su -s /bin/bash breaker -c "
    set -a
    source /etc/circuitbreaker/.env
    set +a
    cd /opt/circuitbreaker/apps/backend
    /opt/circuitbreaker/apps/backend/venv/bin/alembic upgrade head
  " >> "$LOG_FILE" 2>&1
  
  # Verify migrations ran
  local migration_count=$(PGPASSWORD="$CB_DB_PASSWORD" psql \
    -h 127.0.0.1 -p 6432 -U breaker -d circuitbreaker -tAc \
    "SELECT COUNT(*) FROM alembic_version" 2>/dev/null || echo "0")
  
  if [[ "$migration_count" -gt 0 ]]; then
    echo "    Migrations applied: $migration_count"
    cb_ok "Database schema ready"
  else
    cb_fail "Database migrations did not run" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi

  cb_step "Granting NET_RAW capability to venv Python interpreter"
  if command -v setcap &>/dev/null; then
    _py_real=$(realpath /opt/circuitbreaker/apps/backend/venv/bin/python3.12 2>/dev/null \
               || echo /opt/circuitbreaker/apps/backend/venv/bin/python3.12)
    if setcap cap_net_raw+ep "$_py_real" >> "$LOG_FILE" 2>&1; then
      cb_ok "NET_RAW capability granted"
    else
      cb_warn "setcap failed — SNMP/ICMP telemetry may not function"
    fi
  else
    cb_warn "setcap not found — install libcap2-bin and re-run"
  fi
}

# ============================================================================
# STAGE 7: FRONTEND BUILD
# ============================================================================

stage7_build_frontend() {
  cb_section "Frontend Build"
  
  cb_step "Installing Node.js dependencies (may take 1-2 minutes)"
  cd /opt/circuitbreaker/apps/frontend
  echo "    Running: npm ci"
  if ! npm ci >> "${CB_DATA_DIR}/logs/install.log" 2>&1; then
    cb_fail "npm install failed" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  cb_ok "Node dependencies installed"
  
  cb_step "Building frontend application (React + Vite, may take 1-2 minutes)"
  echo "    Running: npm run build"
  if ! npm run build >> "${CB_DATA_DIR}/logs/install.log" 2>&1; then
    cb_fail "Frontend build failed" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  
  # Verify build output
  if [[ ! -f /opt/circuitbreaker/apps/frontend/dist/index.html ]]; then
    cb_fail "Frontend build produced no output" "Check: tail -50 ${CB_DATA_DIR}/logs/install.log"
  fi
  
  # Fix permissions
  chown -R root:root /opt/circuitbreaker/apps/frontend/dist
  chmod -R 755 /opt/circuitbreaker/apps/frontend/dist
  
  echo "    Output: /opt/circuitbreaker/apps/frontend/dist/"
  cb_ok "Frontend built successfully"
}

# ============================================================================
# STAGE 8: START EVERYTHING & FINAL VERIFY
# ============================================================================

stage8_start_services() {
  cb_section "Starting Application Services"
  
  # Start backend
  cb_step "Starting backend API"
  if ! systemctl start circuitbreaker-backend >> "$LOG_FILE" 2>&1; then
    cb_fail "Backend failed to start" "Check: journalctl -u circuitbreaker-backend -n 100"
  fi
  
  # Wait for backend health endpoint
  local max_wait=30
  local elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null | grep -q '"ready"'; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [[ $elapsed -ge $max_wait ]]; then
      cb_fail "Backend API did not start" "Run: cb doctor"
    fi
  done
  cb_ok "Backend API started"
  
  # Start workers
  cb_step "Starting worker processes"
  systemctl start "circuitbreaker-worker@discovery" >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@webhook" >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@notification" >> "$LOG_FILE" 2>&1
  systemctl start "circuitbreaker-worker@telemetry" >> "$LOG_FILE" 2>&1
  sleep 2
  cb_ok "Workers started"
  
  # Start/reload Caddy
  cb_step "Starting Caddy"
  if systemctl is-active caddy &>/dev/null; then
    systemctl reload caddy >> "$LOG_FILE" 2>&1 || cb_fail "Caddy reload failed" "Check: caddy validate --config /etc/caddy/Caddyfile && journalctl -u caddy -n 50"
  else
    systemctl start caddy >> "$LOG_FILE" 2>&1 || cb_fail "Caddy failed to start" "Check: journalctl -u caddy -n 50"
  fi
  sleep 1

  local caddy_port=443
  [[ "$NO_TLS" == "true" ]] && caddy_port="$CB_PORT"
  if ! nc -z 127.0.0.1 "$caddy_port" 2>/dev/null; then
    cb_fail "Caddy not listening on port $caddy_port" "Check: journalctl -u caddy -n 50"
  fi
  cb_ok "Caddy started"
  
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
  cb_section "Installing Management CLI"
  cb_step "Installing cb command-line tool"
  echo "    Location: /usr/local/bin/cb"
  echo "    Commands: status, doctor, logs, restart, backup, update, version, uninstall"
  
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
[[ "${DOCKER_PROXY_ENABLED:-false}" == "true" ]] && \
  SERVICES+=("circuitbreaker-docker-proxy")

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
  if [[ "${DOCKER_PROXY_ENABLED:-false}" == "true" ]]; then
    check "Docker proxy (2375)" \
      "curl -sf http://127.0.0.1:2375/version" \
      "journalctl -u circuitbreaker-docker-proxy -n 30"
  fi
  check "caddy (443)"        "nc -z 127.0.0.1 443"             "caddy validate --config /etc/caddy/Caddyfile && journalctl -u caddy -n 30"
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
    -u caddy
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

  echo "Stopping Docker proxy container..."
  docker stop cb-docker-proxy 2>/dev/null || true
  docker rm cb-docker-proxy 2>/dev/null || true

  echo "Stopping and disabling all services..."
  systemctl stop \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry" \
    caddy 2>/dev/null || true

  systemctl disable \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry" \
    circuitbreaker-docker-proxy \
    circuitbreaker.target caddy 2>/dev/null || true

  echo "Killing any remaining CircuitBreaker processes..."
  pkill -u breaker 2>/dev/null || true
  sleep 2
  pkill -9 -u breaker 2>/dev/null || true

  echo "Removing systemd unit files..."
  rm -f /etc/systemd/system/circuitbreaker-*.service
  rm -f /etc/systemd/system/circuitbreaker.target
  systemctl daemon-reload
  systemctl reset-failed 2>/dev/null || true

  echo "Removing application files..."
  rm -rf /opt/circuitbreaker /etc/circuitbreaker /etc/nats
  rm -rf "${CB_DATA_DIR}"

  echo "Removing Caddy configuration..."
  rm -f /etc/caddy/Caddyfile

  echo "Removing NATS binary..."
  rm -f /usr/local/bin/nats-server

  echo "Removing CB CLI..."
  rm -f /usr/local/bin/cb

  echo "Removing system user..."
  userdel -r breaker 2>/dev/null || userdel breaker 2>/dev/null || true

  echo "Removing /etc/hosts entry..."
  if [[ -n "${CB_FQDN:-}" ]]; then
    sed -i "/[[:space:]]${CB_FQDN}$/d" /etc/hosts
  fi

  echo "Removing Caddy apt repository..."
  rm -f /etc/apt/sources.list.d/caddy-stable.list
  rm -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  apt-get remove -y caddy 2>/dev/null || dnf remove -y caddy 2>/dev/null || true

  echo "Removing NodeSource repository..."
  rm -f /etc/apt/sources.list.d/nodesource.list
  rm -f /usr/share/keyrings/nodesource.gpg

  echo "Circuit Breaker fully removed."
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
  source /etc/circuitbreaker/.env
  local detected_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")
  local version=$(cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "unknown")
  
  cb_section "Circuit Breaker is running!"
  echo ""
  
  # Build list of accessible URLs
  echo -e "  ${BOLD}${GREEN}Access URLs:${RESET}"
  echo ""
  
  if [[ "$NO_TLS" == "false" ]]; then
    # HTTPS is available
    if [[ -n "$CB_FQDN" ]]; then
      echo -e "  ${GREEN}✓${RESET}  https://${CB_FQDN}/ ${BOLD}(PRIMARY - Use this for account creation)${RESET}"
      if [[ "$CB_CERT_TYPE" == "letsencrypt" ]]; then
        echo -e "     ${DIM}Certificate: Let's Encrypt (trusted)${RESET}"
      else
        echo -e "     ${DIM}Certificate: Self-signed (accept browser warning)${RESET}"
      fi
    else
      echo -e "  ${GREEN}✓${RESET}  https://${detected_ip}/ ${BOLD}(PRIMARY - Use this for account creation)${RESET}"
      echo -e "     ${DIM}Certificate: Self-signed (accept browser warning)${RESET}"
    fi
    
    # HTTP fallback (but warn about limitations)
    if [[ -n "$CB_FQDN" ]]; then
      echo -e "  ${YELLOW}⚠${RESET}  http://${CB_FQDN}:${CB_PORT}/ ${DIM}(Limited - no account creation)${RESET}"
    fi
    echo -e "  ${YELLOW}⚠${RESET}  http://${detected_ip}:${CB_PORT}/ ${DIM}(Limited - no account creation)${RESET}"
  else
    # No TLS - HTTP only
    if [[ -n "$CB_FQDN" ]]; then
      echo -e "  ${GREEN}✓${RESET}  http://${CB_FQDN}:${CB_PORT}/"
    fi
    echo -e "  ${GREEN}✓${RESET}  http://${detected_ip}:${CB_PORT}/"
    echo -e "  ${RED}⚠  WARNING: No HTTPS - account creation may not work!${RESET}"
  fi
  
  echo ""
  echo -e "  ┌──────────────────────────────────────────────┐"
  echo -e "  │  Version:  ${version}"
  if [[ -n "$CB_FQDN" ]]; then
    echo -e "  │  Domain:   ${CB_FQDN}"
  fi
  if [[ "$NO_TLS" == "false" ]]; then
    echo -e "  │  TLS:      ${CB_CERT_TYPE}"
  fi
  echo -e "  ├──────────────────────────────────────────────┤"
  echo -e "  │  Status:   cb status"
  echo -e "  │  Health:   cb doctor"
  echo -e "  │  Logs:     cb logs"
  echo -e "  └──────────────────────────────────────────────┘"
  echo ""
  
  if [[ "$NO_TLS" == "false" ]]; then
    echo -e "  ${YELLOW}${BOLD}⚠  CRITICAL: Account creation requires HTTPS${RESET}"
    echo -e "     Modern browsers block crypto APIs on insecure HTTP connections."
    echo -e "     ${BOLD}Always use the HTTPS URL above${RESET} when creating accounts."
    if [[ "$CB_CERT_TYPE" == "self-signed" ]]; then
      echo -e "     You will see a certificate warning - click 'Advanced' → 'Proceed'."
    fi
    echo ""
  fi
  
  echo -e "  ${BOLD}Centralized Logs:${RESET}"
  echo -e "    ${CB_DATA_DIR}/logs/install.log       (this install)"
  echo -e "    journalctl -u circuitbreaker-backend  (API logs)"
  echo -e "    journalctl -u circuitbreaker-worker@* (worker logs)"
  echo -e "    journalctl -u circuitbreaker-postgres (database)"
  echo -e "    journalctl -u circuitbreaker-redis    (cache)"
  echo -e "    journalctl -u circuitbreaker-nats     (messaging)"
  echo ""
  echo -e "  ${GREEN}${BOLD}Installation complete!${RESET} Open the HTTPS URL above to get started."
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

  ensure_hosts_entry
  
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
  write_wait_for_services_script
  stage4_write_systemd_units
  stage3_configure_docker_proxy

  # Show changelog
  if [[ "$old_head" != "unknown" ]]; then
    cb_section "Changes in this update"
    git -C /opt/circuitbreaker log --oneline "${old_head}..HEAD" 2>/dev/null || echo "  (changelog unavailable)"
  fi
  
  # Update Python dependencies
  stage6_setup_python
  # Re-apply NET_RAW after venv rebuild (setcap is wiped when venv is recreated)
  if command -v setcap &>/dev/null; then
    _py_real=$(realpath /opt/circuitbreaker/apps/backend/venv/bin/python3.12 2>/dev/null \
               || echo /opt/circuitbreaker/apps/backend/venv/bin/python3.12)
    setcap cap_net_raw+ep "$_py_real" >> "$LOG_FILE" 2>&1 || \
      cb_warn "setcap failed — SNMP/ICMP telemetry may not function"
  fi

  # Rebuild frontend
  stage7_build_frontend
  
  # Restart services
  cb_step "Restarting all services"
  systemctl start circuitbreaker.target >> "$LOG_FILE" 2>&1
  sleep 5
  
  # Wait for backend
  local max_wait=30
  local elapsed=0
  until curl -sf http://127.0.0.1:8000/api/v1/health 2>/dev/null | grep -q '"ready"'; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [[ $elapsed -ge $max_wait ]]; then
      cb_fail "Backend did not start after upgrade" "Run: cb doctor"
    fi
  done
  cb_ok "Services restarted"

  stage9_install_cb_cli
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
  
  # Configure services
  stage3_configure_postgres
  stage3_configure_pgbouncer
  stage3_configure_redis
  stage3_configure_nats
  stage3_configure_caddy
  stage3_configure_docker_proxy

  # Deploy and build
  stage5_deploy_code
  write_wait_for_services_script
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

