#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker Native Installer
# Single-file production installer for Circuit Breaker on Linux

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# Default values
CB_PORT=8088
CB_DATA_DIR=/var/lib/circuitbreaker
CB_BRANCH=main
CB_FQDN="circuitbreaker.lab"
CB_CERT_TYPE="self-signed"
CB_EMAIL=""
UNATTENDED=false
UPGRADE_MODE=false
NO_TLS=false
FORCE_DEPS=false
DOCKER_AVAILABLE=false
INSTALL_DOCKER=false

# UI Functions
cb_version() {
  cat /opt/circuitbreaker/VERSION 2>/dev/null || echo "installing"
}

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)              ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${RESET}"
}

cb_step() {
  echo -e "  ${CYAN}▸${RESET} $1..."
}

cb_ok() {
  echo -e "  ${GREEN}✓${RESET}  $1"
}

cb_warn() {
  echo -e "  ${YELLOW}⚠${RESET}  $1"
}

cb_fail() {
  echo -e "\n  ${RED}✗  ERROR: $1${RESET}"
  echo -e "  ${YELLOW}→  $2${RESET}\n"
  exit 1
}

cb_section() {
  echo -e "\n  ${BOLD}$1${RESET}"
  echo "  $(printf '─%.0s' {1..42})"
}

cb_render_template() {
  local src="$1"
  local dest="$2"
  eval "cat <<__CB_TEMPLATE_EOF__
$(cat "$src")
__CB_TEMPLATE_EOF__" > "$dest"
}



stage0_bootstrap_preflight() {
  cb_header
  cb_section "Bootstrap Pre-flight Checks"
  
  # Root check
  cb_step "Checking root privileges"
  if [[ $EUID -ne 0 ]]; then
    if command -v sudo &>/dev/null; then
      cb_step "Elevating privileges with sudo"
      exec sudo -E bash "$0" "$@"
    fi
    cb_fail "Root access required" "Run as root or install sudo"
  fi
  cb_ok "Running as root"

  # OS Detection (Minimal for git install)
  cb_step "Detecting operating system"
  if [[ ! -f /etc/os-release ]]; then
    cb_fail "Cannot detect OS" "/etc/os-release not found"
  fi
  source /etc/os-release
  OS_ID="$ID"
  
  case "$OS_ID" in
    ubuntu|debian) PKG_MGR="apt-get" ;;
    fedora|rhel|rocky|almalinux) PKG_MGR="dnf" ;;
    arch) PKG_MGR="pacman" ;;
    *) cb_fail "Unsupported OS: $OS_ID" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux, Arch" ;;
  esac
  
  # Ensure git is installed
  if ! command -v git &>/dev/null; then
    cb_step "Installing git"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      $PKG_MGR update -y -q >/dev/null 2>&1
      $PKG_MGR install -y -q git >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "pacman" ]]; then
      pacman -Sy --noconfirm --needed git >/dev/null 2>&1
    else
      $PKG_MGR install -y -q git >/dev/null 2>&1
    fi
    cb_ok "Git installed"
  fi
}


stage0_clone_repo() {
  cb_step "Cloning repository from GitHub"
  echo "    Repo: github.com/BlkLeg/CircuitBreaker"
  echo "    Branch: $CB_BRANCH"
  echo "    Location: /opt/circuitbreaker"
  
  if [[ -d /opt/circuitbreaker/.git ]]; then
    git -C /opt/circuitbreaker fetch origin >> "$LOG_FILE" 2>&1
    git -C /opt/circuitbreaker checkout "$CB_BRANCH" >> "$LOG_FILE" 2>&1
    git -C /opt/circuitbreaker pull origin "$CB_BRANCH" >> "$LOG_FILE" 2>&1
  else
    if [[ -d /opt/circuitbreaker ]] && [[ ! -d /opt/circuitbreaker/.git ]]; then
      rm -rf /opt/circuitbreaker/apps /opt/circuitbreaker/scripts
    fi
    if ! git clone --branch "$CB_BRANCH" --depth 1       https://github.com/BlkLeg/CircuitBreaker.git       /opt/circuitbreaker >> "$LOG_FILE" 2>&1; then
      cb_fail "Git clone failed" "Check: tail -50 ${LOG_FILE}"
    fi
  fi
  cb_ok "Repository cloned"
}


