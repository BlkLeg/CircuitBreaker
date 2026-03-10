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
CB_TAG="${CB_TAG:-latest}"
CB_INSTALL_DIR="${CB_INSTALL_DIR:-$HOME/.circuit-breaker}"
CB_YES="${CB_YES:-0}"
CB_NO_DESKTOP="${CB_NO_DESKTOP:-0}"
CB_NO_SYSTEMD="${CB_NO_SYSTEMD:-0}"

CB_IMAGE="${CB_IMAGE:-ghcr.io/blkleg/circuitbreaker:${CB_VERSION}}"
CB_PORT="${CB_PORT:-8080}"
CB_CONTAINER="${CB_CONTAINER:-circuit-breaker}"
CB_VOLUME="${CB_VOLUME:-circuit-breaker-data}"
CB_BINARY_DATA_DIR="${CB_BINARY_DATA_DIR:-/var/lib/circuit-breaker}"
CB_BINARY_LOG_DIR="${CB_BINARY_LOG_DIR:-/var/log/circuit-breaker}"
CB_BINARY_SHARE_DIR="${CB_BINARY_SHARE_DIR:-/usr/local/share/circuit-breaker}"
CB_BINARY_CERT_DIR="${CB_BINARY_CERT_DIR:-/etc/circuit-breaker/certs}"
CB_BINARY_TLS_MODE="${CB_BINARY_TLS_MODE:-off}"
CB_BINARY_TLS_CERT_FILE="${CB_BINARY_TLS_CERT_FILE:-}"
CB_BINARY_TLS_KEY_FILE="${CB_BINARY_TLS_KEY_FILE:-}"
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

# ─── Download command (curl or wget) ──────────────────────────────────────────
# Production install requires downloads; prefer curl, fall back to wget (e.g. minimal Ubuntu).
if command -v curl >/dev/null 2>&1; then
  CB_FETCH="curl"
  CB_FETCH_STDOUT=()  # curl -fsSL URL
  CB_FETCH_FILE=()    # curl -fsSL URL -o FILE
  CB_FETCH_CHECK=()   # curl -sf URL -o /dev/null (for health)
elif command -v wget >/dev/null 2>&1; then
  CB_FETCH="wget"
  CB_FETCH_STDOUT=("wget" "-qO-")
  CB_FETCH_FILE=("wget" "-qO")
  CB_FETCH_CHECK=("wget" "-q" "--spider")
else
  echo "Circuit Breaker install requires curl or wget. Install one (e.g. sudo apt-get install -y curl) and try again." >&2
  exit 1
fi

# Download URL to stdout (for piping) or to a file. Usage: cb_fetch <url> [output_file] [insecure] [timeout_sec]
# If output_file is omitted, prints to stdout. insecure=1 skips TLS verify. timeout_sec optional (e.g. 3).
cb_fetch() {
  local url="$1"
  local out="$2"
  local insecure="${3:-0}"
  local timeout="${4:-}"
  if [[ "$CB_FETCH" == "curl" ]]; then
    local curl_args=(-fsSL)
    [[ "$insecure" == "1" ]] && curl_args+=(-k)
    [[ -n "$timeout" ]] && curl_args+=(--connect-timeout "$timeout")
    if [[ -n "$out" ]]; then
      curl "${curl_args[@]}" "$url" -o "$out"
    else
      curl "${curl_args[@]}" "$url"
    fi
  else
    local wget_args=(-q)
    [[ "$insecure" == "1" ]] && wget_args+=(--no-check-certificate)
    [[ -n "$timeout" ]] && wget_args+=(--timeout="$timeout")
    if [[ -n "$out" ]]; then
      wget "${wget_args[@]}" -O "$out" "$url"
    else
      wget "${wget_args[@]}" -O - "$url"
    fi
  fi
}

# Probe URL (exit 0 if reachable). Usage: cb_fetch_ok <url> [insecure]
cb_fetch_ok() {
  local url="$1"
  local insecure="${2:-0}"
  if [[ "$CB_FETCH" == "curl" ]]; then
    local curl_args=(-sf)
    [[ "$insecure" == "1" ]] && curl_args+=(-k)
    curl "${curl_args[@]}" "$url" >/dev/null 2>&1
  else
    wget -q --spider "${url}" 2>/dev/null
  fi
}

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

