#!/usr/bin/env bash
#
# Circuit Breaker Installer
#
# GitHub : https://github.com/BlkLeg/circuitbreaker
# Issues : https://github.com/BlkLeg/circuitbreaker/issues
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
#   wget -qO- https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash
#
# Environment variable overrides (usable with curl | bash):
#   CB_PORT=8080                         Host port to expose (default: 8080)
#   CB_VOLUME=circuit-breaker-data       Docker volume name or host path
#   CB_IMAGE=ghcr.io/blkleg/...          Override the Docker image
#   CB_CONTAINER=circuit-breaker         Container name
#   CB_TLS=1                             Enable HTTPS via Caddy reverse proxy
#   CB_HOSTNAME=circuitbreaker.local     Hostname for TLS certificate
#

set -e
export DEBIAN_FRONTEND=noninteractive

# ─── Trap Ctrl-C ─────────────────────────────────────────────────────────────
trap 'echo -e "${COLOUR_RESET}"; exit 1' INT

# ─── Defaults ────────────────────────────────────────────────────────────────
CB_IMAGE="${CB_IMAGE:-ghcr.io/blkleg/circuitbreaker:latest}"
CB_PORT="${CB_PORT:-8080}"
CB_CONTAINER="${CB_CONTAINER:-circuit-breaker}"
CB_VOLUME="${CB_VOLUME:-circuit-breaker-data}"
MINIMUM_DOCKER_VERSION=20
REGION=""
ARCH=""

# ─── TLS / Caddy defaults ────────────────────────────────────────────────────
CB_TLS="${CB_TLS:-}"
CB_HOSTNAME="${CB_HOSTNAME:-circuitbreaker.local}"
CB_CADDY_CONTAINER="cb-caddy"
CB_CADDY_DATA_VOLUME="cb-caddy-data"
CB_CADDY_CONFIG_VOLUME="cb-caddy-config"
CB_NETWORK="cb-network"
CB_CONFIG_DIR="${CB_CONFIG_DIR:-$HOME/.circuit-breaker}"
CB_CA_SYSTEM_NAME="circuit-breaker-caddy-ca"
CB_CA_NSS_NAME="CircuitBreaker-Caddy-CA"

# ─── Colors ──────────────────────────────────────────────────────────────────
COLOUR_RESET='\e[0m'
aCOLOUR=(
  '\e[38;5;154m'  # [0] green  — OK, bullets, lines
  '\e[1m'         # [1] bold   — descriptions
  '\e[90m'        # [2] grey   — brackets, credits
  '\e[91m'        # [3] red    — FAILED
  '\e[33m'        # [4] yellow — NOTICE
)
GREEN_LINE=" ${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
GREEN_BULLET=" ${aCOLOUR[0]}-${COLOUR_RESET}"

# ─── Status helpers ───────────────────────────────────────────────────────────
Show() {
  case $1 in
    0) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[0]} OK ${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
    1) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[3]}FAILED${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2"; exit 1 ;;
    2) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[0]} INFO ${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
    3) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[4]}NOTICE${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
  esac
}

# ─── Header ──────────────────────────────────────────────────────────────────
Print_Header() {
  clear
  echo -e "${aCOLOUR[0]}"
  cat <<'BANNER'
  ░██████  ░██                               ░██   ░██    ░████████                                  ░██                           
 ░██   ░██                                         ░██    ░██    ░██                                 ░██                           
░██        ░██░██░████  ░███████  ░██    ░██ ░██░████████ ░██    ░██  ░██░████  ░███████   ░██████   ░██    ░██ ░███████  ░██░████ 
░██        ░██░███     ░██    ░██ ░██    ░██ ░██   ░██    ░████████   ░███     ░██    ░██       ░██  ░██   ░██ ░██    ░██ ░███     
░██        ░██░██      ░██        ░██    ░██ ░██   ░██    ░██     ░██ ░██      ░█████████  ░███████  ░███████  ░█████████ ░██      
 ░██   ░██ ░██░██      ░██    ░██ ░██   ░███ ░██   ░██    ░██     ░██ ░██      ░██        ░██   ░██  ░██   ░██ ░██        ░██      
  ░██████  ░██░██       ░███████   ░█████░██ ░██    ░████ ░█████████  ░██       ░███████   ░█████░██ ░██    ░██ ░███████  ░██      

BANNER
  echo -e "${COLOUR_RESET}"
  echo -e "  Homelab topology, documented."
  echo -e "  ${aCOLOUR[2]}https://github.com/BlkLeg/circuitbreaker${COLOUR_RESET}"
  echo ""
}

