#!/usr/bin/env bash
# deploy/native/uninstall.sh — Circuit Breaker Native Uninstaller
# Usage: sudo bash deploy/native/uninstall.sh
set -euo pipefail

# ── Colors / helpers ─────────────────────────────────────────────────────────
RESET="\033[0m"; BOLD="\033[1m"; GREEN="\033[32m"
ORANGE="\033[33m"; RED="\033[31m"; DIM="\033[2m"; CYAN="\033[36m"

ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
info() { echo -e "  ${CYAN}→${RESET} $*"; }
warn() { echo -e "  ${ORANGE}⚠${RESET} $*"; }
die()  { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

# ── Constants ────────────────────────────────────────────────────────────────
CB_APP_ROOT="/opt/circuitbreaker"
CB_CONFIG_DIR="/etc/circuitbreaker"
CB_DATA_DIR="/var/lib/circuitbreaker"
CB_LOG_DIR="/var/log/circuitbreaker"
CB_USER="breaker"

# ── Banner ───────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${RED}"
cat <<'BANNER'
   ___  _                   _ _   ___
  / __\(_)_ __ ___ _   _(_) |_  / __\_ __ ___  __ _| | _____ _ __
 / /   | | '__/ __| | | | | __| /__\// '__/ _ \/ _` | |/ / _ \ '__|
/ /____| | | | (__| |_| | | |_/ \/  \ | |  __/ (_| |   <  __/ |
\______|_|_|  \___|\__,_|_|\__\_____/_|  \___|\__,_|_|\_\___|_|
BANNER
echo -e "${RESET}"
echo -e "  ${BOLD}Native Uninstaller${RESET}"
echo

# ── Step 1: Check privileges ────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  die "This script must be run as root. Try: sudo bash $0"
fi
ok "Running as root"

# ── Step 2: Confirm ─────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}${RED}WARNING:${RESET} This will remove Circuit Breaker from this system."
echo -e "  ${DIM}The following will be removed:${RESET}"
echo -e "    ${DIM}- Systemd services (circuitbreaker.target and all sub-services)${RESET}"
echo -e "    ${DIM}- Application files at ${CB_APP_ROOT}${RESET}"
echo -e "    ${DIM}- Configuration at ${CB_CONFIG_DIR}${RESET}"
echo -e "    ${DIM}- Log files at ${CB_LOG_DIR}${RESET}"
echo
read -rp "  Are you sure you want to uninstall Circuit Breaker? [y/N] " CONFIRM
case "${CONFIRM}" in
  [yY]|[yY][eE][sS]) ;;
  *) echo; info "Uninstall cancelled."; exit 0 ;;
esac

echo

# ── Step 3: Stop and disable services ───────────────────────────────────────
info "Stopping services..."
systemctl stop circuitbreaker.target 2>/dev/null || true
sleep 2

info "Disabling services..."
systemctl disable circuitbreaker.target 2>/dev/null || true

# Also clean up any old hyphenated services
systemctl disable --now circuit-breaker.service circuit-breaker-native.service 2>/dev/null || true

ok "Services stopped and disabled"

# ── Step 4: Remove systemd units ────────────────────────────────────────────
info "Removing systemd unit files..."
rm -f /etc/systemd/system/circuitbreaker*.service \
      /etc/systemd/system/circuitbreaker*.target \
      /etc/systemd/system/circuitbreaker-worker@.service \
      2>/dev/null || true

# Also remove old hyphenated units
rm -f /etc/systemd/system/circuit-breaker* 2>/dev/null || true

systemctl daemon-reload
ok "Systemd units removed"

# ── Step 5: Remove application files ────────────────────────────────────────
if [ -d "$CB_APP_ROOT" ]; then
  info "Removing application files at ${CB_APP_ROOT}..."
  rm -rf "$CB_APP_ROOT"
  ok "Application files removed"
else
  info "Application directory ${CB_APP_ROOT} not found — skipping"
fi

# ── Step 6: Optionally remove data ──────────────────────────────────────────
if [ -d "$CB_DATA_DIR" ]; then
  echo
  echo -e "  ${BOLD}${ORANGE}Data directory:${RESET} ${CB_DATA_DIR}"
  echo -e "  ${DIM}Contains: database, uploads, backups, certificates${RESET}"
  read -rp "  Remove all data? This cannot be undone! [y/N] " REMOVE_DATA
  case "${REMOVE_DATA}" in
    [yY]|[yY][eE][sS])
      rm -rf "$CB_DATA_DIR"
      ok "Data directory removed"
      ;;
    *)
      info "Data directory preserved at ${CB_DATA_DIR}"
      ;;
  esac
fi

# ── Step 7: Remove log files ────────────────────────────────────────────────
if [ -d "$CB_LOG_DIR" ]; then
  rm -rf "$CB_LOG_DIR"
  ok "Log directory removed"
fi

# ── Step 8: Remove configuration ────────────────────────────────────────────
if [ -d "$CB_CONFIG_DIR" ]; then
  rm -rf "$CB_CONFIG_DIR"
  ok "Configuration directory removed"
fi

# Also remove old hyphenated config
if [ -d "/etc/circuit-breaker" ]; then
  rm -rf "/etc/circuit-breaker"
  ok "Legacy config directory /etc/circuit-breaker removed"
fi

# ── Step 9: Remove CLI symlink ──────────────────────────────────────────────
if [ -f /usr/local/bin/cb ] || [ -L /usr/local/bin/cb ]; then
  rm -f /usr/local/bin/cb
  ok "CLI symlink /usr/local/bin/cb removed"
fi

# ── Step 10: Optionally remove user ─────────────────────────────────────────
if id "$CB_USER" &>/dev/null; then
  echo
  read -rp "  Remove system user '${CB_USER}'? [y/N] " REMOVE_USER
  case "${REMOVE_USER}" in
    [yY]|[yY][eE][sS])
      userdel -r "$CB_USER" 2>/dev/null || userdel "$CB_USER" 2>/dev/null || true
      ok "User '${CB_USER}' removed"
      ;;
    *)
      info "User '${CB_USER}' preserved"
      ;;
  esac
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${BOLD}${GREEN}Circuit Breaker has been uninstalled.${RESET}"
echo
echo -e "  ${DIM}System packages (postgresql, nginx, redis, etc.) were NOT removed.${RESET}"
echo -e "  ${DIM}Remove them manually if no longer needed:${RESET}"
echo -e "    ${DIM}sudo apt purge postgresql pgbouncer redis-server nginx${RESET}"
echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo
