#!/usr/bin/env bash
# Circuit Breaker — Proxmox LXC Helper
# Full whiptail TUI for creating, managing, and removing CB containers.
# 35-step advanced flow matching community Proxmox helper conventions.
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
DEFAULTS_FILE="${HOME}/.cb-proxmox-defaults.json"

# ── Script settings ──────────────────────────────────────────────────────────
CB_GITHUB_REPO="BlkLeg/CircuitBreaker"
CB_RELEASE_API="https://api.github.com/repos/${CB_GITHUB_REPO}/releases"
CB_PORT=8088
CB_FQDN=""
CB_NO_TLS=true
CB_DOCKER=false

# ── Runtime state ─────────────────────────────────────────────────────────────
# Identity
CT_TYPE=1             # 1=unprivileged, 0=privileged
CTID=""
HN="cb"
PW=""

# Resources
CORES=2
RAM=4096
DISK=20
SWAP=512

# Networking
BRIDGE="vmbr0"
IPV4_MODE="dhcp"      # dhcp|static
IPV4_ADDR=""
IPV4_GW=""
IPV6_MODE="none"      # dhcp|static|none
IPV6_ADDR=""
IPV6_GW=""
MTU=1500
DNS_SEARCH=""
DNS_SERVER=""
MAC=""
VLAN=""

# Metadata + SSH
CT_TAGS="circuitbreaker;visualization"
SSH_KEYS=""
SSH_KEY_MODE="none"

# Features
ROOT_ACCESS=1
FUSE=0
TUN_TAP=0
NESTING=1
GPU_PASSTHRU=0
KEYCTL=0

# System
APT_CACHER=""
TIMEZONE=""
PROTECTION=0
MKNOD=0
FS_MOUNTS=""
VERBOSE=0

# Storage + runtime
STORAGE=""
TEMPLATE_STORAGE=""
TEMPLATE=""
CT_IP=""
CLEANUP_CTID=""
INSTALL_MODE="default"

# PVE info
PVE_VERSION=""
PVE_KERNEL=""
PVE_NODE=""

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
  # Clean up temp SSH key file
  rm -f /tmp/cb-ssh-keys-$$.pub 2>/dev/null
}
trap 'cleanup; exit 130' INT TERM EXIT

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

msg_ok()   { echo -e "  ${green}✓${nc}  $1"; }
msg_info() { echo -e "  ${blue}▸${nc}  $1"; }
msg_warn() { echo -e "  ${yellow}⚠${nc}  $1"; }
msg_err()  { echo -e "  ${red}✗${nc}  $1"; }

die() {
  whiptail --backtitle "$BT" --title "Error" --msgbox "$1" 10 60
  return 1
}

# Validate IPv4 CIDR notation (e.g. 192.168.1.50/24)
validate_cidr4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]] || return 1
}

# ── Preflight ─────────────────────────────────────────────────────────────────
preflight() {
  if ! command -v pveversion &>/dev/null; then
    echo -e "${red}This script must run on a Proxmox VE host.${nc}"
    exit 1
  fi

  for pkg in whiptail jq; do
    if ! command -v "$pkg" &>/dev/null; then
      echo -e "${yellow}Installing $pkg...${nc}"
      apt-get update -qq && apt-get install -y "$pkg" >/dev/null 2>&1
    fi
  done

  if ! curl -sf --max-time 10 https://github.com -o /dev/null 2>/dev/null; then
    echo -e "${red}No internet — curl to github.com failed.${nc}"
    exit 1
  fi
}

# ── PVE detection ─────────────────────────────────────────────────────────────
detect_pve_info() {
  PVE_VERSION=$(pveversion 2>/dev/null | sed 's/.*pve-manager\/\([^ ]*\).*/\1/')
  PVE_KERNEL=$(uname -r)
  PVE_NODE=$(hostname)
}

detect_storage() {
  local candidates
  candidates=$(pvesm status --content rootdir 2>/dev/null \
    | awk 'NR>1 && $3=="active" {print $1}')

  if [[ -z "$candidates" ]]; then
    candidates=$(pvesm status 2>/dev/null \
      | awk 'NR>1 && $3=="active" {print $1}')
  fi

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
  ip -br link show type bridge 2>/dev/null | awk '{print $1}' || echo "vmbr0"
}

detect_timezone() {
  TIMEZONE=$(cat /etc/timezone 2>/dev/null) \
    || TIMEZONE=$(timedatectl show -p Timezone --value 2>/dev/null) \
    || TIMEZONE="UTC"
}

# ── Storage radiolist builder with free/used space ────────────────────────────
build_storage_radiolist() {
  local content_type="$1" default="$2"
  local -n _result=$3
  _result=()

  while IFS= read -r line; do
    local name status total used avail stype
    name=$(echo "$line" | awk '{print $1}')
    stype=$(echo "$line" | awk '{print $2}')
    status=$(echo "$line" | awk '{print $3}')
    [[ "$status" == "active" ]] || continue
    total=$(echo "$line" | awk '{print $4}')
    used=$(echo "$line" | awk '{print $5}')
    avail=$(echo "$line" | awk '{print $6}')
    [[ "$avail" =~ ^[0-9]+$ ]] || continue

    local free_h used_h
    free_h=$(awk "BEGIN{printf \"%.1fGB\", $avail/1048576}" 2>/dev/null || echo "?")
    used_h=$(awk "BEGIN{printf \"%.1fGB\", $used/1048576}" 2>/dev/null || echo "?")

    local tag="OFF"
    [[ "$name" == "$default" ]] && tag="ON"
    _result+=("$name" "($stype) Free: $free_h  Used: $used_h" "$tag")
  done < <(pvesm status --content "$content_type" 2>/dev/null | tail -n +2)
}

# ── Wait helpers ──────────────────────────────────────────────────────────────
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

