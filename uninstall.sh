#!/usr/bin/env bash
#
# Circuit Breaker Uninstaller
#
# GitHub : https://github.com/BlkLeg/circuitbreaker
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash
#   bash uninstall.sh
#

set -e

CB_CONTAINER="${CB_CONTAINER:-circuit-breaker}"
CB_VOLUME="${CB_VOLUME:-circuit-breaker-data}"
CB_IMAGE="${CB_IMAGE:-ghcr.io/blkleg/circuitbreaker:latest}"

# ─── TLS / Caddy defaults (may be overridden by tls.conf) ────────────────────
CB_CONFIG_DIR="${CB_CONFIG_DIR:-$HOME/.circuit-breaker}"
CB_CADDY_CONTAINER="cb-caddy"
CB_CADDY_DATA_VOLUME="cb-caddy-data"
CB_CADDY_CONFIG_VOLUME="cb-caddy-config"
CB_NETWORK="cb-network"
CB_HOSTNAME="circuitbreaker.local"
CB_CA_SYSTEM_NAME="circuit-breaker-caddy-ca"
CB_CA_NSS_NAME="CircuitBreaker-Caddy-CA"

# Load saved TLS config if present (written by install.sh)
if [ -f "$CB_CONFIG_DIR/tls.conf" ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      CB_HOSTNAME)            CB_HOSTNAME="$value" ;;
      CB_CADDY_CONTAINER)     CB_CADDY_CONTAINER="$value" ;;
      CB_CADDY_DATA_VOLUME)   CB_CADDY_DATA_VOLUME="$value" ;;
      CB_CADDY_CONFIG_VOLUME) CB_CADDY_CONFIG_VOLUME="$value" ;;
      CB_NETWORK)             CB_NETWORK="$value" ;;
      CB_CA_SYSTEM_NAME)      CB_CA_SYSTEM_NAME="$value" ;;
      CB_CA_NSS_NAME)         CB_CA_NSS_NAME="$value" ;;
    esac
  done < "$CB_CONFIG_DIR/tls.conf"
fi

# ─── Colors ──────────────────────────────────────────────────────────────────
COLOUR_RESET='\e[0m'
aCOLOUR=(
  '\e[38;5;154m'  # [0] green
  '\e[1m'         # [1] bold
  '\e[90m'        # [2] grey
  '\e[91m'        # [3] red
  '\e[33m'        # [4] yellow
)

Show() {
  case $1 in
    0) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[0]} OK ${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
    1) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[3]}FAILED${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2"; exit 1 ;;
    2) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[0]} INFO ${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
    3) echo -e "${aCOLOUR[2]}[${COLOUR_RESET}${aCOLOUR[4]}NOTICE${COLOUR_RESET}${aCOLOUR[2]}]${COLOUR_RESET} $2" ;;
  esac
}

echo ""
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo -e " ${aCOLOUR[1]}Circuit Breaker Uninstaller${COLOUR_RESET}"
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo ""

# Verify Docker is available
if ! command -v docker >/dev/null 2>&1; then
  Show 1 "Docker is not installed. Nothing to uninstall."
fi

# Stop the container
if docker ps --format '{{.Names}}' | grep -q "^${CB_CONTAINER}$"; then
  Show 2 "Stopping container: $CB_CONTAINER"
  docker stop "$CB_CONTAINER" >/dev/null
  Show 0 "Container stopped."
else
  Show 3 "Container '$CB_CONTAINER' is not running."
fi

# Remove the container
if docker ps -a --format '{{.Names}}' | grep -q "^${CB_CONTAINER}$"; then
  Show 2 "Removing container: $CB_CONTAINER"
  docker rm "$CB_CONTAINER" >/dev/null
  Show 0 "Container removed."
else
  Show 3 "Container '$CB_CONTAINER' not found — already removed or never installed."
fi

# Remove the data volume
echo ""
Show 3 "Data volume: $CB_VOLUME"
echo ""
echo -e "  ${aCOLOUR[4]}WARNING:${COLOUR_RESET} Deleting the volume permanently removes all your inventory"
echo -e "  data, including hardware, services, topology, and user accounts."
echo ""
printf "  Delete data volume '%s'? [Y/n] " "$CB_VOLUME"
read -r REPLY < /dev/tty
echo ""

