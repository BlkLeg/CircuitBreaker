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
#   CB_MODE=docker|binary                Install mode
#   CB_PORT=8080                         Host port (Docker mode)
#   CB_VOLUME=circuit-breaker-data       Docker volume name or host path
#   CB_IMAGE=ghcr.io/blkleg/...          Override the Docker image
#   CB_CONTAINER=circuit-breaker         Container name
#   CB_TLS=1                             Enable HTTPS via Caddy reverse proxy
#   CB_HOSTNAME=circuitbreaker.local     Hostname for TLS certificate
#   CB_VERSION=latest                    Image/binary version tag
#   CB_YES=1                             Non-interactive mode
#

set -eo pipefail
export DEBIAN_FRONTEND=noninteractive

# ─── Trap Ctrl-C ─────────────────────────────────────────────────────────────
trap 'echo -e "${COLOUR_RESET}"; exit 1' INT

# ─── Defaults ────────────────────────────────────────────────────────────────
CB_MODE="${CB_MODE:-}"
CB_VERSION="${CB_VERSION:-latest}"
CB_YES="${CB_YES:-0}"
CB_NO_DESKTOP="${CB_NO_DESKTOP:-0}"
CB_NO_SYSTEMD="${CB_NO_SYSTEMD:-0}"

CB_IMAGE="${CB_IMAGE:-ghcr.io/blkleg/circuitbreaker:${CB_VERSION}}"
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

Confirm() {
  # Confirm "question" — returns 0 (yes) or 1 (no). Skips to default 'y' in non-interactive mode.
  local msg="$1"
  local default="${2:-n}"
  if [[ "$CB_YES" == "1" ]]; then
    [[ "$default" == "y" ]] && return 0 || return 1
  fi
  printf "  %s [y/N] " "$msg"
  read -r reply < /dev/tty
  case "$reply" in [yY][eE][sS]|[yY]) return 0 ;; *) return 1 ;; esac
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

Install mode:
  --mode docker|binary  Choose install mode (skips interactive prompt)
  --version TAG         Image / binary version tag  (default: latest)
  --yes                 Non-interactive; accept all defaults

Docker mode options:
  --port PORT           Host port for Circuit Breaker    (default: 8080)
  --volume NAME         Docker volume name or host path  (default: circuit-breaker-data)
  --image IMAGE         Override the Docker image        (default: ghcr.io/blkleg/circuitbreaker:latest)
  --container NAME      Container name                   (default: circuit-breaker)
  --tls                 Enable HTTPS via Caddy reverse proxy
  --hostname NAME       Hostname for TLS certificate     (default: circuitbreaker.local)

Binary mode options:
  --no-desktop          Skip .desktop file and icon install
  --no-systemd          Skip systemd service setup (useful in WSL/containers)

  --help                Show this help and exit

Environment variables (compatible with 'curl | bash' piping):
  CB_MODE, CB_VERSION, CB_YES, CB_NO_DESKTOP, CB_NO_SYSTEMD
  CB_PORT, CB_VOLUME, CB_IMAGE, CB_CONTAINER, CB_TLS, CB_HOSTNAME

Examples:
  # Interactive install (prompts for Docker vs Binary)
  curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash

  # Docker install, non-interactive
  bash install.sh --mode docker --yes

  # Binary install, specific version, skip desktop
  bash install.sh --mode binary --version v0.1.4 --no-desktop
EOF
  exit 0
}

# ─── Parse CLI flags ─────────────────────────────────────────────────────────
parse_flags() {
  while [[ $# -gt 0 ]]; do
    case $1 in
      --mode)       CB_MODE="$2";      shift 2 ;;
      --version)    CB_VERSION="$2";   CB_IMAGE="ghcr.io/blkleg/circuitbreaker:${2}"; shift 2 ;;
      --port)       CB_PORT="$2";      shift 2 ;;
      --volume)     CB_VOLUME="$2";    shift 2 ;;
      --image)      CB_IMAGE="$2";     shift 2 ;;
      --container)  CB_CONTAINER="$2"; shift 2 ;;
      --tls)        CB_TLS="1";        shift 1 ;;
      --hostname)   CB_HOSTNAME="$2";  shift 2 ;;
      --yes)        CB_YES=1;          shift 1 ;;
      --no-desktop) CB_NO_DESKTOP=1;   shift 1 ;;
      --no-systemd) CB_NO_SYSTEMD=1;   shift 1 ;;
      --help|-h)    usage ;;
      *) echo "Unknown option: $1"; usage ;;
    esac
  done
}