# ── Defaults persistence ─────────────────────────────────────────────────────
save_defaults() {
  jq -n \
    --arg ct_type "$CT_TYPE" \
    --arg cores "$CORES" --arg ram "$RAM" --arg disk "$DISK" --arg swap "$SWAP" \
    --arg bridge "$BRIDGE" --arg ipv4_mode "$IPV4_MODE" \
    --arg ipv4_addr "$IPV4_ADDR" --arg ipv4_gw "$IPV4_GW" \
    --arg ipv6_mode "$IPV6_MODE" --arg ipv6_addr "$IPV6_ADDR" --arg ipv6_gw "$IPV6_GW" \
    --arg mtu "$MTU" --arg dns_search "$DNS_SEARCH" --arg dns_server "$DNS_SERVER" \
    --arg mac "$MAC" --arg vlan "$VLAN" --arg ct_tags "$CT_TAGS" \
    --arg root_access "$ROOT_ACCESS" --arg fuse "$FUSE" --arg tun_tap "$TUN_TAP" \
    --arg nesting "$NESTING" --arg gpu "$GPU_PASSTHRU" --arg keyctl "$KEYCTL" \
    --arg apt_cacher "$APT_CACHER" --arg timezone "$TIMEZONE" \
    --arg protection "$PROTECTION" --arg mknod "$MKNOD" \
    --arg fs_mounts "$FS_MOUNTS" --arg verbose "$VERBOSE" \
    --arg hn "$HN" \
    '{ct_type:$ct_type, hn:$hn, cores:$cores, ram:$ram, disk:$disk, swap:$swap,
      bridge:$bridge, ipv4_mode:$ipv4_mode, ipv4_addr:$ipv4_addr, ipv4_gw:$ipv4_gw,
      ipv6_mode:$ipv6_mode, ipv6_addr:$ipv6_addr, ipv6_gw:$ipv6_gw,
      mtu:$mtu, dns_search:$dns_search, dns_server:$dns_server, mac:$mac, vlan:$vlan,
      ct_tags:$ct_tags, root_access:$root_access, fuse:$fuse, tun_tap:$tun_tap,
      nesting:$nesting, gpu:$gpu, keyctl:$keyctl, apt_cacher:$apt_cacher,
      timezone:$timezone, protection:$protection, mknod:$mknod,
      fs_mounts:$fs_mounts, verbose:$verbose}' \
    > "$DEFAULTS_FILE"
}

load_defaults() {
  [[ -f "$DEFAULTS_FILE" ]] || return 1
  CT_TYPE=$(jq -r '.ct_type // "1"' "$DEFAULTS_FILE")
  HN=$(jq -r '.hn // "cb"' "$DEFAULTS_FILE")
  CORES=$(jq -r '.cores // "2"' "$DEFAULTS_FILE")
  RAM=$(jq -r '.ram // "4096"' "$DEFAULTS_FILE")
  DISK=$(jq -r '.disk // "20"' "$DEFAULTS_FILE")
  SWAP=$(jq -r '.swap // "512"' "$DEFAULTS_FILE")
  BRIDGE=$(jq -r '.bridge // "vmbr0"' "$DEFAULTS_FILE")
  IPV4_MODE=$(jq -r '.ipv4_mode // "dhcp"' "$DEFAULTS_FILE")
  IPV4_ADDR=$(jq -r '.ipv4_addr // ""' "$DEFAULTS_FILE")
  IPV4_GW=$(jq -r '.ipv4_gw // ""' "$DEFAULTS_FILE")
  IPV6_MODE=$(jq -r '.ipv6_mode // "none"' "$DEFAULTS_FILE")
  IPV6_ADDR=$(jq -r '.ipv6_addr // ""' "$DEFAULTS_FILE")
  IPV6_GW=$(jq -r '.ipv6_gw // ""' "$DEFAULTS_FILE")
  MTU=$(jq -r '.mtu // "1500"' "$DEFAULTS_FILE")
  DNS_SEARCH=$(jq -r '.dns_search // ""' "$DEFAULTS_FILE")
  DNS_SERVER=$(jq -r '.dns_server // ""' "$DEFAULTS_FILE")
  MAC=$(jq -r '.mac // ""' "$DEFAULTS_FILE")
  VLAN=$(jq -r '.vlan // ""' "$DEFAULTS_FILE")
  CT_TAGS=$(jq -r '.ct_tags // "circuitbreaker;visualization"' "$DEFAULTS_FILE")
  ROOT_ACCESS=$(jq -r '.root_access // "1"' "$DEFAULTS_FILE")
  FUSE=$(jq -r '.fuse // "0"' "$DEFAULTS_FILE")
  TUN_TAP=$(jq -r '.tun_tap // "0"' "$DEFAULTS_FILE")
  NESTING=$(jq -r '.nesting // "1"' "$DEFAULTS_FILE")
  GPU_PASSTHRU=$(jq -r '.gpu // "0"' "$DEFAULTS_FILE")
  KEYCTL=$(jq -r '.keyctl // "0"' "$DEFAULTS_FILE")
  APT_CACHER=$(jq -r '.apt_cacher // ""' "$DEFAULTS_FILE")
  TIMEZONE=$(jq -r '.timezone // ""' "$DEFAULTS_FILE")
  PROTECTION=$(jq -r '.protection // "0"' "$DEFAULTS_FILE")
  MKNOD=$(jq -r '.mknod // "0"' "$DEFAULTS_FILE")
  FS_MOUNTS=$(jq -r '.fs_mounts // ""' "$DEFAULTS_FILE")
  VERBOSE=$(jq -r '.verbose // "0"' "$DEFAULTS_FILE")
}

# ── Dynamic pct create command builder ────────────────────────────────────────
build_pct_cmd() {
  PCT_CMD=("pct" "create" "$CTID" "${TEMPLATE_STORAGE}:vztmpl/$TEMPLATE")

  PCT_CMD+=(--hostname "$HN")
  [[ -n "$PW" ]] && PCT_CMD+=(--password "$PW")
  PCT_CMD+=(--memory "$RAM")
  PCT_CMD+=(--swap "$SWAP")
  PCT_CMD+=(--cores "$CORES")
  PCT_CMD+=(--rootfs "${STORAGE}:${DISK}")
  PCT_CMD+=(--ostype debian)
  PCT_CMD+=(--unprivileged "$CT_TYPE")
  PCT_CMD+=(--onboot 1)
  PCT_CMD+=(--force 1)

  # Network
  local net0="name=eth0,bridge=${BRIDGE}"
  case "$IPV4_MODE" in
    dhcp)   net0+=",ip=dhcp" ;;
    static) net0+=",ip=${IPV4_ADDR},gw=${IPV4_GW}" ;;
  esac
  case "$IPV6_MODE" in
    dhcp)   net0+=",ip6=dhcp" ;;
    static) net0+=",ip6=${IPV6_ADDR},gw6=${IPV6_GW}" ;;
    none)   net0+=",ip6=manual" ;;
  esac
  [[ -n "$MTU" && "$MTU" != "1500" ]] && net0+=",mtu=${MTU}"
  [[ -n "$MAC" ]] && net0+=",hwaddr=${MAC}"
  [[ -n "$VLAN" ]] && net0+=",tag=${VLAN}"
  PCT_CMD+=(--net0 "$net0")

  # Features
  local features="nesting=${NESTING}"
  [[ "$KEYCTL" -eq 1 ]] && features+=",keyctl=1"
  [[ "$FUSE" -eq 1 ]] && features+=",fuse=1"
  [[ -n "$FS_MOUNTS" ]] && features+=",mount=${FS_MOUNTS}"
  PCT_CMD+=(--features "$features")

  # DNS
  [[ -n "$DNS_SEARCH" ]] && PCT_CMD+=(--searchdomain "$DNS_SEARCH")
  [[ -n "$DNS_SERVER" ]] && PCT_CMD+=(--nameserver "$DNS_SERVER")

  # Tags
  [[ -n "$CT_TAGS" ]] && PCT_CMD+=(--tags "$CT_TAGS")

  # SSH keys
  if [[ -n "$SSH_KEYS" ]]; then
    local keyfile="/tmp/cb-ssh-keys-$$.pub"
    echo "$SSH_KEYS" > "$keyfile"
    PCT_CMD+=(--ssh-public-keys "$keyfile")
  fi

  # Protection
  [[ "$PROTECTION" -eq 1 ]] && PCT_CMD+=(--protection 1)

  # Timezone
  [[ -n "$TIMEZONE" ]] && PCT_CMD+=(--timezone "$TIMEZONE")
}

