#!/usr/bin/env bash
# Circuit Breaker — Proxmox LXC Helper
# Full whiptail TUI for creating, managing, and removing CB containers.
# Usage: bash -c "$(curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/cb-proxmox-deploy.sh)"

# ── Colors (tput) ─────────────────────────────────────────────────────────────
red=$(tput setaf 1 2>/dev/null)
green=$(tput setaf 2 2>/dev/null)
yellow=$(tput setaf 3 2>/dev/null)
blue=$(tput setaf 4 2>/dev/null)
bold=$(tput bold 2>/dev/null)
nc=$(tput sgr0 2>/dev/null)

# ── Constants ─────────────────────────────────────────────────────────────────
BT="Circuit Breaker — Proxmox Helper"
LOG_FILE="/tmp/cb-proxmox.log"
CB_INSTALL_URL="https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh"
CB_PORT=8088

# ── Runtime state ─────────────────────────────────────────────────────────────
CTID=""
HN="circuitbreaker"
PW=""
CORES=2
RAM=4096
DISK=20
SWAP=512
STORAGE=""
BRIDGE="vmbr0"
TEMPLATE=""
CT_IP=""
CLEANUP_CTID=""

# ── Logging ───────────────────────────────────────────────────────────────────
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Cleanup trap ──────────────────────────────────────────────────────────────
cleanup() {
  if [[ -n "$CLEANUP_CTID" ]]; then
    echo -e "\n${yellow}Interrupted — destroying container $CLEANUP_CTID...${nc}"
    pct stop "$CLEANUP_CTID" --skiplock 2>/dev/null
    pct destroy "$CLEANUP_CTID" --purge 2>/dev/null
    echo -e "${green}Container $CLEANUP_CTID removed.${nc}"
    CLEANUP_CTID=""
  fi
}
trap 'cleanup; exit 130' INT TERM

# ── Helpers ───────────────────────────────────────────────────────────────────
msg_ok()   { echo -e "  ${green}✓${nc}  $1"; }
msg_info() { echo -e "  ${blue}▸${nc}  $1"; }
msg_warn() { echo -e "  ${yellow}⚠${nc}  $1"; }
msg_err()  { echo -e "  ${red}✗${nc}  $1"; }

die() {
  whiptail --backtitle "$BT" --title "Error" --msgbox "$1" 10 60
  return 1
}

# ── Preflight ─────────────────────────────────────────────────────────────────
preflight() {
  if ! command -v pveversion &>/dev/null; then
    echo -e "${red}This script must run on a Proxmox VE host.${nc}"
    exit 1
  fi

  if ! command -v whiptail &>/dev/null; then
    echo -e "${yellow}Installing whiptail...${nc}"
    apt-get update -qq && apt-get install -y whiptail >/dev/null 2>&1
  fi

  if ! curl -sf --max-time 10 https://github.com -o /dev/null 2>/dev/null; then
    echo -e "${red}No internet — curl to github.com failed.${nc}"
    exit 1
  fi
}

# ── Detect infrastructure ────────────────────────────────────────────────────
detect_storage() {
  # Only list storages that support container rootfs
  local candidates
  candidates=$(pvesm status --content rootdir 2>/dev/null \
    | awk 'NR>1 && $3=="active" {print $1}')

  if [[ -z "$candidates" ]]; then
    # Fallback: any active storage
    candidates=$(pvesm status 2>/dev/null \
      | awk 'NR>1 && $3=="active" {print $1}')
  fi

  # Prefer local-lvm, then local-zfs, then first available
  if echo "$candidates" | grep -qx "local-lvm"; then
    STORAGE="local-lvm"
  elif echo "$candidates" | grep -qx "local-zfs"; then
    STORAGE="local-zfs"
  else
    STORAGE=$(echo "$candidates" | head -1)
  fi

  [[ -n "$STORAGE" ]] || { echo -e "${red}No active storage found.${nc}"; exit 1; }
}

detect_next_ctid() {
  CTID=$(pvesh get /cluster/nextid 2>/dev/null | tr -d '[:space:]')
  [[ "$CTID" =~ ^[0-9]+$ ]] || CTID=""
}

detect_template() {
  TEMPLATE=$(pveam available --section system 2>/dev/null \
    | awk '/debian-12/ {print $2}' | sort -V | tail -1)
}

detect_bridges() {
  # Return list of bridges for whiptail
  ip -br link show type bridge 2>/dev/null | awk '{print $1}' || echo "vmbr0"
}