# ─── Usage ───────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: install.sh [OPTIONS]

  --port PORT       Host port for Circuit Breaker    (default: 8080)
  --volume NAME     Docker volume name or host path  (default: circuit-breaker-data)
  --image IMAGE     Override the Docker image        (default: ghcr.io/blkleg/circuitbreaker:latest)
  --container NAME  Container name                   (default: circuit-breaker)
  --tls             Enable HTTPS via Caddy reverse proxy
  --hostname NAME   Hostname for TLS certificate     (default: circuitbreaker.local)
  --help            Show this help message and exit

Environment variables (compatible with 'curl | bash' piping):
  CB_PORT, CB_VOLUME, CB_IMAGE, CB_CONTAINER, CB_TLS, CB_HOSTNAME

Examples:
  # Default install
  curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash

  # Custom port
  CB_PORT=9090 curl -fsSL .../install.sh | bash

  # Install with HTTPS enabled
  CB_TLS=1 curl -fsSL .../install.sh | bash

  # Local run with flags
  bash install.sh --port 9090 --tls --hostname mylab.local
EOF
  exit 0
}

# ─── Parse CLI flags ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --port)      CB_PORT="$2";      shift 2 ;;
    --volume)    CB_VOLUME="$2";    shift 2 ;;
    --image)     CB_IMAGE="$2";     shift 2 ;;
    --container) CB_CONTAINER="$2"; shift 2 ;;
    --tls)       CB_TLS="1";        shift 1 ;;
    --hostname)  CB_HOSTNAME="$2";  shift 2 ;;
    --help|-h)   usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

###############################################################################
# CHECKS
###############################################################################

# 0. Detect download region (for Docker mirror selection)
Get_Region() {
  Show 2 "Detecting region..."
  REGION=$(curl --connect-timeout 3 -sf https://ipconfig.io/country_code 2>/dev/null || true)
  if [[ -z "$REGION" ]]; then
    REGION=$(curl --connect-timeout 3 -sf https://ifconfig.io/country_code 2>/dev/null || true)
  fi
  # Discard any response that isn't a valid 2-letter country code
  if ! [[ "$REGION" =~ ^[A-Z]{2}$ ]]; then
    REGION=""
  fi
  Show 0 "Region: ${REGION:-unknown}"
}

# 1. Check architecture
Check_Arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64)         ARCH="amd64"  ;;
    aarch64|arm64)  ARCH="arm64"  ;;
    armv7l)         ARCH="arm/v7" ;;
    *)
      Show 1 "Unsupported architecture: $machine. Circuit Breaker supports amd64, arm64, and armv7."
      ;;
  esac
  Show 0 "Architecture: $machine (${ARCH})"
}

# 2. Check OS (Linux only for automated install)
Check_OS() {
  local os
  os="$(uname -s)"
  if [[ "$os" != "Linux" ]]; then
    echo ""
    if [[ "$os" == "Darwin" ]]; then
      Show 3 "macOS detected. This script targets Linux."
      echo "  On macOS, install Docker Desktop first: https://docs.docker.com/desktop/install/mac-install/"
      echo "  Then run:  docker run -d -p 8080:8080 -v circuit-breaker-data:/data --restart unless-stopped $CB_IMAGE"
    else
      Show 3 "Unsupported OS: $os."
      echo "  Install Docker manually: https://docs.docker.com/get-docker/"
      echo "  Then run:  docker run -d -p 8080:8080 -v circuit-breaker-data:/data --restart unless-stopped $CB_IMAGE"
    fi
    exit 1
  fi
  Show 0 "OS: $os"
}

# 3. Check available memory
Check_Memory() {
  local free_mb
  free_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo "0")
  if [[ "$free_mb" -lt 256 ]]; then
    Show 3 "Low memory: ${free_mb} MB available. Circuit Breaker recommends at least 256 MB free."
    printf "  Continue anyway? [y/N] "
    read -r reply < /dev/tty
    case "$reply" in
      [yY][eE][sS]|[yY]) Show 3 "Memory check bypassed." ;;
      *) Show 1 "Installation aborted due to low memory." ;;
    esac
  else
    Show 0 "Memory: ${free_mb} MB available."
  fi
}