###############################################################################
# SYSTEM CHECKS
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

# Arch string for binary downloads (amd64/arm64 only — arm/v7 not supported for native binary)
Detect_Binary_Arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64)        echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) Show 1 "Native binary install requires amd64 or arm64. Detected: $machine. Use --mode docker instead." ;;
  esac
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
    if ! Confirm "Continue anyway?"; then
      Show 1 "Installation aborted due to low memory."
    fi
    Show 3 "Memory check bypassed."
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
    if ! Confirm "Continue anyway?"; then
      Show 1 "Installation aborted due to low disk space."
    fi
    Show 3 "Disk check bypassed."
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

# 6. Validate sudo access (binary mode requires it throughout)
Require_Sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    # Running as root — define sudo as a no-op
    sudo() { "$@"; }
    export -f sudo
    Show 0 "Running as root."
    return
  fi
  Show 2 "Binary install requires sudo for system directories. Validating access..."
  if ! sudo -v 2>/dev/null; then
    Show 1 "sudo access is required for native binary install. Re-run as root or with sudo."
  fi
  Show 0 "sudo access confirmed."
}

###############################################################################
# DOCKER HELPERS
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
    Show 2 "Docker is not installed."
    if Confirm "Install Docker now?" "y"; then
      Install_Docker
    else
      Show 1 "Docker is required for Docker mode. Install Docker and re-run, or use --mode binary."
    fi
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

  if Confirm "Enable HTTPS?"; then
    CB_TLS="1"
    Show 0 "HTTPS will be enabled via Caddy."
  else
    CB_TLS=""
    Show 2 "Skipping HTTPS. Circuit Breaker will be HTTP-only."
  fi
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
    if ! Confirm "Continue anyway?"; then
      Show 2 "Disabling HTTPS due to port conflict."
      CB_TLS=""
    else
      Show 3 "Port conflict acknowledged."
    fi
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

  if ! Confirm "Proceed?" "y"; then
    Show 3 "CA trust skipped. Browsers will show security warnings."
    _Print_Manual_CA_Instructions "$cert_file"
    return
  fi

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
  # CB_CONFIG_DIR controls where the token is written:
  #   Docker mode: ~/.circuit-breaker/env
  #   Binary mode: /etc/circuit-breaker/env  (CB_CONFIG_DIR overridden before call)
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
# DOCKER INSTALL HELPERS
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
  local port="${1:-$CB_PORT}"
  Show 2 "Waiting for Circuit Breaker to be ready..."
  local tries=0
  until curl -sf "http://127.0.0.1:${port}/api/v1/health" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [[ $tries -ge 30 ]]; then
      Show 1 "Health check timed out after $((tries * 2))s."
    fi
    sleep 2
  done
  Show 0 "Circuit Breaker is ready."
}

# Install the Docker-based systemd unit (embeds unit inline — works when curl | bash)
Setup_Systemd_Docker() {
  if [[ "$CB_NO_SYSTEMD" == "1" ]]; then
    Show 2 "Skipping systemd setup (--no-systemd)."
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    Show 3 "systemctl not found — skipping systemd service install."
    return
  fi

  Show 2 "Installing systemd service (Docker mode)..."
  sudo tee /etc/systemd/system/circuit-breaker.service >/dev/null <<UNIT
[Unit]
Description=Circuit Breaker (Docker)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
Environment="CB_CONTAINER=${CB_CONTAINER}"
Environment="CB_IMAGE=${CB_IMAGE}"
Environment="CB_PORT=${CB_PORT}"
Environment="CB_VOLUME=${CB_VOLUME}"

ExecStartPre=-/usr/bin/docker stop \${CB_CONTAINER}
ExecStartPre=-/usr/bin/docker rm   \${CB_CONTAINER}
ExecStart=/usr/bin/docker run \\
  --name  \${CB_CONTAINER} \\
  --detach \\
  -p      \${CB_PORT}:8080 \\
  -v      \${CB_VOLUME}:/data \\
  --security-opt seccomp=unconfined \\
  \${CB_IMAGE}
ExecStop=/usr/bin/docker stop \${CB_CONTAINER}
ExecReload=/usr/bin/docker pull \${CB_IMAGE} && \${EXEC_STOP} && \${EXEC_START}

TimeoutStartSec=120
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable --now circuit-breaker
  Show 0 "systemd service enabled: circuit-breaker"
}

