#!/usr/bin/env bash
set -euo pipefail


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
    # Temporarily disable set -u to check for missing vars
    set +u
    source /etc/circuitbreaker/.env
    set -u
    
    local appended="false"
    if [[ -z "${CB_JWT_SECRET:-}" ]]; then
      CB_JWT_SECRET=$(openssl rand -hex 64)
      echo "CB_JWT_SECRET=${CB_JWT_SECRET}" >> /etc/circuitbreaker/.env
      appended="true"
    fi
    if [[ -z "${CB_VAULT_KEY:-}" ]]; then
      CB_VAULT_KEY=$(openssl rand -base64 32 | tr '/+' '_-')
      echo "CB_VAULT_KEY=${CB_VAULT_KEY}" >> /etc/circuitbreaker/.env
      appended="true"
    fi
    if [[ -z "${CB_DB_PASSWORD:-}" ]]; then
      CB_DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
      echo "CB_DB_PASSWORD=${CB_DB_PASSWORD}" >> /etc/circuitbreaker/.env
      echo "CB_DB_URL=postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker" >> /etc/circuitbreaker/.env
      echo "CB_DB_POOL_URL=postgresql://breaker:${CB_DB_PASSWORD}@127.0.0.1:6432/circuitbreaker" >> /etc/circuitbreaker/.env
      appended="true"
    fi
    if [[ -z "${CB_REDIS_PASSWORD:-}" ]]; then
      CB_REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
      echo "CB_REDIS_PASSWORD=${CB_REDIS_PASSWORD}" >> /etc/circuitbreaker/.env
      echo "CB_REDIS_URL=redis://:${CB_REDIS_PASSWORD}@127.0.0.1:6379/0" >> /etc/circuitbreaker/.env
      appended="true"
    fi
    if [[ -z "${CB_NATS_TOKEN:-}" ]]; then
      CB_NATS_TOKEN=$(openssl rand -base64 48 | tr -d '/+=')
      echo "CB_NATS_TOKEN=${CB_NATS_TOKEN}" >> /etc/circuitbreaker/.env
      echo "CB_NATS_URL=nats://127.0.0.1:4222" >> /etc/circuitbreaker/.env
      appended="true"
    fi

    if [[ "$appended" == "true" ]]; then
      cb_ok "Added missing secrets to existing .env"
    fi
    # Re-source to ensure everything is in the environment
    set +u
    source /etc/circuitbreaker/.env
    set -u
  else
    cb_step "Generating secrets"
    
    # Export as environment variables so cb_render_template can access them
    export CB_JWT_SECRET=$(openssl rand -hex 64)
    export CB_VAULT_KEY=$(openssl rand -base64 32 | tr '/+' '_-')
    export CB_DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    export CB_REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
    export CB_NATS_TOKEN=$(openssl rand -base64 48 | tr -d '/+=' )
    
    export CB_DETECTED_IP=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")
    
    if ! cb_render_template "/opt/circuitbreaker/deploy/misc/.env.template" "/etc/circuitbreaker/.env"; then
      cb_fail "Failed to render .env template" "Check: /opt/circuitbreaker/deploy/misc/.env.template exists"
    fi
    
    chmod 640 /etc/circuitbreaker/.env
    chown root:breaker /etc/circuitbreaker/.env
    
    cb_ok "Secrets generated and saved"
    set +u
    source /etc/circuitbreaker/.env
    set -u
  fi

  # Detect Redis user (Arch uses 'redis', Debian uses 'redis', some RHEL might use '_redis')
  export CB_REDIS_USER="redis"
  if id redis &>/dev/null; then
    CB_REDIS_USER="redis"
  elif id _redis &>/dev/null; then
    CB_REDIS_USER="_redis"
  fi
  export CB_DATA_DIR
}

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