# 4. Check available disk space
Check_Disk() {
  local free_gb
  free_gb=$(df -BG / 2>/dev/null | awk 'NR==2{gsub("G",""); print $4}' || echo "0")
  if [[ "$free_gb" -lt 1 ]]; then
    Show 3 "Low disk space: ${free_gb} GB free. Recommend at least 1 GB."
    printf "  Continue anyway? [y/N] "
    read -r reply < /dev/tty
    case "$reply" in
      [yY][eE][sS]|[yY]) Show 3 "Disk check bypassed." ;;
      *) Show 1 "Installation aborted due to low disk space." ;;
    esac
  else
    Show 0 "Disk: ${free_gb} GB free."
  fi
}

# 5. Find a free port (auto-increments if default is taken)
Find_Free_Port() {
  local original="$CB_PORT"
  while ss -tlnp 2>/dev/null | grep -q ":${CB_PORT} "; do
    CB_PORT=$((CB_PORT + 1))
  done
  if [[ "$CB_PORT" != "$original" ]]; then
    Show 3 "Port $original is already in use. Using port $CB_PORT instead."
  else
    Show 0 "Port $CB_PORT is available."
  fi
}

###############################################################################
# DOCKER
###############################################################################

Check_Docker_Daemon() {
  local tries=0
  until docker info >/dev/null 2>&1; do
    tries=$((tries + 1))
    [[ $tries -ge 4 ]] && Show 1 "Docker daemon is not responding. Start it and re-run this script."
    Show 2 "Waiting for Docker daemon... (attempt $tries/3)"
    sudo systemctl start docker 2>/dev/null || true
    sleep 3
  done
  Show 0 "Docker daemon is running."
}

Install_Docker() {
  Show 2 "Installing Docker via https://get.docker.com ..."
  if [[ "$REGION" == "CN" ]]; then
    curl -fsSL https://get.docker.com | sudo bash -s docker --mirror Aliyun
  else
    curl -fsSL https://get.docker.com | sudo bash
  fi
  sudo systemctl enable docker 2>/dev/null || true
  sudo systemctl start  docker 2>/dev/null || true
  # Add the current user to the docker group so sudo is not required in future
  if ! id -nG "$USER" 2>/dev/null | grep -qw docker; then
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    Show 3 "Added $USER to the docker group. You may need to log out and back in for this to take effect."
  fi
  Show 0 "Docker installed successfully."
  Check_Docker_Daemon
}

Check_Docker() {
  if command -v docker >/dev/null 2>&1; then
    local ver major
    ver=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "0.0.0")
    major="${ver%%.*}"
    if [[ "$major" -lt "$MINIMUM_DOCKER_VERSION" ]]; then
      Show 1 "Docker $ver is too old (minimum required: $MINIMUM_DOCKER_VERSION). Please upgrade Docker and re-run."
    fi
    Show 0 "Docker $ver detected."
    Check_Docker_Daemon
  else
    Show 2 "Docker is not installed. Installing now..."
    Install_Docker
  fi
}

###############################################################################
# TLS (CADDY REVERSE PROXY)
###############################################################################

Prompt_TLS() {
  # Skip prompt if already set via CLI flag or env var
  if [[ -n "$CB_TLS" ]]; then
    Show 0 "HTTPS enabled via flag/environment (hostname: $CB_HOSTNAME)."
    return
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}HTTPS / TLS Configuration${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  Circuit Breaker can be served over ${aCOLOUR[0]}HTTPS${COLOUR_RESET} using a local Caddy"
  echo -e "  reverse proxy with an automatically generated TLS certificate."
  echo ""
  echo -e "  ${aCOLOUR[2]}What this does:${COLOUR_RESET}"
  echo -e "   $GREEN_BULLET Runs a lightweight Caddy container alongside Circuit Breaker"
  echo -e "   $GREEN_BULLET Generates a local Certificate Authority for HTTPS"
  echo -e "   $GREEN_BULLET Installs the CA into your system and browser trust stores"
  echo -e "   $GREEN_BULLET Maps ${aCOLOUR[1]}${CB_HOSTNAME}${COLOUR_RESET} → 127.0.0.1 in /etc/hosts"
  echo ""
  echo -e "  ${aCOLOUR[4]}Requires:${COLOUR_RESET} root (sudo) access for CA trust and /etc/hosts"
  echo ""
  printf "  Enable HTTPS? [y/N] "
  read -r reply < /dev/tty
  echo ""

  case "$reply" in
    [yY][eE][sS]|[yY])
      CB_TLS="1"
      Show 0 "HTTPS will be enabled via Caddy."
      ;;
    *)
      CB_TLS=""
      Show 2 "Skipping HTTPS. Circuit Breaker will be HTTP-only."
      ;;
  esac
}