Prompt_Input() {
  local prompt="$1"
  local default="${2:-}"
  if [[ "$CB_YES" == "1" ]]; then
    printf '%s' "$default"
    return
  fi
  if [[ -n "$default" ]]; then
    printf "  %s [%s] " "$prompt" "$default"
  else
    printf "  %s " "$prompt"
  fi
  read -r reply < /dev/tty
  if [[ -z "$reply" ]]; then
    printf '%s' "$default"
  else
    printf '%s' "$reply"
  fi
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
  --mode docker|compose|binary  Choose install mode (skips interactive prompt)
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
  --tls-mode MODE       Native HTTPS mode: off, local, or provided
  --cert-file PATH      Existing TLS certificate path for native installs
  --key-file PATH       Existing TLS private key path for native installs

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
      --tls-mode)   CB_BINARY_TLS_MODE="$2"; shift 2 ;;
      --cert-file)  CB_BINARY_TLS_CERT_FILE="$2"; shift 2 ;;
      --key-file)   CB_BINARY_TLS_KEY_FILE="$2"; shift 2 ;;
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
  REGION=$(cb_fetch "https://ipconfig.io/country_code" "" 0 3 2>/dev/null || true)
  if [[ -z "$REGION" ]]; then
    REGION=$(cb_fetch "https://ifconfig.io/country_code" "" 0 3 2>/dev/null || true)
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
    cb_fetch "https://get.docker.com" "" 0 | sudo bash -s docker --mirror Aliyun
  else
    cb_fetch "https://get.docker.com" "" 0 | sudo bash
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
  local cert_file="${1:-$CB_CONFIG_DIR/caddy-root-ca.crt}"

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Root Certificate Trust${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  Circuit Breaker generated a local Certificate Authority for HTTPS."
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

Upsert_Env_Value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  if [[ -f "$env_file" ]] && grep -q "^${key}=" "$env_file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
  else
    printf '%s=%s\n' "$key" "$value" >> "$env_file"
  fi
}

Persist_Binary_Runtime_Env() {
  local env_file="/etc/circuit-breaker/env"
  sudo touch "$env_file"
  sudo chown root:circuitbreaker "$env_file"
  sudo chmod 640 "$env_file"

  local tmp_env
  tmp_env=$(mktemp)
  sudo cp "$env_file" "$tmp_env"

  Upsert_Env_Value "$tmp_env" "APP_VERSION" "$(/usr/local/bin/circuit-breaker --version 2>/dev/null | head -1 || echo "$CB_VERSION")"
  Upsert_Env_Value "$tmp_env" "CB_SHARE_DIR" "$CB_BINARY_SHARE_DIR"
  Upsert_Env_Value "$tmp_env" "CB_ALEMBIC_INI" "$CB_BINARY_SHARE_DIR/backend/alembic.ini"
  Upsert_Env_Value "$tmp_env" "CB_DOCS_SEED_FILE" "$CB_BINARY_SHARE_DIR/DocsPage.md"
  Upsert_Env_Value "$tmp_env" "STATIC_DIR" "$CB_BINARY_SHARE_DIR/frontend"
  Upsert_Env_Value "$tmp_env" "CB_DATA_DIR" "$CB_BINARY_DATA_DIR"
  if [[ "$CB_BINARY_TLS_MODE" != "off" && -n "$CB_BINARY_TLS_CERT_FILE" && -n "$CB_BINARY_TLS_KEY_FILE" ]]; then
    Upsert_Env_Value "$tmp_env" "CB_TLS_ENABLED" "true"
    Upsert_Env_Value "$tmp_env" "CB_TLS_CERT_FILE" "$CB_BINARY_TLS_CERT_FILE"
    Upsert_Env_Value "$tmp_env" "CB_TLS_KEY_FILE" "$CB_BINARY_TLS_KEY_FILE"
  else
    Upsert_Env_Value "$tmp_env" "CB_TLS_ENABLED" "false"
  fi

  sudo install -m 640 -o root -g circuitbreaker "$tmp_env" "$env_file"
  rm -f "$tmp_env"
  Show 0 "Native runtime environment saved to $env_file"
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
  local scheme="${2:-http}"
  local insecure="${3:-0}"
  Show 2 "Waiting for Circuit Breaker to be ready..."
  local tries=0
  until cb_fetch_ok "${scheme}://127.0.0.1:${port}/api/v1/health" "$insecure"; do
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
    url=$(cb_fetch "https://api.github.com/repos/BlkLeg/CircuitBreaker/releases/latest" "" 0 \
          | grep '"browser_download_url"' \
          | grep "circuit-breaker_.*_linux_${arch}\.tar\.gz" \
          | head -1 | cut -d'"' -f4 || true)
  else
    url="https://github.com/BlkLeg/CircuitBreaker/releases/download/${CB_VERSION}/circuit-breaker_${CB_VERSION}_linux_${arch}.tar.gz"
  fi

  if [[ -z "$url" ]]; then
    rm -rf "$tmpdir"
    Show 1 "Could not resolve binary download URL for ${arch}. Check https://github.com/BlkLeg/CircuitBreaker/releases"
  fi

  Show 2 "Downloading: $url"
  cb_fetch "$url" "$tmpdir/cb.tar.gz" 0 || { rm -rf "$tmpdir"; Show 1 "Download failed."; }
  tar -xzf "$tmpdir/cb.tar.gz" -C "$tmpdir"

  if [[ ! -f "$tmpdir/circuit-breaker" ]]; then
    rm -rf "$tmpdir"
    Show 1 "Binary not found in archive."
  fi
  if [[ ! -d "$tmpdir/share" ]]; then
    rm -rf "$tmpdir"
    Show 1 "Shared runtime assets not found in archive."
  fi

  CB_BINARY_TMPDIR="$tmpdir"
  Show 0 "Native package downloaded and unpacked."
}

