#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker — Proxmox VM Installer
#
# Creates a Proxmox QEMU/KVM virtual machine pre-configured for Circuit
# Breaker. Since VMs require a full OS installation, this script creates the
# VM and attaches the ISO — the user must complete the OS install manually,
# then run the Circuit Breaker install script.
#
# Usage:
#   ./vm-install.sh --iso <path-to-debian-iso> [OPTIONS]
#
# Options:
#   --vmid <id>        VM ID (default: next available)
#   --storage <name>   Proxmox storage target (default: local-lvm)
#   --hostname <name>  VM name (default: circuitbreaker)
#   --memory <MB>      Memory in MB (default: 4096)
#   --cores <n>        CPU cores (default: 2)
#   --disk <GB>        Disk size in GB (default: 20)
#   --bridge <name>    Network bridge (default: vmbr0)
#   --iso <path>       Path to Debian ISO (required, e.g. local:iso/debian-12.x.x-amd64-netinst.iso)
#   --help             Show this help message
# ──────────────────────────────────────────────────────────────────────────────

# ── Color helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }
header()  { echo -e "\n${BOLD}── $* ──${NC}"; }

# ── Defaults ──────────────────────────────────────────────────────────────────
VMID=""
STORAGE="local-lvm"
HOSTNAME="circuitbreaker"
MEMORY=4096
CORES=2
DISK=20
BRIDGE="vmbr0"
ISO=""

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
        --iso)      ISO="$2";      shift 2 ;;
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

if ! command -v qm &>/dev/null; then
    error "qm command not found. This script must run on a Proxmox VE host."
    exit 1
fi
success "Running on Proxmox VE"

if [[ $(id -u) -ne 0 ]]; then
    error "This script must be run as root (or via sudo)."
    exit 1
fi
success "Running as root"

if [[ -z "$ISO" ]]; then
    error "An ISO image is required. Specify one with --iso."
    echo ""
    echo "Example:"
    echo "  ./vm-install.sh --iso local:iso/debian-12.9.0-amd64-netinst.iso"
    echo ""
    echo "Available ISOs on this host:"
    pvesm list local --content iso 2>/dev/null | tail -n +2 | awk '{print "  " $1}' || echo "  (none found)"
    exit 1
fi
success "ISO specified: ${ISO}"

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

# ── Create VM ─────────────────────────────────────────────────────────────────
header "Creating VM (VMID ${VMID})"

info "Name:      ${HOSTNAME}"
info "Memory:    ${MEMORY} MB"
info "Cores:     ${CORES}"
info "Disk:      ${DISK} GB"
info "Storage:   ${STORAGE}"
info "Bridge:    ${BRIDGE}"
info "ISO:       ${ISO}"

qm create "$VMID" \
    --name "$HOSTNAME" \
    --memory "$MEMORY" \
    --cores "$CORES" \
    --net0 "virtio,bridge=${BRIDGE}" \
    --ide2 "${ISO},media=cdrom" \
    --scsi0 "${STORAGE}:${DISK}" \
    --scsihw virtio-scsi-single \
    --boot "order=ide2;scsi0" \
    --ostype l26 \
    --agent enabled=1 \
    --serial0 socket \
    --vga serial0

success "VM created"

# ── Post-creation instructions ───────────────────────────────────────────────
header "Next steps"

echo ""
echo -e "${GREEN}${BOLD}============================================${NC}"
echo -e "${GREEN}${BOLD}  VM ${VMID} created successfully${NC}"
echo -e "${GREEN}${BOLD}============================================${NC}"
echo ""
echo -e "${BOLD}The VM is ready but requires manual OS installation.${NC}"
echo ""
echo -e "${CYAN}Step 1: Start the VM and install Debian${NC}"
echo "  qm start ${VMID}"
echo "  # Open the Proxmox web console or use:"
echo "  # qm terminal ${VMID}  (serial console)"
echo ""
echo -e "${CYAN}Step 2: After Debian is installed and booted, install Circuit Breaker${NC}"
echo "  # SSH into the VM or use the console, then run:"
echo "  curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash"
echo ""
echo -e "${CYAN}Step 3: Access Circuit Breaker${NC}"
echo "  # Once installed, access the web UI at:"
echo "  # http://<vm-ip>:8080"
echo ""
echo -e "${CYAN}VM management commands:${NC}"
echo "  qm start ${VMID}               # Start VM"
echo "  qm stop ${VMID}                # Stop VM"
echo "  qm shutdown ${VMID}            # Graceful shutdown"
echo "  qm destroy ${VMID} --purge     # Remove VM entirely"
echo "  qm terminal ${VMID}            # Serial console"
echo ""
echo -e "${YELLOW}Tip:${NC} After OS install, remove the ISO to boot from disk:"
echo "  qm set ${VMID} --ide2 none"
echo "  qm set ${VMID} --boot order=scsi0"
echo ""