case "$REPLY" in
  [nN][oO]|[nN])
    Show 2 "Data volume retained."
    echo "  To remove it later: docker volume rm $CB_VOLUME"
    ;;
  *)
    if docker volume inspect "$CB_VOLUME" >/dev/null 2>&1; then
      docker volume rm "$CB_VOLUME" >/dev/null
      Show 0 "Volume '$CB_VOLUME' deleted."
    else
      Show 3 "Volume '$CB_VOLUME' not found — may have already been removed."
    fi
    ;;
esac

# Remove the Docker image
echo ""
Show 3 "Docker image: $CB_IMAGE"
echo ""
printf "  Remove Docker image '%s'? [Y/n] " "$CB_IMAGE"
read -r REPLY < /dev/tty
echo ""

case "$REPLY" in
  [nN][oO]|[nN])
    Show 2 "Docker image retained."
    echo "  To remove it later: docker rmi $CB_IMAGE"
    ;;
  *)
    if docker image inspect "$CB_IMAGE" >/dev/null 2>&1; then
      if docker rmi "$CB_IMAGE" >/dev/null 2>&1; then
        Show 0 "Image '$CB_IMAGE' removed."
      else
        Show 3 "Image '$CB_IMAGE' could not be removed — it may still be in use by another container."
      fi
    else
      Show 3 "Image '$CB_IMAGE' not found — may have already been removed."
    fi
    ;;
esac

# ─── TLS / Caddy cleanup ─────────────────────────────────────────────────────
TLS_DETECTED=0
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${CB_CADDY_CONTAINER}$" \
   || [ -f "$CB_CONFIG_DIR/tls.conf" ]; then
  TLS_DETECTED=1
fi

if [[ "$TLS_DETECTED" == "1" ]]; then
  echo ""
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo -e " ${aCOLOUR[1]}TLS / Caddy Cleanup${COLOUR_RESET}"
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo ""

  # ── Caddy container ──
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CB_CADDY_CONTAINER}$"; then
    Show 2 "Stopping Caddy container: $CB_CADDY_CONTAINER"
    docker stop "$CB_CADDY_CONTAINER" >/dev/null
    Show 0 "Caddy container stopped."
  fi
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${CB_CADDY_CONTAINER}$"; then
    Show 2 "Removing Caddy container: $CB_CADDY_CONTAINER"
    docker rm "$CB_CADDY_CONTAINER" >/dev/null
    Show 0 "Caddy container removed."
  else
    Show 3 "Caddy container '$CB_CADDY_CONTAINER' not found — already removed."
  fi

  # ── Caddy volumes ──
  for vol in "$CB_CADDY_DATA_VOLUME" "$CB_CADDY_CONFIG_VOLUME"; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
      docker volume rm "$vol" >/dev/null
      Show 0 "Volume '$vol' removed."
    fi
  done

  # ── Docker network ──
  if docker network inspect "$CB_NETWORK" >/dev/null 2>&1; then
    docker network rm "$CB_NETWORK" >/dev/null 2>&1 \
      && Show 0 "Docker network '$CB_NETWORK' removed." \
      || Show 3 "Network '$CB_NETWORK' still in use — skipped."
  fi

  # ── Caddy Docker image ──
  if docker image inspect caddy:2-alpine >/dev/null 2>&1; then
    echo ""
    printf "  Remove Caddy Docker image 'caddy:2-alpine'? [Y/n] "
    read -r REPLY < /dev/tty
    echo ""
    case "$REPLY" in
      [nN][oO]|[nN])
        Show 2 "Caddy image retained."
        ;;
      *)
        docker rmi caddy:2-alpine >/dev/null 2>&1 \
          && Show 0 "Caddy image removed." \
          || Show 3 "Caddy image could not be removed."
        ;;
    esac
  fi

  # ── CA certificates and /etc/hosts ──
  echo ""
  Show 2 "Cleaning up CA certificates and /etc/hosts..."
  echo ""
  echo -e "  ${aCOLOUR[4]}The following cleanup requires root (sudo) access:${COLOUR_RESET}"
  echo -e "    • Remove CA certificate from system trust store"
  echo -e "    • Remove '${CB_HOSTNAME}' from /etc/hosts"
  echo ""
  printf "  Proceed with CA cleanup? [Y/n] "
  read -r REPLY < /dev/tty
  echo ""

  case "$REPLY" in
    [nN][oO]|[nN])
      Show 2 "CA cleanup skipped."
      echo "  You may need to manually remove:"
      echo "    • System CA cert: ${CB_CA_SYSTEM_NAME}.crt"
      echo "    • NSS cert: ${CB_CA_NSS_NAME}"
      echo "    • /etc/hosts entry for ${CB_HOSTNAME}"
      ;;
    *)
      echo -e "  ${aCOLOUR[4]}You may be prompted for your password.${COLOUR_RESET}"
      echo ""

      if sudo -v 2>/dev/null; then
        # System trust store — Fedora / RHEL
        if [ -f "/etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt" ]; then
          sudo rm -f "/etc/pki/ca-trust/source/anchors/${CB_CA_SYSTEM_NAME}.crt"
          sudo update-ca-trust 2>/dev/null
          Show 0 "Removed CA from system trust store (Fedora/RHEL)."
        # System trust store — Debian / Ubuntu
        elif [ -f "/usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt" ]; then
          sudo rm -f "/usr/local/share/ca-certificates/${CB_CA_SYSTEM_NAME}.crt"
          sudo update-ca-certificates --fresh 2>/dev/null
          Show 0 "Removed CA from system trust store (Debian/Ubuntu)."
        # System trust store — Arch
        elif [ -f "/etc/ca-certificates/trust-source/anchors/${CB_CA_SYSTEM_NAME}.crt" ]; then
          sudo rm -f "/etc/ca-certificates/trust-source/anchors/${CB_CA_SYSTEM_NAME}.crt"
          sudo trust extract-compat 2>/dev/null
          Show 0 "Removed CA from system trust store (Arch)."
        else
          Show 3 "No system CA certificate found — may have already been removed."
        fi

        # NSS database (Chrome / Brave / Chromium)
        if command -v certutil >/dev/null 2>&1 && [ -d "$HOME/.pki/nssdb" ]; then
          certutil -d sql:"$HOME/.pki/nssdb" -D -n "$CB_CA_NSS_NAME" 2>/dev/null \
            && Show 0 "Removed CA from browser trust store (NSS)." \
            || Show 3 "No NSS certificate '${CB_CA_NSS_NAME}' found."
        fi

        # /etc/hosts
        if grep -q "$CB_HOSTNAME" /etc/hosts 2>/dev/null; then
          sudo sed -i "/${CB_HOSTNAME}/d" /etc/hosts
          Show 0 "Removed '${CB_HOSTNAME}' from /etc/hosts."
        else
          Show 3 "'${CB_HOSTNAME}' not found in /etc/hosts."
        fi
      else
        Show 3 "Could not obtain sudo access. Manual cleanup required."
      fi
      ;;
  esac
