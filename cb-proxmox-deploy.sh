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
BT="Circuit Breaker LXC Deploy"   # whiptail backtitle

# ── Colors ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# ── Verbosity ──────────────────────────────────────────────────────────────────
QUIET=false
VERBOSE=false

# ── CLI arg vars ───────────────────────────────────────────────────────────────
CTID_OVERRIDE=""
PRESET_OVERRIDE=""
CORES_OVERRIDE=""
MEM_OVERRIDE=""
DISK_OVERRIDE=""
RECREATE=false
SKIP_TUI=false
PASSWORD_OVERRIDE=""
HOSTNAME_OVERRIDE=""

# ── Preset table ───────────────────────────────────────────────────────────────
declare -A PRESETS
PRESETS[small]="1 2048 10"
PRESETS[med]="2 4096 20"
PRESETS[large]="4 8192 50"
DEFAULT_PRESET="med"

# ── Container defaults ─────────────────────────────────────────────────────────
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
if [[ -t 1 && -e /dev/tty ]]; then
  exec > >(tee >(sed -u 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE") >/dev/tty) 2>&1
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
  echo -e "\n  ${BOLD}$1${RESET}"
  [[ "$QUIET" != "true" ]] && echo "  $(printf '─%.0s' {1..46})"
}

tui_step() {
  [[ "$QUIET" == "true" ]] && return
  printf "  ${CYAN}▸${RESET} %s..." "$1"
}

tui_ok() {
  local msg="$1" detail="${2:-}"
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

# ── Error handler ──────────────────────────────────────────────────────────────

error_handler() {
  spinner_stop
  echo -e "\n  ${RED}✗  Unexpected error at line $1${RESET}"
  echo -e "  ${YELLOW}→  Command: $2${RESET}"
  echo -e "  ${YELLOW}→  Log: $LOG_FILE${RESET}"
  echo ""
}
trap 'error_handler ${LINENO} "$BASH_COMMAND"' ERR

# ── Cleanup trap ───────────────────────────────────────────────────────────────

cleanup() {
  spinner_stop
  if [[ "$CLEANUP_ON_EXIT" == "true" && -n "${CTID:-}" ]]; then
    CLEANUP_ON_EXIT=false  # prevent double-destroy
    echo ""
    tui_warn "Interrupted — destroying container $CTID..."
    pct stop "$CTID" --skiplock 2>/dev/null || true
    pct destroy "$CTID" --purge 2>/dev/null || true
    tui_ok "Container $CTID removed"
  fi
}

trap 'cleanup; exit 130' INT TERM
trap 'spinner_stop; cleanup' EXIT

# ── Arg parser ─────────────────────────────────────────────────────────────────

print_help() {
  cat <<EOF

  Usage: cb-proxmox-deploy.sh [OPTIONS]

  Options:
    --quiet             Show phase headers and final result only
    --verbose           Stream all pct exec output (no spinners)
    --ctid=N            Use specific container ID (skip auto-detect)
    --preset=NAME       Resource preset: small | med | large
    --cores=N           Override preset CPU cores
    --mem=N             Override preset RAM in MB
    --disk=N            Override preset disk in GB
    --recreate          Destroy existing container with same hostname first
    --skip-tui          Non-interactive mode (skip all whiptail dialogs)
    --password=PASS     Root password (required with --skip-tui)
    --hostname=NAME     Container hostname (default: circuitbreaker)
    --version           Print CB_VERSION and exit
    --help              Print this help and exit

  Presets:
    small   1 core  /  2 GB RAM /  10 GB disk
    med     2 cores /  4 GB RAM /  20 GB disk  (default)
    large   4 cores /  8 GB RAM /  50 GB disk

  Examples:
    cb-proxmox-deploy.sh
    cb-proxmox-deploy.sh --preset=large --verbose
    cb-proxmox-deploy.sh --skip-tui --password=s3cr3t --hostname=cb01
    cb-proxmox-deploy.sh --ctid=200 --recreate

EOF
}

parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --quiet)        QUIET=true ;;
      --verbose)      VERBOSE=true ;;
      --recreate)     RECREATE=true ;;
      --skip-tui)     SKIP_TUI=true ;;
      --ctid=*)       CTID_OVERRIDE="${arg#*=}" ;;
      --preset=*)     PRESET_OVERRIDE="${arg#*=}" ;;
      --cores=*)      CORES_OVERRIDE="${arg#*=}" ;;
      --mem=*)        MEM_OVERRIDE="${arg#*=}" ;;
      --disk=*)       DISK_OVERRIDE="${arg#*=}" ;;
      --password=*)   PASSWORD_OVERRIDE="${arg#*=}" ;;
      --hostname=*)   HOSTNAME_OVERRIDE="${arg#*=}" ;;
      --version)      echo "$CB_VERSION"; exit 0 ;;
      --help|-h)      print_help; exit 0 ;;
      *) echo "Unknown option: $arg"; print_help; exit 1 ;;
    esac
  done

  # Apply preset
  local preset="${PRESET_OVERRIDE:-$DEFAULT_PRESET}"
  preset="${preset,,}"
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

  # Hostname override
  [[ -n "$HOSTNAME_OVERRIDE" ]] && CT_HOSTNAME="$HOSTNAME_OVERRIDE"

  # --skip-tui validation
  if [[ "$SKIP_TUI" == "true" && -z "$PASSWORD_OVERRIDE" ]]; then
    echo "Error: --skip-tui requires --password=PASS"
    exit 1
  fi
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
  if pvesm status 2>/dev/null | awk 'NR>1 && $1=="local-lvm" && $3=="active" {found=1} END {exit !found}'; then
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

