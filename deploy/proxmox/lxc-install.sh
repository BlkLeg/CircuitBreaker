#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker — Proxmox LXC Installer
#
# Creates an unprivileged Debian 12 LXC container on a Proxmox VE host and
# installs Circuit Breaker natively (no Docker). The container is configured
# with nesting enabled and net_raw capability retained for nmap scanning.
#
# Usage:
#   ./lxc-install.sh [OPTIONS]
#
# Options:
#   --vmid <id>        Container ID (default: next available)
#   --storage <name>   Proxmox storage target (default: local-lvm)
#   --hostname <name>  Container hostname (default: circuitbreaker)
#   --memory <MB>      Memory in MB (default: 2048)
#   --cores <n>        CPU cores (default: 2)
#   --disk <GB>        Root disk size in GB (default: 8)
#   --bridge <name>    Network bridge (default: vmbr0)
#   --help             Show this help message
# ──────────────────────────────────────────────────────────────────────────────

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
header()  { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Defaults ──────────────────────────────────────────────────────────────────
VMID=""
STORAGE="local-lvm"
HOSTNAME="circuitbreaker"
MEMORY=2048
CORES=2
DISK=8
BRIDGE="vmbr0"

# ── Parse arguments ───────────────────────────────────────────────────────────
usage() {
    sed -n '/^# Usage:/,/^# ─/p' "$0" | head -n -1 | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --vmid)     VMID="$2";     shift 2 ;;
        --storage)  STORAGE="$2";  shift 2 ;;
        --hostname) HOSTNAME="$2"; shift 2 ;;
        --memory)   MEMORY="$2";   shift 2 ;;
        --cores)    CORES="$2";    shift 2 ;;
        --disk)     DISK="$2";     shift 2 ;;
        --bridge)   BRIDGE="$2";   shift 2 ;;
        --help|-h)  usage ;;
        *)
            error "Unknown option: $1"
            echo "Run with --help for usage information."
            exit 1
            ;;
    esac
done

# ── Pre-flight checks ────────────────────────────────────────────────────────
header "Pre-flight checks"

if ! command -v pct &>/dev/null; then
    error "pct command not found. This script must run on a Proxmox VE host."
    exit 1
fi
success "Running on Proxmox VE"

if [[ $(id -u) -ne 0 ]]; then
    error "This script must be run as root (or via sudo)."
    exit 1
fi
success "Running as root"

# ── Resolve VMID ──────────────────────────────────────────────────────────────
if [[ -z "$VMID" ]]; then
    VMID=$(pvesh get /cluster/nextid 2>/dev/null || echo "")
    if [[ -z "$VMID" ]]; then
        error "Could not determine next available VMID. Specify one with --vmid."
        exit 1
    fi
    info "Auto-selected VMID: ${BOLD}${VMID}${NC}"
else
    info "Using VMID: ${BOLD}${VMID}${NC}"
fi

# ── Download CT template ─────────────────────────────────────────────────────
header "Container template"

TEMPLATE_STORAGE="local"
TEMPLATE_NAME="debian-12-standard"

# Find the latest cached Debian 12 template
CACHED_TEMPLATE=$(pveam list "$TEMPLATE_STORAGE" 2>/dev/null \
    | grep "$TEMPLATE_NAME" \
    | sort -t_ -k2 -V \
    | tail -n1 \
    | awk '{print $1}' || true)

if [[ -z "$CACHED_TEMPLATE" ]]; then
    info "Downloading Debian 12 CT template..."
    pveam update &>/dev/null || true

    # Find the latest available template name
    AVAIL_TEMPLATE=$(pveam available --section system 2>/dev/null \
        | grep "$TEMPLATE_NAME" \
        | sort -t_ -k2 -V \
        | tail -n1 \
        | awk '{print $2}')

    if [[ -z "$AVAIL_TEMPLATE" ]]; then
        error "Could not find a Debian 12 standard template. Check your Proxmox template sources."
        exit 1
    fi

    pveam download "$TEMPLATE_STORAGE" "$AVAIL_TEMPLATE"
    CACHED_TEMPLATE="${TEMPLATE_STORAGE}:vztmpl/${AVAIL_TEMPLATE}"
    success "Template downloaded: ${CACHED_TEMPLATE}"