stage3_configure_postgres() {
  cb_section "Configuring PostgreSQL 15"
  
  # Validate required secrets are set
  if [[ -z "${CB_DB_PASSWORD:-}" ]]; then
    cb_fail "Database password not set" "This should have been generated in stage1_bootstrap — check /etc/circuitbreaker/.env"
  fi
  
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
  cb_render_template "/opt/circuitbreaker/deploy/config/postgresql.conf.template" "/tmp/snippet.temp"
  cat "/tmp/snippet.temp" >> "${CB_DATA_DIR}/postgres/postgresql.conf"
  rm -f "/tmp/snippet.temp"
  cb_render_template "/opt/circuitbreaker/deploy/config/pg_hba.conf" "${CB_DATA_DIR}/postgres/pg_hba.conf"
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
  
  # Validate required secrets are set
  if [[ -z "${CB_DB_PASSWORD:-}" ]]; then
    cb_fail "Database password not set" "This should have been generated in stage1_bootstrap — check /etc/circuitbreaker/.env"
  fi
  
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
  export pgbouncer_hash=$(echo -n "${CB_DB_PASSWORD}breaker" | md5sum | cut -d' ' -f1)
  echo "    Pool port: 6432, Backend: PostgreSQL 5432"
  
  mkdir -p /etc/pgbouncer
  
  # Write userlist.txt
  cb_render_template "/opt/circuitbreaker/deploy/config/userlist.txt" "/etc/pgbouncer/userlist.txt"  
  chown postgres:postgres /etc/pgbouncer/userlist.txt
  chmod 600 /etc/pgbouncer/userlist.txt
  
  # Write pgbouncer.ini
  cb_render_template "/opt/circuitbreaker/deploy/config/pgbouncer.ini" "/etc/pgbouncer/pgbouncer.ini"  
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
  
  # Validate required secrets are set
  if [[ -z "${CB_REDIS_PASSWORD:-}" ]]; then
    cb_fail "Redis password not set" "This should have been generated in stage1_bootstrap — check /etc/circuitbreaker/.env"
  fi
  
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
  mkdir -p "${CB_DATA_DIR}/redis"
  chown "${CB_REDIS_USER}:${CB_REDIS_USER}" "${CB_DATA_DIR}/redis"
  chmod 755 "${CB_DATA_DIR}/redis"
  echo "    Redis data: ${CB_DATA_DIR}/redis (${CB_REDIS_USER}:${CB_REDIS_USER})"
  
  cb_render_template "/opt/circuitbreaker/deploy/config/redis.conf" "/etc/redis/redis.conf"
  chown "${CB_REDIS_USER}:${CB_REDIS_USER}" /etc/redis/redis.conf
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
  if ! redis-cli -a "$CB_REDIS_PASSWORD" --no-auth-warning PING 2>/dev/null | grep -q PONG; then
    cb_fail "Redis not responding" "Check: journalctl -u circuitbreaker-redis -n 50"
  fi
  cb_ok "Redis connection verified"
}