# ── Whiptail configuration dialogs ────────────────────────────────────────────

whiptail_config() {
  # ── Dialog 1: Settings menu ───────────────────────────────────────────────────
  local SETTINGS_CHOICE
  SETTINGS_CHOICE=$(whiptail \
    --backtitle "$BT" \
    --title "SETTINGS" \
    --ok-button "Next" --cancel-button "Exit" \
    --radiolist "\nChoose installation method:\n" 12 62 2 \
    "1" "Default Settings  (Medium: 2c / 4 GB / 20 GB)" ON \
    "2" "Advanced Settings (custom size and type)" OFF \
    3>&1 1>&2 2>&3) || { echo "  Aborted."; exit 0; }

  # ── Dialog 2: Advanced settings (resource preset) ────────────────────────────
  if [[ "$SETTINGS_CHOICE" == "2" && -z "$PRESET_OVERRIDE" ]]; then
    local PRESET_CHOICE
    PRESET_CHOICE=$(whiptail \
      --backtitle "$BT" \
      --title "RESOURCE PRESET" \
      --ok-button "Next" --cancel-button "Back" \
      --radiolist "\nSelect container size:\n" 15 62 4 \
      "small"  "Small   —  1c /  2 GB RAM /  10 GB disk" OFF \
      "med"    "Medium  —  2c /  4 GB RAM /  20 GB disk" ON \
      "large"  "Large   —  4c /  8 GB RAM /  50 GB disk" OFF \
      "manual" "Manual  —  enter custom values"           OFF \
      3>&1 1>&2 2>&3) || PRESET_CHOICE="med"   # Back → use default

    if [[ "${PRESET_CHOICE:-med}" == "manual" ]]; then
      local INPUT_CORES INPUT_RAM INPUT_DISK
      INPUT_CORES=$(whiptail --backtitle "$BT" --title "CPU CORES" \
        --inputbox "\nNumber of CPU cores:" 10 50 "$CT_CORES" \
        3>&1 1>&2 2>&3) || INPUT_CORES="$CT_CORES"
      INPUT_RAM=$(whiptail --backtitle "$BT" --title "RAM (MB)" \
        --inputbox "\nRAM in megabytes (e.g. 4096):" 10 50 "$CT_RAM" \
        3>&1 1>&2 2>&3) || INPUT_RAM="$CT_RAM"
      INPUT_DISK=$(whiptail --backtitle "$BT" --title "DISK (GB)" \
        --inputbox "\nDisk size in gigabytes (e.g. 20):" 10 50 "$CT_DISK" \
        3>&1 1>&2 2>&3) || INPUT_DISK="$CT_DISK"
      CT_CORES="${INPUT_CORES:-$CT_CORES}"
      CT_RAM="${INPUT_RAM:-$CT_RAM}"
      CT_DISK="${INPUT_DISK:-$CT_DISK}"
    elif [[ -n "${PRESETS[${PRESET_CHOICE:-med}]+x}" ]]; then
      read -r CT_CORES CT_RAM CT_DISK <<< "${PRESETS[${PRESET_CHOICE:-med}]}"
    fi
  fi

  # ── Dialog 3: Hostname ────────────────────────────────────────────────────────
  local INPUT_HOSTNAME
  INPUT_HOSTNAME=$(whiptail \
    --backtitle "$BT" \
    --title "HOSTNAME" \
    --ok-button "Next" --cancel-button "Exit" \
    --inputbox "\nEnter container hostname:\n" 10 62 "$CT_HOSTNAME" \
    3>&1 1>&2 2>&3) || { echo "  Aborted."; exit 0; }
  CT_HOSTNAME="${INPUT_HOSTNAME:-circuitbreaker}"

  # ── Dialog 4: Root password (with confirmation + retry loop) ─────────────────
  while true; do
    local INPUT_PW INPUT_PW2
    INPUT_PW=$(whiptail \
      --backtitle "$BT" \
      --title "ROOT PASSWORD" \
      --ok-button "Next" --cancel-button "Exit" \
      --passwordbox "\nEnter container root password:\n" 10 62 \
      3>&1 1>&2 2>&3) || { echo "  Aborted."; exit 0; }

    if [[ -z "$INPUT_PW" ]]; then
      whiptail --backtitle "$BT" --title "VALIDATION" \
        --msgbox "\nPassword cannot be empty. Please try again." 8 52
      continue
    fi

    INPUT_PW2=$(whiptail \
      --backtitle "$BT" \
      --title "CONFIRM PASSWORD" \
      --ok-button "Next" --cancel-button "Exit" \
      --passwordbox "\nConfirm root password:\n" 10 62 \
      3>&1 1>&2 2>&3) || { echo "  Aborted."; exit 0; }

    if [[ "$INPUT_PW" != "$INPUT_PW2" ]]; then
      whiptail --backtitle "$BT" --title "VALIDATION" \
        --msgbox "\nPasswords do not match. Please try again." 8 52
      continue
    fi

    CT_PASSWORD="$INPUT_PW"
    break
  done

  # ── Dialog 5: Proxmox API integration ─────────────────────────────────────────
  if whiptail \
    --backtitle "$BT" \
    --title "PROXMOX API" \
    --ok-button "Configure" --cancel-button "Skip" \
    --yesno "\nConfigure Proxmox auto-discovery now?\n\nThis connects Circuit Breaker to this PVE host.\nYou can also do this later in CB Settings → Integrations.\n" 14 62; then

    CONFIGURE_API=true

    local INPUT_TOKEN_ID
    INPUT_TOKEN_ID=$(whiptail \
      --backtitle "$BT" \
      --title "API TOKEN ID" \
      --ok-button "Next" --cancel-button "Skip API" \
      --inputbox "\nAPI Token ID  (format: user@realm!tokenname)\n" 11 62 \
      "circuitbreaker@pam!circuitbreaker" \
      3>&1 1>&2 2>&3) || { CONFIGURE_API=false; }

    if [[ "$CONFIGURE_API" == "true" ]]; then
      TOKEN_ID="${INPUT_TOKEN_ID:-circuitbreaker@pam!circuitbreaker}"

      while true; do
        TOKEN_SECRET=$(whiptail \
          --backtitle "$BT" \
          --title "API TOKEN SECRET" \
          --ok-button "Next" --cancel-button "Skip API" \
          --passwordbox "\nAPI Token Secret:\n" 10 62 \
          3>&1 1>&2 2>&3) || { CONFIGURE_API=false; TOKEN_SECRET=""; break; }

        if [[ -z "$TOKEN_SECRET" ]]; then
          whiptail --backtitle "$BT" --title "VALIDATION" \
            --msgbox "\nToken secret cannot be empty.\nPress 'Skip API' to skip integration setup." 9 58
          continue
        fi
        break
      done
    fi
  fi

  # ── Dialog 6: Confirmation ─────────────────────────────────────────────────────
  local API_DISPLAY
  [[ "$CONFIGURE_API" == "true" ]] && API_DISPLAY="configure" || API_DISPLAY="skip"

  whiptail \
    --backtitle "$BT" \
    --title "CONFIRM DEPLOYMENT" \
    --ok-button "Create Container" --cancel-button "Abort" \
    --yesno "
Deployment Summary
──────────────────────────────────────────
  Container ID : $CTID
  Hostname     : $CT_HOSTNAME
  Resources    : ${CT_CORES}c  /  ${CT_RAM} MB RAM  /  ${CT_DISK} GB disk
  Storage      : $STORAGE
  Bridge       : $CT_BRIDGE
  Proxmox API  : $API_DISPLAY
──────────────────────────────────────────
Proceed with container creation?" 20 62 || { echo "  Aborted."; exit 0; }
}

