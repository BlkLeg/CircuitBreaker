#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker Native Installer
# Downloads a pre-built bundle from GitHub Releases and installs it.
# Usage: curl -fsSL https://github.com/BlkLeg/CircuitBreaker/releases/latest/download/install.sh | bash

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# GitHub repo for release downloads
CB_GITHUB_REPO="BlkLeg/CircuitBreaker"
CB_RELEASE_API="https://api.github.com/repos/${CB_GITHUB_REPO}/releases"

# Default values
CB_PORT=8088
CB_DATA_DIR=/var/lib/circuitbreaker
CB_FQDN="circuitbreaker.lab"
CB_CERT_TYPE="self-signed"
CB_EMAIL=""
CB_VERSION=""
CB_LOCAL_BUNDLE=""
UNATTENDED=false
UPGRADE_MODE=false
NO_TLS=false
FORCE_DEPS=false
DOCKER_AVAILABLE=false
INSTALL_DOCKER=true
SKIP_CHECKSUM=false

# UI Functions
cb_version() {
  cat /opt/circuitbreaker/share/VERSION 2>/dev/null || echo "installing"
}

cb_header() {
  clear
  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)                 ║"
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
  if [[ -n "${2:-}" ]]; then
    echo -e "  ${YELLOW}→  $2${RESET}"
  fi
  if [[ ${#CB_STAGE_HINTS[@]} -gt 0 ]]; then
    echo -e "\n  ${BOLD}Debug steps:${RESET}"
    local _hint_i=1
    for _hint in "${CB_STAGE_HINTS[@]}"; do
      echo -e "    ${DIM}${_hint_i}.${RESET} ${_hint}"
      (( _hint_i++ ))
    done
  fi
  echo ""
  exit 1
}

# Hint array populated before each major stage; cleared on success
CB_STAGE_HINTS=()

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

  # Privilege confirmation
  cb_step "Checking privileges"
  if [[ $EUID -ne 0 ]]; then
    cb_fail "Root privileges required" "Run with: sudo bash install.sh"
  fi
  cb_ok "Running as root"

  # OS Detection
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
  cb_ok "OS: $OS_ID ($PKG_MGR)"

  # Architecture detection
  cb_step "Detecting architecture"
  case "$(uname -m)" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    *) cb_fail "Unsupported architecture: $(uname -m)" "Supported: x86_64, aarch64" ;;
  esac
  cb_ok "Architecture: $(uname -m) ($ARCH)"

  # Ensure curl and jq are installed (needed for bundle download)
  cb_step "Checking required tools"
  local need_install=false
  for tool in curl jq; do
    if ! command -v "$tool" &>/dev/null; then
      need_install=true
      break
    fi
  done

  if [[ "$need_install" == "true" ]]; then
    cb_step "Installing curl and jq"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      $PKG_MGR update -y -q >/dev/null 2>&1
      $PKG_MGR install -y -q curl jq >/dev/null 2>&1
    elif [[ "$PKG_MGR" == "pacman" ]]; then
      pacman -Sy --noconfirm --needed curl jq >/dev/null 2>&1
    else
      $PKG_MGR install -y -q curl jq >/dev/null 2>&1
    fi
  fi
  cb_ok "curl and jq available"
}