# ── Post-create LXC config edits (before start) ──────────────────────────────
post_create_config() {
  local conf="/etc/pve/lxc/${CTID}.conf"
  [[ -f "$conf" ]] || return 0

  # TUN/TAP
  if [[ "$TUN_TAP" -eq 1 ]]; then
    echo "lxc.cgroup2.devices.allow: c 10:200 rwm" >> "$conf"
    echo "lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file" >> "$conf"
  fi

  # GPU passthrough (Intel/AMD integrated)
  if [[ "$GPU_PASSTHRU" -eq 1 ]]; then
    echo "lxc.cgroup2.devices.allow: c 226:* rwm" >> "$conf"
    echo "lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir" >> "$conf"
  fi

  # mknod
  if [[ "$MKNOD" -eq 1 ]]; then
    echo "lxc.cgroup2.devices.allow: b *:* rwm" >> "$conf"
    echo "lxc.cgroup2.devices.allow: c *:* rwm" >> "$conf"
  fi
}

# ── Post-start configuration (requires running container) ─────────────────────
post_start_config() {
  # APT Cacher-NG proxy
  if [[ -n "$APT_CACHER" ]]; then
    pct exec "$CTID" -- bash -c \
      "echo 'Acquire::http::Proxy \"${APT_CACHER}\";' > /etc/apt/apt.conf.d/01proxy" 2>/dev/null
  fi

  # Disable IPv6
  if [[ "$IPV6_MODE" == "none" ]]; then
    pct exec "$CTID" -- bash -c \
      "sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1; echo 'net.ipv6.conf.all.disable_ipv6=1' >> /etc/sysctl.conf" 2>/dev/null
  fi

  # Disable root SSH
  if [[ "$ROOT_ACCESS" -eq 0 ]]; then
    pct exec "$CTID" -- bash -c \
      "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config 2>/dev/null" 2>/dev/null
  fi
}

# ── Build installer command ───────────────────────────────────────────────────
build_installer_cmd() {
  local cmd="bash /tmp/cb-bundle/install.sh --unattended --local-bundle /tmp/cb-bundle.tar.gz"
  [[ "$CB_NO_TLS" == true ]] && cmd+=" --no-tls"
  [[ -n "$CB_FQDN" ]] && cmd+=" --fqdn '${CB_FQDN}'"
  [[ "$CB_PORT" != "8088" ]] && cmd+=" --port ${CB_PORT}"
  [[ "$CB_DOCKER" == true ]] && cmd+=" --docker"
  echo "$cmd"
}

# ══════════════════════════════════════════════════════════════════════════════
# ADVANCED INSTALL — SCREEN FUNCTIONS (Screens 2–34)
# Each returns 0 = forward, 1 = back/cancel
# ══════════════════════════════════════════════════════════════════════════════

# Screen 2 — Container Type
adv_container_type() {
  local sel
  sel=$(whiptail --backtitle "$BT" --title "Container Type" \
    --radiolist "Select container type:" 12 55 2 \
    "1" "Unprivileged (Recommended)" "$([ "$CT_TYPE" = "1" ] && echo ON || echo OFF)" \
    "0" "Privileged" "$([ "$CT_TYPE" = "0" ] && echo ON || echo OFF)" \
    3>&1 1>&2 2>&3) || return 1
  CT_TYPE="$sel"
}

# Screen 3 — Root Password + Confirm
adv_root_password() {
  while true; do
    PW=$(whiptail --backtitle "$BT" --title "Root Password" \
      --passwordbox "Set root password (leave blank for no auth):" 10 55 \
      3>&1 1>&2 2>&3) || return 1
    local PW2
    PW2=$(whiptail --backtitle "$BT" --title "Confirm Password" \
      --passwordbox "Confirm root password:" 10 55 \
      3>&1 1>&2 2>&3) || return 1
    if [[ "$PW" == "$PW2" ]]; then
      break
    fi
    whiptail --backtitle "$BT" --title "Mismatch" \
      --msgbox "Passwords do not match. Try again." 8 40
  done
}

# Screens 4–5 — CTID + Hostname
adv_identity() {
  detect_next_ctid
  local input
  input=$(whiptail --backtitle "$BT" --title "Container ID" \
    --inputbox "Container ID (auto-detected):" 10 50 "${CTID:-100}" \
    3>&1 1>&2 2>&3) || return 1
  CTID="$input"

  input=$(whiptail --backtitle "$BT" --title "Hostname" \
    --inputbox "Container hostname:" 10 50 "$HN" \
    3>&1 1>&2 2>&3) || return 1
  HN="$input"
}

# Screens 6–8 — Disk, Cores, RAM
adv_resources() {
  local input
  input=$(whiptail --backtitle "$BT" --title "Disk Size" \
    --inputbox "Root disk in GB (min 10):" 10 50 "$DISK" \
    3>&1 1>&2 2>&3) || return 1
  [[ "$input" =~ ^[0-9]+$ ]] && DISK="$input"

  input=$(whiptail --backtitle "$BT" --title "CPU Cores" \
    --inputbox "Number of CPU cores:" 10 50 "$CORES" \
    3>&1 1>&2 2>&3) || return 1
  [[ "$input" =~ ^[0-9]+$ ]] && CORES="$input"

  input=$(whiptail --backtitle "$BT" --title "RAM" \
    --inputbox "RAM in MiB:" 10 50 "$RAM" \
    3>&1 1>&2 2>&3) || return 1
  [[ "$input" =~ ^[0-9]+$ ]] && RAM="$input"
}