# ── Non-interactive config (--skip-tui) ────────────────────────────────────────

skiptui_config() {
  CT_PASSWORD="$PASSWORD_OVERRIDE"
  tui_ok "Mode"      "non-interactive (--skip-tui)"
  tui_ok "Hostname"  "$CT_HOSTNAME"
  tui_ok "Resources" "${CT_CORES}c / ${CT_RAM} MB / ${CT_DISK} GB"
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
        tui_ok "Circuit Breaker already running in CT $EXISTING_CT" "IP: $EXISTING_IP"
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
    pveam update; echo ""
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
      pveam download local "$TEMPLATE"; echo ""
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
  local pct_create_args=(
    pct create "$CTID" "local:vztmpl/$TEMPLATE"
    --hostname   "$CT_HOSTNAME"
    --password   "$CT_PASSWORD"
    --memory     "$CT_RAM"
    --swap       "$CT_SWAP"
    --cores      "$CT_CORES"
    --rootfs     "${STORAGE}:${CT_DISK}"
    --net0       "name=eth0,bridge=${CT_BRIDGE},ip=dhcp"
    --ostype     debian
    --unprivileged 0
    --features   "nesting=1,keyctl=1"
    --onboot     1
  )
  spinner_start "Creating container $CTID"
  if [[ "$VERBOSE" == "true" ]]; then
    spinner_stop; tui_step "Creating container $CTID"; echo ""
    "${pct_create_args[@]}"; echo ""
  else
    "${pct_create_args[@]}" >/dev/null 2>&1
    spinner_stop
  fi
  tui_ok "Container $CTID created"

  # Start container
  spinner_start "Starting container"
  pct start "$CTID" >/dev/null 2>&1
  spinner_stop
  tui_ok "Container started"
  sleep 3  # allow init to begin before first pct exec

  # Wait for DHCP IP (60s timeout) — filter to IPv4 only
  spinner_start "Waiting for DHCP address"
  local deadline=$(( $(date +%s) + 60 ))
  CT_IP=""
  while (( $(date +%s) < deadline )); do
    CT_IP=$(timeout 10 pct exec "$CTID" -- hostname -I 2>/dev/null \
      | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1 || true)
    [[ -n "$CT_IP" ]] && break
    sleep 2
  done
  spinner_stop
  [[ -n "$CT_IP" ]] || tui_fail "Container did not receive a DHCP address within 60s" \
    "Check bridge $CT_BRIDGE and DHCP server"
  tui_ok "Container IP" "$CT_IP"

  # Wait for systemd to be ready — accept both 'running' and 'degraded'
  spinner_start "Waiting for container init"
  local init_deadline=$(( $(date +%s) + 30 ))
  local sysstate=""
  while (( $(date +%s) < init_deadline )); do
    sysstate=$(timeout 10 pct exec "$CTID" -- systemctl is-system-running 2>/dev/null || true)
    [[ "$sysstate" == "running" || "$sysstate" == "degraded" ]] && break
    sleep 1
  done
  spinner_stop
  tui_ok "Container ready"

  tui_phase_done
}