Check_TLS_Ports() {
  local conflict=0
  if ss -tlnp 2>/dev/null | grep -q ":80 "; then
    Show 3 "Port 80 is already in use."
    conflict=1
  fi
  if ss -tlnp 2>/dev/null | grep -q ":443 "; then
    Show 3 "Port 443 is already in use."
    conflict=1
  fi

  if [[ "$conflict" == "1" ]]; then
    echo ""
    echo -e "  Caddy needs ports 80 (HTTP→HTTPS redirect) and 443 (HTTPS)."
    printf "  Continue anyway? [y/N] "
    read -r reply < /dev/tty
    case "$reply" in
      [yY][eE][sS]|[yY]) Show 3 "Port conflict acknowledged." ;;
      *)
        Show 2 "Disabling HTTPS due to port conflict."
        CB_TLS=""
        ;;
    esac
  else
    Show 0 "Ports 80 and 443 are available."
  fi
}

Setup_TLS() {
  Show 2 "Preparing TLS configuration..."

  mkdir -p "$CB_CONFIG_DIR"

  # Generate Caddyfile
  cat > "$CB_CONFIG_DIR/Caddyfile" <<CADDYEOF
{
	local_certs
}

${CB_HOSTNAME} {
	reverse_proxy ${CB_CONTAINER}:8080 {
		header_up Host {host}
		header_up X-Real-IP {remote_host}
		header_up X-Forwarded-Proto {scheme}
	}

	encode gzip

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}
}
CADDYEOF
  Show 0 "Caddyfile written to $CB_CONFIG_DIR/Caddyfile"

  # Persist TLS settings so the uninstaller can reference them
  cat > "$CB_CONFIG_DIR/tls.conf" <<TLSEOF
CB_HOSTNAME=${CB_HOSTNAME}
CB_CADDY_CONTAINER=${CB_CADDY_CONTAINER}
CB_CADDY_DATA_VOLUME=${CB_CADDY_DATA_VOLUME}
CB_CADDY_CONFIG_VOLUME=${CB_CADDY_CONFIG_VOLUME}
CB_NETWORK=${CB_NETWORK}
CB_CA_SYSTEM_NAME=${CB_CA_SYSTEM_NAME}
CB_CA_NSS_NAME=${CB_CA_NSS_NAME}
TLSEOF

  # Create Docker network (idempotent)
  docker network create "$CB_NETWORK" 2>/dev/null || true
  Show 0 "Docker network '$CB_NETWORK' ready."

  # Pull Caddy image
  Show 2 "Pulling Caddy image: caddy:2-alpine"
  docker pull caddy:2-alpine || Show 1 "Failed to pull Caddy image."
  Show 0 "Caddy image ready."
}

Start_Caddy() {
  # Idempotent: remove any previous Caddy container
  if docker ps -a --format '{{.Names}}' | grep -q "^${CB_CADDY_CONTAINER}$"; then
    Show 2 "Removing existing Caddy container..."
    docker rm -f "$CB_CADDY_CONTAINER" >/dev/null
  fi

  Show 2 "Starting Caddy reverse proxy..."
  docker run -d \
    --name "$CB_CADDY_CONTAINER" \
    --network "$CB_NETWORK" \
    -p "80:80" \
    -p "443:443" \
    -v "$CB_CONFIG_DIR/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -v "${CB_CADDY_DATA_VOLUME}:/data" \
    -v "${CB_CADDY_CONFIG_VOLUME}:/config" \
    --restart unless-stopped \
    caddy:2-alpine \
    || Show 1 "Failed to start Caddy. Check: docker logs $CB_CADDY_CONTAINER"
  Show 0 "Caddy is running."
}