stage0_download_bundle() {
  cb_section "Downloading Circuit Breaker Bundle"

  if [[ -n "$CB_LOCAL_BUNDLE" ]]; then
    # Local bundle mode (Proxmox helper pre-downloaded it)
    cb_step "Using local bundle"
    if [[ ! -f "$CB_LOCAL_BUNDLE" ]]; then
      cb_fail "Local bundle not found" "$CB_LOCAL_BUNDLE"
    fi
    CB_BUNDLE_TARBALL="$CB_LOCAL_BUNDLE"
    cb_ok "Local bundle: $CB_LOCAL_BUNDLE"
  else
    # Query GitHub for release
    cb_step "Querying GitHub for release"
    local release_json
    if [[ -n "$CB_VERSION" ]]; then
      release_json=$(curl -fsSL "${CB_RELEASE_API}/tags/v${CB_VERSION}" 2>/dev/null) \
        || cb_fail "Release v${CB_VERSION} not found" "Check: https://github.com/${CB_GITHUB_REPO}/releases"
    else
      release_json=$(curl -fsSL "${CB_RELEASE_API}/latest" 2>/dev/null) \
        || cb_fail "Failed to fetch latest release" "Check internet connectivity"
    fi

    CB_VERSION=$(echo "$release_json" | jq -r '.tag_name' | tr -d v)
    if [[ -z "$CB_VERSION" ]] || [[ "$CB_VERSION" == "null" ]]; then
      cb_fail "Failed to parse release version" "GitHub API may be rate-limited"
    fi
    cb_ok "Release: v${CB_VERSION}"

    local tarball_name="circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz"
    local tarball_url
    tarball_url=$(echo "$release_json" | jq -r ".assets[] | select(.name==\"${tarball_name}\") | .browser_download_url")
    if [[ -z "$tarball_url" ]] || [[ "$tarball_url" == "null" ]]; then
      cb_fail "Bundle not found for ${ARCH}" "Asset ${tarball_name} missing from release v${CB_VERSION}"
    fi

    cb_step "Downloading ${tarball_name}"
    curl -fsSL -o "/tmp/${tarball_name}" "$tarball_url" \
      || cb_fail "Download failed" "$tarball_url"
    cb_ok "Downloaded $(du -h "/tmp/${tarball_name}" | cut -f1)"

    # Verify checksum if available
    local checksum_url="${tarball_url}.sha256"
    if [[ "$SKIP_CHECKSUM" == "true" ]]; then
      cb_warn "Skipping SHA256 verification (--skip-checksum)"
    elif curl -fsSL -o "/tmp/${tarball_name}.sha256" "$checksum_url" 2>/dev/null; then
      cb_step "Verifying checksum"
      if (cd /tmp && sha256sum -c "${tarball_name}.sha256" >/dev/null 2>&1); then
        cb_ok "SHA256 checksum verified"
      else
        rm -f "/tmp/${tarball_name}.sha256"
        cb_fail "SHA256 mismatch — bundle may be corrupted or tampered" \
          "Use --skip-checksum to bypass (only for trusted local bundles)"
      fi
      rm -f "/tmp/${tarball_name}.sha256"
    fi

    CB_BUNDLE_TARBALL="/tmp/${tarball_name}"
  fi

  # Extract bundle
  cb_step "Extracting bundle"
  rm -rf /tmp/cb-bundle
  mkdir -p /tmp/cb-bundle
  tar -xzf "$CB_BUNDLE_TARBALL" -C /tmp/cb-bundle
  CB_BUNDLE_DIR="/tmp/cb-bundle"
  cb_ok "Bundle extracted"
}


stage0_install_bundle() {
  cb_section "Installing Bundle"

  # Create target directory structure
  mkdir -p /opt/circuitbreaker/bin
  mkdir -p /opt/circuitbreaker/share
  mkdir -p /opt/circuitbreaker/deploy
  mkdir -p /opt/circuitbreaker/scripts

  # Copy binary
  cb_step "Installing binary"
  cp -f "${CB_BUNDLE_DIR}/circuit-breaker" /opt/circuitbreaker/bin/circuit-breaker
  chmod 755 /opt/circuitbreaker/bin/circuit-breaker
  chown root:root /opt/circuitbreaker/bin/circuit-breaker
  cb_ok "Binary installed to /opt/circuitbreaker/bin/"

  # Copy share assets (frontend, backend/migrations, VERSION, etc.)
  cb_step "Installing application assets"
  cp -rf "${CB_BUNDLE_DIR}/share/." /opt/circuitbreaker/share/
  chown -R root:root /opt/circuitbreaker/share/
  chmod -R 755 /opt/circuitbreaker/share/
  cb_ok "Assets installed to /opt/circuitbreaker/share/"

  # Copy deploy infrastructure (config templates, systemd, nginx, cli)
  if [[ -d "${CB_BUNDLE_DIR}/deploy" ]]; then
    cp -rf "${CB_BUNDLE_DIR}/deploy/." /opt/circuitbreaker/deploy/
    chown -R root:root /opt/circuitbreaker/deploy/
    cb_ok "Deploy templates installed"
  fi

  # Cleanup
  rm -rf /tmp/cb-bundle
  if [[ -z "$CB_LOCAL_BUNDLE" ]] && [[ -n "${CB_BUNDLE_TARBALL:-}" ]]; then
    rm -f "$CB_BUNDLE_TARBALL"
  fi
}