# ── Phase 3: Install Circuit Breaker ──────────────────────────────────────────

PHASE3_RETRIED=false

phase3_install_cb() {
  tui_phase "Phase 3 — Circuit Breaker Installation"

  local ARCH; ARCH=$(uname -m)
  local DEB_ARCH="amd64"
  [[ "$ARCH" == "aarch64" ]] && DEB_ARCH="arm64"

  local install_block
  if [[ "$CB_VERSION" == "latest" ]]; then
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

  local full_script="export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y --no-install-recommends curl ca-certificates >/dev/null 2>&1
${install_block}"

  # Disable ERR trap during install — we handle failure explicitly
  trap - ERR

  local exit_code=0
  if [[ "$VERBOSE" == "true" ]]; then
    echo ""
    tui_step "Running installer inside container $CTID"; echo ""
    pct exec "$CTID" -- bash -c "$full_script" || exit_code=$?
    echo ""
  else
    spinner_start "Installing Circuit Breaker in container $CTID"
    pct exec "$CTID" -- bash -c "$full_script" >> "$LOG_FILE" 2>&1 || exit_code=$?
    spinner_stop
  fi

  # Re-enable ERR trap
  trap 'error_handler ${LINENO} "$BASH_COMMAND"' ERR

  if [[ $exit_code -ne 0 ]]; then
    echo ""
    tui_warn "Installation inside container failed (exit code: $exit_code)"
    tui_warn "Log: $LOG_FILE"

    local RECOVERY
    RECOVERY=$(whiptail \
      --backtitle "$BT" \
      --title "INSTALLATION FAILED" \
      --ok-button "Select" --cancel-button "Remove & Exit" \
      --menu "\nInstallation failed (exit code: $exit_code)\nLog: $LOG_FILE\n" 14 64 3 \
      "1" "Remove container and exit" \
      "2" "Keep container for debugging" \
      "3" "Retry with verbose output" \
      3>&1 1>&2 2>&3) || RECOVERY="1"

    case "$RECOVERY" in
      1) pct stop "$CTID" --skiplock 2>/dev/null || true
         pct destroy "$CTID" --purge 2>/dev/null || true
         CLEANUP_ON_EXIT=false
         echo "  Container removed."; exit 1 ;;
      2) CLEANUP_ON_EXIT=false
         tui_fail "Container $CTID kept for debugging" \
           "pct exec $CTID -- journalctl -u circuitbreaker -n 50" ;;
      3) if [[ "$PHASE3_RETRIED" == "true" ]]; then
           tui_fail "Retry also failed (exit code: $exit_code)" \
             "Check log: $LOG_FILE"
         fi
         PHASE3_RETRIED=true; VERBOSE=true; phase3_install_cb; return ;;
    esac
  fi

  tui_ok "Circuit Breaker installed"
  CLEANUP_ON_EXIT=false  # Success — don't destroy on subsequent errors
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
      ready=true; break
    fi
    sleep 5
  done
  spinner_stop
  [[ "$ready" == "true" ]] || tui_fail "Circuit Breaker API did not respond within 120s" \
    "Check logs: pct exec $CTID -- journalctl -u circuitbreaker -n 50"
  tui_ok "API ready" "http://$CT_IP:$CB_PORT"

  # Push Proxmox integration config (best-effort, pre-OOBE open endpoint)
  if [[ "$CONFIGURE_API" == "true" ]]; then
    spinner_start "Registering Proxmox integration"
    local PVE_HOST_IP; PVE_HOST_IP=$(hostname -I | awk '{print $1}')
    local PVE_HOSTNAME; PVE_HOSTNAME=$(hostname)
    local HTTP_STATUS json_payload
    # Build JSON safely via python3 to handle special chars in hostname/token values
    json_payload=$(python3 -c "
import json, sys
print(json.dumps({
  'type': 'proxmox',
  'name': sys.argv[1],
  'host': sys.argv[2],
  'token_id': sys.argv[3],
  'token_secret': sys.argv[4],
  'verify_ssl': False
}))" "$PVE_HOSTNAME" "$PVE_HOST_IP" "$TOKEN_ID" "$TOKEN_SECRET" 2>/dev/null) || json_payload=""
    TOKEN_SECRET=""  # clear from memory immediately after use
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      --max-time 10 \
      -X POST "http://$CT_IP:$CB_PORT/api/v1/integration_configs" \
      -H "Content-Type: application/json" \
      -d "$json_payload" \
      2>/dev/null || echo "000")
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
  [[ "$CONFIGURE_API" == "true" ]] && api_status="configured ✓" || api_status="skipped"

  local ctid_line url_line api_line
  printf -v ctid_line "%-46s" "  Container ID : $CTID"
  printf -v url_line  "%-46s" "  URL          : http://$CT_IP:$CB_PORT"
  printf -v api_line  "%-46s" "  Proxmox API  : $api_status"

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
  if [[ "$SKIP_TUI" == "true" ]]; then
    skiptui_config
  else
    whiptail_config
  fi
  phase2_create_lxc
  phase3_install_cb
  phase4_health_check
  phase5_success
}

main "$@"