Wait_For_Caddy_CA() {
  Show 2 "Waiting for Caddy to generate CA certificate..."
  local tries=0
  until docker exec "$CB_CADDY_CONTAINER" test -f /data/caddy/pki/authorities/local/root.crt 2>/dev/null; do
    tries=$((tries + 1))
    if [[ $tries -ge 15 ]]; then
      Show 1 "Timed out waiting for Caddy CA (30s). Check: docker logs $CB_CADDY_CONTAINER"
    fi
    sleep 2
  done

  docker cp "${CB_CADDY_CONTAINER}:/data/caddy/pki/authorities/local/root.crt" \
    "$CB_CONFIG_DIR/caddy-root-ca.crt"
  Show 0 "CA certificate extracted to $CB_CONFIG_DIR/caddy-root-ca.crt"
}

Trust_CA() {
  local cert_file="$CB_CONFIG_DIR/caddy-root-ca.crt"

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Root Certificate Trust${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  Caddy generated a local Certificate Authority for HTTPS."
  echo -e "  To access ${aCOLOUR[0]}https://${CB_HOSTNAME}${COLOUR_RESET} without browser warnings,"
  echo -e "  the CA needs to be trusted by your system and browser."
  echo ""
  echo -e "  ${aCOLOUR[4]}The following operations require root (sudo) access:${COLOUR_RESET}"
  echo -e "   $GREEN_BULLET Install CA certificate into system trust store"
  echo -e "   $GREEN_BULLET Add '${CB_HOSTNAME}' → 127.0.0.1 to /etc/hosts"
  echo ""
  printf "  Proceed? [Y/n] "
  read -r reply < /dev/tty
  echo ""

  case "$reply" in
    [nN][oO]|[nN])
      Show 3 "CA trust skipped. Browsers will show security warnings."
      _Print_Manual_CA_Instructions "$cert_file"
      return
      ;;
  esac

  echo -e "  ${aCOLOUR[4]}You may be prompted for your password.${COLOUR_RESET}"
  echo ""

  # Validate sudo access once upfront so the user only types their password once
  if ! sudo -v 2>/dev/null; then
    Show 3 "Could not obtain sudo access."
    _Print_Manual_CA_Instructions "$cert_file"
    return
  fi

  # ── System trust store ──────────────────────────────────────────────────
  local sys_ok=0
  if [ -d /etc/pki/ca-trust/source/anchors ]; then
    sudo cp "$cert_file" "/etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt"
    sudo update-ca-trust
    sys_ok=1
    Show 0 "CA trusted by system (Fedora/RHEL)."
  elif [ -d /usr/local/share/ca-certificates ]; then
    sudo cp "$cert_file" "/usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt"
    sudo update-ca-certificates
    sys_ok=1
    Show 0 "CA trusted by system (Debian/Ubuntu)."
  elif [ -d /etc/ca-certificates/trust-source/anchors ]; then
    sudo cp "$cert_file" "/etc/ca-certificates/trust-source/anchors/${CB_CA_SYSTEM_NAME}.crt"
    sudo trust extract-compat
    sys_ok=1
    Show 0 "CA trusted by system (Arch)."
  fi

  if [[ "$sys_ok" == "0" ]]; then
    Show 3 "Could not detect system CA trust store — manual install needed."
  fi

  # ── Browser trust store (NSS — Chrome / Brave / Chromium) ──────────────
  if command -v certutil >/dev/null 2>&1; then
    local nssdb="$HOME/.pki/nssdb"
    if [ ! -d "$nssdb" ]; then
      mkdir -p "$nssdb"
      certutil -d sql:"$nssdb" -N --empty-password 2>/dev/null
    fi
    certutil -d sql:"$nssdb" -D -n "$CB_CA_NSS_NAME" 2>/dev/null || true
    certutil -d sql:"$nssdb" -A -t "C,," -n "$CB_CA_NSS_NAME" -i "$cert_file"
    Show 0 "CA trusted by Chrome / Brave / Chromium (NSS)."
  else
    Show 3 "certutil not found — Chromium-based browsers may show warnings."
    echo -e "  Install ${aCOLOUR[1]}nss-tools${COLOUR_RESET} (Fedora) or ${aCOLOUR[1]}libnss3-tools${COLOUR_RESET} (Debian/Ubuntu), then run:"
    echo -e "  certutil -d sql:\$HOME/.pki/nssdb -A -t 'C,,' -n '${CB_CA_NSS_NAME}' -i $cert_file"
  fi

  # ── /etc/hosts ─────────────────────────────────────────────────────────
  if grep -q "$CB_HOSTNAME" /etc/hosts 2>/dev/null; then
    Show 0 "'$CB_HOSTNAME' already present in /etc/hosts."
  else
    echo "127.0.0.1  $CB_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
    Show 0 "Added '$CB_HOSTNAME' → 127.0.0.1 to /etc/hosts."
  fi
}

