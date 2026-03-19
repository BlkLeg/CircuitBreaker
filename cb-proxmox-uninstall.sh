#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker — Proxmox LXC Uninstaller
# Stops and destroys the Circuit Breaker LXC container on a Proxmox VE host.
# See cb-proxmox-deploy.sh to create a new container.

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║  Circuit Breaker — Proxmox Uninstaller   ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${RESET}"
}

cb_step() { echo -e "  ${CYAN}▸${RESET} $1..."; }
cb_ok()   { echo -e "  ${GREEN}✓${RESET}  $1"; }
cb_warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }

cb_fail() {
  echo -e "\n  ${RED}✗  ERROR: $1${RESET}"
  [[ -n "${2-}" ]] && echo -e "  ${YELLOW}→  $2${RESET}"
  echo ""
  exit 1
}

cb_header

# Verify we're on a Proxmox VE host
if ! command -v pct &>/dev/null; then
  cb_fail "This script must run on a Proxmox VE host" "pct not found"
fi

# Auto-detect CTID by hostname, or prompt
DEFAULT_CTID=""
DEFAULT_CTID=$(pct list 2>/dev/null | awk 'NR>1 && $3=="circuitbreaker" {print $1}' | head -1 || true)

echo ""
if [[ -n "$DEFAULT_CTID" ]]; then
  read -rp "  Container ID to remove? [${DEFAULT_CTID}]: " INPUT_CTID
  CTID="${INPUT_CTID:-$DEFAULT_CTID}"
else
  read -rp "  Container ID to remove: " CTID
fi

[[ "$CTID" =~ ^[0-9]+$ ]] || cb_fail "Invalid CTID: $CTID"

# Verify container exists
if ! pct status "$CTID" &>/dev/null; then
  cb_fail "Container $CTID does not exist" "Check 'pct list' for available containers"
fi

CT_NAME=$(pct config "$CTID" 2>/dev/null | awk '/^hostname:/ {print $2}' || echo "unknown")
CT_STATUS=$(pct status "$CTID" 2>/dev/null | awk '{print $2}' || echo "unknown")

echo ""
echo -e "  ${BOLD}Container to remove:${RESET}"
echo "    ID       : $CTID"
echo "    Hostname : $CT_NAME"
echo "    Status   : $CT_STATUS"
echo ""
read -rp "  Permanently destroy this container? [y/N]: " CONFIRM
[[ "${CONFIRM:-N}" =~ ^[Yy]$ ]] || { echo "  Aborted."; exit 0; }

echo ""
cb_step "Stopping container $CTID"
pct stop "$CTID" --skiplock 2>/dev/null || true
cb_ok "Container stopped"

cb_step "Destroying container $CTID"
pct destroy "$CTID" --purge
cb_ok "Container $CTID removed"

echo ""
echo -e "  ${GREEN}${BOLD}Done.${RESET} Container $CTID ($CT_NAME) has been destroyed."
echo ""
