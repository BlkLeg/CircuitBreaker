#!/usr/bin/env bash
# Circuit Breaker LXC Creator
# Run from Proxmox VE shell:
# bash -c "$(wget -qLO - https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/proxmox/ct/circuitbreaker.sh)"
set -euo pipefail

APP="CircuitBreaker"
VAR_VERSION="0.2.2"
INSTALL_SCRIPT="https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/proxmox/install/circuitbreaker-install.sh"

# ── CT defaults ───────────────────────────────────────────────
CT_TYPE="1"           # Unprivileged — no nesting needed, no Docker
CT_DISK_SIZE="6"      # GB — smaller now, no Docker layer storage
CT_RAM="1024"         # MB — 1GB comfortable, 512MB minimum
CT_CPU="2"
CT_HOSTNAME="circuitbreaker"
CT_OS="debian"
CT_OS_VERSION="12"
CT_NET_BRIDGE="vmbr0"
CT_NET_IP="dhcp"
CT_ONBOOT="1"
CT_FEATURES=""        # Intentionally empty — no nesting, no special caps

# ── Colors ───────────────────────────────────────────────────
YW=$(echo "\033[33m"); BL=$(echo "\033[36m"); RD=$(echo "\033[01;31m")
BGN=$(echo "\033[4;92m"); GN=$(echo "\033[1;92m"); DGN=$(echo "\033[32m")
CL=$(echo "\033[m"); BOLD=$(echo "\033[1m")