stage3_configure_nats() {
  cb_section "Configuring NATS"
  
  # Validate required secrets are set
  if [[ -z "${CB_NATS_TOKEN:-}" ]]; then
    cb_fail "NATS token not set" "This should have been generated in stage1_bootstrap — check /etc/circuitbreaker/.env"
  fi
  
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
  cb_render_template "/opt/circuitbreaker/deploy/config/nats.conf" "/etc/nats/nats.conf"  
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

stage3_configure_nginx() {
  cb_section "Configuring Nginx"

  local cert_path="${CB_DATA_DIR}/tls"
  local use_tls=true

  # TLS certificate generation
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
          cb_ok "DNS validation passed for $CB_FQDN"
          # Let's Encrypt certs are expected to already be at cert_path (e.g. via certbot)
        fi
      else
        cb_warn "Let's Encrypt requires both --fqdn and --email, falling back to self-signed"
        CB_CERT_TYPE="self-signed"
      fi
    fi

    # Generate self-signed certificate if Let's Encrypt is not in use
    if [[ "$CB_CERT_TYPE" == "self-signed" ]]; then
      local cert_cn="${CB_FQDN:-circuitbreaker}"
      local cert_ip
      cert_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || true)
      if [[ ! -f "${CB_DATA_DIR}/tls/fullchain.pem" ]]; then
        cb_step "Generating self-signed TLS certificate"
        local san="DNS:${cert_cn}"
        [[ -n "$cert_ip" ]] && san="${san},IP:${cert_ip}"
        openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
          -keyout "${CB_DATA_DIR}/tls/privkey.pem" \
          -out "${CB_DATA_DIR}/tls/fullchain.pem" \
          -subj "/CN=${cert_cn}/O=CircuitBreaker" \
          -addext "subjectAltName=${san}" >> "$LOG_FILE" 2>&1
        cb_ok "Self-signed TLS certificate generated"
      else
        cb_ok "TLS certificate already exists — reusing"
      fi
    fi

    # Nginx master reads certs as root; worker runs as nginx/www-data
    local nginx_group="nginx"
    id -g nginx &>/dev/null || nginx_group="www-data"
    chown -R root:"$nginx_group" "${CB_DATA_DIR}/tls"
    chmod 750 "${CB_DATA_DIR}/tls"
    chmod 640 "${CB_DATA_DIR}/tls"/*.pem
  else
    use_tls=false
  fi

  # Write Nginx configuration
  cb_step "Writing Nginx configuration"

  # Build server_name directive
  local server_name="${CB_FQDN:-_}"
  local cert_ip
  cert_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || true)

  if [[ "$use_tls" == "true" ]]; then
    # TLS mode: HTTPS on 443 + HTTP→HTTPS redirect on CB_PORT
    cb_render_template "/opt/circuitbreaker/deploy/nginx/circuitbreaker-tls.conf" "/etc/nginx/conf.d/circuitbreaker.conf"
  else
    # NO_TLS mode: plain HTTP on CB_PORT
    cb_render_template "/opt/circuitbreaker/deploy/nginx/circuitbreaker.conf" "/etc/nginx/conf.d/circuitbreaker.conf"
  fi

  cb_ok "Nginx configuration written"

  # Remove default site that conflicts on port 80/443
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

  # Validate config
  cb_step "Validating Nginx configuration"
  if ! nginx -t >> "$LOG_FILE" 2>&1; then
    cb_fail "Nginx config validation failed" "Check: nginx -t"
  fi
  cb_ok "Nginx configuration validated"

  ensure_hosts_entry

  cb_ok "Nginx configured (will start after frontend build)"
}

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
  cp "/opt/circuitbreaker/deploy/misc/docker-proxy.env" "/etc/circuitbreaker/docker-proxy.env"
  chmod 640 /etc/circuitbreaker/docker-proxy.env
  chown root:breaker /etc/circuitbreaker/docker-proxy.env
  cb_ok "Allowlist written to /etc/circuitbreaker/docker-proxy.env"

  # Inject DOCKER_HOST into .env (idempotent — skip if already present)
  if ! grep -q "^DOCKER_PROXY_ENABLED=" /etc/circuitbreaker/.env; then
    cat "/opt/circuitbreaker/deploy/misc/.env.template" >> "/etc/circuitbreaker/.env"
    cb_ok "DOCKER_HOST injected into .env"
  else
    cb_ok "Docker env vars already present — skipping"
  fi

  cb_ok "Docker socket proxy configured"
}

write_wait_for_services_script() {
  cb_section "Creating Service Health Check Script"
  cb_step "Writing wait-for-services.sh"
  echo "    Location: /opt/circuitbreaker/scripts/wait-for-services.sh"
  echo "    Purpose: Pre-start verification for backend API"
  
  mkdir -p /opt/circuitbreaker/scripts
  
  cp "/opt/circuitbreaker/deploy/scripts/wait-for-services.sh" "/opt/circuitbreaker/scripts/wait-for-services.sh"  
  chmod 755 /opt/circuitbreaker/scripts/wait-for-services.sh
  chown root:root /opt/circuitbreaker/scripts/wait-for-services.sh
  
  cb_ok "wait-for-services.sh created"
}

write_service_scripts() {
  cb_section "Writing Service Scripts"
  mkdir -p /opt/circuitbreaker/scripts

  # healthcheck.sh — liveness probe called by circuitbreaker-healthcheck.timer
  cb_step "Writing healthcheck.sh"
  cp "/opt/circuitbreaker/deploy/scripts/healthcheck.sh" "/opt/circuitbreaker/scripts/healthcheck.sh"
  chmod 700 /opt/circuitbreaker/scripts/healthcheck.sh
  chown root:root /opt/circuitbreaker/scripts/healthcheck.sh

  # validate-secrets.sh — pre-start guard called as ExecStartPre in backend.service
  cb_step "Writing validate-secrets.sh"
  cp "/opt/circuitbreaker/deploy/scripts/validate-secrets.sh" "/opt/circuitbreaker/scripts/validate-secrets.sh"
  chmod 750 /opt/circuitbreaker/scripts/validate-secrets.sh
  chown root:breaker /opt/circuitbreaker/scripts/validate-secrets.sh

  cb_ok "Service scripts created"
}

stage4_write_systemd_units() {
  cb_section "Writing systemd Service Units"
  cb_step "Creating systemd unit files"
  echo "    All services will log to systemd journal"
  echo "    View with: journalctl -u circuitbreaker-<service>"

  # Detect Redis user for templating (Arch uses 'redis', Debian uses 'redis', some RHEL might use '_redis')
  export CB_REDIS_USER="redis"
  if id redis &>/dev/null; then
    CB_REDIS_USER="redis"
  elif id _redis &>/dev/null; then
    CB_REDIS_USER="_redis"
  fi

  # circuitbreaker-postgres.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-postgres.service" "/etc/systemd/system/circuitbreaker-postgres.service"
  # circuitbreaker-pgbouncer.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-pgbouncer.service" "/etc/systemd/system/circuitbreaker-pgbouncer.service"
  # circuitbreaker-redis.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-redis.service" "/etc/systemd/system/circuitbreaker-redis.service"
  # circuitbreaker-nats.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-nats.service" "/etc/systemd/system/circuitbreaker-nats.service"
  # circuitbreaker-backend.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-backend.service" "/etc/systemd/system/circuitbreaker-backend.service"
  # circuitbreaker-worker@.service (template)
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-worker@.service" "/etc/systemd/system/circuitbreaker-worker@.service"
  # circuitbreaker.target
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker.target" "/etc/systemd/system/circuitbreaker.target"
  # circuitbreaker-healthcheck.service
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-healthcheck.service" "/etc/systemd/system/circuitbreaker-healthcheck.service"
  # circuitbreaker-healthcheck.timer
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker-healthcheck.timer" "/etc/systemd/system/circuitbreaker-healthcheck.timer"
  # circuitbreaker.slice — aggregate memory cap across all CB services
  cb_render_template "/opt/circuitbreaker/deploy/systemd/circuitbreaker.slice" "/etc/systemd/system/circuitbreaker.slice"
  # circuitbreaker-docker-proxy.service — only written when Docker is present
  # is required by tecnativa/docker-socket-proxy to bind to the Docker socket.
  # Port 2375 is bound to 127.0.0.1 only — never 0.0.0.0 (unauthenticated Docker API).
  if [[ "$DOCKER_AVAILABLE" == "true" ]]; then
    cp "/opt/circuitbreaker/deploy/systemd/circuitbreaker-docker-proxy.service" "/etc/systemd/system/circuitbreaker-docker-proxy.service"
  fi

  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker.target >> "$LOG_FILE" 2>&1
  systemctl enable circuitbreaker.slice \
    circuitbreaker-postgres circuitbreaker-pgbouncer \
    circuitbreaker-redis circuitbreaker-nats circuitbreaker-backend \
    "circuitbreaker-worker@discovery" "circuitbreaker-worker@webhook" \
    "circuitbreaker-worker@notification" "circuitbreaker-worker@telemetry" \
    circuitbreaker-healthcheck.timer \
    nginx >> "$LOG_FILE" 2>&1
  [[ "$DOCKER_AVAILABLE" == "true" ]] && \
    systemctl enable circuitbreaker-docker-proxy >> "$LOG_FILE" 2>&1 || true

  cb_ok "Systemd units created and enabled"
}

stage6_setup_python() {
  cb_section "Python Backend Setup"
  
  # Create virtual environment
  cb_step "Creating Python virtual environment"
  echo "    Location: /opt/circuitbreaker/apps/backend/venv"
  if ! python3.12 -m venv /opt/circuitbreaker/apps/backend/venv >> "$LOG_FILE" 2>&1; then
    cb_fail "Python venv creation failed" "Is python3.12 installed? Check: python3.12 --version"
  fi
  chown -R breaker:breaker /opt/circuitbreaker/apps/backend/venv
  cb_ok "Virtual environment created"
  
  # Install dependencies as breaker user
  cb_step "Installing Python dependencies (may take 1-2 minutes)"
  echo "    Installing from: apps/backend/requirements.txt"
  if ! su -s /bin/bash breaker -c "
    source /opt/circuitbreaker/apps/backend/venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r /opt/circuitbreaker/apps/backend/requirements.txt -r /opt/circuitbreaker/apps/backend/requirements-pg.txt
    pip install --quiet -e /opt/circuitbreaker/apps/backend/
  " >> "$LOG_FILE" 2>&1; then
    cb_fail "Python dependency install failed" "Check: tail -100 ${CB_DATA_DIR}/logs/install.log"
  fi
  if [[ ! -x /opt/circuitbreaker/apps/backend/venv/bin/uvicorn ]]; then
    cb_fail "uvicorn not found after pip install" "Check: tail -100 ${CB_DATA_DIR}/logs/install.log"
  fi
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

stage8_start_services() {
  cb_section "Starting Application Services"

  # Pre-flight: verify critical paths exist before starting services
  for required_file in \
    /opt/circuitbreaker/scripts/validate-secrets.sh \
    /opt/circuitbreaker/scripts/wait-for-services.sh \
    /opt/circuitbreaker/apps/backend/venv/bin/uvicorn; do
    if [[ ! -x "$required_file" ]]; then
      cb_fail "Missing: $required_file" "A previous stage may have failed — check install.log"
    fi
  done

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
  
  # Start/restart Nginx
  cb_step "Starting Nginx"
  systemctl restart nginx >> "$LOG_FILE" 2>&1 || cb_fail "Nginx failed to start" "Check: nginx -t && journalctl -u nginx -n 50"
  sleep 1

  local nginx_port=443
  [[ "$NO_TLS" == "true" ]] && nginx_port="$CB_PORT"
  if ! nc -z 127.0.0.1 "$nginx_port" 2>/dev/null; then
    cb_fail "Nginx not listening on port $nginx_port" "Check: nginx -t && journalctl -u nginx -n 50"
  fi
  cb_ok "Nginx started"
  
  # Detect primary IP and update .env
  local detected_ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[^ ]+' || echo "localhost")
  if ! grep -q "CB_HOST_IP=" /etc/circuitbreaker/.env 2>/dev/null; then
    echo "CB_HOST_IP=$detected_ip" >> /etc/circuitbreaker/.env
  fi
  
  cb_ok "All services running"
}

stage9_install_cb_cli() {
  cb_section "Installing Management CLI"
  cb_step "Installing cb command-line tool"
  echo "    Location: /usr/local/bin/cb"
  echo "    Commands: status, doctor, logs, restart, backup, update, version, uninstall"
  
  cp "/opt/circuitbreaker/deploy/cli/cb" "/usr/local/bin/cb"  
  chmod 755 /usr/local/bin/cb
  chown root:root /usr/local/bin/cb
  
  cb_ok "CB CLI installed"
}

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

stage2_dependencies() {
  if [[ "$UPGRADE_MODE" == "true" ]] && [[ "$FORCE_DEPS" == "false" ]]; then
    cb_section "Dependencies"
    cb_ok "Skipping dependency installation (upgrade mode)"
    return
  fi

  cb_section "Installing Dependencies"

  # Group 0: SSH server — ensures remote access after install on bare LXC/VM templates
  cb_step "Ensuring SSH server is available"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    $PKG_MGR install -y -q openssh-server >> "$LOG_FILE" 2>&1
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -S --noconfirm --needed openssh >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q openssh-server >> "$LOG_FILE" 2>&1
  fi
  systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || true
  cb_ok "SSH server enabled"

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

  # Group 4: pgbouncer, Redis, Nginx
  cb_step "Installing pgbouncer, Redis, and Nginx"
  if [[ "$PKG_MGR" == "apt-get" ]]; then
    $PKG_MGR install -y -q pgbouncer redis-server nginx >> "$LOG_FILE" 2>&1
  elif [[ "$PKG_MGR" == "pacman" ]]; then
    pacman -S --noconfirm --needed pgbouncer redis nginx >> "$LOG_FILE" 2>&1
  else
    $PKG_MGR install -y -q pgbouncer redis nginx >> "$LOG_FILE" 2>&1
  fi

  # Stop nginx immediately — package auto-starts with default config
  systemctl stop nginx >> "$LOG_FILE" 2>&1 || true

  for bin in pgbouncer redis-server redis-cli nginx; do
    if ! command -v "$bin" &>/dev/null && ! command -v "${bin%-*}" &>/dev/null; then
      cb_fail "$bin not found after install" "Check: $PKG_MGR install logs"
    fi
  done
  cb_ok "pgbouncer, Redis, Nginx installed"

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
    # Arch does not provide a python3.12 binary — symlink if python3 is >= 3.12
    if ! command -v python3.12 &>/dev/null; then
      local arch_pyver
      arch_pyver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
      if [[ "$(echo -e "3.12\n$arch_pyver" | sort -V | head -1)" == "3.12" ]]; then
        ln -sf "$(command -v python3)" /usr/local/bin/python3.12
        cb_ok "Symlinked python3 ($arch_pyver) → python3.12"
      else
        cb_fail "Python >= 3.12 required, got $arch_pyver" "Install python >= 3.12"
      fi
    fi
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

  # Docker detection — enables container telemetry proxy when Docker is present
  cb_step "Checking for Docker daemon"
  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_AVAILABLE=true
    cb_ok "Docker detected — socket proxy will be configured"
  else
    # Offer to install Docker if not present and --docker wasn't already passed
    if [[ "$INSTALL_DOCKER" != "true" ]]; then
      if [[ "$UNATTENDED" == "false" ]]; then
        echo -e "  ${YELLOW}Docker not found.${RESET} Docker enables container telemetry."
        read -t 15 -r -p "  Install Docker CE? [y/N]: " docker_input || docker_input=""
        if [[ "$docker_input" =~ ^[Yy]$ ]]; then
          INSTALL_DOCKER=true
        fi
      else
        cb_warn "Docker not found — pass --docker to install it (enables container telemetry)"
      fi
    fi

    # Install Docker if requested (by flag or interactive prompt)
    if [[ "$INSTALL_DOCKER" == "true" ]]; then
      cb_step "Installing Docker CE"
      if [[ "$PKG_MGR" == "apt-get" ]]; then
        local docker_distro="$OS_ID"
        curl -fsSL "https://download.docker.com/linux/${docker_distro}/gpg" \
          | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg >> "$LOG_FILE" 2>&1
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
https://download.docker.com/linux/${docker_distro} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
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
      DOCKER_AVAILABLE=true
    else
      DOCKER_AVAILABLE=false
      if [[ "$UNATTENDED" == "false" ]]; then
        cb_warn "Docker skipped — container telemetry will be unavailable"
      fi
    fi
  fi
}

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
  
  # Code already updated by bootstrap script

  write_wait_for_services_script
  write_service_scripts

  # Docker install + detection must run BEFORE stage4 writes conditional systemd units
  # (stage4 checks DOCKER_AVAILABLE to decide whether to write the docker-proxy unit)
  if [[ "$INSTALL_DOCKER" == "true" ]] && ! command -v docker &>/dev/null; then
    cb_step "Installing Docker CE"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      local docker_distro="$OS_ID"
      curl -fsSL "https://download.docker.com/linux/${docker_distro}/gpg" \
        | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg >> "$LOG_FILE" 2>&1
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
https://download.docker.com/linux/${docker_distro} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
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

  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_AVAILABLE=true
  fi

  stage4_write_systemd_units

  # --- Caddy → Nginx migration (one-time) ---
  if ! command -v nginx &>/dev/null; then
    cb_step "Installing Nginx (replacing Caddy)"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      $PKG_MGR install -y -q nginx >> "$LOG_FILE" 2>&1
    elif [[ "$PKG_MGR" == "pacman" ]]; then
      pacman -S --noconfirm --needed nginx >> "$LOG_FILE" 2>&1
    else
      $PKG_MGR install -y -q nginx >> "$LOG_FILE" 2>&1
    fi
    systemctl stop nginx >> "$LOG_FILE" 2>&1 || true
    cb_ok "Nginx installed"
  fi

  # Stop Caddy if still present (port 443 conflict)
  if systemctl is-active caddy &>/dev/null 2>&1; then
    cb_step "Stopping Caddy (replaced by Nginx)"
    systemctl stop caddy >> "$LOG_FILE" 2>&1 || true
    systemctl disable caddy >> "$LOG_FILE" 2>&1 || true
    cb_ok "Caddy stopped and disabled"
  fi
  rm -f /etc/caddy/Caddyfile 2>/dev/null || true

  # Always regenerate Nginx config on upgrade (picks up CSP/config changes; certs preserved if existing)
  stage3_configure_nginx

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
  stage9_install_cb_cli

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

  stage10_final_output
}