Install_Binary_Bundle() {
  [[ -n "${CB_BINARY_TMPDIR:-}" && -d "${CB_BINARY_TMPDIR}" ]] \
    || Show 1 "Binary package was not downloaded correctly."

  sudo install -Dm755 "$CB_BINARY_TMPDIR/circuit-breaker" /usr/local/bin/circuit-breaker
  sudo install -d -m 755 "$CB_BINARY_SHARE_DIR"
  sudo cp -a "$CB_BINARY_TMPDIR/share/." "$CB_BINARY_SHARE_DIR/"
  Show 0 "Binary installed to /usr/local/bin/circuit-breaker"
  Show 0 "Shared runtime assets installed to $CB_BINARY_SHARE_DIR"
}

Create_User_And_Dirs() {
  if ! id circuitbreaker &>/dev/null; then
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin circuitbreaker
    Show 0 "System user 'circuitbreaker' created."
  else
    Show 0 "System user 'circuitbreaker' already exists."
  fi
  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker "$CB_BINARY_DATA_DIR"
  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker "$CB_BINARY_LOG_DIR"
  sudo install -d -m 755 /etc/circuit-breaker
  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker "$CB_BINARY_CERT_DIR"
  Show 0 "Directories created."
}

Generate_Local_TLS_Certs() {
  command -v openssl >/dev/null 2>&1 || Show 1 "openssl is required to generate local TLS certificates."

  local cert_dir
  cert_dir=$(Prompt_Input "Certificate storage directory" "$CB_BINARY_CERT_DIR")
  [[ -n "$cert_dir" ]] || cert_dir="$CB_BINARY_CERT_DIR"
  CB_BINARY_CERT_DIR="$cert_dir"
  CB_HOSTNAME=$(Prompt_Input "Hostname for the local HTTPS certificate" "$CB_HOSTNAME")
  [[ -n "$CB_HOSTNAME" ]] || CB_HOSTNAME="circuitbreaker.local"

  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker "$CB_BINARY_CERT_DIR"

  local ca_key="$CB_BINARY_CERT_DIR/circuit-breaker-local-ca.key"
  local ca_crt="$CB_BINARY_CERT_DIR/circuit-breaker-local-ca.crt"
  local server_key="$CB_BINARY_CERT_DIR/server.key"
  local server_csr="$CB_BINARY_CERT_DIR/server.csr"
  local server_crt="$CB_BINARY_CERT_DIR/server.crt"
  local ext_file="$CB_BINARY_CERT_DIR/server.ext"

  sudo openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -subj "/CN=Circuit Breaker Local CA" \
    -keyout "$ca_key" -out "$ca_crt" >/dev/null 2>&1
  sudo openssl req -newkey rsa:2048 -nodes \
    -subj "/CN=${CB_HOSTNAME}" \
    -keyout "$server_key" -out "$server_csr" >/dev/null 2>&1
  sudo tee "$ext_file" >/dev/null <<EOF
subjectAltName=DNS:${CB_HOSTNAME},IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF
  sudo openssl x509 -req -sha256 -days 825 \
    -in "$server_csr" -CA "$ca_crt" -CAkey "$ca_key" -CAcreateserial \
    -out "$server_crt" -extfile "$ext_file" >/dev/null 2>&1
  sudo rm -f "$server_csr" "$ext_file"
  sudo chown root:circuitbreaker "$server_key" "$server_crt"
  sudo chmod 600 "$ca_key"
  sudo chmod 640 "$server_key"
  sudo chmod 644 "$ca_crt" "$server_crt"

  CB_BINARY_TLS_MODE="local"
  CB_BINARY_TLS_CERT_FILE="$server_crt"
  CB_BINARY_TLS_KEY_FILE="$server_key"
  Show 0 "Local HTTPS certificates generated."

  if Confirm "Trust the generated local Certificate Authority now?" "y"; then
    Trust_CA "$ca_crt"
  else
    Show 3 "Skipping CA trust. Browsers will show a certificate warning."
  fi
}

