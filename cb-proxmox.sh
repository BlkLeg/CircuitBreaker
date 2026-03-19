#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker — Proxmox LXC Helper
# Runs on the Proxmox host. Creates a Debian 12 LXC container,
# installs Circuit Breaker natively inside it, and auto-configures
# the Proxmox API integration before the OOBE wizard.

LOG_FILE="/tmp/cb-proxmox-install.log"
CB_INSTALL_URL="https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh"
CB_VERSION="latest"
CB_PORT=8088

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Container defaults
CT_CORES=2
CT_RAM=4096
CT_SWAP=512
CT_DISK=20
CT_BRIDGE=vmbr0

# Runtime vars
CTID=""
STORAGE=""
CT_HOSTNAME="circuitbreaker"
CT_PASSWORD=""
TOKEN_ID=""
TOKEN_SECRET=""
CONFIGURE_API=false
CT_IP=""
CLEANUP_ON_EXIT=false

# ── Logging ───────────────────────────────────────────────────────────────────

# Strip ANSI codes from log file so it stays readable
exec > >(sed -u 's/\x1b\[[0-9;]*m//g' | tee -a "$LOG_FILE" >/dev/tty) 2>&1

# ── UI helpers ────────────────────────────────────────────────────────────────

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║     Circuit Breaker — Proxmox Helper     ║"
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

cb_section() {
  echo -e "\n  ${BOLD}$1${RESET}"
  echo "  $(printf '─%.0s' {1..42})"
}

# ── Cleanup trap ──────────────────────────────────────────────────────────────

cleanup() {
  if [[ "$CLEANUP_ON_EXIT" == "true" && -n "$CTID" ]]; then
    echo ""
    cb_warn "Interrupted — destroying container $CTID..."
    pct stop "$CTID" --skiplock 2>/dev/null || true
    pct destroy "$CTID" --purge 2>/dev/null || true
    cb_ok "Container $CTID removed."
  fi
  exit 1
}

trap cleanup INT TERM

# ── Phase 1: Preflight ────────────────────────────────────────────────────────