_Print_Manual_CA_Instructions() {
  local cert_file="$1"
  echo ""
  echo -e "  ${aCOLOUR[1]}Manual setup instructions:${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[2]}# 1. System trust store${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[2]}# Fedora / RHEL:${COLOUR_RESET}"
  echo -e "  sudo cp $cert_file /etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt"
  echo -e "  sudo update-ca-trust"
  echo -e "  ${aCOLOUR[2]}# Debian / Ubuntu:${COLOUR_RESET}"
  echo -e "  sudo cp $cert_file /usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt"
  echo -e "  sudo update-ca-certificates"
  echo ""
  echo -e "  ${aCOLOUR[2]}# 2. Chrome / Brave / Chromium:${COLOUR_RESET}"
  echo -e "  certutil -d sql:\$HOME/.pki/nssdb -A -t 'C,,' -n '${CB_CA_NSS_NAME}' -i $cert_file"
  echo ""
  echo -e "  ${aCOLOUR[2]}# 3. /etc/hosts:${COLOUR_RESET}"
  echo -e "  echo '127.0.0.1  $CB_HOSTNAME' | sudo tee -a /etc/hosts"
  echo ""
}

###############################################################################
# API TOKEN
###############################################################################

Generate_API_Token() {
  mkdir -p "$CB_CONFIG_DIR"
  chmod 700 "$CB_CONFIG_DIR"

  local env_file="$CB_CONFIG_DIR/env"

  # Reuse existing token on re-installs to avoid breaking API integrations
  if [[ -f "$env_file" ]] && grep -q '^CB_API_TOKEN=' "$env_file" 2>/dev/null; then
    Show 0 "Existing API token found — reusing."
    return
  fi

  local token
  if ! command -v openssl >/dev/null 2>&1; then
    Show 3 "openssl not found — generating token with /dev/urandom."
    token=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  else
    token=$(openssl rand -hex 32)
  fi

  cat > "$env_file" <<ENVEOF
# Circuit Breaker — auto-generated environment (install.sh)
# This file contains secrets. Do NOT share or commit it.
CB_API_TOKEN=${token}
ENVEOF

  chmod 600 "$env_file"
  Show 0 "API master token generated and saved to $env_file"
}

###############################################################################
# INSTALL
###############################################################################

Pull_And_Run() {
  Show 2 "Pulling image: $CB_IMAGE"
  docker pull "$CB_IMAGE" || Show 1 "Image pull failed. Verify your internet connection and that the GHCR package is public."
  Show 0 "Image pulled."

  # Stop and remove any existing container with the same name (idempotent re-runs)
  if docker ps -a --format '{{.Names}}' | grep -q "^${CB_CONTAINER}$"; then
    Show 2 "Removing existing container: $CB_CONTAINER"
    docker rm -f "$CB_CONTAINER" >/dev/null
  fi

  Show 2 "Starting Circuit Breaker..."

  local network_args=()
  if [[ "$CB_TLS" == "1" ]]; then
    network_args=(--network "$CB_NETWORK")
  fi

  local env_args=()
  if [[ -f "$CB_CONFIG_DIR/env" ]]; then
    env_args=(--env-file "$CB_CONFIG_DIR/env")
  fi

  docker run -d \
    --name  "$CB_CONTAINER" \
    "${network_args[@]}" \
    "${env_args[@]}" \
    -p      "${CB_PORT}:8080" \
    -v      "${CB_VOLUME}:/data" \
    --security-opt seccomp=unconfined \
    --restart unless-stopped \
    "$CB_IMAGE" \
    || Show 1 "Failed to start container. Inspect logs with: docker logs $CB_CONTAINER"
  Show 0 "Container started."
}

Wait_For_Ready() {
  Show 2 "Waiting for Circuit Breaker to be ready..."
  local tries=0
  # Use curl from the host against the exposed port — more reliable than docker exec
  # (curl is not installed inside the container) and also validates the port mapping.
  until curl -sf http://127.0.0.1:${CB_PORT}/api/v1/health >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ $tries -ge 30 ]]; then
      Show 1 "Health check timed out after $((tries * 2))s. Check logs: docker logs $CB_CONTAINER"
    fi
    sleep 2
  done
  Show 0 "Circuit Breaker is ready."
}