# Screens 9–16 — Networking (bridge, IPv4, IPv6, MTU, DNS×2, MAC, VLAN)
adv_networking() {
  # ── Screen 9: Bridge ─────────────────────────────────────────────────────────
  local bridge_list=()
  while IFS= read -r b; do
    [[ -n "$b" ]] || continue
    local tag="OFF"
    [[ "$b" == "$BRIDGE" ]] && tag="ON"
    bridge_list+=("$b" "" "$tag")
  done < <(detect_bridges)

  if [[ ${#bridge_list[@]} -gt 0 ]]; then
    local bsel
    bsel=$(whiptail --backtitle "$BT" --title "Network Bridge" \
      --radiolist "Select network bridge:" 15 55 6 \
      "${bridge_list[@]}" 3>&1 1>&2 2>&3) || return 1
    BRIDGE="$bsel"
  fi

  # ── Screen 10: IPv4 ──────────────────────────────────────────────────────────
  local ipv4_sel
  ipv4_sel=$(whiptail --backtitle "$BT" --title "IPv4 Configuration" \
    --radiolist "Select IPv4 mode:" 14 55 3 \
    "DHCP"   "Automatic (DHCP)" "$([ "$IPV4_MODE" = "dhcp" ] && echo ON || echo OFF)" \
    "Static" "Manual IP address" "$([ "$IPV4_MODE" = "static" ] && echo ON || echo OFF)" \
    "Range"  "DHCP with reservation" OFF \
    3>&1 1>&2 2>&3) || return 1

  case "$ipv4_sel" in
    DHCP) IPV4_MODE="dhcp"; IPV4_ADDR=""; IPV4_GW="" ;;
    Static)
      IPV4_MODE="static"
      local input _prompt="IP/CIDR (e.g. 10.10.10.50/24):"
      while true; do
        input=$(whiptail --backtitle "$BT" --title "IPv4 Address" \
          --inputbox "$_prompt" 10 60 "$IPV4_ADDR" \
          3>&1 1>&2 2>&3) || return 1
        if validate_cidr4 "$input"; then
          IPV4_ADDR="$input"
          break
        fi
        _prompt="Invalid format. Use x.x.x.x/prefix (e.g. 10.10.10.50/24):"
      done
      input=$(whiptail --backtitle "$BT" --title "IPv4 Gateway" \
        --inputbox "Gateway (e.g. 10.10.10.1):" 10 55 "$IPV4_GW" \
        3>&1 1>&2 2>&3) || return 1
      IPV4_GW="$input"
      ;;
    Range)
      IPV4_MODE="dhcp"
      whiptail --backtitle "$BT" --title "DHCP Range" --msgbox \
        "IP ranges are managed by your DHCP server.\n\nConfigure a DHCP reservation for this container's MAC address on your router/DHCP server.\n\nProceeding with DHCP mode." 12 60
      ;;
  esac

  # ── Screen 11: IPv6 ──────────────────────────────────────────────────────────
  local ipv6_sel
  ipv6_sel=$(whiptail --backtitle "$BT" --title "IPv6 Configuration" \
    --radiolist "Select IPv6 mode:" 14 55 3 \
    "DHCP"    "Automatic (SLAAC/DHCPv6)" "$([ "$IPV6_MODE" = "dhcp" ] && echo ON || echo OFF)" \
    "Static"  "Manual IPv6 address"      "$([ "$IPV6_MODE" = "static" ] && echo ON || echo OFF)" \
    "None"    "Disable IPv6"             "$([ "$IPV6_MODE" = "none" ] && echo ON || echo OFF)" \
    3>&1 1>&2 2>&3) || return 1

  case "$ipv6_sel" in
    DHCP)   IPV6_MODE="dhcp"; IPV6_ADDR=""; IPV6_GW="" ;;
    Static)
      IPV6_MODE="static"
      local input
      input=$(whiptail --backtitle "$BT" --title "IPv6 Address" \
        --inputbox "IPv6/prefix (e.g. fd00::50/64):" 10 55 "$IPV6_ADDR" \
        3>&1 1>&2 2>&3) || return 1
      IPV6_ADDR="$input"
      input=$(whiptail --backtitle "$BT" --title "IPv6 Gateway" \
        --inputbox "IPv6 gateway:" 10 55 "$IPV6_GW" \
        3>&1 1>&2 2>&3) || return 1
      IPV6_GW="$input"
      ;;
    None) IPV6_MODE="none"; IPV6_ADDR=""; IPV6_GW="" ;;
  esac

  # ── Screen 12: MTU ──────────────────────────────────────────────────────────
  local input
  input=$(whiptail --backtitle "$BT" --title "Interface MTU" \
    --inputbox "MTU size (68-9000, default 1500):" 10 50 "$MTU" \
    3>&1 1>&2 2>&3) || return 1
  [[ "$input" =~ ^[0-9]+$ ]] && MTU="$input"

  # ── Screen 13: DNS Search Domain ────────────────────────────────────────────
  input=$(whiptail --backtitle "$BT" --title "DNS Search Domain" \
    --inputbox "DNS search domain (blank = use host):" 10 55 "$DNS_SEARCH" \
    3>&1 1>&2 2>&3) || return 1
  DNS_SEARCH="$input"

  # ── Screen 14: DNS Server ───────────────────────────────────────────────────
  input=$(whiptail --backtitle "$BT" --title "DNS Server" \
    --inputbox "DNS server IP (blank = use host):" 10 55 "$DNS_SERVER" \
    3>&1 1>&2 2>&3) || return 1
  DNS_SERVER="$input"

  # ── Screen 15: MAC Address ─────────────────────────────────────────────────
  input=$(whiptail --backtitle "$BT" --title "MAC Address" \
    --inputbox "MAC address (blank = auto-generate):" 10 55 "$MAC" \
    3>&1 1>&2 2>&3) || return 1
  MAC="$input"

  # ── Screen 16: VLAN ────────────────────────────────────────────────────────
  input=$(whiptail --backtitle "$BT" --title "VLAN Tag" \
    --inputbox "VLAN tag (1-4094, blank = none):" 10 55 "$VLAN" \
    3>&1 1>&2 2>&3) || return 1
  VLAN="$input"
}

# Screen 17 — Container Tags
adv_metadata() {
  local input
  input=$(whiptail --backtitle "$BT" --title "Container Tags" \
    --inputbox "Tags (semicolon separated):" 10 55 "$CT_TAGS" \
    3>&1 1>&2 2>&3) || return 1
  CT_TAGS="$input"
}