###############################################################################
# BINARY INSTALL HELPERS
###############################################################################

Download_Binary() {
  local arch url tmpdir
  tmpdir=$(mktemp -d)
  arch=$(Detect_Binary_Arch)

  if [[ "$CB_VERSION" == "latest" ]]; then
    Show 2 "Resolving latest release from GitHub..."
    url=$(curl -fsSL https://api.github.com/repos/BlkLeg/CircuitBreaker/releases/latest \
          | grep '"browser_download_url"' \
          | grep "linux-${arch}\.tar\.gz" \
          | head -1 | cut -d'"' -f4 || true)
  else
    url="https://github.com/BlkLeg/CircuitBreaker/releases/download/${CB_VERSION}/circuit-breaker-${CB_VERSION}-linux-${arch}.tar.gz"
  fi

  if [[ -z "$url" ]]; then
    rm -rf "$tmpdir"
    Show 1 "Could not resolve binary download URL for ${arch}. Check https://github.com/BlkLeg/CircuitBreaker/releases"
  fi

  Show 2 "Downloading: $url"
  curl -fsSL "$url" -o "$tmpdir/cb.tar.gz" || { rm -rf "$tmpdir"; Show 1 "Download failed."; }
  tar -xzf "$tmpdir/cb.tar.gz" -C "$tmpdir"

  if [[ ! -f "$tmpdir/circuit-breaker" ]]; then
    # Some tarballs have a subdirectory
    local found
    found=$(find "$tmpdir" -name "circuit-breaker" -type f | head -1 || true)
    [[ -z "$found" ]] && { rm -rf "$tmpdir"; Show 1 "Binary not found in archive."; }
    cp "$found" "$tmpdir/circuit-breaker"
  fi

  sudo install -Dm755 "$tmpdir/circuit-breaker" /usr/local/bin/circuit-breaker
  rm -rf "$tmpdir"
  Show 0 "Binary installed to /usr/local/bin/circuit-breaker"
}

Create_User_And_Dirs() {
  if ! id circuitbreaker &>/dev/null; then
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin circuitbreaker
    Show 0 "System user 'circuitbreaker' created."
  else
    Show 0 "System user 'circuitbreaker' already exists."
  fi
  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker /var/lib/circuit-breaker
  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker /var/log/circuit-breaker
  sudo install -d -m 755 /etc/circuit-breaker
  Show 0 "Directories created."
}

Generate_Config() {
  local cfg="/etc/circuit-breaker/config.yaml"
  if [[ -f "$cfg" ]]; then
    Show 0 "Config already exists at $cfg — skipping (idempotent)."
    return
  fi
  sudo tee "$cfg" >/dev/null <<CFGEOF
# Circuit Breaker configuration — generated by install.sh
port: 8080
data_dir: /var/lib/circuit-breaker
log_dir: /var/log/circuit-breaker
auth_enabled: false
CFGEOF
  Show 0 "Config written to $cfg"
}

