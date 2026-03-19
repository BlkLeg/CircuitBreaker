#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker — Proxmox LXC Deploy Script
# Runs on the Proxmox VE host. Creates a Debian 12 LXC container and
# installs Circuit Breaker natively inside it.

CB_VERSION="latest"
CB_INSTALL_URL="https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh"
CB_GITHUB_REPO="BlkLeg/CircuitBreaker"
CB_PORT=8088
LOG_FILE="/tmp/cb-proxmox.log"

# ── Colors ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Verbosity flags ────────────────────────────────────────────────────────────
QUIET=false
VERBOSE=false

# ── CLI arg vars ───────────────────────────────────────────────────────────────
CTID_OVERRIDE=""
PRESET_OVERRIDE=""
CORES_OVERRIDE=""
MEM_OVERRIDE=""
DISK_OVERRIDE=""
RECREATE=false

# ── Preset table ───────────────────────────────────────────────────────────────
declare -A PRESETS
PRESETS[small]="1 2048 10"
PRESETS[med]="2 4096 20"
PRESETS[large]="4 8192 50"
DEFAULT_PRESET="med"

# ── Container defaults (overridden by parse_args) ──────────────────────────────
CT_CORES=2
CT_RAM=4096
CT_SWAP=512
CT_DISK=20
CT_BRIDGE=vmbr0

# ── Runtime state ──────────────────────────────────────────────────────────────
CTID=""
STORAGE=""
CT_HOSTNAME="circuitbreaker"
CT_PASSWORD=""
TOKEN_ID=""
TOKEN_SECRET=""
CONFIGURE_API=false
CT_IP=""
CLEANUP_ON_EXIT=false
SPINNER_PID=""

# ── Logging: strip ANSI → tee to log file + /dev/tty ──────────────────────────
# Only redirect when running interactively (always true on a PVE host)
if [[ -t 1 && -e /dev/tty ]]; then
  exec > >(sed -u 's/\x1b\[[0-9;]*m//g' | tee -a "$LOG_FILE" >/dev/tty) 2>&1
fi

# ── TUI Helpers ────────────────────────────────────────────────────────────────

tui_banner() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║    Circuit Breaker — Proxmox LXC Deploy     ║"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${RESET}"
}

tui_phase() {
  local title="$1"
  echo -e "\n  ${BOLD}${title}${RESET}"
  [[ "$QUIET" != "true" ]] && echo "  $(printf '─%.0s' {1..46})"
}

tui_step() {
  [[ "$QUIET" == "true" ]] && return
  printf "  ${CYAN}▸${RESET} %s..." "$1"
}

tui_ok() {
  local msg="$1"
  local detail="${2:-}"
  [[ "$QUIET" == "true" ]] && return
  if [[ -n "$detail" ]]; then
    printf "\r  ${GREEN}✓${RESET} %-38s ${DIM}%s${RESET}\n" "$msg" "$detail"
  else
    printf "\r  ${GREEN}✓${RESET} %s\n" "$msg"
  fi
}

tui_fail() {
  spinner_stop
  echo -e "\n  ${RED}✗  ERROR: $1${RESET}"
  [[ -n "${2:-}" ]] && echo -e "  ${YELLOW}→  $2${RESET}"
  echo ""
  exit 1
}

tui_warn() {
  echo -e "  ${YELLOW}⚠${RESET}  $1"
}

tui_phase_done() {
  [[ "$QUIET" == "true" ]] && return
  echo "  $(printf '─%.0s' {1..40}) ${GREEN}[✓ COMPLETE]${RESET}"
}

# ── Spinner ────────────────────────────────────────────────────────────────────

spinner_start() {
  [[ "$QUIET" == "true" || "$VERBOSE" == "true" ]] && return
  local msg="$1"
  (
    local frames=('▸' '▹' '◃')
    local i=0
    while true; do
      printf "\r  ${CYAN}%s${RESET} %s..." "${frames[$((i % 3))]}" "$msg"
      (( i++ ))
      sleep 0.15
    done
  ) &
  SPINNER_PID=$!
  disown "$SPINNER_PID" 2>/dev/null || true
}