fi

# ─── Config directory cleanup (API token, TLS config, etc.) ──────────────────
if [ -d "$CB_CONFIG_DIR" ]; then
  rm -rf "$CB_CONFIG_DIR"
  Show 0 "Removed config directory: $CB_CONFIG_DIR"
fi

echo ""
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo -e " Circuit Breaker has been uninstalled."
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo ""
echo -e "  ${aCOLOUR[2]}To reinstall: curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash${COLOUR_RESET}"
echo ""
echo -e "${aCOLOUR[0]}"
cat <<'BANNER'
  ░██████  ░██                               ░██   ░██    ░████████                                  ░██                           
 ░██   ░██                                         ░██    ░██    ░██                                 ░██                           
░██        ░██░██░████  ░███████  ░██    ░██ ░██░████████ ░██    ░██  ░██░████  ░███████   ░██████   ░██    ░██ ░███████  ░██░████ 
░██        ░██░███     ░██    ░██ ░██    ░██ ░██   ░██    ░████████   ░███     ░██    ░██       ░██  ░██   ░██ ░██    ░██ ░███     
░██        ░██░██      ░██        ░██    ░██ ░██   ░██    ░██     ░██ ░██      ░█████████  ░███████  ░███████  ░█████████ ░██      
 ░██   ░██ ░██░██      ░██    ░██ ░██   ░███ ░██   ░██    ░██     ░██ ░██      ░██        ░██   ░██  ░██   ░██ ░██        ░██      
  ░██████  ░██░██       ░███████   ░█████░██ ░██    ░████ ░█████████  ░██       ░███████   ░█████░██ ░██    ░██ ░███████  ░██      

BANNER
echo -e "${COLOUR_RESET}"