Setup_Provided_TLS_Certs() {
  local source_cert source_key cert_dir
  source_cert=$(Prompt_Input "Path to your TLS certificate file" "$CB_BINARY_TLS_CERT_FILE")
  source_key=$(Prompt_Input "Path to your TLS private key file" "$CB_BINARY_TLS_KEY_FILE")
  cert_dir=$(Prompt_Input "Certificate storage directory" "$CB_BINARY_CERT_DIR")

  [[ -f "$source_cert" ]] || Show 1 "Certificate file not found: $source_cert"
  [[ -f "$source_key" ]] || Show 1 "Private key file not found: $source_key"
  [[ -n "$cert_dir" ]] || cert_dir="$CB_BINARY_CERT_DIR"
  CB_BINARY_CERT_DIR="$cert_dir"

  sudo install -d -m 750 -o circuitbreaker -g circuitbreaker "$CB_BINARY_CERT_DIR"
  sudo install -m 640 -o root -g circuitbreaker "$source_cert" "$CB_BINARY_CERT_DIR/server.crt"
  sudo install -m 640 -o root -g circuitbreaker "$source_key" "$CB_BINARY_CERT_DIR/server.key"

  CB_BINARY_TLS_MODE="provided"
  CB_BINARY_TLS_CERT_FILE="$CB_BINARY_CERT_DIR/server.crt"
  CB_BINARY_TLS_KEY_FILE="$CB_BINARY_CERT_DIR/server.key"
  Show 0 "Provided TLS certificate and key installed."
}

Configure_Binary_TLS() {
  if [[ "$CB_BINARY_TLS_MODE" == "off" ]]; then
    if ! Confirm "Enable HTTPS for the native binary install?"; then
      Show 2 "Skipping HTTPS for native install."
      return
    fi
    echo ""
    echo -e "$GREEN_LINE"
    echo -e " ${aCOLOUR[1]}Native HTTPS Mode${COLOUR_RESET}"
    echo -e "$GREEN_LINE"
    echo ""
    echo -e "  ${aCOLOUR[1]}[1]${COLOUR_RESET} Generate and trust a local HTTPS certificate"
    echo -e "  ${aCOLOUR[1]}[2]${COLOUR_RESET} Use an existing certificate and private key"
    echo ""
    printf "  Choice [1/2]: "
    read -r tls_choice < /dev/tty
    case "$tls_choice" in
      1) CB_BINARY_TLS_MODE="local" ;;
      2) CB_BINARY_TLS_MODE="provided" ;;
      *) Show 1 "Invalid HTTPS choice '$tls_choice'." ;;
    esac
  fi

  case "$CB_BINARY_TLS_MODE" in
    off|"") ;;
    local) Generate_Local_TLS_Certs ;;
    provided) Setup_Provided_TLS_Certs ;;
    *) Show 1 "Unsupported native TLS mode '$CB_BINARY_TLS_MODE'. Use off, local, or provided." ;;
  esac
}