# Screen 18 — SSH Keys
adv_ssh_keys() {
  local mode
  mode=$(whiptail --backtitle "$BT" --title "SSH Keys" \
    --radiolist "Provision SSH public keys for root:" 14 55 4 \
    "Found"  "Auto-detect from ~/.ssh/" "$([ "$SSH_KEY_MODE" = "found" ] && echo ON || echo OFF)" \
    "Manual" "Paste a public key"       "$([ "$SSH_KEY_MODE" = "manual" ] && echo ON || echo OFF)" \
    "Folder" "Read from a directory"    "$([ "$SSH_KEY_MODE" = "folder" ] && echo ON || echo OFF)" \
    "None"   "Skip SSH keys"            "$([ "$SSH_KEY_MODE" = "none" ] && echo ON || echo OFF)" \
    3>&1 1>&2 2>&3) || return 1

  SSH_KEY_MODE=$(echo "$mode" | tr '[:upper:]' '[:lower:]')
  SSH_KEYS=""

  case "$SSH_KEY_MODE" in
    found)
      local keys=""
      for f in ~/.ssh/*.pub; do
        [[ -f "$f" ]] || continue
        keys+="$(cat "$f")\n"
      done
      if [[ -z "$keys" ]]; then
        whiptail --backtitle "$BT" --msgbox "No public keys found in ~/.ssh/" 8 50
        SSH_KEY_MODE="none"
      else
        SSH_KEYS=$(echo -e "$keys")
        whiptail --backtitle "$BT" --msgbox "Found $(echo -e "$keys" | grep -c .)" 8 40
      fi
      ;;
    manual)
      local input
      input=$(whiptail --backtitle "$BT" --title "SSH Public Key" \
        --inputbox "Paste your SSH public key:" 10 70 \
        3>&1 1>&2 2>&3) || true
      SSH_KEYS="$input"
      ;;
    folder)
      local dir
      dir=$(whiptail --backtitle "$BT" --title "SSH Key Directory" \
        --inputbox "Path to directory with .pub files:" 10 60 "/root/.ssh" \
        3>&1 1>&2 2>&3) || true
      if [[ -d "$dir" ]]; then
        for f in "$dir"/*.pub; do
          [[ -f "$f" ]] && SSH_KEYS+="$(cat "$f")\n"
        done
        SSH_KEYS=$(echo -e "$SSH_KEYS")
      fi
      ;;
    none) SSH_KEYS="" ;;
  esac
}

# Screens 19–24 — Features (root, FUSE, TUN, nesting, GPU, keyctl)
adv_features() {
  # Screen 19: Root access
  if whiptail --backtitle "$BT" --title "Root Access" \
    --yesno "Enable root SSH access?" 8 45 $([ "$ROOT_ACCESS" -eq 0 ] && echo "--defaultno"); then
    ROOT_ACCESS=1
  else
    ROOT_ACCESS=0
  fi

  # Screen 20: FUSE
  if whiptail --backtitle "$BT" --title "FUSE Support" \
    --yesno "Enable FUSE support?" 8 45 $([ "$FUSE" -eq 0 ] && echo "--defaultno"); then
    FUSE=1
  else
    FUSE=0
  fi

  # Screen 21: TUN/TAP
  if whiptail --backtitle "$BT" --title "TUN/TAP Device" \
    --yesno "Enable TUN/TAP device support?" 8 45 $([ "$TUN_TAP" -eq 0 ] && echo "--defaultno"); then
    TUN_TAP=1
  else
    TUN_TAP=0
  fi

  # Screen 22: Nesting
  if whiptail --backtitle "$BT" --title "Nesting" \
    --yesno "Enable nesting? (Required for Docker)" 8 50 $([ "$NESTING" -eq 0 ] && echo "--defaultno"); then
    NESTING=1
  else
    NESTING=0
  fi

  # Screen 23: GPU passthrough
  if whiptail --backtitle "$BT" --title "GPU Passthrough" \
    --yesno "Enable GPU passthrough? (Intel/AMD iGPU only)" 8 55 --defaultno; then
    GPU_PASSTHRU=1
    whiptail --backtitle "$BT" --title "GPU Note" --msgbox \
      "GPU passthrough will mount /dev/dri into the container.\n\nNVIDIA discrete GPUs require additional host-side driver configuration not handled by this script." 12 60
  else
    GPU_PASSTHRU=0
  fi

  # Screen 24: Keyctl
  if whiptail --backtitle "$BT" --title "Keyctl Support" \
    --yesno "Enable keyctl support?" 8 45 $([ "$KEYCTL" -eq 0 ] && echo "--defaultno"); then
    KEYCTL=1
  else
    KEYCTL=0
  fi
}

# Screens 25–29 — System (APT cacher, timezone, protection, mknod, mounts)
adv_system() {
  # Screen 25: APT Cacher-NG
  if whiptail --backtitle "$BT" --title "APT Cacher-NG" \
    --yesno "Use an APT Cacher-NG proxy?" 8 45 --defaultno; then
    local input
    input=$(whiptail --backtitle "$BT" --title "APT Proxy URL" \
      --inputbox "Proxy URL (e.g. http://apt-cacher:3142):" 10 60 "$APT_CACHER" \
      3>&1 1>&2 2>&3) || true
    APT_CACHER="$input"
  else
    APT_CACHER=""
  fi

  # Screen 26: Timezone
  detect_timezone
  local input
  input=$(whiptail --backtitle "$BT" --title "Container Timezone" \
    --inputbox "Timezone (detected from host):" 10 55 "$TIMEZONE" \
    3>&1 1>&2 2>&3) || return 1
  TIMEZONE="$input"

  # Screen 27: Protection
  if whiptail --backtitle "$BT" --title "Container Protection" \
    --yesno "Enable container protection?\n(Prevents accidental deletion)" 9 50 --defaultno; then
    PROTECTION=1
  else
    PROTECTION=0
  fi

  # Screen 28: mknod
  if whiptail --backtitle "$BT" --title "Device Node Creation" \
    --yesno "Allow device node creation (mknod)?" 8 50 --defaultno; then
    MKNOD=1
  else
    MKNOD=0
  fi

  # Screen 29: Filesystem mounts
  input=$(whiptail --backtitle "$BT" --title "Filesystem Mounts" \
    --inputbox "Allow filesystem types (comma-sep, e.g. nfs,cifs; blank=none):" 10 65 "$FS_MOUNTS" \
    3>&1 1>&2 2>&3) || return 1
  FS_MOUNTS="$input"
}

# Screen 30 — Verbose Mode
adv_verbose() {
  if whiptail --backtitle "$BT" --title "Verbose Mode" \
    --yesno "Enable verbose output during installation?" 8 55 --defaultno; then
    VERBOSE=1
  else
    VERBOSE=0
  fi
}

# Screen 31 — Confirm Settings
adv_confirm() {
  local ct_label="Unprivileged"
  [[ "$CT_TYPE" -eq 0 ]] && ct_label="Privileged"

  local summary=""
  summary+="Container Type:  $ct_label\n"
  summary+="Container ID:    $CTID\n"
  summary+="Hostname:        $HN\n"
  summary+="Disk:            ${DISK} GB\n"
  summary+="CPU:             $CORES core(s)\n"
  summary+="RAM:             ${RAM} MiB\n"
  summary+="Bridge:          $BRIDGE\n"
  summary+="IPv4:            $IPV4_MODE"
  [[ "$IPV4_MODE" == "static" ]] && summary+=" ($IPV4_ADDR gw $IPV4_GW)"
  summary+="\n"
  summary+="IPv6:            $IPV6_MODE"
  [[ "$IPV6_MODE" == "static" ]] && summary+=" ($IPV6_ADDR gw $IPV6_GW)"
  summary+="\n"
  [[ "$MTU" != "1500" ]] && summary+="MTU:             $MTU\n"
  [[ -n "$DNS_SEARCH" ]] && summary+="DNS Search:      $DNS_SEARCH\n"
  [[ -n "$DNS_SERVER" ]] && summary+="DNS Server:      $DNS_SERVER\n"
  [[ -n "$MAC" ]] && summary+="MAC:             $MAC\n"
  [[ -n "$VLAN" ]] && summary+="VLAN:            $VLAN\n"
  summary+="Tags:            $CT_TAGS\n"
  summary+="SSH Keys:        $SSH_KEY_MODE\n"
  summary+="Root SSH:        $([ "$ROOT_ACCESS" -eq 1 ] && echo Yes || echo No)\n"
  summary+="Nesting:         $([ "$NESTING" -eq 1 ] && echo Yes || echo No)\n"
  [[ "$FUSE" -eq 1 ]] && summary+="FUSE:            Yes\n"
  [[ "$TUN_TAP" -eq 1 ]] && summary+="TUN/TAP:         Yes\n"
  [[ "$GPU_PASSTHRU" -eq 1 ]] && summary+="GPU Passthru:    Yes\n"
  [[ "$KEYCTL" -eq 1 ]] && summary+="Keyctl:          Yes\n"
  [[ -n "$APT_CACHER" ]] && summary+="APT Proxy:       $APT_CACHER\n"
  summary+="Timezone:        ${TIMEZONE:-host}\n"
  [[ "$PROTECTION" -eq 1 ]] && summary+="Protection:      Yes\n"
  [[ "$MKNOD" -eq 1 ]] && summary+="mknod:           Yes\n"
  [[ -n "$FS_MOUNTS" ]] && summary+="FS Mounts:       $FS_MOUNTS\n"

  whiptail --backtitle "$BT" --title "Confirm Settings" --scrolltext \
    --yesno "$summary\nProceed with installation?" 28 65 || return 1
}

# Screens 32–33 — Template + Container Storage
adv_storage() {
  # ── Screen 32: Template storage ──────────────────────────────────────────────
  local tmpl_list=()
  build_storage_radiolist "vztmpl" "${TEMPLATE_STORAGE:-local}" tmpl_list

  if [[ ${#tmpl_list[@]} -gt 3 ]]; then
    local tsel
    tsel=$(whiptail --backtitle "$BT" --title "Template Storage" \
      --radiolist "Select storage for templates:" 15 65 6 \
      "${tmpl_list[@]}" 3>&1 1>&2 2>&3) || return 1
    TEMPLATE_STORAGE="$tsel"
  elif [[ ${#tmpl_list[@]} -eq 3 ]]; then
    TEMPLATE_STORAGE="${tmpl_list[0]}"
  else
    TEMPLATE_STORAGE="local"
  fi

  # ── Screen 33: Container storage ─────────────────────────────────────────────
  local root_list=()
  build_storage_radiolist "rootdir" "$STORAGE" root_list

  if [[ ${#root_list[@]} -gt 3 ]]; then
    local rsel
    rsel=$(whiptail --backtitle "$BT" --title "Container Storage" \
      --radiolist "Select storage for container rootfs:" 15 65 6 \
      "${root_list[@]}" 3>&1 1>&2 2>&3) || return 1
    STORAGE="$rsel"
  elif [[ ${#root_list[@]} -eq 3 ]]; then
    STORAGE="${root_list[0]}"
  fi

  # ── Validate free space ────────────────────────────────────────────────────
  local avail_kib
  avail_kib=$(pvesm status --content rootdir 2>/dev/null \
    | awk -v s="$STORAGE" '$1==s && $3=="active" {print $6}')
  if [[ "$avail_kib" =~ ^[0-9]+$ ]] && (( avail_kib > 0 )); then
    local avail_gb=$(( avail_kib / 1048576 ))
    if (( avail_gb < DISK )); then
      local free_h
      free_h=$(awk "BEGIN{printf \"%.1f\", $avail_kib/1048576}")
      whiptail --backtitle "$BT" --title "Insufficient Space" \
        --msgbox "Storage '$STORAGE' has ${free_h}GB free but ${DISK}GB requested.\n\nSelect a different storage or reduce disk size." 10 60
      return 1
    fi
  fi
}

# Screen 34 — Save Advanced Settings
adv_save_defaults() {
  if whiptail --backtitle "$BT" --title "Save Settings" \
    --yesno "Save these settings as user defaults?\n\n(Load with 'User Defaults' from main menu)" 10 55 --defaultno; then
    save_defaults
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# INSTALL ORCHESTRATORS
# ══════════════════════════════════════════════════════════════════════════════

func_advanced_install() {
  INSTALL_MODE="advanced"
  local step=0
  local -a steps=(
    adv_container_type    # 0  — Screen 2
    adv_root_password     # 1  — Screen 3
    adv_identity          # 2  — Screens 4-5
    adv_resources         # 3  — Screens 6-8
    adv_networking        # 4  — Screens 9-16
    adv_metadata          # 5  — Screen 17
    adv_ssh_keys          # 6  — Screen 18
    adv_features          # 7  — Screens 19-24
    adv_system            # 8  — Screens 25-29
    adv_verbose           # 9  — Screen 30
    adv_confirm           # 10 — Screen 31
    adv_storage           # 11 — Screens 32-33
    adv_save_defaults     # 12 — Screen 34
  )

  while (( step < ${#steps[@]} )); do
    if "${steps[$step]}"; then
      (( step++ ))
    else
      if (( step == 0 )); then
        return  # Cancel on first screen = back to main menu
      fi
      (( step-- ))
    fi
  done

  func_do_install
}

func_default_install() {
  INSTALL_MODE="default"

  # Auto-set defaults
  CT_TYPE=1; HN="cb"; CORES=2; RAM=4096; DISK=20; SWAP=512
  NESTING=1; KEYCTL=0; IPV4_MODE="dhcp"; IPV6_MODE="none"
  BRIDGE="vmbr0"; VERBOSE=0
  detect_next_ctid
  [[ -n "$CTID" ]] || { die "Could not determine next CTID."; return; }
  detect_timezone

  # Prompt: password
  adv_root_password || return

  # Prompt: storage selection
  adv_storage || return

  func_do_install
}

func_user_defaults() {
  if ! load_defaults; then
    whiptail --backtitle "$BT" --title "User Defaults" \
      --msgbox "No saved defaults found.\n\nUse 'Advanced Settings' to configure and save defaults." 10 55
    return
  fi

  INSTALL_MODE="defaults"
  detect_next_ctid
  [[ -n "$CTID" ]] || { die "Could not determine next CTID."; return; }

  # Prompt: password (never saved)
  adv_root_password || return

  # Prompt: storage (never saved — depends on host)
  adv_storage || return

  # Show summary and confirm
  adv_confirm || return

  func_do_install
}

func_settings() {
  while true; do
    local choice
    choice=$(whiptail --backtitle "$BT" --title "Settings" \
      --menu "Configure script settings:" 20 70 7 \
      "URL"    "Install URL: .../${CB_INSTALL_URL##*/}" \
      "Branch" "Git branch: $CB_BRANCH" \
      "Port"   "CB port: $CB_PORT" \
      "FQDN"   "FQDN: ${CB_FQDN:-auto}" \
      "TLS"    "TLS: $([ "$CB_NO_TLS" = true ] && echo disabled || echo enabled)" \
      "Docker" "Docker mode: $([ "$CB_DOCKER" = true ] && echo enabled || echo disabled)" \
      "Back"   "Return to main menu" \
      3>&1 1>&2 2>&3) || return

    case "$choice" in
      URL)    CB_INSTALL_URL=$(whiptail --backtitle "$BT" --inputbox "Install URL:" 10 70 "$CB_INSTALL_URL" 3>&1 1>&2 2>&3) || true ;;
      Branch) CB_BRANCH=$(whiptail --backtitle "$BT" --inputbox "Git branch:" 10 50 "$CB_BRANCH" 3>&1 1>&2 2>&3) || true ;;
      Port)   CB_PORT=$(whiptail --backtitle "$BT" --inputbox "Port:" 10 50 "$CB_PORT" 3>&1 1>&2 2>&3) || true ;;
      FQDN)   CB_FQDN=$(whiptail --backtitle "$BT" --inputbox "FQDN (blank=auto):" 10 50 "$CB_FQDN" 3>&1 1>&2 2>&3) || true ;;
      TLS)    if whiptail --backtitle "$BT" --yesno "Enable TLS?" 8 40; then CB_NO_TLS=false; else CB_NO_TLS=true; fi ;;
      Docker) if whiptail --backtitle "$BT" --yesno "Use Docker deployment mode?" 8 45; then CB_DOCKER=true; else CB_DOCKER=false; fi ;;
      Back)   return ;;
    esac
  done
}