Setup_Systemd_Binary() {
  if [[ "$CB_NO_SYSTEMD" == "1" ]]; then
    Show 2 "Skipping systemd setup (--no-systemd)."
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    Show 3 "systemctl not found — skipping systemd service install."
    return
  fi

  Show 2 "Installing systemd service (native binary)..."
  sudo tee /etc/systemd/system/circuit-breaker.service >/dev/null <<'UNIT'
[Unit]
Description=Circuit Breaker (Native)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=circuitbreaker
Group=circuitbreaker
WorkingDirectory=/var/lib/circuit-breaker
EnvironmentFile=-/etc/circuit-breaker/env
ExecStart=/usr/local/bin/circuit-breaker --config /etc/circuit-breaker/config.yaml
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
UNIT

  # Copy API token env file so the service picks it up
  if [[ -f "/etc/circuit-breaker/env" ]]; then
    sudo chmod 640 /etc/circuit-breaker/env
    sudo chown root:circuitbreaker /etc/circuit-breaker/env
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable --now circuit-breaker
  Show 0 "systemd service enabled: circuit-breaker"
}

Setup_Desktop() {
  if [[ "$CB_NO_DESKTOP" == "1" ]]; then
    Show 2 "Skipping desktop integration (--no-desktop)."
    return
  fi
  if ! command -v xdg-open >/dev/null 2>&1 && [[ -z "${DISPLAY:-}" ]] && [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    Show 3 "No display environment detected — skipping desktop integration."
    return
  fi

  Show 2 "Installing desktop integration..."

  # Write .desktop file
  sudo tee /usr/share/applications/circuit-breaker.desktop >/dev/null <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Circuit Breaker
Comment=Homelab topology, documented.
Exec=xdg-open http://localhost:8080
Icon=circuit-breaker
Terminal=false
Categories=Network;System;Utility;
DESKTOP
  Show 0 ".desktop file installed."

  # Install icon — prefer local repo copy, fall back to GitHub raw
  local icon_dest="/usr/share/icons/hicolor/256x256/apps/circuit-breaker.png"
  sudo install -d /usr/share/icons/hicolor/256x256/apps/

  local icon_src=""
  # Look for icon relative to this script (local repo run)
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "")"
  for candidate in \
    "$script_dir/frontend/public/android-chrome-512x512.png" \
    "$script_dir/frontend/public/android-chrome-192x192.png" \
    "$script_dir/frontend/public/CB-AZ_Final.png"; do
    if [[ -f "$candidate" ]]; then
      icon_src="$candidate"
      break
    fi
  done

  if [[ -n "$icon_src" ]]; then
    sudo install -Dm644 "$icon_src" "$icon_dest"
    Show 0 "Icon installed from local repo."
  else
    # Download from GitHub
    Show 2 "Downloading app icon from GitHub..."
    local icon_url="https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/frontend/public/android-chrome-512x512.png"
    if curl -fsSL "$icon_url" -o /tmp/cb-icon.png 2>/dev/null; then
      sudo install -Dm644 /tmp/cb-icon.png "$icon_dest"
      rm -f /tmp/cb-icon.png
      Show 0 "Icon installed."
    else
      Show 3 "Could not download icon — desktop entry will use a fallback."
    fi
  fi

  # Refresh icon cache
  gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true

  # Desktop shortcut (interactive sessions only)
  if [[ -d "$HOME/Desktop" ]] && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    ln -sf /usr/share/applications/circuit-breaker.desktop "$HOME/Desktop/circuit-breaker.desktop" 2>/dev/null || true
    Show 0 "Desktop shortcut created at ~/Desktop/circuit-breaker.desktop"
  fi
}

###############################################################################
# INSTALL CONFIG  (read by the cb command)
###############################################################################

Save_Install_Config() {
  mkdir -p "$CB_CONFIG_DIR"
  chmod 700 "$CB_CONFIG_DIR"
  # CB_BACKEND_CONTAINER and CB_DATA_DIR are set to their single-container
  # values here; the compose path writes its own install.conf via make install-cb.
  cat > "$CB_CONFIG_DIR/install.conf" <<CONFEOF
# Circuit Breaker — install config (written by install.sh, read by cb)
CB_MODE=${CB_MODE}
CB_CONTAINER=${CB_CONTAINER}
CB_BACKEND_CONTAINER=${CB_CONTAINER}
CB_VOLUME=${CB_VOLUME}
CB_PORT=${CB_PORT}
CB_IMAGE=${CB_IMAGE}
CB_DATA_DIR=/data
CONFEOF
  chmod 600 "$CB_CONFIG_DIR/install.conf"
  Show 0 "Install config saved to $CB_CONFIG_DIR/install.conf"
}