Generate_Config() {
  local cfg="/etc/circuit-breaker/config.yaml"
  if [[ -f "$cfg" ]]; then
    sudo cp "$cfg" "${cfg}.bak"
    Show 3 "Existing config backed up to ${cfg}.bak before refresh."
  fi
  sudo tee "$cfg" >/dev/null <<CFGEOF
# Circuit Breaker configuration — generated by install.sh
host: 0.0.0.0
port: ${CB_PORT}
data_dir: ${CB_BINARY_DATA_DIR}
log_dir: ${CB_BINARY_LOG_DIR}
share_dir: ${CB_BINARY_SHARE_DIR}
static_dir: ${CB_BINARY_SHARE_DIR}/frontend
uploads_dir: ${CB_BINARY_DATA_DIR}/uploads
workers: 1
tls_enabled: $([[ "$CB_BINARY_TLS_MODE" == "off" || -z "$CB_BINARY_TLS_MODE" ]] && echo "false" || echo "true")
tls_cert_file: ${CB_BINARY_TLS_CERT_FILE}
tls_key_file: ${CB_BINARY_TLS_KEY_FILE}
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
  sudo tee /etc/systemd/system/circuit-breaker.service >/dev/null <<UNIT
[Unit]
Description=Circuit Breaker (Native)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=circuitbreaker
Group=circuitbreaker
WorkingDirectory=${CB_BINARY_DATA_DIR}
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
  local desktop_scheme="http"
  local desktop_host="localhost"
  if [[ "$CB_MODE" == "binary" && "$CB_BINARY_TLS_MODE" != "off" && -n "$CB_BINARY_TLS_MODE" ]]; then
    desktop_scheme="https"
    desktop_host="$CB_HOSTNAME"
  fi

  # Write .desktop file
  sudo tee /usr/share/applications/circuit-breaker.desktop >/dev/null <<DESKTOP
[Desktop Entry]
Type=Application
Name=Circuit Breaker
Comment=Homelab topology, documented.
Exec=xdg-open ${desktop_scheme}://${desktop_host}:${CB_PORT}
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
    if cb_fetch "$icon_url" /tmp/cb-icon.png 0 2>/dev/null; then
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
CB_BACKEND_CONTAINER=$([[ "$CB_MODE" == "binary" ]] && echo "" || echo "${CB_CONTAINER}")
CB_VOLUME=${CB_VOLUME}
CB_PORT=${CB_PORT}
CB_IMAGE=${CB_IMAGE}
CB_DATA_DIR=$([[ "$CB_MODE" == "binary" ]] && echo "${CB_BINARY_DATA_DIR}" || echo "/data")
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
    if cb_fetch "$url" /tmp/cb-cli 0 2>/dev/null; then
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
  elif [[ "$mode" == "compose" ]]; then
    cat >> "$tmp" <<COMPOSE_VARS
CB_INSTALL_DIR="${CB_INSTALL_DIR}"
CB_COMPOSE_FILE="${CB_INSTALL_DIR}/docker-compose.prod.yml"
COMPOSE_VARS
  elif [[ "$mode" == "binary" ]]; then
    cat >> "$tmp" <<BINARY_VARS
CB_BINARY_DATA_DIR="${CB_BINARY_DATA_DIR}"
CB_BINARY_LOG_DIR="${CB_BINARY_LOG_DIR}"
CB_BINARY_SHARE_DIR="${CB_BINARY_SHARE_DIR}"
CB_BINARY_CERT_DIR="${CB_BINARY_CERT_DIR}"
CB_BINARY_TLS_MODE="${CB_BINARY_TLS_MODE}"
CB_HOSTNAME="${CB_HOSTNAME}"
CB_CA_SYSTEM_NAME="${CB_CA_SYSTEM_NAME}"
CB_CA_NSS_NAME="${CB_CA_NSS_NAME}"
BINARY_VARS
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

elif [[ "$INSTALLED_MODE" == "compose" ]]; then

  stop_systemd

  Show 2 "Stopping compose stack..."
  if [[ -f "$CB_COMPOSE_FILE" ]]; then
    (cd "$(dirname "$CB_COMPOSE_FILE")" && docker compose -f "$(basename "$CB_COMPOSE_FILE")" down) 2>/dev/null || true
  elif [[ -d "$CB_INSTALL_DIR" ]]; then
    (cd "$CB_INSTALL_DIR" && docker compose -f docker-compose.prod.yml down) 2>/dev/null || true
  fi
  Show 0 "Compose stack stopped."

  if Confirm "Remove Docker volumes (all data)?"; then
    if [[ -f "$CB_COMPOSE_FILE" ]]; then
      (cd "$(dirname "$CB_COMPOSE_FILE")" && docker compose -f "$(basename "$CB_COMPOSE_FILE")" down -v) 2>/dev/null || true
    elif [[ -d "$CB_INSTALL_DIR" ]]; then
      (cd "$CB_INSTALL_DIR" && docker compose -f docker-compose.prod.yml down -v) 2>/dev/null || true
    fi
    Show 0 "Volumes removed."
  else
    Show 3 "Volumes kept."
  fi

  if Confirm "Remove install directory '$CB_INSTALL_DIR' (compose files, .env)?"; then
    rm -rf "$CB_INSTALL_DIR"
    Show 0 "Install directory removed."
  else
    Show 3 "Install directory kept at $CB_INSTALL_DIR"
  fi

elif [[ "$INSTALLED_MODE" == "binary" ]]; then

  stop_systemd

  sudo rm -f /usr/local/bin/circuit-breaker
  Show 0 "Binary removed."

  sudo rm -rf "$CB_BINARY_SHARE_DIR"
  Show 0 "Shared runtime assets removed."

  sudo rm -rf /etc/circuit-breaker/
  Show 0 "Config removed."

  sudo rm -f /usr/share/applications/circuit-breaker.desktop
  sudo rm -f /usr/share/icons/hicolor/256x256/apps/circuit-breaker.png
  rm -f "$HOME/Desktop/circuit-breaker.desktop" 2>/dev/null || true
  gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
  Show 0 "Desktop entry and icon removed."

  if [[ "$CB_BINARY_TLS_MODE" == "local" ]]; then
    sudo rm -f "/etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    sudo rm -f "/usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    sudo rm -f "/etc/ca-certificates/trust-source/anchors/${CB_CA_SYSTEM_NAME}.crt" 2>/dev/null || true
    command -v update-ca-trust >/dev/null 2>&1 && sudo update-ca-trust || true
    command -v update-ca-certificates >/dev/null 2>&1 && sudo update-ca-certificates || true
    if command -v certutil >/dev/null 2>&1; then
      certutil -d sql:"$HOME/.pki/nssdb" -D -n "$CB_CA_NSS_NAME" 2>/dev/null || true
    fi
    if grep -q "$CB_HOSTNAME" /etc/hosts 2>/dev/null; then
      sudo sed -i "/$CB_HOSTNAME/d" /etc/hosts
    fi
    Show 0 "Local HTTPS trust removed."
  fi

  if Confirm "Remove data (${CB_BINARY_DATA_DIR}) and logs (${CB_BINARY_LOG_DIR})?"; then
    sudo rm -rf "$CB_BINARY_DATA_DIR" "$CB_BINARY_LOG_DIR"
    Show 0 "Data and logs removed."
  else
    Show 3 "Data and logs kept at ${CB_BINARY_DATA_DIR} and ${CB_BINARY_LOG_DIR}"
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
    CB_MODE="${CB_MODE:-docker}"
    Show 0 "Non-interactive mode: defaulting to ${CB_MODE} install."
    return
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}How would you like to install Circuit Breaker?${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[1]}[1]${COLOUR_RESET} Docker container  ${aCOLOUR[2]}(single image — minimal)${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[1]}[2]${COLOUR_RESET} Compose stack    ${aCOLOUR[2]}(full capability — discovery, webhooks, HTTPS)${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[1]}[3]${COLOUR_RESET} Native binary    ${aCOLOUR[2]}(systemd service, FHS paths, no Docker required)${COLOUR_RESET}"
  echo -e "  ${aCOLOUR[1]}[Q]${COLOUR_RESET} Quit"
  echo ""
  printf "  Choice [1/2/3/Q]: "
  read -r choice < /dev/tty
  echo ""

  case "$choice" in
    1)    CB_MODE="docker" ;;
    2)    CB_MODE="compose" ;;
    3)    CB_MODE="binary" ;;
    [qQ]) echo "  Exiting."; exit 0 ;;
    *)    Show 1 "Invalid choice '$choice'. Re-run and enter 1, 2, 3, or Q." ;;
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