spinner_stop() {
  if [[ -n "${SPINNER_PID:-}" ]]; then
    kill "$SPINNER_PID" 2>/dev/null || true
    wait "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=""
    printf "\r\033[K"
  fi
}

# ── Cleanup trap ───────────────────────────────────────────────────────────────

cleanup() {
  spinner_stop
  if [[ "$CLEANUP_ON_EXIT" == "true" && -n "${CTID:-}" ]]; then
    echo ""
    tui_warn "Interrupted — destroying container $CTID..."
    pct stop "$CTID" --skiplock 2>/dev/null || true
    pct destroy "$CTID" --purge 2>/dev/null || true
    tui_ok "Container $CTID removed"
  fi
}

trap 'cleanup; exit 130' INT TERM
trap 'spinner_stop' EXIT

# ── Arg parser ─────────────────────────────────────────────────────────────────

print_help() {
  cat <<EOF

  Usage: cb-proxmox-deploy.sh [OPTIONS]

  Options:
    --quiet           Show phase headers and final result only
    --verbose         Stream all pct exec output directly (no spinners)
    --ctid=N          Use specific container ID (skip auto-detect)
    --preset=NAME     Resource preset: small | med | large
    --cores=N         Override preset CPU cores
    --mem=N           Override preset RAM in MB
    --disk=N          Override preset disk in GB
    --recreate        Destroy existing container with same hostname first
    --version         Print CB_VERSION and exit
    --help            Print this help and exit

  Presets:
    small   1 core  /  2 GB RAM /  10 GB disk
    med     2 cores /  4 GB RAM /  20 GB disk  (default)
    large   4 cores /  8 GB RAM /  50 GB disk

  Examples:
    cb-proxmox-deploy.sh --preset=small
    cb-proxmox-deploy.sh --preset=large --verbose
    cb-proxmox-deploy.sh --ctid=200 --recreate

EOF
}

parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --quiet)      QUIET=true ;;
      --verbose)    VERBOSE=true ;;
      --recreate)   RECREATE=true ;;
      --ctid=*)     CTID_OVERRIDE="${arg#*=}" ;;
      --preset=*)   PRESET_OVERRIDE="${arg#*=}" ;;
      --cores=*)    CORES_OVERRIDE="${arg#*=}" ;;
      --mem=*)      MEM_OVERRIDE="${arg#*=}" ;;
      --disk=*)     DISK_OVERRIDE="${arg#*=}" ;;
      --version)    echo "$CB_VERSION"; exit 0 ;;
      --help|-h)    print_help; exit 0 ;;
      *) echo "Unknown option: $arg"; print_help; exit 1 ;;
    esac
  done

  # Apply preset (user choice or default)
  local preset="${PRESET_OVERRIDE:-$DEFAULT_PRESET}"
  preset="${preset,,}"  # lowercase
  if [[ -n "${PRESETS[$preset]+x}" ]]; then
    read -r CT_CORES CT_RAM CT_DISK <<< "${PRESETS[$preset]}"
  else
    echo "Unknown preset: '$preset' (valid: small, med, large)"
    exit 1
  fi

  # Per-resource overrides
  [[ -n "$CORES_OVERRIDE" ]] && CT_CORES="$CORES_OVERRIDE"
  [[ -n "$MEM_OVERRIDE"   ]] && CT_RAM="$MEM_OVERRIDE"
  [[ -n "$DISK_OVERRIDE"  ]] && CT_DISK="$DISK_OVERRIDE"
}

# ── Phase 1: Preflight ─────────────────────────────────────────────────────────