# ── Wait for DHCP IP ─────────────────────────────────────────────────────────
wait_for_ip() {
  local ctid="$1" timeout=60
  local deadline=$(( $(date +%s) + timeout ))
  CT_IP=""
  while (( $(date +%s) < deadline )); do
    CT_IP=$(pct exec "$ctid" -- hostname -I 2>/dev/null \
      | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -1)
    [[ -n "$CT_IP" ]] && return 0
    sleep 2
  done
  return 1
}

# ── Wait for health endpoint ─────────────────────────────────────────────────
wait_for_health() {
  local ip="$1" timeout=120
  local deadline=$(( $(date +%s) + timeout ))
  while (( $(date +%s) < deadline )); do
    if curl -sf --max-time 5 "http://$ip:$CB_PORT/api/v1/health" -o /dev/null 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  return 1
}

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL FLOWS
# ══════════════════════════════════════════════════════════════════════════════

func_preset() {
  # ── Size radiolist ──────────────────────────────────────────────────────────
  local size
  size=$(whiptail --backtitle "$BT" --title "Container Size" \
    --radiolist "Choose a resource preset:" 15 55 4 \
    "small"  "1 core  /  2 GB RAM / 10 GB disk" OFF \
    "medium" "2 cores /  4 GB RAM / 20 GB disk" ON \
    "large"  "4 cores /  8 GB RAM / 50 GB disk" OFF \
    "custom" "Enter values manually" OFF \
    3>&1 1>&2 2>&3) || return

  case "$size" in
    small)  CORES=1; RAM=2048;  DISK=10 ;;
    medium) CORES=2; RAM=4096;  DISK=20 ;;
    large)  CORES=4; RAM=8192;  DISK=50 ;;
    custom) func_custom_size || return ;;
  esac

  func_common_prompts || return
  func_do_install
}