Install_Compose_Mode() {
  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Compose Stack Install (Prebuilt)${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""

  CB_PORT="80"
  Check_Docker
  Check_Compose_Ports
  mkdir -p "$CB_INSTALL_DIR"
  CB_CONFIG_DIR="$CB_INSTALL_DIR"
  chmod 700 "$CB_INSTALL_DIR"

  Show 2 "Downloading compose files..."
  # Single source of truth for production Docker: docker/docker-compose.prod.yml (see README)
  local base="https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main"
  cb_fetch "${base}/docker/docker-compose.prod.yml" "$CB_INSTALL_DIR/docker-compose.prod.yml" 0 \
    || Show 1 "Failed to download docker-compose.prod.yml"
  cb_fetch "${base}/docker/Caddyfile" "$CB_INSTALL_DIR/Caddyfile" 0 \
    || Show 1 "Failed to download Caddyfile"
  cb_fetch "${base}/docker/.env.example" "$CB_INSTALL_DIR/.env.example" 0 \
    || Show 1 "Failed to download .env.example"
  Show 0 "Compose files downloaded."

  if [[ ! -f "$CB_INSTALL_DIR/.env" ]]; then
    cp "$CB_INSTALL_DIR/.env.example" "$CB_INSTALL_DIR/.env"
    Show 0 "Created .env from template."
  fi

  export CB_TAG
  Show 2 "Pulling images..."
  (cd "$CB_INSTALL_DIR" && docker compose -f docker-compose.prod.yml pull) \
    || Show 1 "Failed to pull images."
  Show 0 "Images pulled."

  Show 2 "Starting compose stack..."
  (cd "$CB_INSTALL_DIR" && docker compose -f docker-compose.prod.yml up -d) \
    || Show 1 "Failed to start compose stack."
  Show 0 "Stack started."

  Wait_For_Ready "80" "http" "0"
  Setup_Systemd_Compose
  Save_Install_Config_Compose
  Install_CB_Command
  Write_Uninstall_Script "compose"
  Welcome_Banner_Compose
}

Check_Compose_Ports() {
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
    Show 1 "Compose stack requires ports 80 and 443. Stop the conflicting service or choose a different install mode."
  fi
  Show 0 "Ports 80 and 443 are available."
}

Setup_Systemd_Compose() {
  if [[ "$CB_NO_SYSTEMD" == "1" ]]; then
    Show 2 "Skipping systemd setup (--no-systemd)."
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    Show 3 "systemctl not found — skipping systemd service install."
    return
  fi

  Show 2 "Installing systemd service (Compose mode)..."
  sudo tee /etc/systemd/system/circuit-breaker.service >/dev/null <<UNIT
[Unit]
Description=Circuit Breaker (Docker Compose)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${CB_INSTALL_DIR}

ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
ExecReload=/usr/bin/docker compose -f docker-compose.prod.yml pull && /usr/bin/docker compose -f docker-compose.prod.yml up -d

TimeoutStartSec=120
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable --now circuit-breaker
  Show 0 "systemd service enabled: circuit-breaker"
}

Save_Install_Config_Compose() {
  mkdir -p "$CB_CONFIG_DIR"
  chmod 700 "$CB_CONFIG_DIR"
  cat > "$CB_CONFIG_DIR/install.conf" <<CONFEOF
# Circuit Breaker — install config (compose mode)
CB_MODE=compose
CB_CONTAINER=cb-backend
CB_BACKEND_CONTAINER=cb-backend
CB_INSTALL_DIR=${CB_INSTALL_DIR}
CB_COMPOSE_FILE=${CB_INSTALL_DIR}/docker-compose.prod.yml
CB_PORT=80
CB_DATA_DIR=/app/data
CB_IMAGE=ghcr.io/blkleg/circuitbreaker:backend-${CB_TAG}
CONFEOF
  chmod 600 "$CB_CONFIG_DIR/install.conf"
  Show 0 "Install config saved to $CB_CONFIG_DIR/install.conf"
}

Welcome_Banner_Compose() {
  local public_ip=""
  public_ip=$(cb_fetch "https://ipinfo.io/ip" "" 0 4 2>/dev/null | tr -d '\n' || true)
  if [[ -z "$public_ip" ]]; then
    public_ip=$(cb_fetch "https://ifconfig.me" "" 0 4 2>/dev/null | tr -d '\n' || true)
  fi
  if ! [[ "$public_ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    public_ip=""
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Circuit Breaker is running!${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[2]}Mode    :${COLOUR_RESET} Compose (full stack)"
  echo -e "  ${aCOLOUR[2]}Install :${COLOUR_RESET} $CB_INSTALL_DIR"
  echo -e "  ${aCOLOUR[2]}Service :${COLOUR_RESET} systemctl status circuit-breaker"
  echo ""

  echo -e "$GREEN_BULLET ${aCOLOUR[0]}https://localhost${COLOUR_RESET}  ${aCOLOUR[2]}← HTTPS (trust CA when prompted)${COLOUR_RESET}"
  if [[ -n "$public_ip" ]]; then
    echo -e "$GREEN_BULLET https://${public_ip}  ${aCOLOUR[2]}← public / VPS address${COLOUR_RESET}"
  fi
  if command -v ip >/dev/null 2>&1; then
    while IFS= read -r ip_addr; do
      [[ "$ip_addr" == "$public_ip" ]] && continue
      echo -e "$GREEN_BULLET https://${ip_addr}"
    done < <(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
  fi
  echo ""
  echo -e "  ${aCOLOUR[4]}Next step    :${COLOUR_RESET} open the URL above and complete first-run setup"
  echo -e "  ${aCOLOUR[2]}             The vault key is generated automatically during setup.${COLOUR_RESET}"
  echo ""
  echo -e "  ${aCOLOUR[2]}cb command   :${COLOUR_RESET} cb help"
  echo ""
  echo -e "  To update    : docker compose -f $CB_INSTALL_DIR/docker-compose.prod.yml pull && docker compose up -d"
  echo -e "  To uninstall : cb uninstall"
  echo -e "${COLOUR_RESET}"
}

Install_Binary_Mode() {
  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Native Binary Install${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""

  Require_Sudo
  Find_Free_Port
  Download_Binary
  Install_Binary_Bundle
  Create_User_And_Dirs
  Configure_Binary_TLS

  # For binary mode, write config + token to /etc/circuit-breaker/
  CB_CONFIG_DIR="/etc/circuit-breaker"
  Generate_Config
  Generate_API_Token
  Persist_Binary_Runtime_Env

  Setup_Systemd_Binary
  Setup_Desktop
  if [[ "$CB_BINARY_TLS_MODE" == "off" || -z "$CB_BINARY_TLS_MODE" ]]; then
    Wait_For_Ready "$CB_PORT" "http" "0"
  else
    Wait_For_Ready "$CB_PORT" "https" "1"
  fi
  Save_Install_Config
  Install_CB_Command
  Write_Uninstall_Script "binary"
  rm -rf "${CB_BINARY_TMPDIR:-}"
  Welcome_Banner_Binary
}

###############################################################################
# WELCOME BANNERS
###############################################################################

Welcome_Banner_Docker() {
  local public_ip=""
  public_ip=$(cb_fetch "https://ipinfo.io/ip" "" 0 4 2>/dev/null | tr -d '\n' || true)
  if [[ -z "$public_ip" ]]; then
    public_ip=$(cb_fetch "https://ifconfig.me" "" 0 4 2>/dev/null | tr -d '\n' || true)
  fi
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
  local scheme="http"
  local host="localhost"
  if [[ "$CB_BINARY_TLS_MODE" != "off" && -n "$CB_BINARY_TLS_MODE" ]]; then
    scheme="https"
    host="$CB_HOSTNAME"
  fi

  echo ""
  echo -e "$GREEN_LINE"
  echo -e " ${aCOLOUR[1]}Circuit Breaker is running!${COLOUR_RESET}"
  echo -e "$GREEN_LINE"
  echo ""
  echo -e "  ${aCOLOUR[2]}Mode    :${COLOUR_RESET} Native binary"
  echo -e "  ${aCOLOUR[2]}Version :${COLOUR_RESET} ${ver}"
  echo -e "  ${aCOLOUR[2]}Binary  :${COLOUR_RESET} /usr/local/bin/circuit-breaker"
  echo -e "  ${aCOLOUR[2]}Config  :${COLOUR_RESET} /etc/circuit-breaker/config.yaml"
  echo -e "  ${aCOLOUR[2]}Data    :${COLOUR_RESET} ${CB_BINARY_DATA_DIR}"
  echo -e "  ${aCOLOUR[2]}Service :${COLOUR_RESET} systemctl status circuit-breaker"
  echo ""
  echo -e "$GREEN_BULLET ${aCOLOUR[0]}${scheme}://${host}:${CB_PORT}${COLOUR_RESET}"
  if command -v ip >/dev/null 2>&1; then
    while IFS= read -r ip_addr; do
      echo -e "$GREEN_BULLET ${scheme}://${ip_addr}:${CB_PORT}"
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
    docker)   Install_Docker_Mode ;;
    compose)  Install_Compose_Mode ;;
    binary)   Install_Binary_Mode ;;
    *) Show 1 "Unknown install mode: '$CB_MODE'. Use --mode docker, --mode compose, or --mode binary." ;;
  esac
}

main "$@"