phase1_preflight() {
  tui_phase "Phase 1 — Preflight Checks"

  spinner_start "Verifying Proxmox VE host"
  if ! command -v pveversion &>/dev/null; then
    spinner_stop
    tui_fail "This script must run on a Proxmox VE host" \
      "pveversion not found — are you on PVE?"
  fi
  PVE_VER=$(pveversion 2>/dev/null | grep -oP 'pve-manager/\K[0-9]+\.[0-9]+' || echo "unknown")
  spinner_stop
  tui_ok "Proxmox VE detected" "v${PVE_VER}"

  spinner_start "Checking internet connectivity"
  if ! curl -sf --max-time 10 https://github.com -o /dev/null; then
    spinner_stop
    tui_fail "No internet access" \
      "curl to github.com failed — check DNS and routing"
  fi
  spinner_stop
  tui_ok "Internet reachable"

  if [[ -n "$CTID_OVERRIDE" ]]; then
    CTID="$CTID_OVERRIDE"
    tui_ok "Container ID" "$CTID (manual)"
  else
    spinner_start "Selecting next available CTID"
    CTID=$(pvesh get /cluster/nextid 2>/dev/null | tr -d '[:space:]')
    spinner_stop
    [[ "$CTID" =~ ^[0-9]+$ ]] || tui_fail "Could not determine next CTID from pvesh"
    tui_ok "Container ID" "$CTID (auto)"
  fi

  spinner_start "Detecting storage pool"
  if pvesm status 2>/dev/null | awk 'NR>1 && $1=="local-lvm" && $2=="lvm-thin" {found=1} END {exit !found}'; then
    STORAGE="local-lvm"
  elif pvesm status 2>/dev/null | awk 'NR>1 && $1=="local" {found=1} END {exit !found}'; then
    STORAGE="local"
  else
    STORAGE=$(pvesm status 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')
    [[ -n "$STORAGE" ]] || { spinner_stop; tui_fail "No active storage pool found" "Check 'pvesm status'"; }
  fi
  spinner_stop
  tui_ok "Storage pool" "$STORAGE"

  spinner_start "Checking network bridge"
  if ! ip link show "$CT_BRIDGE" &>/dev/null; then
    spinner_stop
    tui_fail "Bridge $CT_BRIDGE not found" \
      "Check 'ip link show' for available bridges"
  fi
  spinner_stop
  tui_ok "Network bridge" "$CT_BRIDGE"

  tui_phase_done
}

# ── Interactive configuration ──────────────────────────────────────────────────

interactive_config() {
  echo ""
  echo -e "  ${BOLD}Configuration${RESET}"
  echo "  $(printf '─%.0s' {1..46})"

  # Preset prompt (skip if --preset was provided via CLI)
  if [[ -z "$PRESET_OVERRIDE" ]]; then
    echo ""
    echo -e "  ${CYAN}Resource preset?${RESET}"
    echo -e "    ${DIM}small  — 1 core  /  2 GB RAM /  10 GB disk${RESET}"
    echo -e "    ${DIM}med    — 2 cores /  4 GB RAM /  20 GB disk  [default]${RESET}"
    echo -e "    ${DIM}large  — 4 cores /  8 GB RAM /  50 GB disk${RESET}"
    echo -e "    ${DIM}M      — enter manually${RESET}"
    read -rp "  Choice [Med]: " INPUT_PRESET
    INPUT_PRESET="${INPUT_PRESET:-med}"
    INPUT_PRESET="${INPUT_PRESET,,}"

    if [[ "$INPUT_PRESET" == "m" ]]; then
      read -rp "  Cores [${CT_CORES}]:   " INPUT_CORES;  CT_CORES="${INPUT_CORES:-$CT_CORES}"
      read -rp "  RAM MB [${CT_RAM}]: "   INPUT_RAM;    CT_RAM="${INPUT_RAM:-$CT_RAM}"
      read -rp "  Disk GB [${CT_DISK}]: " INPUT_DISK;   CT_DISK="${INPUT_DISK:-$CT_DISK}"
    elif [[ -n "${PRESETS[$INPUT_PRESET]+x}" ]]; then
      read -r CT_CORES CT_RAM CT_DISK <<< "${PRESETS[$INPUT_PRESET]}"
    else
      tui_warn "Unknown preset '$INPUT_PRESET' — using med defaults"
      read -r CT_CORES CT_RAM CT_DISK <<< "${PRESETS[med]}"
    fi
  fi

  echo ""
  read -rp "  Hostname? [circuitbreaker]: " INPUT_HOSTNAME
  CT_HOSTNAME="${INPUT_HOSTNAME:-circuitbreaker}"

  echo ""
  read -rsp "  Container root password: " CT_PASSWORD; echo ""
  [[ -n "$CT_PASSWORD" ]] || tui_fail "Container password cannot be empty" \
    "Re-run and enter a password"

  echo ""
  read -rp "  Configure Proxmox auto-discovery? [Y/n]: " CONFIGURE_INPUT
  CONFIGURE_INPUT="${CONFIGURE_INPUT:-Y}"
  if [[ "${CONFIGURE_INPUT}" =~ ^[Yy]$ ]]; then
    CONFIGURE_API=true
    echo ""
    read -rp "    Token ID? [circuitbreaker@pam!circuitbreaker]: " INPUT_TOKEN_ID
    TOKEN_ID="${INPUT_TOKEN_ID:-circuitbreaker@pam!circuitbreaker}"
    echo ""
    read -rsp "    Token Secret? (hidden): " TOKEN_SECRET; echo ""
    [[ -n "$TOKEN_SECRET" ]] || tui_fail "Token secret cannot be empty" \
      "Re-run and enter the secret when prompted"
    tui_ok "API credentials collected (secret not logged)"
  else
    CONFIGURE_API=false
    tui_ok "Skipping Proxmox API configuration"
  fi

  echo ""
  echo -e "  ${BOLD}Deployment summary${RESET}"
  echo "  $(printf '─%.0s' {1..46})"
  printf "    %-16s %s\n" "Container ID :" "$CTID"
  printf "    %-16s %s\n" "Hostname :"     "$CT_HOSTNAME"
  printf "    %-16s %s\n" "Resources :"    "${CT_CORES} cores / ${CT_RAM} MB RAM / ${CT_DISK} GB disk"
  printf "    %-16s %s\n" "Storage :"      "$STORAGE"
  printf "    %-16s %s\n" "Bridge :"       "$CT_BRIDGE"
  printf "    %-16s %s\n" "Proxmox API :"  "$([ "$CONFIGURE_API" == "true" ] && echo "configure ✓" || echo "skip")"
  echo ""
  read -rp "  Proceed? [Y/n]: " PROCEED
  [[ "${PROCEED:-Y}" =~ ^[Nn]$ ]] && { echo "  Aborted."; exit 0; }
}

# ── Phase 2: LXC Creation ──────────────────────────────────────────────────────

phase2_create_lxc() {
  tui_phase "Phase 2 — LXC Container Creation"

  # Idempotency check
  local EXISTING_CT
  EXISTING_CT=$(pct list 2>/dev/null | awk -v h="$CT_HOSTNAME" 'NR>1 && $3==h {print $1}' | head -1 || true)
  if [[ -n "$EXISTING_CT" ]]; then
    if [[ "$RECREATE" == "true" ]]; then
      spinner_start "Destroying existing container $EXISTING_CT"
      pct stop "$EXISTING_CT" --skiplock 2>/dev/null || true
      pct destroy "$EXISTING_CT" --purge 2>/dev/null || true
      spinner_stop
      tui_ok "Container $EXISTING_CT destroyed"
    else
      local EXISTING_IP
      EXISTING_IP=$(pct exec "$EXISTING_CT" -- hostname -I 2>/dev/null | awk '{print $1}' || true)
      if [[ -n "$EXISTING_IP" ]] && curl -sf --max-time 5 "http://$EXISTING_IP:$CB_PORT/api/v1/health" -o /dev/null 2>/dev/null; then
        echo ""
        tui_ok "Circuit Breaker already running in container $EXISTING_CT" "IP: $EXISTING_IP"
        tui_warn "To upgrade:  pct exec $EXISTING_CT -- bash -c \"curl -fsSL $CB_INSTALL_URL | bash -s -- --unattended --upgrade\""
        tui_warn "To redeploy: re-run with --recreate"
        exit 0
      fi
      tui_warn "Container $EXISTING_CT exists but CB is not healthy — using new CTID $CTID"
    fi
  fi

  # Update template list
  spinner_start "Updating template list"
  if [[ "$VERBOSE" == "true" ]]; then
    spinner_stop; tui_step "Updating template list"; echo ""
    pveam update
    echo ""
  else
    pveam update >/dev/null 2>&1
    spinner_stop
  fi
  tui_ok "Template list updated"

  # Locate Debian 12 template
  spinner_start "Locating Debian 12 template"
  local TEMPLATE
  TEMPLATE=$(pveam available --section system 2>/dev/null \
    | awk '/debian-12/ {print $2}' | sort -V | tail -1)
  spinner_stop
  [[ -n "$TEMPLATE" ]] || tui_fail "No Debian 12 template found" \
    "Check 'pveam available --section system' manually"
  tui_ok "Template" "$TEMPLATE"

  # Download template if not cached
  if ! pveam list local 2>/dev/null | grep -q "$TEMPLATE"; then
    spinner_start "Downloading $TEMPLATE"
    if [[ "$VERBOSE" == "true" ]]; then
      spinner_stop; tui_step "Downloading $TEMPLATE"; echo ""
      pveam download local "$TEMPLATE"
      echo ""
    else
      pveam download local "$TEMPLATE" >/dev/null 2>&1
      spinner_stop
    fi
    tui_ok "Template downloaded"
  else
    tui_ok "Template cached"
  fi

  # Create container
  CLEANUP_ON_EXIT=true
  spinner_start "Creating container $CTID"
  if [[ "$VERBOSE" == "true" ]]; then
    spinner_stop; tui_step "Creating container $CTID"; echo ""
    pct create "$CTID" "local:vztmpl/$TEMPLATE" \
      --hostname   "$CT_HOSTNAME"  \
      --password   "$CT_PASSWORD"  \
      --memory     "$CT_RAM"       \
      --swap       "$CT_SWAP"      \
      --cores      "$CT_CORES"     \
      --rootfs     "${STORAGE}:${CT_DISK}" \
      --net0       "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
      --ostype     debian          \
      --unprivileged 0             \
      --features   "nesting=1,keyctl=1" \
      --onboot     1
    echo ""
  else
    pct create "$CTID" "local:vztmpl/$TEMPLATE" \
      --hostname   "$CT_HOSTNAME"  \
      --password   "$CT_PASSWORD"  \
      --memory     "$CT_RAM"       \
      --swap       "$CT_SWAP"      \
      --cores      "$CT_CORES"     \
      --rootfs     "${STORAGE}:${CT_DISK}" \
      --net0       "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
      --ostype     debian          \
      --unprivileged 0             \
      --features   "nesting=1,keyctl=1" \
      --onboot     1 >/dev/null 2>&1
    spinner_stop
  fi
  tui_ok "Container $CTID created"

  # Start container
  spinner_start "Starting container"
  pct start "$CTID" >/dev/null 2>&1
  spinner_stop
  tui_ok "Container started"

  # Wait for DHCP IP (60s timeout)
  spinner_start "Waiting for DHCP address"
  local deadline=$(( $(date +%s) + 60 ))
  while (( $(date +%s) < deadline )); do
    CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)
    [[ -n "$CT_IP" ]] && break
    sleep 2
  done
  spinner_stop
  [[ -n "$CT_IP" ]] || tui_fail "Container did not receive a DHCP address within 60s" \
    "Check bridge $CT_BRIDGE and DHCP server"
  tui_ok "Container IP" "$CT_IP"

  tui_phase_done
}