# Parse command-line arguments
show_help() {
  echo "Circuit Breaker Native Installer"
  echo ""
  echo "Usage: bash install.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --port <number>        HTTP port (default: 8088)"
  echo "  --fqdn <domain>        Fully qualified domain name (optional)"
  echo "  --cert-type <type>     Certificate type: self-signed or letsencrypt (default: self-signed)"
  echo "  --email <address>      Email for Let's Encrypt notifications"
  echo "  --data-dir <path>      Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls               Skip TLS cert generation"
  echo "  --version <version>    Install specific version (default: latest)"
  echo "  --local-bundle <path>  Use a pre-downloaded bundle tarball"
  echo "  --unattended           Skip all prompts, use defaults (for Proxmox LXC)"
  echo "  --upgrade              Force upgrade mode even if install not detected"
  echo "  --force-deps           Force reinstall dependencies in upgrade mode"
  echo "  --docker               Install Docker CE and enable container telemetry proxy"
  echo "  --skip-checksum        Skip SHA256 bundle verification (for air-gapped or local bundle use)"
  echo "  --help                 Show this help message"
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
    --version)
      CB_VERSION="$2"
      shift 2
      ;;
    --local-bundle)
      CB_LOCAL_BUNDLE="$2"
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
    --skip-checksum)
      SKIP_CHECKSUM=true
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
CB_BUNDLE_TARBALL=""
CB_BUNDLE_DIR=""


# ============================================================================
# MAIN EXECUTION — all stage functions are defined in deploy/setup.sh
# ============================================================================

main() {
  stage0_bootstrap_preflight

  LOG_FILE="/tmp/cb-bootstrap.log"
  echo "=== Bootstrap Log ===" > "$LOG_FILE"

  stage0_download_bundle
  stage0_install_bundle

  if [[ -f /opt/circuitbreaker/deploy/setup.sh ]]; then
    source /opt/circuitbreaker/deploy/setup.sh

    # Always run full preflight — sets OS_VERSION, ARCH, PG_BIN_DIR, LOG_FILE
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
    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "Retry: bash install.sh --unattended"
    )
    stage1_bootstrap
    CB_STAGE_HINTS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "Check internet: curl -I https://github.com"
      "Retry with fresh deps: bash install.sh --force-deps"
      "Manual package check: ${PKG_MGR} install -y postgresql-15 redis nginx pgbouncer"
    )
    stage2_dependencies
    CB_STAGE_HINTS=()

    stage4_write_systemd_units

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "PostgreSQL status: systemctl status circuitbreaker-postgres"
      "PostgreSQL logs: journalctl -u circuitbreaker-postgres -n 30"
      "Check disk space: df -h ${CB_DATA_DIR}"
      "Retry: bash install.sh --force-deps"
    )
    stage3_configure_postgres
    CB_STAGE_HINTS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "pgbouncer status: systemctl status circuitbreaker-pgbouncer"
      "pgbouncer logs: journalctl -u circuitbreaker-pgbouncer -n 30"
    )
    stage3_configure_pgbouncer
    CB_STAGE_HINTS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "Redis status: systemctl status circuitbreaker-redis"
      "Redis logs: journalctl -u circuitbreaker-redis -n 30"
      "Port check: ss -tlnp | grep 6379"
    )
    stage3_configure_redis
    CB_STAGE_HINTS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "NATS status: systemctl status circuitbreaker-nats"
      "NATS logs: journalctl -u circuitbreaker-nats -n 30"
      "NATS binary: ls -la /opt/circuitbreaker/bin/nats-server"
    )
    stage3_configure_nats
    CB_STAGE_HINTS=()

    stage3_configure_nginx
    stage3_configure_docker_proxy
    write_wait_for_services_script
    write_service_scripts
    stage6_apply_binary
    stage9_install_cb_cli

    CB_STAGE_HINTS=(
      "Service status: systemctl status circuitbreaker.target"
      "All CB logs: journalctl -u 'circuitbreaker-*' --no-pager -n 50"
      "Check config: cat /etc/circuitbreaker/.env"
      "Manual start: systemctl start circuitbreaker.target"
    )
    stage8_start_services
    CB_STAGE_HINTS=()

    stage10_final_output
  else
    cb_fail "Setup scripts not found" "Check bundle structure at /opt/circuitbreaker/deploy/"
  fi
}

# Run main
main