###############################################################################
# CB COMMAND
###############################################################################

Install_CB_Command() {
  local dest="/usr/local/bin/cb"
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

  if [[ -f "$script_dir/cb" ]]; then
    sudo install -Dm755 "$script_dir/cb" "$dest"
    Show 0 "cb command installed from local repo to $dest"
  else
    Show 2 "Downloading cb from GitHub..."
    local url="https://raw.githubusercontent.com/BlkLeg/circuitbreaker/${CB_VERSION}/cb"
    if curl -fsSL "$url" -o /tmp/cb-cli 2>/dev/null; then
      sudo install -Dm755 /tmp/cb-cli "$dest"
      rm -f /tmp/cb-cli
      Show 0 "cb command downloaded and installed to $dest"
    else
      Show 3 "Could not install cb command — skipping. You can install it later from the repo."
    fi
  fi
}

###############################################################################
# UNINSTALL SCRIPT (written at install time)
###############################################################################

Write_Uninstall_Script() {
  local mode="$1"
  local dest="/usr/local/bin/uninstall-circuit-breaker"
  local tmp
  tmp=$(mktemp)

  # Header — variables expanded at write time
  cat > "$tmp" <<HEADER
#!/usr/bin/env bash
# Circuit Breaker Uninstaller
# Generated by install.sh — mode: ${mode}
set -e

COLOUR_RESET='\e[0m'
GREEN='\e[38;5;154m'
RED='\e[91m'
YELLOW='\e[33m'
GREY='\e[90m'

Show() {
  case \$1 in
    0) echo -e "\${GREY}[\${COLOUR_RESET}\${GREEN} OK \${COLOUR_RESET}\${GREY}]\${COLOUR_RESET} \$2" ;;
    1) echo -e "\${GREY}[\${COLOUR_RESET}\${RED}FAILED\${COLOUR_RESET}\${GREY}]\${COLOUR_RESET} \$2"; exit 1 ;;
    2) echo -e "\${GREY}[\${COLOUR_RESET}\${GREEN} INFO \${COLOUR_RESET}\${GREY}]\${COLOUR_RESET} \$2" ;;
    3) echo -e "\${GREY}[\${COLOUR_RESET}\${YELLOW}NOTICE\${COLOUR_RESET}\${GREY}]\${COLOUR_RESET} \$2" ;;
  esac
}

CB_YES=\${CB_YES:-0}
Confirm() {
  local msg="\$1"
  [[ "\$CB_YES" == "1" ]] && return 1
  printf "  %s [y/N] " "\$msg"
  read -r r < /dev/tty
  case "\$r" in [yY][eE][sS]|[yY]) return 0 ;; *) return 1 ;; esac
}

INSTALLED_MODE="${mode}"
HEADER

  # Embed mode-specific variables
  if [[ "$mode" == "docker" ]]; then
    cat >> "$tmp" <<DOCKER_VARS
CB_CONTAINER="${CB_CONTAINER}"
CB_IMAGE="${CB_IMAGE}"
CB_VOLUME="${CB_VOLUME}"
CB_TLS="${CB_TLS}"
CB_HOSTNAME="${CB_HOSTNAME}"
CB_CADDY_CONTAINER="${CB_CADDY_CONTAINER}"
CB_CADDY_DATA_VOLUME="${CB_CADDY_DATA_VOLUME}"
CB_CADDY_CONFIG_VOLUME="${CB_CADDY_CONFIG_VOLUME}"
CB_NETWORK="${CB_NETWORK}"
CB_CA_SYSTEM_NAME="${CB_CA_SYSTEM_NAME}"
CB_CA_NSS_NAME="${CB_CA_NSS_NAME}"
CB_CONFIG_DIR="${CB_CONFIG_DIR}"
DOCKER_VARS
  fi

  # Uninstall logic — single-quote heredoc so no expansion happens here
  cat >> "$tmp" << 'UNINSTALL_BODY'

echo ""
echo "  Circuit Breaker Uninstaller"
echo "  ─────────────────────────────────────────────────────"
echo ""