# ── Phase 3: Install Circuit Breaker ──────────────────────────────────────────

phase3_install_cb() {
  tui_phase "Phase 3 — Circuit Breaker Installation"

  # Determine DEB arch from host (container arch matches host)
  local ARCH; ARCH=$(uname -m)
  local DEB_ARCH="amd64"
  [[ "$ARCH" == "aarch64" ]] && DEB_ARCH="arm64"

  local install_block
  if [[ "$CB_VERSION" == "latest" ]]; then
    # No valid DEB URL for "latest" — go straight to install.sh
    tui_ok "Install method" "curl | install.sh (CB_VERSION=latest)"
    install_block="curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --no-tls"
  else
    local DEB_URL="https://github.com/${CB_GITHUB_REPO}/releases/download/v${CB_VERSION}/circuit-breaker_${CB_VERSION}_${DEB_ARCH}.deb"
    tui_ok "Install method" "DEB with curl fallback (v${CB_VERSION} ${DEB_ARCH})"
    install_block="
if curl -fsSL --head '${DEB_URL}' -o /dev/null 2>/dev/null; then
  echo '[cb-deploy] Downloading DEB package...'
  curl -fsSL '${DEB_URL}' -o /tmp/cb.deb
  dpkg -i /tmp/cb.deb || apt-get -f install -y
  systemctl enable --now circuitbreaker
else
  echo '[cb-deploy] DEB not found — falling back to install.sh'
  curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --no-tls
fi"
  fi

  local full_script="
apt-get update -qq
apt-get install -y --no-install-recommends curl >/dev/null 2>&1
${install_block}
"

  if [[ "$VERBOSE" == "true" ]]; then
    echo ""
    tui_step "Running installer inside container $CTID"
    echo ""
    pct exec "$CTID" -- bash -c "$full_script"
    echo ""
  else
    spinner_start "Installing Circuit Breaker in container $CTID"
    pct exec "$CTID" -- bash -c "
apt-get update -qq >/dev/null 2>&1
apt-get install -y --no-install-recommends curl >/dev/null 2>&1
${install_block}
" 2>&1 | tee -a "$LOG_FILE" >/dev/null
    spinner_stop
  fi
  tui_ok "Circuit Breaker installed"

  # Installation succeeded — disable container cleanup on subsequent errors
  CLEANUP_ON_EXIT=false

  tui_phase_done
}

