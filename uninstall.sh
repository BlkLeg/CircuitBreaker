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

# Optionally remove the data volume
echo ""
Show 3 "Data volume: $CB_VOLUME"
echo ""
echo -e "  ${aCOLOUR[4]}WARNING:${COLOUR_RESET} Deleting the volume permanently removes all your inventory"
echo -e "  data, including hardware, services, topology, and user accounts."
echo ""
printf "  Delete data volume '%s'? [y/N] " "$CB_VOLUME"
read -r REPLY < /dev/tty
echo ""

case "$REPLY" in
  [yY][eE][sS]|[yY])
    if docker volume inspect "$CB_VOLUME" >/dev/null 2>&1; then
      docker volume rm "$CB_VOLUME" >/dev/null
      Show 0 "Volume '$CB_VOLUME' deleted."
    else
      Show 3 "Volume '$CB_VOLUME' not found — may have already been removed."
    fi
    ;;
  *)
    Show 2 "Data volume retained."
    echo "  To remove it later: docker volume rm $CB_VOLUME"
    ;;
esac

echo ""
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo -e " Circuit Breaker has been uninstalled."
echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
echo ""
echo -e "  ${aCOLOUR[2]}To reinstall: curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/install.sh | bash${COLOUR_RESET}"
echo ""