stop_systemd() {
  if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled circuit-breaker &>/dev/null; then
    Show 2 "Stopping systemd service..."
    sudo systemctl stop circuit-breaker 2>/dev/null || true
    sudo systemctl disable circuit-breaker 2>/dev/null || true
    sudo rm -f /etc/systemd/system/circuit-breaker.service
    sudo systemctl daemon-reload
    Show 0 "systemd service removed."
  fi
}

if [[ "$INSTALLED_MODE" == "docker" ]]; then

  stop_systemd

  Show 2 "Stopping Docker container: $CB_CONTAINER"
  docker stop "$CB_CONTAINER" 2>/dev/null || true
  docker rm   "$CB_CONTAINER" 2>/dev/null || true
  Show 0 "Container removed."

  if Confirm "Remove Docker volume '$CB_VOLUME' (all data)?"; then
    docker volume rm "$CB_VOLUME" 2>/dev/null || true
    Show 0 "Volume removed."
  else
    Show 3 "Volume '$CB_VOLUME' kept."
  fi

  if Confirm "Remove Docker image '$CB_IMAGE'?"; then
    docker rmi "$CB_IMAGE" 2>/dev/null || true
    Show 0 "Image removed."
  fi

  # TLS cleanup
  if [[ -n "$CB_TLS" ]]; then
    Show 2 "Removing Caddy container..."
    docker stop "$CB_CADDY_CONTAINER" 2>/dev/null || true
    docker rm   "$CB_CADDY_CONTAINER" 2>/dev/null || true
    docker volume rm "$CB_CADDY_DATA_VOLUME" "$CB_CADDY_CONFIG_VOLUME" 2>/dev/null || true
    docker network rm "$CB_NETWORK" 2>/dev/null || true
    Show 0 "Caddy removed."

    # Remove system CA
    sudo rm -f "/etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    sudo rm -f "/usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    sudo rm -f "/etc/ca-certificates/trust-source/anchors/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    command -v update-ca-trust        >/dev/null 2>&1 && sudo update-ca-trust        || true
    command -v update-ca-certificates >/dev/null 2>&1 && sudo update-ca-certificates || true
    Show 0 "System CA removed."

    # Remove NSS entry
    if command -v certutil >/dev/null 2>&1; then
      certutil -d sql:"$HOME/.pki/nssdb" -D -n "$CB_CA_NSS_NAME" 2>/dev/null || true
      Show 0 "Browser CA removed."
    fi

    # /etc/hosts
    if grep -q "$CB_HOSTNAME" /etc/hosts 2>/dev/null; then
      sudo sed -i "/$CB_HOSTNAME/d" /etc/hosts
      Show 0 "Removed '$CB_HOSTNAME' from /etc/hosts."
    fi
  fi

  # Config dir
  if [[ -d "$CB_CONFIG_DIR" ]]; then
    if Confirm "Remove config directory '$CB_CONFIG_DIR' (contains API token)?"; then
      rm -rf "$CB_CONFIG_DIR"
      Show 0 "Config directory removed."
    fi
  fi

elif [[ "$INSTALLED_MODE" == "binary" ]]; then

  stop_systemd

  sudo rm -f /usr/local/bin/circuit-breaker
  Show 0 "Binary removed."

  sudo rm -rf /etc/circuit-breaker/
  Show 0 "Config removed."

  sudo rm -f /usr/share/applications/circuit-breaker.desktop
  sudo rm -f /usr/share/icons/hicolor/256x256/apps/circuit-breaker.png
  rm -f "$HOME/Desktop/circuit-breaker.desktop" 2>/dev/null || true
  gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
  Show 0 "Desktop entry and icon removed."

  if Confirm "Remove data (/var/lib/circuit-breaker) and logs (/var/log/circuit-breaker)?"; then
    sudo rm -rf /var/lib/circuit-breaker /var/log/circuit-breaker
    Show 0 "Data and logs removed."
  else
    Show 3 "Data and logs kept at /var/lib/circuit-breaker and /var/log/circuit-breaker"
  fi

  if id circuitbreaker &>/dev/null; then
    sudo userdel circuitbreaker 2>/dev/null || true
    Show 0 "System user 'circuitbreaker' removed."
  fi