func_advanced() {
  # ── CTID ────────────────────────────────────────────────────────────────────
  detect_next_ctid
  local input
  input=$(whiptail --backtitle "$BT" --title "Container ID" \
    --inputbox "CTID (auto-detected):" 10 50 "${CTID:-100}" \
    3>&1 1>&2 2>&3) || return
  CTID="$input"

  # ── Resources ───────────────────────────────────────────────────────────────
  func_custom_size || return

  # ── Storage selector ────────────────────────────────────────────────────────
  local storage_list=()
  while IFS= read -r s; do
    [[ -n "$s" ]] && storage_list+=("$s" "" OFF)
  done < <(pvesm status --content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1}')

  if [[ ${#storage_list[@]} -gt 0 ]]; then
    # Pre-select current STORAGE
    for i in $(seq 1 3 ${#storage_list[@]}); do
      if [[ "${storage_list[$((i-1))]}" == "$STORAGE" ]]; then
        storage_list[$((i+1))]="ON"
      fi
    done
    local sel
    sel=$(whiptail --backtitle "$BT" --title "Storage" \
      --radiolist "Select storage for rootfs:" 15 55 6 \
      "${storage_list[@]}" 3>&1 1>&2 2>&3) || return
    STORAGE="$sel"
  fi

  # ── Bridge selector ─────────────────────────────────────────────────────────
  local bridge_list=()
  while IFS= read -r b; do
    [[ -n "$b" ]] && bridge_list+=("$b" "" OFF)
  done < <(detect_bridges)

  if [[ ${#bridge_list[@]} -gt 0 ]]; then
    for i in $(seq 1 3 ${#bridge_list[@]}); do
      if [[ "${bridge_list[$((i-1))]}" == "$BRIDGE" ]]; then
        bridge_list[$((i+1))]="ON"
      fi
    done
    local bsel
    bsel=$(whiptail --backtitle "$BT" --title "Network Bridge" \
      --radiolist "Select bridge:" 15 55 6 \
      "${bridge_list[@]}" 3>&1 1>&2 2>&3) || return
    BRIDGE="$bsel"
  fi

  func_common_prompts || return
  func_do_install
}

func_custom_size() {
  local input
  input=$(whiptail --backtitle "$BT" --title "CPU Cores" \
    --inputbox "Number of CPU cores:" 10 50 "$CORES" 3>&1 1>&2 2>&3) || return
  CORES="$input"

  input=$(whiptail --backtitle "$BT" --title "RAM" \
    --inputbox "RAM in MB:" 10 50 "$RAM" 3>&1 1>&2 2>&3) || return
  RAM="$input"

  input=$(whiptail --backtitle "$BT" --title "Disk Size" \
    --inputbox "Root disk in GB:" 10 50 "$DISK" 3>&1 1>&2 2>&3) || return
  DISK="$input"
}

func_common_prompts() {
  # ── Hostname ────────────────────────────────────────────────────────────────
  local input
  input=$(whiptail --backtitle "$BT" --title "Hostname" \
    --inputbox "Container hostname:" 10 50 "$HN" 3>&1 1>&2 2>&3) || return
  HN="$input"

  # ── Root password ───────────────────────────────────────────────────────────
  PW=$(whiptail --backtitle "$BT" --title "Root Password" \
    --passwordbox "Set root password (for SSH access):" 10 50 \
    3>&1 1>&2 2>&3) || return
  [[ -n "$PW" ]] || { die "Password cannot be empty."; return 1; }

  # ── Auto-detect CTID if not already set ─────────────────────────────────────
  if [[ -z "$CTID" ]]; then
    detect_next_ctid
    [[ -n "$CTID" ]] || { die "Could not determine next CTID."; return 1; }
  fi

  # ── Summary & confirm ──────────────────────────────────────────────────────
  whiptail --backtitle "$BT" --title "Install Summary" --yesno \
    "Container ID:  $CTID\n\
Hostname:      $HN\n\
Resources:     ${CORES} cores / ${RAM} MB RAM / ${DISK} GB disk\n\
Storage:       $STORAGE\n\
Bridge:        $BRIDGE\n\n\
Proceed with installation?" 16 60 || return
}

# ── Do the actual install ─────────────────────────────────────────────────────
func_do_install() {
  clear
  echo -e "\n${bold}Circuit Breaker — LXC Installation${nc}\n"

  # ── Template ────────────────────────────────────────────────────────────────
  msg_info "Updating template list..."
  pveam update >/dev/null 2>&1
  detect_template
  if [[ -z "$TEMPLATE" ]]; then
    msg_err "No Debian 12 template found."
    return 1
  fi
  msg_ok "Template: $TEMPLATE"

  if ! pveam list local 2>/dev/null | grep -q "$TEMPLATE"; then
    msg_info "Downloading $TEMPLATE..."
    if ! pveam download local "$TEMPLATE" >/dev/null 2>&1; then
      msg_err "Template download failed."
      return 1
    fi
  fi
  msg_ok "Template cached"

  # ── Create container ────────────────────────────────────────────────────────
  CLEANUP_CTID="$CTID"
  msg_info "Creating container $CTID..."
  local create_err
  create_err=$(pct create "$CTID" "local:vztmpl/$TEMPLATE" \
    --hostname   "$HN" \
    --password   "$PW" \
    --memory     "$RAM" \
    --swap       "$SWAP" \
    --cores      "$CORES" \
    --rootfs     "${STORAGE}:${DISK}" \
    --net0       "name=eth0,bridge=${BRIDGE},ip=dhcp" \
    --ostype     debian \
    --unprivileged 0 \
    --features   "nesting=1,keyctl=1" \
    --onboot     1 2>&1)
  if [[ $? -ne 0 ]]; then
    msg_err "pct create failed:"
    echo "       $create_err"
    CLEANUP_CTID=""
    return 1
  fi
  PW=""  # clear password from memory
  msg_ok "Container $CTID created"

  # ── Start container ─────────────────────────────────────────────────────────
  msg_info "Starting container..."
  if ! pct start "$CTID" 2>&1; then
    msg_err "Failed to start container $CTID."
    return 1
  fi
  msg_ok "Container started"

  # ── Wait for DHCP ───────────────────────────────────────────────────────────
  msg_info "Waiting for DHCP address..."
  if ! wait_for_ip "$CTID"; then
    msg_err "No DHCP address within 60s. Check bridge $BRIDGE."
    return 1
  fi
  msg_ok "Container IP: $CT_IP"

  # ── Install Circuit Breaker ─────────────────────────────────────────────────
  msg_info "Installing Circuit Breaker (this takes a few minutes)..."
  echo ""
  if ! pct exec "$CTID" -- bash -c \
    "curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --no-tls" 2>&1; then
    msg_err "Circuit Breaker installation failed inside container."
    return 1
  fi
  echo ""
  msg_ok "Circuit Breaker installed"

  # ── Health check ────────────────────────────────────────────────────────────
  msg_info "Waiting for API health check..."
  if ! wait_for_health "$CT_IP"; then
    msg_err "API did not respond within 120s."
    msg_warn "Check: pct exec $CTID -- journalctl -u circuitbreaker -n 50"
    CLEANUP_CTID=""
    return 1
  fi
  msg_ok "API ready at http://$CT_IP:$CB_PORT"

  # ── Done ────────────────────────────────────────────────────────────────────
  CLEANUP_CTID=""  # install succeeded — don't destroy on interrupt
  echo ""
  echo -e "${green}${bold}  ╔══════════════════════════════════════════════════╗"
  echo -e "  ║   Circuit Breaker installed successfully!        ║"
  echo -e "  ╠══════════════════════════════════════════════════╣"
  printf  "  ║  Container ID : %-32s║\n" "$CTID"
  printf  "  ║  URL          : %-32s║\n" "http://$CT_IP:$CB_PORT"
  echo -e "  ╚══════════════════════════════════════════════════╝${nc}"
  echo ""
  echo -e "  Open the URL above to complete setup (OOBE wizard)."
  echo -e "  ${blue}Log:${nc} $LOG_FILE"
  echo ""
  read -rp "  Press Enter to return to menu..."
}

# ══════════════════════════════════════════════════════════════════════════════
# UNINSTALL
# ══════════════════════════════════════════════════════════════════════════════

func_uninstall() {
  local ct_list=()
  while IFS= read -r line; do
    local vmid name
    vmid=$(echo "$line" | awk '{print $1}')
    name=$(echo "$line" | awk '{print $NF}')
    [[ -n "$vmid" ]] && ct_list+=("$vmid" "$name" OFF)
  done < <(pct list 2>/dev/null | awk 'NR>1')

  if [[ ${#ct_list[@]} -eq 0 ]]; then
    whiptail --backtitle "$BT" --title "Uninstall" --msgbox "No containers found." 8 40
    return
  fi

  local target
  target=$(whiptail --backtitle "$BT" --title "Uninstall — Select Container" \
    --radiolist "Select container to destroy:" 18 60 8 \
    "${ct_list[@]}" 3>&1 1>&2 2>&3) || return

  whiptail --backtitle "$BT" --title "Confirm Destroy" \
    --yesno "Permanently destroy container $target?\n\nThis cannot be undone." 10 50 || return

  clear
  msg_info "Stopping container $target..."
  pct stop "$target" --skiplock 2>/dev/null
  msg_info "Destroying container $target..."
  if pct destroy "$target" --purge 2>/dev/null; then
    msg_ok "Container $target destroyed."
  else
    msg_err "Failed to destroy container $target."
  fi
  echo ""
  read -rp "  Press Enter to return to menu..."
}

# ══════════════════════════════════════════════════════════════════════════════
# UPDATE
# ══════════════════════════════════════════════════════════════════════════════

func_update() {
  local ct_list=()
  while IFS= read -r line; do
    local vmid name
    vmid=$(echo "$line" | awk '{print $1}')
    name=$(echo "$line" | awk '{print $NF}')
    [[ -n "$vmid" ]] && ct_list+=("$vmid" "$name" OFF)
  done < <(pct list 2>/dev/null | awk 'NR>1 && $2=="running"')

  if [[ ${#ct_list[@]} -eq 0 ]]; then
    whiptail --backtitle "$BT" --title "Update" --msgbox "No running containers found." 8 45
    return
  fi

  local target
  target=$(whiptail --backtitle "$BT" --title "Update — Select Container" \
    --radiolist "Select container to update:" 18 60 8 \
    "${ct_list[@]}" 3>&1 1>&2 2>&3) || return

  clear
  echo -e "\n${bold}Updating Circuit Breaker in container $target${nc}\n"
  if pct exec "$target" -- bash -c \
    "curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --upgrade" 2>&1; then
    msg_ok "Update complete."
  else
    msg_err "Update failed. Check logs inside container."
  fi
  echo ""
  read -rp "  Press Enter to return to menu..."
}

# ══════════════════════════════════════════════════════════════════════════════
# VIEW LOGS
# ══════════════════════════════════════════════════════════════════════════════

func_viewlogs() {
  if [[ -f "$LOG_FILE" ]]; then
    whiptail --backtitle "$BT" --title "Install Log" \
      --scrolltext --textbox "$LOG_FILE" 30 80
  else
    whiptail --backtitle "$BT" --title "Logs" --msgbox "No log file found." 8 40
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

main() {
  preflight
  detect_storage

  while true; do
    CHOICE=$(whiptail --backtitle "$BT" --title "Circuit Breaker LXC" \
      --menu "What would you like to do?" 18 64 6 \
      "1)" "Install Circuit Breaker LXC (Recommended)" \
      "2)" "Advanced Install (Custom CTID/Size/Storage)" \
      "3)" "Uninstall Container" \
      "4)" "Update Circuit Breaker" \
      "5)" "View Logs" \
      "6)" "Exit" \
      3>&1 1>&2 2>&3)

    if [[ $? -ne 0 ]]; then
      clear
      exit 0
    fi

    case "$CHOICE" in
      "1)") func_preset ;;
      "2)") func_advanced ;;
      "3)") func_uninstall ;;
      "4)") func_update ;;
      "5)") func_viewlogs ;;
      "6)") clear; exit 0 ;;
    esac
  done
}

main