else
    success "Template cached: ${CACHED_TEMPLATE}"
fi

# ── Create host-side data directory ──────────────────────────────────────────
DATA_DIR="/var/lib/circuitbreaker-${VMID}"
mkdir -p "$DATA_DIR"
info "Data directory: ${DATA_DIR}"

# ── Create LXC container ─────────────────────────────────────────────────────
header "Creating LXC container (CT ${VMID})"

info "Hostname:  ${HOSTNAME}"
info "Memory:    ${MEMORY} MB"
info "Cores:     ${CORES}"
info "Disk:      ${DISK} GB"
info "Storage:   ${STORAGE}"
info "Bridge:    ${BRIDGE}"

pct create "$VMID" "$CACHED_TEMPLATE" \
    --hostname "$HOSTNAME" \
    --memory "$MEMORY" \
    --cores "$CORES" \
    --rootfs "${STORAGE}:${DISK}" \
    --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
    --unprivileged 1 \
    --features nesting=1 \
    --ostype debian \
    --start 0

success "Container created"

# ── Apply extra LXC config (net_raw for nmap, bind mount for data) ────────
CT_CONF="/etc/pve/lxc/${VMID}.conf"

# Retain net_raw capability so nmap works inside the container
if ! grep -q "lxc.cap.keep" "$CT_CONF" 2>/dev/null; then
    echo "lxc.cap.keep: net_raw" >> "$CT_CONF"
    success "Added lxc.cap.keep: net_raw"
fi

# Bind mount for persistent data
if ! grep -q "mp0:" "$CT_CONF" 2>/dev/null; then
    echo "mp0: ${DATA_DIR},mp=/var/lib/circuitbreaker" >> "$CT_CONF"
    success "Added bind mount: ${DATA_DIR} -> /var/lib/circuitbreaker"
fi

# ── Start container ──────────────────────────────────────────────────────────
header "Starting container"

pct start "$VMID"
info "Waiting for container to come online..."

RETRIES=30
for i in $(seq 1 $RETRIES); do
    if pct exec "$VMID" -- ping -c1 -W1 8.8.8.8 &>/dev/null; then
        success "Container is online (attempt ${i}/${RETRIES})"
        break
    fi
    if [[ $i -eq $RETRIES ]]; then
        error "Container did not get network connectivity after ${RETRIES} attempts."
        error "Check your bridge (${BRIDGE}) and DHCP configuration."
        exit 1
    fi
    sleep 2
done

# ── Install Circuit Breaker ─────────────────────────────────────────────────
header "Installing Circuit Breaker"

info "Running native installer inside CT ${VMID}..."

pct exec "$VMID" -- bash -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates
    curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | CB_INSTALL_MODE=native bash
'

success "Circuit Breaker installed"

# ── Get container IP ─────────────────────────────────────────────────────────
header "Deployment complete"

CT_IP=$(pct exec "$VMID" -- hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo -e "${GREEN}${BOLD}============================================${NC}"
echo -e "${GREEN}${BOLD}  Circuit Breaker is ready!${NC}"
echo -e "${GREEN}${BOLD}============================================${NC}"
echo ""

if [[ -n "$CT_IP" ]]; then
    echo -e "  ${BOLD}Web UI:${NC}     http://${CT_IP}:8080"
else
    warn "Could not determine container IP. Check with: pct exec ${VMID} -- hostname -I"
fi

echo -e "  ${BOLD}Container:${NC}  CT ${VMID} (${HOSTNAME})"
echo -e "  ${BOLD}Data dir:${NC}   ${DATA_DIR}"
echo ""
echo -e "${CYAN}Management commands:${NC}"
echo "  pct enter ${VMID}              # Shell into container"
echo "  pct stop ${VMID}               # Stop container"
echo "  pct start ${VMID}              # Start container"
echo "  pct destroy ${VMID} --purge    # Remove container entirely"
echo ""
echo -e "${CYAN}Service management (inside container):${NC}"
echo "  systemctl status circuitbreaker"
echo "  journalctl -u circuitbreaker -f"
echo ""