phase1_preflight() {
  cb_section "Phase 1 — Preflight Checks"

  cb_step "Verifying Proxmox VE host"
  if ! command -v pveversion &>/dev/null; then
    cb_fail "This script must run on a Proxmox VE host" \
      "pveversion not found — are you on PVE?"
  fi
  PVE_VER=$(pveversion | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' || echo "unknown")
  cb_ok "Proxmox VE $PVE_VER detected"

  cb_step "Checking internet connectivity"
  if ! curl -sf --max-time 10 https://github.com -o /dev/null; then
    cb_fail "No internet access" \
      "curl to github.com failed — check DNS and routing"
  fi
  cb_ok "Internet reachable"

  cb_step "Selecting next available CTID"
  CTID=$(pvesh get /cluster/nextid 2>/dev/null | tr -d '[:space:]')
  [[ "$CTID" =~ ^[0-9]+$ ]] || cb_fail "Could not determine next CTID from pvesh"
  cb_ok "CTID: $CTID"

  cb_step "Detecting storage pool"
  # Prefer local-lvm, fall back to local, then first available
  if pvesm status | awk 'NR>1 && $1=="local-lvm" && $2=="lvm-thin" {found=1} END {exit !found}'; then
    STORAGE="local-lvm"
  elif pvesm status | awk 'NR>1 && $1=="local" {found=1} END {exit !found}'; then
    STORAGE="local"
  else
    STORAGE=$(pvesm status | awk 'NR>1 && $3=="active" {print $1; exit}')
    [[ -n "$STORAGE" ]] || cb_fail "No active storage pool found" \
      "Check 'pvesm status' and ensure at least one pool is active"
  fi
  cb_ok "Storage: $STORAGE"

  cb_step "Prompting for hostname"
  echo ""
  read -rp "  Hostname? [circuitbreaker]: " INPUT_HOSTNAME
  CT_HOSTNAME="${INPUT_HOSTNAME:-circuitbreaker}"
  cb_ok "Hostname: $CT_HOSTNAME"

  # Resource confirmation
  echo ""
  echo "  Resources: ${CT_CORES} cores / ${CT_RAM}MB RAM / ${CT_DISK}GB disk"
  read -rp "  Use these defaults? [Y/n]: " CONFIRM_RESOURCES
  if [[ "${CONFIRM_RESOURCES:-Y}" =~ ^[Nn]$ ]]; then
    read -rp "  Cores [${CT_CORES}]: "   INPUT_CORES; CT_CORES="${INPUT_CORES:-$CT_CORES}"
    read -rp "  RAM MB [${CT_RAM}]: "    INPUT_RAM;   CT_RAM="${INPUT_RAM:-$CT_RAM}"
    read -rp "  Disk GB [${CT_DISK}]: "  INPUT_DISK;  CT_DISK="${INPUT_DISK:-$CT_DISK}"
  fi
  cb_ok "Resources: ${CT_CORES} cores / ${CT_RAM}MB RAM / ${CT_DISK}GB disk"

  # Container root password
  echo ""
  read -rsp "  Container root password: " CT_PASSWORD; echo ""
  [[ -n "$CT_PASSWORD" ]] || cb_fail "Container password cannot be empty" "Re-run and enter a password"
  cb_ok "Container password set"

  # Idempotency: check if a container with this hostname already has CB running
  EXISTING_CT=$(pct list | awk -v h="$CT_HOSTNAME" 'NR>1 && $3==h {print $1}' | head -1)
  if [[ -n "$EXISTING_CT" ]]; then
    EXISTING_IP=$(pct exec "$EXISTING_CT" -- hostname -I 2>/dev/null | awk '{print $1}' || true)
    if [[ -n "$EXISTING_IP" ]] && curl -sf --max-time 5 "http://$EXISTING_IP:$CB_PORT/api/v1/health" -o /dev/null 2>/dev/null; then
      echo ""
      cb_ok "Circuit Breaker already running in container $EXISTING_CT (IP: $EXISTING_IP)"
      cb_warn "To upgrade: pct exec $EXISTING_CT -- bash -c \"curl -fsSL $CB_INSTALL_URL | bash -s -- --unattended --upgrade\""
      exit 0
    fi
  fi
}

# ── Phase 2: API token ────────────────────────────────────────────────────────

phase2_api_token() {
  cb_section "Phase 2 — Proxmox API Integration (optional)"

  echo ""
  read -rp "  Configure Proxmox auto-discovery? [Y/n]: " CONFIGURE_INPUT
  CONFIGURE_INPUT="${CONFIGURE_INPUT:-Y}"

  if [[ "$CONFIGURE_INPUT" =~ ^[Yy]$ ]]; then
    CONFIGURE_API=true
    echo ""
    read -rp "  API Token ID? [circuitbreaker@pam!circuitbreaker]: " INPUT_TOKEN_ID
    TOKEN_ID="${INPUT_TOKEN_ID:-circuitbreaker@pam!circuitbreaker}"

    echo ""
    read -rsp "  API Token Secret (hidden): " TOKEN_SECRET
    echo ""

    [[ -n "$TOKEN_SECRET" ]] || cb_fail "Token secret cannot be empty" \
      "Re-run and enter the secret when prompted"

    cb_ok "API credentials collected (secret not logged)"
  else
    CONFIGURE_API=false
    cb_ok "Skipping Proxmox API configuration"
  fi
}

# ── Phase 3: Create LXC ───────────────────────────────────────────────────────

phase3_create_lxc() {
  cb_section "Phase 3 — Create LXC Container"

  # Download Debian 12 template
  cb_step "Updating template list"
  pveam update >/dev/null 2>&1
  cb_ok "Template list updated"

  cb_step "Locating Debian 12 template"
  TEMPLATE=$(pveam available --section system 2>/dev/null \
    | awk '/debian-12/ {print $2}' | sort -V | tail -1)
  [[ -n "$TEMPLATE" ]] || cb_fail "No Debian 12 template found" \
    "Check 'pveam available --section system' manually"
  cb_ok "Template: $TEMPLATE"

  # Download if not already cached
  if ! pveam list local 2>/dev/null | grep -q "$TEMPLATE"; then
    cb_step "Downloading $TEMPLATE"
    pveam download local "$TEMPLATE"
    cb_ok "Template downloaded"
  else
    cb_ok "Template already cached"
  fi

  # Create container
  cb_step "Creating container $CTID"
  CLEANUP_ON_EXIT=true
  pct create "$CTID" "local:vztmpl/$TEMPLATE" \
    --hostname   "$CT_HOSTNAME" \
    --password   "$CT_PASSWORD" \
    --memory     "$CT_RAM" \
    --swap       "$CT_SWAP" \
    --cores      "$CT_CORES" \
    --rootfs     "${STORAGE}:${CT_DISK}" \
    --net0       "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
    --ostype     debian \
    --unprivileged 0 \
    --features   "nesting=1,keyctl=1" \
    --onboot     1
  cb_ok "Container $CTID created"

  cb_step "Starting container"
  pct start "$CTID"
  cb_ok "Container started"

  # Wait for DHCP IP (up to 30s)
  cb_step "Waiting for DHCP address"
  local deadline=$(( $(date +%s) + 30 ))
  while (( $(date +%s) < deadline )); do
    CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)
    [[ -n "$CT_IP" ]] && break
    sleep 2
  done
  [[ -n "$CT_IP" ]] || cb_fail "Container did not get a DHCP address within 30s" \
    "Check bridge $CT_BRIDGE and DHCP server"
  cb_ok "Container IP: $CT_IP"
}