# ── Phase 4: Health Check ──────────────────────────────────────────────────────

phase4_health_check() {
  tui_phase "Phase 4 — Health Check"

  spinner_start "Waiting for Circuit Breaker API"
  local deadline=$(( $(date +%s) + 120 ))
  local ready=false
  while (( $(date +%s) < deadline )); do
    if curl -sf --max-time 5 "http://$CT_IP:$CB_PORT/api/v1/health" -o /dev/null 2>/dev/null; then
      ready=true
      break
    fi
    sleep 5
  done
  spinner_stop
  [[ "$ready" == "true" ]] || tui_fail "Circuit Breaker API did not respond within 120s" \
    "Check logs: pct exec $CTID -- journalctl -u circuitbreaker -n 50"
  tui_ok "API ready" "http://$CT_IP:$CB_PORT"

  # Push Proxmox integration (best-effort, pre-OOBE open endpoint)
  if [[ "$CONFIGURE_API" == "true" ]]; then
    spinner_start "Registering Proxmox integration"
    local PVE_HOST_IP; PVE_HOST_IP=$(hostname -I | awk '{print $1}')
    local PVE_HOSTNAME; PVE_HOSTNAME=$(hostname)
    local HTTP_STATUS
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
      }" 2>/dev/null || echo "000")
    TOKEN_SECRET=""  # clear from memory
    spinner_stop
    if [[ "$HTTP_STATUS" =~ ^2 ]]; then
      tui_ok "Proxmox integration registered" "HTTP $HTTP_STATUS"
    else
      tui_warn "Integration POST returned HTTP $HTTP_STATUS — configure manually in CB Settings → Integrations"
    fi
  fi

  tui_phase_done
}