header_info() {
    clear
    cat <<'BANNER'
   ___  _                   _ _   ___
  / __\(_)_ __ ___ _   _(_) |_  / __\_ __ ___  __ _| | _____ _ __
 / /   | | '__/ __| | | | | __| /__\// '__/ _ \/ _` | |/ / _ \ '__|
/ /____| | | | (__| |_| | | |_/ \/  \ | |  __/ (_| |   <  __/ |
\______|_|_|  \___|\__,_|_|\__\_____/_|  \___|\__,_|_|\_\___|_|
BANNER
    echo -e "\n ${GN}v${VAR_VERSION}${CL} — Homelab topology, documented."
    echo -e " ${DGN}Native LXC — Python + Postgres + nginx (no Docker overhead)${CL}\n"
}

msg_info()  { echo -e " ${BL}[INFO]${CL} ${1}"; }
msg_ok()    { echo -e " ${GN}[OK]${CL}   ${1}"; }
msg_error() { echo -e " ${RD}[ERROR]${CL} ${1}"; exit 1; }

[[ ! -f /etc/pve/.version ]] && \
    msg_error "Run this from the Proxmox VE host shell, not inside a container."

get_storage() {
    STORAGE=$(pvesm status -content rootdir | awk 'NR>1{print $1}' | head -1)
    [[ -z "$STORAGE" ]] && msg_error "No rootdir storage found."
    echo "$STORAGE"
}

get_next_id() {
    pvesh get /cluster/nextid 2>/dev/null || echo "100"
}

choose_mode() {
    whiptail --backtitle "Circuit Breaker LXC" \
        --title "Setup Mode" \
        --menu "\nNative LXC — runs Python + Postgres directly, no Docker.\n" \
        13 60 2 \
        "1" "Quick Setup  (recommended — 1GB RAM, 2 vCPU, 6GB)" \
        "2" "Advanced     (customize resources and network)" \
        3>&1 1>&2 2>&3
}

advanced_settings() {
    CT_HOSTNAME=$(whiptail --inputbox "Hostname" 8 58 "$CT_HOSTNAME" \
        --title "Hostname" 3>&1 1>&2 2>&3)

    CT_RAM=$(whiptail --inputbox \
        "RAM in MB\n\nMinimum: 512\nRecommended: 1024\nComfortable: 2048" \
        10 58 "$CT_RAM" --title "Memory" 3>&1 1>&2 2>&3)

    CT_CPU=$(whiptail --inputbox "CPU cores" 8 58 "$CT_CPU" \
        --title "CPU" 3>&1 1>&2 2>&3)

    CT_DISK_SIZE=$(whiptail --inputbox "Disk (GB)" 8 58 "$CT_DISK_SIZE" \
        --title "Disk" 3>&1 1>&2 2>&3)

    CT_NET_IP=$(whiptail --inputbox \
        "IP address (CIDR) or 'dhcp'\nExample: 192.168.1.50/24" \
        9 58 "$CT_NET_IP" --title "Network IP" 3>&1 1>&2 2>&3)

    if [[ "$CT_NET_IP" != "dhcp" ]]; then
        CT_NET_GW=$(whiptail --inputbox "Gateway" 8 58 "" \
            --title "Gateway" 3>&1 1>&2 2>&3)
    fi

    CT_ONBOOT=$(whiptail --title "Start on Boot" --menu "" 9 40 2 \
        "1" "Yes (recommended)" "0" "No" \
        3>&1 1>&2 2>&3)
}

get_template() {
    local TS
    TS=$(pvesm status -content vztmpl | awk 'NR>1{print $1}' | head -1)
    [[ -z "$TS" ]] && msg_error "No template storage found."

    TMPL=$(pveam list "$TS" | grep "debian-12-standard" | sort -r | head -1 | awk '{print $1}')
    if [[ -z "$TMPL" ]]; then
        msg_info "Downloading Debian 12 template..."
        pveam update >/dev/null 2>&1
        DL=$(pveam available --section system \
            | grep "debian-12-standard" | sort -r | head -1 | awk '{print $2}')
        pveam download "$TS" "$DL" | grep -v "^$" || true
        TMPL="${TS}:vztmpl/${DL}"
    fi
    echo "$TMPL"
}

create_container() {
    local CTID=$1 STORAGE=$2 TEMPLATE=$3 PASSWORD=$4

    local NET="name=eth0,bridge=${CT_NET_BRIDGE}"
    [[ "$CT_NET_IP" == "dhcp" ]] && NET="${NET},ip=dhcp" \
        || NET="${NET},ip=${CT_NET_IP}${CT_NET_GW:+,gw=${CT_NET_GW}}"

    msg_info "Creating unprivileged LXC ${CTID}..."
    pct create "$CTID" "$TEMPLATE" \
        --hostname   "$CT_HOSTNAME" \
        --password   "$PASSWORD" \
        --unprivileged 1 \
        --cores      "$CT_CPU" \
        --memory     "$CT_RAM" \
        --rootfs     "${STORAGE}:${CT_DISK_SIZE}" \
        --net0       "$NET" \
        --onboot     "$CT_ONBOOT" \
        --ostype     "$CT_OS" \
        --tags       "circuitbreaker,homelab,native" \
        --description "Circuit Breaker v${VAR_VERSION}
Stack: Python 3.11 + Postgres 15 + nginx (native, no Docker)
Update: pct exec ${CTID} -- cb-update
Logs:   pct exec ${CTID} -- journalctl -u circuitbreaker -f
GitHub: https://github.com/BlkLeg/CircuitBreaker" \
        >/dev/null
    msg_ok "Container ${CTID} created (unprivileged, no special features)"
}

provision_container() {
    local CTID=$1
    msg_info "Starting container..."
    pct start "$CTID"
    sleep 4

    msg_info "Waiting for network..."
    local T=0
    until pct exec "$CTID" -- ping -c1 8.8.8.8 >/dev/null 2>&1; do
        T=$((T+1)); [[ $T -ge 20 ]] && msg_error "No network in CT. Check vmbr0."
        sleep 3
    done
    msg_ok "Network ready"

    msg_info "Provisioning Circuit Breaker (native Python + Postgres)..."
    pct exec "$CTID" -- bash -c \
        "wget -qLO /tmp/cb-install.sh '${INSTALL_SCRIPT}' \
        && chmod +x /tmp/cb-install.sh \
        && bash /tmp/cb-install.sh \
        && rm /tmp/cb-install.sh"
    msg_ok "Provisioning complete"
}

get_ct_ip() {
    pct exec "$1" -- \
        bash -c "ip -4 addr show eth0 2>/dev/null | awk '/inet/{print \$2}' | cut -d/ -f1" \
        || echo "check-proxmox-ui"
}

main() {
    header_info
    command -v pct   >/dev/null || msg_error "Must run on Proxmox VE host."
    command -v pvesm >/dev/null || msg_error "Must run on Proxmox VE host."

    MODE=$(choose_mode)
    [[ "$MODE" == "2" ]] && advanced_settings

    CTID=$(get_next_id)
    STORAGE=$(get_storage)
    TEMPLATE=$(get_template)
    PASSWORD=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 20)

    whiptail --backtitle "Circuit Breaker LXC" \
        --title "Confirm" --yesno "
  Container ID : ${CTID}
  Hostname     : ${CT_HOSTNAME}
  RAM          : ${CT_RAM} MB
  CPU          : ${CT_CPU} vCPU
  Disk         : ${CT_DISK_SIZE} GB
  Network      : ${CT_NET_IP}
  Storage      : ${STORAGE}
  Stack        : Python + Postgres + nginx (native)
  No Docker    : yes

  Create container?" 18 54 \
        || { echo "Aborted."; exit 0; }

    create_container "$CTID" "$STORAGE" "$TEMPLATE" "$PASSWORD"
    provision_container "$CTID"

    # Save creds on Proxmox host
    CT_IP=$(get_ct_ip "$CTID")
    CREDS="/root/circuitbreaker-${CTID}.creds"
    cat > "$CREDS" <<EOF
Circuit Breaker — ${CT_HOSTNAME} (CT ${CTID})
Created : $(date)
Stack   : Python 3.11 + Postgres 15 + nginx (native LXC)
Root pw : ${PASSWORD}
Web UI  : https://${CT_IP}
API     : https://${CT_IP}/api/v1/health
Update  : pct exec ${CTID} -- cb-update
Logs    : pct exec ${CTID} -- journalctl -u circuitbreaker -f
EOF
    chmod 600 "$CREDS"

    echo ""
    echo -e " ${BGN}╔═══════════════════════════════════════════╗${CL}"
    echo -e " ${BGN}║   Circuit Breaker is ready!               ║${CL}"
    echo -e " ${BGN}╚═══════════════════════════════════════════╝${CL}"
    echo ""
    echo -e "  ${BOLD}Open:${CL}    https://${CT_IP}"
    echo -e "  ${BOLD}Console:${CL} pct exec ${CTID} -- bash"
    echo -e "  ${BOLD}Logs:${CL}    pct exec ${CTID} -- journalctl -u circuitbreaker -f"
    echo -e "  ${BOLD}Update:${CL}  pct exec ${CTID} -- cb-update"
    echo -e "  ${DGN}Creds:   ${CREDS}${CL}"
    echo ""
}

main "$@"