fi

sudo rm -f /usr/local/bin/uninstall-circuit-breaker
sudo rm -f /usr/local/bin/cb
Show 0 "Circuit Breaker uninstalled."
UNINSTALL_BODY

  sudo install -Dm755 "$tmp" "$dest"
  rm -f "$tmp"
  Show 0 "Uninstall script installed to $dest"
}

###############################################################################
# MODE SELECTION
###############################################################################

Prompt_Mode() {
  # Skip if set by flag or environment
  if [[ -n "$CB_MODE" ]]; then
    Show 0 "Install mode: $CB_MODE"
    return
  fi

  # Non-interactive default
  if [[ "$CB_YES" == "1" ]]; then
    CB_MODE="docker"
    Show 0 "Non-interactive mode: defaulting to Docker install."
    return
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}How would you like to install Circuit Breaker?${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[1]}[1]${COLOUR_RESET} Docker container  ${aCOLOUR[2]}(recommended — no build dependencies required)${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[1]}[2]${COLOUR_RESET} Native binary     ${aCOLOUR[2]}(systemd service, FHS paths, no Docker required)${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[1]}[Q]${COLOUR_RESET} Quit"
  echo ""
  printf "  Choice [1/2/Q]: "
  read -r choice < /dev/tty
  echo ""

  case "$choice" in
    1)    CB_MODE="docker" ;;
    2)    CB_MODE="binary" ;;
    [qQ]) echo "  Exiting."; exit 0 ;;
    *)    Show 1 "Invalid choice '$choice'. Re-run and enter 1, 2, or Q." ;;
  esac
  Show 0 "Install mode: $CB_MODE"
}

###############################################################################
# MODE ORCHESTRATORS
###############################################################################