# ══════════════════════════════════════════════════════════════════════════════
# DO INSTALL — Screen 35 (emoji output + create/start/install)
# ══════════════════════════════════════════════════════════════════════════════

func_do_install() {
  clear
  local ct_label="Unprivileged"
  [[ "$CT_TYPE" -eq 0 ]] && ct_label="Privileged"

  echo ""
  case "$INSTALL_MODE" in
    default)  echo "  ⚙️  Using Default Settings on node $PVE_NODE" ;;
    defaults) echo "  ⚙️  Using Saved Defaults on node $PVE_NODE" ;;
    advanced) echo "  ⚙️  Using Advanced Settings on node $PVE_NODE" ;;
  esac
  echo "  💡  PVE Version $PVE_VERSION (Kernel: $PVE_KERNEL)"
  echo "  🆔  Container ID: $CTID"
  echo "  🖥️  Operating System: debian (12)"
  echo "  📦  Container Type: $ct_label"
  echo "  💾  Disk Size: $DISK GB"
  echo "  🧠  CPU Cores: $CORES"
  echo "  🛠️  RAM Size: $RAM MiB"
  echo ""
  echo "  🚀  Creating Circuit Breaker LXC..."
  echo ""

  # ── Template ────────────────────────────────────────────────────────────────
  pveam update >/dev/null 2>&1
  detect_template
  if [[ -z "$TEMPLATE" ]]; then
    msg_err "No Debian 12 template found."
    read -rp "  Press Enter to return to menu..."
    return 1
  fi

  # Show storage info
  local ct_free tmpl_free
  ct_free=$(pvesm status --content rootdir 2>/dev/null \
    | awk -v s="$STORAGE" '$1==s {printf "Free: %.1fGB  Used: %.1fGB", $6/1048576, $5/1048576}')
  tmpl_free=$(pvesm status --content vztmpl 2>/dev/null \
    | awk -v s="$TEMPLATE_STORAGE" '$1==s {printf "Free: %.1fGB  Used: %.1fGB", $6/1048576, $5/1048576}')

  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    msg_info "Downloading $TEMPLATE..."
    pvesm set "$TEMPLATE_STORAGE" 2>/dev/null || true  # clear stale locks
    if ! timeout 300 pveam download "$TEMPLATE_STORAGE" "$TEMPLATE" >/dev/null 2>&1; then
      msg_err "Template download failed or timed out (5m limit)."
      msg_warn "Check: pvesm status && pvesm list $TEMPLATE_STORAGE"
      read -rp "  Press Enter to return to menu..."
      return 1
    fi
  fi

  echo "  ✔️  Storage $STORAGE ($ct_free) [Container]"
  echo "  ✔️  Template storage $TEMPLATE_STORAGE ($tmpl_free) [Template]"
  echo "  ✔️  Template $TEMPLATE [online]"

  # ── Build and run pct create ────────────────────────────────────────────────
  CLEANUP_CTID="$CTID"
  # Clear any stale lock on this CTID before creation
  pct unlock "$CTID" 2>/dev/null || true
  build_pct_cmd

  local create_err
  create_err=$(timeout 120 "${PCT_CMD[@]}" 2>&1)
  if [[ $? -ne 0 ]]; then
    msg_err "pct create failed:"
    echo "       $create_err"
    msg_warn "Debug: pvesm status | journalctl -u pvedaemon -n 20"
    CLEANUP_CTID=""
    read -rp "  Press Enter to return to menu..."
    return 1
  fi
  PW=""  # clear password from memory

  # ── Post-create config (before start) ───────────────────────────────────────
  post_create_config

  # ── Start container ─────────────────────────────────────────────────────────
  pct unlock "$CTID" 2>/dev/null || true
  if ! pct start "$CTID" 2>&1; then
    msg_err "Failed to start container $CTID."
    read -rp "  Press Enter to return to menu..."
    return 1
  fi

  # ── Wait for IP ─────────────────────────────────────────────────────────────
  msg_info "Waiting for network..."
  if [[ "$IPV4_MODE" == "dhcp" ]]; then
    if ! wait_for_ip "$CTID"; then
      msg_err "No DHCP address within 60s. Check bridge $BRIDGE."
      CLEANUP_CTID=""
      read -rp "  Press Enter to return to menu..."
      return 1
    fi
  else
    # Static IP — extract base IP from CIDR notation
    CT_IP="${IPV4_ADDR%%/*}"
    sleep 3  # Brief wait for container networking
  fi
  echo "  ✔️  Container $CTID started (IP: $CT_IP)"

  # ── Post-start config ──────────────────────────────────────────────────────
  post_start_config

  # ── Download bundle on PVE host ─────────────────────────────────────────────
  msg_info "Downloading Circuit Breaker bundle..."
  local host_arch
  case "$(uname -m)" in
    x86_64)  host_arch="amd64" ;;
    aarch64) host_arch="arm64" ;;
    *) msg_err "Unsupported architecture: $(uname -m)"; return 1 ;;
  esac

  local release_json cb_version tarball_name tarball_url
  release_json=$(curl -fsSL "${CB_RELEASE_API}/latest" 2>/dev/null) \
    || { msg_err "Failed to fetch latest release from GitHub"; return 1; }
  cb_version=$(echo "$release_json" | jq -r '.tag_name' | tr -d v)
  tarball_name="circuit-breaker_${cb_version}_linux_${host_arch}.tar.gz"
  tarball_url=$(echo "$release_json" | jq -r ".assets[] | select(.name==\"${tarball_name}\") | .browser_download_url")

  if [[ -z "$tarball_url" ]] || [[ "$tarball_url" == "null" ]]; then
    msg_err "Bundle ${tarball_name} not found in release v${cb_version}"
    return 1
  fi

  curl -fsSL -o "/tmp/${tarball_name}" "$tarball_url" \
    || { msg_err "Failed to download bundle"; return 1; }
  echo "  ✔️  Bundle downloaded: v${cb_version} (${host_arch})"

  # ── Push bundle into container ────────────────────────────────────────────
  msg_info "Pushing bundle into container..."
  pct push "$CTID" "/tmp/${tarball_name}" "/tmp/cb-bundle.tar.gz"
  pct exec "$CTID" -- bash -c "mkdir -p /tmp/cb-bundle && tar -xzf /tmp/cb-bundle.tar.gz -C /tmp/cb-bundle"

  # ── Install dependencies (curl+jq needed by installer) ───────────────────
  msg_info "Preparing container (installing curl and jq)..."
  if ! pct exec "$CTID" -- bash -c "apt-get update -qq && apt-get install -y curl jq" >/dev/null 2>&1; then
    msg_err "Failed to install curl/jq inside container."
    CLEANUP_CTID=""
    read -rp "  Press Enter to return to menu..."
    return 1
  fi

  # Clean up host-side tarball
  rm -f "/tmp/${tarball_name}"

  # ── Install Circuit Breaker from bundle ──────────────────────────────────
  msg_info "Installing Circuit Breaker (this takes a few minutes)..."
  echo ""
  local installer_cmd
  installer_cmd=$(build_installer_cmd)

  local install_log="/tmp/cb-install-${CTID}.log"
  if [[ "$VERBOSE" -eq 1 ]]; then
    timeout 600 pct exec "$CTID" -- bash -c "$installer_cmd" 2>&1 | tee "$install_log"
  else
    timeout 600 pct exec "$CTID" -- bash -c "$installer_cmd" &>"$install_log"
  fi
  local install_rc=$?
  echo ""
  if [[ $install_rc -ne 0 ]]; then
    msg_err "Circuit Breaker installation failed (exit code $install_rc)."
    msg_warn "Last 20 lines of install log ($install_log):"
    tail -20 "$install_log" 2>/dev/null | sed 's/^/    /'
    echo ""
    echo "  Debug steps:"
    echo "    1. Enter container:  pct enter $CTID"
    echo "    2. Full install log: tail -50 /var/lib/circuitbreaker/logs/install.log"
    echo "    3. CB service:       systemctl status circuitbreaker.target"
    echo "    4. All CB logs:      journalctl -u 'circuitbreaker-*' --no-pager -n 50"
    echo "    5. Re-run installer: bash /tmp/cb-bundle/install.sh --unattended"
    echo ""
    CLEANUP_CTID=""
    read -rp "  Press Enter to return to menu..."
    return 1
  fi

  # ── Health check ────────────────────────────────────────────────────────────
  msg_info "Waiting for API health check..."
  if ! wait_for_health "$CT_IP"; then
    msg_err "API did not respond within 120s."
    msg_warn "Check: pct exec $CTID -- journalctl -u circuitbreaker -n 50"
    CLEANUP_CTID=""
    read -rp "  Press Enter to return to menu..."
    return 1
  fi

  # ── Done ────────────────────────────────────────────────────────────────────
  CLEANUP_CTID=""
  echo ""
  echo "  ✔️  Circuit Breaker installed + running"
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
  timeout 600 pct exec "$target" -- bash -c \
    "curl -fsSL '${CB_INSTALL_URL}' | bash -s -- --unattended --upgrade"
  local rc=$?
  if [[ $rc -eq 0 ]]; then
    msg_ok "Update complete."
  else
    msg_err "Update failed (exit code $rc)."
    echo "  Debug: pct enter $target  →  journalctl -u 'circuitbreaker-*' -n 50"
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
  detect_pve_info
  detect_storage

  while true; do
    CHOICE=$(whiptail --backtitle "$BT" --title "Circuit Breaker LXC" \
      --menu "What would you like to do?" 20 64 8 \
      "1)" "Default Install" \
      "2)" "Advanced Settings" \
      "3)" "User Defaults" \
      "4)" "Settings" \
      "5)" "Uninstall Container" \
      "6)" "Update Circuit Breaker" \
      "7)" "View Logs" \
      "8)" "Exit" \
      3>&1 1>&2 2>&3)

    if [[ $? -ne 0 ]]; then
      clear
      exit 0
    fi

    case "$CHOICE" in
      "1)") func_default_install ;;
      "2)") func_advanced_install ;;
      "3)") func_user_defaults ;;
      "4)") func_settings ;;
      "5)") func_uninstall ;;
      "6)") func_update ;;
      "7)") func_viewlogs ;;
      "8)") clear; exit 0 ;;
    esac
  done
}

main