# Parse command-line arguments
show_help() {
  echo "Circuit Breaker Native Installer"
  echo ""
  echo "Usage: bash install.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --port <number>      HTTP port (default: 8088)"
  echo "  --fqdn <domain>      Fully qualified domain name (optional)"
  echo "  --cert-type <type>   Certificate type: self-signed or letsencrypt (default: self-signed)"
  echo "  --email <address>    Email for Let's Encrypt notifications (required if --cert-type letsencrypt)"
  echo "  --data-dir <path>    Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls             Skip TLS cert generation"
  echo "  --branch <name>      Git branch to install from (default: main)"
  echo "  --unattended         Skip all prompts, use defaults (for Proxmox LXC)"
  echo "  --upgrade            Force upgrade mode even if install not detected"
  echo "  --force-deps         Force reinstall dependencies in upgrade mode"
  echo "  --docker             Install Docker CE and enable container telemetry proxy"
  echo "  --help               Show this help message"
  echo ""
  exit 0
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --port)
      CB_PORT="$2"
      shift 2
      ;;
    --fqdn)
      CB_FQDN="$2"
      shift 2
      ;;
    --cert-type)
      CB_CERT_TYPE="$2"
      shift 2
      ;;
    --email)
      CB_EMAIL="$2"
      shift 2
      ;;
    --data-dir)
      CB_DATA_DIR="$2"
      shift 2
      ;;
    --no-tls)
      NO_TLS=true
      shift
      ;;
    --branch)
      CB_BRANCH="$2"
      shift 2
      ;;
    --unattended)
      UNATTENDED=true
      shift
      ;;
    --upgrade)
      UPGRADE_MODE=true
      shift
      ;;
    --force-deps)
      FORCE_DEPS=true
      shift
      ;;
    --docker)
      INSTALL_DOCKER=true
      shift
      ;;
    --help)
      show_help
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run with --help for usage information"
      exit 1
      ;;
  esac
done

# Global vars set during execution
PKG_MGR=""
OS_ID=""
OS_VERSION=""
ARCH=""
LOG_FILE=""
PG_BIN_DIR=""


# ============================================================================
# MAIN EXECUTION — all stage functions are defined in deploy/setup.sh
# ============================================================================

main() {
  stage0_bootstrap_preflight
  
  # Minimal IP detection for logging
  LOG_FILE="/tmp/cb-bootstrap.log"
  echo "=== Bootstrap Log ===" > "$LOG_FILE"

  stage0_clone_repo
  
  if [[ -f /opt/circuitbreaker/deploy/setup.sh ]]; then
    source /opt/circuitbreaker/deploy/setup.sh

    # Always run full preflight — sets OS_VERSION, ARCH, PG_BIN_DIR, LOG_FILE
    # (interactive prompts are skipped in upgrade mode)
    stage0_preflight

    # Merge bootstrap log into final install log
    if [[ -f /tmp/cb-bootstrap.log ]] && [[ "$LOG_FILE" != "/tmp/cb-bootstrap.log" ]]; then
      cat /tmp/cb-bootstrap.log >> "$LOG_FILE"
      rm -f /tmp/cb-bootstrap.log
    fi

    if [[ "$UPGRADE_MODE" == "true" ]]; then
      run_upgrade
      exit 0
    fi

    # Full Fresh Install Flow
    stage1_bootstrap
    stage2_dependencies
    stage4_write_systemd_units
    stage3_configure_postgres
    stage3_configure_pgbouncer
    stage3_configure_redis
    stage3_configure_nats
    stage3_configure_nginx
    stage3_configure_docker_proxy
    write_wait_for_services_script
    write_service_scripts
    stage6_setup_python
    stage7_build_frontend
    stage9_install_cb_cli
    stage8_start_services
    stage10_final_output
  else
    cb_fail "Setup scripts not found" "Check repo structure"
  fi
}

# Run main
main