Install_Docker_Mode() {
  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Docker Install${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""

  Find_Free_Port
  Check_Docker
  Generate_API_Token
  Prompt_TLS
  if [[ "$CB_TLS" == "1" ]]; then
    Check_TLS_Ports
    Setup_TLS
  fi
  Pull_And_Run
  Wait_For_Ready "$CB_PORT"
  if [[ "$CB_TLS" == "1" ]]; then
    Start_Caddy
    Wait_For_Caddy_CA
    Trust_CA
  fi
  Setup_Systemd_Docker
  Save_Install_Config
  Install_CB_Command
  Write_Uninstall_Script "docker"
  Welcome_Banner_Docker
}

Install_Binary_Mode() {
  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Native Binary Install${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""

  Require_Sudo
  Download_Binary
  Create_User_And_Dirs

  # For binary mode, write config + token to /etc/circuit-breaker/
  CB_CONFIG_DIR="/etc/circuit-breaker"
  Generate_Config
  Generate_API_Token

  Setup_Systemd_Binary
  Setup_Desktop
  Wait_For_Ready 8080
  Save_Install_Config
  Install_CB_Command
  Write_Uninstall_Script "binary"
  Welcome_Banner_Binary
}

###############################################################################
# WELCOME BANNERS
###############################################################################

Welcome_Banner_Docker() {
  local public_ip=""
  public_ip=$(curl -4 -sf --connect-timeout 4 https://ipinfo.io/ip 2>/dev/null \
              || curl -4 -sf --connect-timeout 4 https://ifconfig.me  2>/dev/null \
              || true)
  if ! [[ "$public_ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    public_ip=""
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Circuit Breaker is running!${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[2]}Mode    :${COLOUR_RESET} Docker"
  echo -e "  ${aCOLOUR[2]}Image   :${COLOUR_RESET} $CB_IMAGE"
  echo -e "  ${aCOLOUR[2]}Volume  :${COLOUR_RESET} $CB_VOLUME"
  echo -e "  ${aCOLOUR[2]}Service :${COLOUR_RESET} systemctl status circuit-breaker"
  echo ""

  if [[ "$CB_TLS" == "1" ]]; then
    echo -e "$GREEN_BULLET ${aCOLOUR[0]}https://${CB_HOSTNAME}${COLOUR_RESET}  ${aCOLOUR[2]}← HTTPS via Caddy${COLOUR_RESET}"
  fi
  if [[ -n "$public_ip" ]]; then
    echo -e "$GREEN_BULLET http://${public_ip}:${CB_PORT}  ${aCOLOUR[2]}← public / VPS address${COLOUR_RESET}"
  fi
  if command -v ip >/dev/null 2>&1; then
    while IFS= read -r ip_addr; do
      [[ "$ip_addr" == "$public_ip" ]] && continue
      echo -e "$GREEN_BULLET http://${ip_addr}:${CB_PORT}"
    done < <(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
  fi
  echo -e "$GREEN_BULLET http://localhost:${CB_PORT}"
  echo ""
  if [[ -f "$CB_CONFIG_DIR/env" ]]; then
    echo -e "  ${aCOLOUR[2]}API Token : stored in ${CB_CONFIG_DIR}/env${COLOUR_RESET}"
  fi
  echo -e "  ${aCOLOUR[2]}GitHub    : https://github.com/BlkLeg/circuitbreaker"
  echo -e "  ${aCOLOUR[2]}Docs      : https://blkleg.github.io/circuitbreaker${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[4]}Next step    :${COLOUR_RESET} open the URL above and complete first-run setup"
  echo -e "  ${aCOLOUR[2]}             The vault key is generated automatically during setup.${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[2]}cb command   :${COLOUR_RESET} cb help"
  echo ""
  echo -e "  To stop      : cb restart  ${aCOLOUR[2]}(or: docker stop $CB_CONTAINER)${COLOUR_RESET}"
  echo -e "  To update    : cb update"
  echo -e "  To uninstall : cb uninstall"
  echo -e "${COLOUR_RESET}"
}

Welcome_Banner_Binary() {
  local ver
  ver=$(/usr/local/bin/circuit-breaker --version 2>/dev/null | head -1 || echo "$CB_VERSION")

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Circuit Breaker is running!${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[2]}Mode    :${COLOUR_RESET} Native binary"
  echo -e "  ${aCOLOUR[2]}Version :${COLOUR_RESET} ${ver}"
  echo -e "  ${aCOLOUR[2]}Binary  :${COLOUR_RESET} /usr/local/bin/circuit-breaker"
  echo -e "  ${aCOLOUR[2]}Config  :${COLOUR_RESET} /etc/circuit-breaker/config.yaml"
  echo -e "  ${aCOLOUR[2]}Data    :${COLOUR_RESET} /var/lib/circuit-breaker"
  echo -e "  ${aCOLOUR[2]}Service :${COLOUR_RESET} systemctl status circuit-breaker"
  echo ""
  echo -e "$GREEN_BULLET ${aCOLOUR[0]}http://localhost:8080${COLOUR_RESET}"
  if command -v ip >/dev/null 2>&1; then
    while IFS= read -r ip_addr; do
      echo -e "$GREEN_BULLET http://${ip_addr}:8080"
    done < <(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
  fi
  echo ""
  echo -e "  ${aCOLOUR[2]}GitHub    : https://github.com/BlkLeg/circuitbreaker"
  echo -e "  ${aCOLOUR[2]}Docs      : https://blkleg.github.io/circuitbreaker${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[4]}Next step    :${COLOUR_RESET} open the URL above and complete first-run setup"
  echo -e "  ${aCOLOUR[2]}             The vault key is generated automatically during setup.${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[2]}cb command   :${COLOUR_RESET} cb help"
  echo ""
  echo -e "  To manage    : cb restart / cb logs / cb status"
  echo -e "  To uninstall : cb uninstall"
  echo -e "${COLOUR_RESET}"
}

###############################################################################
# MAIN
###############################################################################

main() {
  parse_flags "$@"

  Print_Header
  Get_Region
  Check_Arch
  Check_OS
  Check_Memory
  Check_Disk

  Prompt_Mode

  case "$CB_MODE" in
    docker) Install_Docker_Mode ;;
    binary) Install_Binary_Mode ;;
    *) Show 1 "Unknown install mode: '$CB_MODE'. Use --mode docker or --mode binary." ;;
  esac
}

main "$@"
