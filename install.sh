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
  --help            Show this help message and exit

Environment variables (compatible with 'curl | bash' piping):
  CB_PORT, CB_VOLUME, CB_IMAGE, CB_CONTAINER

Examples:
  # Default install
  curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash

  # Custom port
  CB_PORT=9090 curl -fsSL .../install.sh | bash

  # Local run with flags
  bash install.sh --port 9090 --volume /opt/cb-data
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
  # Bind to all interfaces so the app is reachable from the host's public IP and
  # any reverse proxy or Cloudflare tunnel. Secure with a host firewall (ufw/iptables).
  docker run -d \
    --name  "$CB_CONTAINER" \
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
  echo -e "  Open your browser and visit the address above."
  echo -e "  On first launch, the setup wizard will guide you through creating"
  echo -e "  your admin account and personalizing your dashboard."
  echo -e "$GREEN_LINE"
  echo ""
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

# Step 7: Pull image and start container
Pull_And_Run

# Step 8: Wait for health
Wait_For_Ready

# Step 9: Print welcome
Welcome_Banner