# ── Phase 4: Install CB ───────────────────────────────────────────────────────

phase4_install_cb() {
  cb_section "Phase 4 — Install Circuit Breaker"

  cb_step "Running installer inside container $CTID"
  echo ""
  # Stream output live — pct exec inherits stdout
  pct exec "$CTID" -- bash -c \
    "curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --no-tls"
  echo ""
  cb_ok "Circuit Breaker installation complete"
}

# ── Phase 5: Auto-configure Proxmox integration ───────────────────────────────

phase5_configure_integration() {
  cb_section "Phase 5 — Post-install Configuration"

  # Poll health endpoint (up to 120s)
  cb_step "Waiting for Circuit Breaker API to become ready"
  local deadline=$(( $(date +%s) + 120 ))
  local ready=false
  while (( $(date +%s) < deadline )); do
    if curl -sf --max-time 5 "http://$CT_IP:$CB_PORT/api/v1/health" -o /dev/null 2>/dev/null; then
      ready=true
      break
    fi
    sleep 5
  done
  [[ "$ready" == "true" ]] || cb_fail "Circuit Breaker API did not respond within 120s" \
    "Check logs inside container: pct exec $CTID -- journalctl -u circuitbreaker -n 50"
  cb_ok "API is ready at http://$CT_IP:$CB_PORT"

  if [[ "$CONFIGURE_API" != "true" ]]; then
    cb_ok "Proxmox API configuration: skipped"
    return
  fi

  cb_step "Registering Proxmox integration"
  PVE_HOST_IP=$(hostname -I | awk '{print $1}')
  PVE_HOSTNAME=$(hostname)

  # TOKEN_SECRET is never logged — passed via shell var only
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    -X POST "http://$CT_IP:$CB_PORT/api/v1/integration_configs" \
    -H "Content-Type: application/json" \
    -d "{
      \"type\":\"proxmox\",
      \"name\":\"${PVE_HOSTNAME}\",
      \"host\":\"${PVE_HOST_IP}\",
      \"token_id\":\"${TOKEN_ID}\",
      \"token_secret\":\"${TOKEN_SECRET}\",
      \"verify_ssl\":false
    }")

  if [[ "$HTTP_STATUS" =~ ^2 ]]; then
    cb_ok "Proxmox integration registered (HTTP $HTTP_STATUS)"
  else
    cb_warn "Integration POST returned HTTP $HTTP_STATUS — verify manually in CB Settings → Integrations"
  fi

  # Clear secret from memory
  TOKEN_SECRET=""
}

# ── Phase 6: Success banner ───────────────────────────────────────────────────

phase6_success() {
  local api_status
  if [[ "$CONFIGURE_API" == "true" ]]; then
    api_status="configured ✓"
  else
    api_status="skipped"
  fi

  # Pad fields to fixed width for the banner
  local ctid_line
  local url_line
  local api_line
  printf -v ctid_line "%-36s" "  Container ID : $CTID"
  printf -v url_line  "%-36s" "  URL          : http://$CT_IP:$CB_PORT"
  printf -v api_line  "%-36s" "  Proxmox API  : $api_status"

  echo ""
  echo -e "${GREEN}${BOLD}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║   Circuit Breaker installed successfully!   ║"
  echo "  ╠══════════════════════════════════════════════╣"
  printf "  ║ %s║\n" "$ctid_line"
  printf "  ║ %s║\n" "$url_line"
  printf "  ║ %s║\n" "$api_line"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${RESET}"
  echo "  Open the URL to complete setup (OOBE wizard)."
  echo ""
  echo -e "  ${CYAN}Log file:${RESET} $LOG_FILE"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
  cb_header
  phase1_preflight
  phase2_api_token
  phase3_create_lxc
  phase4_install_cb
  CLEANUP_ON_EXIT=false  # Installation succeeded — don't destroy on any subsequent error
  phase5_configure_integration
  phase6_success
}

main "$@"