# ── Phase 5: Success Banner ────────────────────────────────────────────────────

phase5_success() {
  local api_status
  if [[ "$CONFIGURE_API" == "true" ]]; then
    api_status="configured ✓"
  else
    api_status="skipped"
  fi

  # Pad each data row to exactly 44 chars (2 indent + 44 = 46 inner box width)
  local ctid_line url_line api_line
  printf -v ctid_line "%-44s" "  Container ID : $CTID"
  printf -v url_line  "%-44s" "  URL          : http://$CT_IP:$CB_PORT"
  printf -v api_line  "%-44s" "  Proxmox API  : $api_status"

  echo ""
  echo -e "${GREEN}${BOLD}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║   Circuit Breaker installed successfully!    ║"
  echo "  ╠══════════════════════════════════════════════╣"
  printf "  ║%s║\n" "$ctid_line"
  printf "  ║%s║\n" "$url_line"
  printf "  ║%s║\n" "$api_line"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${RESET}"
  echo "  Open the URL to complete setup (OOBE wizard)."
  echo ""
  echo -e "  ${CYAN}Log file:${RESET} $LOG_FILE"
  echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────────

main() {
  parse_args "$@"
  tui_banner
  phase1_preflight
  interactive_config
  phase2_create_lxc
  phase3_install_cb
  phase4_health_check
  phase5_success
}

main "$@"