###############################################################################
# WELCOME BANNER
###############################################################################

Welcome_Banner() {
  # Try to resolve the public IP — useful on VPS/cloud where the host NIC only
  # shows a private address and the public IP is assigned at the hypervisor.
  local public_ip=""
  public_ip=$(curl -4 -sf --connect-timeout 4 https://ipinfo.io/ip 2>/dev/null \
              || curl -4 -sf --connect-timeout 4 https://ifconfig.me  2>/dev/null \
              || true)
  # Discard anything that doesn't look like an IPv4 address
  if ! [[ "$public_ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    public_ip=""
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Circuit Breaker is running at:${COLOUR_RESET}"
  echo -e "$GREEN_LINE"

  # HTTPS address first if TLS is enabled
  if [[ "$CB_TLS" == "1" ]]; then
    echo -e "$GREEN_BULLET ${aCOLOUR[0]}https://${CB_HOSTNAME}${COLOUR_RESET}  ${aCOLOUR[2]}← HTTPS via Caddy${COLOUR_RESET}"
  fi

  # Public IP first (most relevant on VPS/cloud)
  if [[ -n "$public_ip" ]]; then
    echo -e "$GREEN_BULLET http://${public_ip}:${CB_PORT}  ${aCOLOUR[2]}← public / VPS address${COLOUR_RESET}"
  fi

  # Private LAN addresses
  if command -v ip >/dev/null 2>&1; then
    while IFS= read -r ip_addr; do
      # Skip the address if it matches the public IP already printed
      [[ "$ip_addr" == "$public_ip" ]] && continue
      echo -e "$GREEN_BULLET http://${ip_addr}:${CB_PORT}"
    done < <(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
  fi

  # Always show localhost as a fallback
  echo -e "$GREEN_BULLET http://localhost:${CB_PORT}"

  echo ""
  if [[ "$CB_TLS" == "1" ]]; then
    echo -e "  Open your browser and visit ${aCOLOUR[0]}https://${CB_HOSTNAME}${COLOUR_RESET}"
  else
    echo -e "  Open your browser and visit the address above."
  fi
  echo -e "  On first launch, the setup wizard will guide you through creating"
  echo -e "  your admin account and personalizing your dashboard."
  echo -e "$GREEN_LINE"
  echo ""
  if [[ -f "$CB_CONFIG_DIR/env" ]]; then
    echo -e "  ${aCOLOUR[2]}API Token : stored in ${CB_CONFIG_DIR}/env${COLOUR_RESET}"
  fi
  echo -e "  ${aCOLOUR[2]}GitHub    : https://github.com/BlkLeg/circuitbreaker"
  echo -e "  ${aCOLOUR[2]}Docs      : https://blkleg.github.io/circuitbreaker${COLOUR_RESET}"
  echo ""
  echo -e "  To stop      : docker stop $CB_CONTAINER"
  echo -e "  To start     : docker start $CB_CONTAINER"
  echo -e "  To uninstall : curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash"
  echo -e "${COLOUR_RESET}"
}

###############################################################################
# MAIN
###############################################################################

Print_Header

# Step 0: Detect region
Get_Region

# Step 1: Architecture
Check_Arch

# Step 2: OS
Check_OS

# Step 3: Memory
Check_Memory

# Step 4: Disk
Check_Disk

# Step 5: Port
Find_Free_Port

# Step 6: Docker
Check_Docker

# Step 7: Generate API master token
Generate_API_Token

# Step 8: TLS prompt
Prompt_TLS

# Step 9: TLS pre-flight (network, Caddyfile, pull Caddy image)
if [[ "$CB_TLS" == "1" ]]; then
  Check_TLS_Ports
fi
if [[ "$CB_TLS" == "1" ]]; then
  Setup_TLS
fi

# Step 10: Pull image and start container
Pull_And_Run

# Step 11: Wait for health
Wait_For_Ready

# Step 12: Start Caddy and trust CA
if [[ "$CB_TLS" == "1" ]]; then
  Start_Caddy
  Wait_For_Caddy_CA
  Trust_CA
fi

# Step 13: Print welcome
Welcome_Banner
