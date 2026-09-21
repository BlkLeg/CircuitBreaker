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

# ─── Non-interactive consent ─────────────────────────────────────────────────
#
# Every prompt in this script reads from /dev/tty, and the preflight below
# refuses to start when no terminal can answer them. That is correct for a
# human running `curl ... | bash`, and it makes the uninstaller unrunnable by
# anything else — including the installer journey, which is why the most
# prominently documented removal path had never been executed by CI.
#
# These two flags are consent expressed on the command line rather than at a
# prompt. There is deliberately no bare `--unattended`: the only questions this
# script asks are "may I delete your data?", so a non-interactive run has to say
# which answer it is giving. Passing neither leaves the interactive behaviour
# exactly as it was.
CB_UNATTENDED=false
CB_PURGE_DATA=false

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge)
      CB_UNATTENDED=true
      CB_PURGE_DATA=true
      ;;
    --keep-data)
      CB_UNATTENDED=true
      CB_PURGE_DATA=false
      ;;
    -h|--help)
      echo "Usage: bash uninstall.sh [--purge | --keep-data]"
      echo ""
      echo "  --purge      Remove everything, including configuration and data."
      echo "               Implies non-interactive: no prompt is shown."
      echo "  --keep-data  Remove the software, retain /etc/circuitbreaker,"
      echo "               /var/lib/circuitbreaker and the Docker data volume."
      echo "               Implies non-interactive."
      echo ""
      echo "  With neither flag the uninstaller is interactive and asks before"
      echo "  removing anything irreversible."
      exit 0
      ;;
    *)
      echo "uninstall.sh: unknown option '$1'" >&2
      echo "Run 'bash uninstall.sh --help' for usage." >&2
      exit 2
      ;;
  esac
  shift
done

# Answers a y/N prompt from the flags when running non-interactively, and from
# /dev/tty otherwise. Callers branch on the value exactly as they did when every
# read was inline, so consent is still explicit at each site.
cb_confirm_destructive() {
  local prompt="$1"
  if [ "$CB_UNATTENDED" = "true" ]; then
    if [ "$CB_PURGE_DATA" = "true" ]; then
      echo "  ${prompt} [--purge] yes"
      REPLY="y"
    else
      echo "  ${prompt} [--keep-data] no"
      REPLY="n"
    fi
    return 0
  fi
  printf "  %s [y/N] " "$prompt"
  read -r REPLY < /dev/tty
}

# The other half: prompts whose subject is recoverable — a Docker image that
# re-pulls, a local CA that re-issues — and which therefore default to yes. A
# non-interactive run takes that default whichever data flag was given, because
# neither flag is about images or certificates.
cb_confirm_cleanup() {
  local prompt="$1"
  if [ "$CB_UNATTENDED" = "true" ]; then
    echo "  ${prompt} [non-interactive] yes"
    REPLY="y"
    return 0
  fi
  printf "  %s [Y/n] " "$prompt"
  read -r REPLY < /dev/tty
}

# ─── sudo on hosts that do not have it ───────────────────────────────────────
#
# Every privileged step below calls `sudo`, which is the right shape for the
# advertised invocation (a non-root operator running the script). It is absent
# from the debian:12 and fedora base images the installer journey runs in, and
# on those the script is already root — so `sudo rm -rf /opt/circuitbreaker`
# died with "command not found" partway through a removal it had already
# started. Only defined when it is both missing and unnecessary; where a real
# sudo exists, that is what runs.
if [ "$(id -u)" -eq 0 ] && ! command -v sudo >/dev/null 2>&1; then
  sudo() { "$@"; }
fi

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

# ─── Progress rendering ──────────────────────────────────────────────────────
#
# Same renderer as the installer. The bundle's copy at
# /opt/circuitbreaker/deploy/lib/ui.sh is authoritative; a standalone
# uninstall.sh downloaded on its own (this script is also served raw and
# curl-piped — docs/installation/uninstalling.md:98) has no bundle to read, and
# every call below goes through _cb_phase so that absence degrades to plain
# Show() output rather than a missing-command error.
if [[ -r /opt/circuitbreaker/deploy/lib/ui.sh ]]; then
  # shellcheck source=deploy/lib/ui.sh
  source /opt/circuitbreaker/deploy/lib/ui.sh
  cb_ui_init
  cb_ui_use_weights CB_PHASE_WEIGHTS_UNINSTALL
fi

# Calls a ui.sh function only if the library was sourced above. Keeps every
# phase/teardown call site identical whether or not the bundle is present, so
# a bare `curl ... | bash` uninstall (no /opt/circuitbreaker) still runs clean
# with no renderer at all.
_cb_phase() { declare -f "$1" >/dev/null 2>&1 && "$@"; return 0; }

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

_cb_phase cb_phase_begin preflight "Pre-flight checks"

# ─── What is actually installed here ─────────────────────────────────────────
#
# Three layouts, and this script used to know about two of them.
#
#   docker   — the container, its volume and Caddy.
#   package  — the deb/rpm layout: /usr/local/bin/circuit-breaker,
#              circuit-breaker.service, /etc/circuit-breaker.
#   native   — what install.sh creates: /opt/circuitbreaker, the
#              circuitbreaker-* units, /etc/circuitbreaker, the breaker user.
#
# The third was invisible. Its paths differ from the packaged ones by a single
# hyphen, and every test of the native section matched only the packaged
# spelling — so `bash uninstall.sh` after `bash install.sh` skipped the whole
# section and left a running deployment behind, reporting success. The
# installer journey now uninstalls what it installed, which is what makes this
# checkable rather than merely written down.
CB_HAS_NATIVE=false
if [ -d /opt/circuitbreaker ] || [ -f /etc/systemd/system/circuitbreaker-backend.service ]; then
  CB_HAS_NATIVE=true
fi

CB_HAS_PACKAGE=false
if [ -f /usr/local/bin/circuit-breaker ] || [ -f /etc/systemd/system/circuit-breaker.service ]; then
  CB_HAS_PACKAGE=true
fi

# Docker is a requirement of the docker layout, not of this script. A native
# install does not need it — install.sh treats container telemetry as optional
# and carries on when Docker cannot be installed — so refusing here made the
# uninstaller unusable on exactly the hosts the native path targets.
if ! command -v docker >/dev/null 2>&1; then
  if [ "$CB_HAS_NATIVE" = "false" ] && [ "$CB_HAS_PACKAGE" = "false" ]; then
    Show 1 "Docker is not installed and no native or packaged install was found. Nothing to uninstall."
  fi
  Show 2 "Docker is not installed — skipping container cleanup."
  docker() { return 1; }
fi

# ─── Interactive terminal preflight ──────────────────────────────────────────
#
# Every prompt below reads from /dev/tty rather than from stdin, and that is
# deliberate: the advertised invocation is `curl ... | bash`, where stdin is the
# downloaded script itself, so a read from stdin would swallow the rest of the
# source. But /dev/tty only resolves for a process that has a controlling
# terminal. Under cron, a CI runner, `ssh host '...'` without -t, or a
# `docker run` without -t, the open returns ENXIO, `read` returns non-zero, and
# `set -e` ends the script on the spot.
#
# The spot it ended at was the *first* prompt — which is below the container
# stop and the container removal. The operator got exit 1, one line of bash's
# own stderr, and a host that still had the image, Caddy, the config directory
# and /usr/local/bin/cb on it. Through a pipe with stderr discarded that is an
# uninstaller which appears to do nothing and in fact half-uninstalled the
# product. So ask "can this process be asked anything at all?" here, before the
# first destructive step, rather than discovering it after.
#
# This does NOT relax the prompts themselves. An operator who has a terminal and
# answers nothing — EOF on the read, a pipe that closes mid-run — must still
# abort rather than fall through to a destructive default; no answer is not
# consent. This preflight is only about the case where no answer was ever
# possible.
#
# The test has to be a real open. `[ -r /dev/tty ]` is not one: /dev/tty is a
# 0666 device node present on every host, so access(2) answers yes even when
# there is no controlling terminal to attach it to and the open(2) that follows
# returns ENXIO. `true < /dev/tty` performs the same open the reads will.
# The 2>/dev/null must come *before* the redirection it is silencing — bash
# applies redirections left to right, so with the order reversed the failure
# message is written to a stderr that has not been redirected yet.
# --purge / --keep-data answer every prompt up front, so there is nothing left
# to ask and no terminal to need. The preflight still applies to every run that
# did not say which answer it is giving.
if [ "$CB_UNATTENDED" = "false" ] && ! true 2>/dev/null < /dev/tty; then
  echo ""
  Show 3 "No terminal is available to answer this uninstaller's prompts."
  echo ""
  echo "  Before removing anything, this script asks whether to delete your data"
  echo "  volume, your Docker images and your CA certificates, and it reads those"
  echo "  answers from /dev/tty. This process has no controlling terminal, so"
  echo "  none of them can be answered — and nothing has been removed."
  echo ""
  echo "  Run it attached to a terminal instead:"
  echo "    curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh -o uninstall.sh"
  echo "    bash uninstall.sh"
  echo ""
  echo "  Over ssh, allocate one with -t. The operator who reaches this message"
  echo "  got here through the piped form, so there is no uninstall.sh on the"
  echo "  remote host to run -- fetch and run it in the same command:"
  echo "    ssh -t <host> 'curl -fsSL https://raw.githubusercontent.com/BlkLeg/circuitbreaker/main/uninstall.sh | bash'"
  echo ""
  Show 1 "Uninstall aborted. Nothing was removed."
fi

_cb_phase cb_phase_end preflight

_cb_phase cb_phase_begin stop "Stopping the container"

# Stop the container
if docker ps --format '{{.Names}}' | grep -q "^${CB_CONTAINER}$"; then
  Show 2 "Stopping container: $CB_CONTAINER"
  docker stop "$CB_CONTAINER" >/dev/null
  Show 0 "Container stopped."
else
  Show 3 "Container '$CB_CONTAINER' is not running."
fi

_cb_phase cb_phase_end stop

_cb_phase cb_phase_begin remove "Removing the container"

# Remove the container
if docker ps -a --format '{{.Names}}' | grep -q "^${CB_CONTAINER}$"; then
  Show 2 "Removing container: $CB_CONTAINER"
  docker rm "$CB_CONTAINER" >/dev/null
  Show 0 "Container removed."
else
  Show 3 "Container '$CB_CONTAINER' not found — already removed or never installed."
fi

# Remove the rollback container `cb update` leaves behind.
#
# cb update renames the running container to <name>-prev before starting the
# replacement, and only removes it once the new one answers /api/v1/livez — so a
# host whose last upgrade failed, or that has no curl to poll with, still has one.
# It mounts CB_VOLUME. Docker refuses to delete a volume a container still
# references, so leaving it here made `docker volume rm` below fail, and this
# script runs under `set -e`: the uninstaller aborted immediately after the
# operator had already confirmed the irreversible data prompt, leaving the image,
# Caddy, the config directory and /usr/local/bin/cb behind with no explanation.
if docker ps -a --format '{{.Names}}' | grep -q "^${CB_CONTAINER}-prev$"; then
  Show 2 "Removing rollback container: ${CB_CONTAINER}-prev"
  docker rm -f "${CB_CONTAINER}-prev" >/dev/null
  Show 0 "Rollback container removed."
fi

_cb_phase cb_phase_end remove

_cb_phase cb_phase_begin cleanup "Removing data"
# The data-volume prompt below is extracted verbatim by
# tests/build/test_uninstall_volume_prompt.py, so nothing is inserted between
# here and its closing `esac` — the teardown call has to sit outside that span.
_cb_phase cb_ui_teardown

# Remove the data volume
echo ""
Show 3 "Data volume: $CB_VOLUME"
echo ""
echo -e "  ${aCOLOUR[4]}WARNING:${COLOUR_RESET} Deleting the volume permanently removes all your inventory"
echo -e "  data, including hardware, services, topology, and user accounts."
echo ""
# This is the only step in the uninstaller that cannot be undone. The container
# and the image both come back from a docker pull and an install.sh re-run, so
# their prompts default to yes; the volume holds the inventory, the topology, the
# user accounts and the vault key, and once docker volume rm returns there is
# nothing left to restore from. So the default here is the opposite of the ones
# below it: anything short of an explicit yes — a bare Enter, a "nope", a "No
# thanks", a stray keystroke — keeps the data. The [yY]* glob and the [y/N]
# marker match the config and data prompts in the Linux and macOS cleanup
# sections further down, which have always had this shape.
#
# Kept inline rather than routed through cb_confirm_destructive: this prompt is
# the one whose exact shape is pinned, character by character, by
# tests/build/test_uninstall_volume_prompt.py — the `[y/N]` marker, the `[yY]*`
# glob and the `< /dev/tty` read are all assertions there, and that test lifts
# this block out of the file and runs it on its own. A non-interactive run
# answers from the flags without moving the read.
if [ "${CB_UNATTENDED:-false}" = "true" ]; then
  if [ "${CB_PURGE_DATA:-false}" = "true" ]; then REPLY="y"; else REPLY="n"; fi
  echo "  Delete data volume '$CB_VOLUME'? [non-interactive] $REPLY"
else
  printf "  Delete data volume '%s'? [y/N] " "$CB_VOLUME"
  read -r REPLY < /dev/tty
fi
echo ""

case "$REPLY" in
  [yY]*)
    if docker volume inspect "$CB_VOLUME" >/dev/null 2>&1; then
      # `if !` rather than a bare call: errexit would otherwise kill the script
      # here without printing anything, at the one point where the operator has
      # just said yes to something irreversible and most needs to be told what
      # actually happened. Anything still mounting the volume keeps it alive.
      if ! docker volume rm "$CB_VOLUME" >/dev/null 2>&1; then
        Show 3 "Volume '$CB_VOLUME' is still in use and was NOT deleted."
        echo "  Something still references it. Find it with:"
        echo "    docker ps -a --filter volume=$CB_VOLUME"
        echo "  then remove that container and re-run: docker volume rm $CB_VOLUME"
      else
        Show 0 "Volume '$CB_VOLUME' deleted."
      fi
    else
      Show 3 "Volume '$CB_VOLUME' not found — may have already been removed."
    fi
    ;;
  *)
    Show 2 "Data volume retained."
    echo "  To remove it later: docker volume rm $CB_VOLUME"
    ;;
esac

_cb_phase cb_phase_end cleanup

# Remove the Docker image
echo ""
Show 3 "Docker image: $CB_IMAGE"
echo ""
_cb_phase cb_ui_teardown
cb_confirm_cleanup "$(printf "Remove Docker image '%s'?" "$CB_IMAGE")"
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
    _cb_phase cb_ui_teardown
    cb_confirm_cleanup "Remove Caddy Docker image 'caddy:2-alpine'?"
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
  _cb_phase cb_ui_teardown
  cb_confirm_cleanup "Proceed with CA cleanup?"
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

# ─── install.sh (native) cleanup ────────────────────────────────────────────
#
# The layout install.sh builds: /opt/circuitbreaker, seven circuitbreaker-*
# units plus a target, a slice, a healthcheck timer, the helper daemon, an
# nginx site and the `breaker` service account. None of it shares a path with
# the packaged layout below, which is why the section below never touched it.
#
# Ordered stop-then-remove, and idempotent throughout: every step tolerates the
# thing it removes being absent, so a re-run after a partial uninstall finishes
# the job instead of failing on the first missing file.
if [ "$CB_HAS_NATIVE" = "true" ]; then
  echo ""
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo -e " ${aCOLOUR[1]}Circuit Breaker (install.sh) Cleanup${COLOUR_RESET}"
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo ""

  # The target first, so systemd tears the tree down in dependency order rather
  # than leaving the backend talking to a database that has already gone.
  Show 2 "Stopping Circuit Breaker services..."
  sudo systemctl stop circuitbreaker.target >/dev/null 2>&1 || true
  for unit in \
    circuitbreaker-healthcheck.timer \
    circuitbreaker-healthcheck.service \
    'circuitbreaker-worker@*.service' \
    circuitbreaker-backend.service \
    circuitbreaker-docker-proxy.service \
    cb-helperd.service \
    circuitbreaker-nats.service \
    circuitbreaker-redis.service \
    circuitbreaker-pgbouncer.service \
    circuitbreaker-postgres.service; do
    # Unquoted on purpose for the worker glob: systemctl expands instance
    # templates itself only for a literal list, so the shell supplies the names.
    # shellcheck disable=SC2086
    sudo systemctl stop $unit >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    sudo systemctl disable $unit >/dev/null 2>&1 || true
  done
  sudo systemctl disable circuitbreaker.target >/dev/null 2>&1 || true
  # The slice outlives its units: removing circuitbreaker.slice's unit file
  # leaves the cgroup loaded and "active" until something stops it, so
  # `systemctl list-units 'circuitbreaker*'` still names the product on a host
  # it has been removed from.
  sudo systemctl stop circuitbreaker.slice >/dev/null 2>&1 || true
  Show 0 "Services stopped and disabled."

  Show 2 "Removing systemd units..."
  sudo rm -f \
    /etc/systemd/system/circuitbreaker-backend.service \
    /etc/systemd/system/circuitbreaker-postgres.service \
    /etc/systemd/system/circuitbreaker-pgbouncer.service \
    /etc/systemd/system/circuitbreaker-redis.service \
    /etc/systemd/system/circuitbreaker-nats.service \
    /etc/systemd/system/circuitbreaker-docker-proxy.service \
    /etc/systemd/system/circuitbreaker-healthcheck.service \
    /etc/systemd/system/circuitbreaker-healthcheck.timer \
    /etc/systemd/system/'circuitbreaker-worker@.service' \
    /etc/systemd/system/circuitbreaker.target \
    /etc/systemd/system/circuitbreaker.slice \
    /etc/systemd/system/cb-helperd.service >/dev/null 2>&1 || true
  sudo systemctl daemon-reload >/dev/null 2>&1 || true
  # Without this a unit that exited non-zero stays in `failed` forever, and
  # `systemctl status` keeps naming a service that no longer exists.
  sudo systemctl reset-failed >/dev/null 2>&1 || true
  Show 0 "systemd units removed."

  # nginx keeps serving a proxy_pass to a backend that is gone otherwise, which
  # is worse than serving nothing: the operator gets 502s from a product they
  # believe they removed.
  if [ -e /etc/nginx/sites-enabled/circuitbreaker.conf ] \
    || [ -e /etc/nginx/conf.d/circuitbreaker.conf ]; then
    Show 2 "Removing nginx site configuration..."
    sudo rm -f \
      /etc/nginx/sites-enabled/circuitbreaker.conf \
      /etc/nginx/sites-available/circuitbreaker.conf \
      /etc/nginx/conf.d/circuitbreaker.conf >/dev/null 2>&1 || true
    if sudo nginx -t >/dev/null 2>&1; then
      sudo systemctl reload nginx >/dev/null 2>&1 || true
      Show 0 "nginx configuration removed and reloaded."
    else
      Show 3 "nginx configuration removed; nginx did not reload cleanly — check: nginx -t"
    fi
  fi

  if [ -d /opt/circuitbreaker ]; then
    sudo rm -rf /opt/circuitbreaker
    Show 0 "Application directory removed (/opt/circuitbreaker)."
  fi

  if [ -f /usr/local/bin/cb ]; then
    sudo rm -f /usr/local/bin/cb
    Show 0 "cb CLI removed."
  fi

  # The installed uninstaller, unless it is the script currently running. bash
  # reads a script incrementally, so deleting the file mid-execution can leave
  # the interpreter reading from a hole; when this IS that file it stays, and
  # the operator is told so rather than finding it later and wondering.
  if [ -f /usr/local/bin/uninstall-circuit-breaker ]; then
    if [ "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || true)" = /usr/local/bin/uninstall-circuit-breaker ]; then
      Show 2 "Uninstaller retained at /usr/local/bin/uninstall-circuit-breaker (it is running now)."
      Show 2 "  Remove it with: sudo rm /usr/local/bin/uninstall-circuit-breaker"
    else
      sudo rm -f /usr/local/bin/uninstall-circuit-breaker
      Show 0 "Installed uninstaller removed."
    fi
  fi

  # Runtime state systemd owns rather than the package: left behind, the next
  # install inherits a vault.env written by a deployment that no longer exists.
  sudo rm -rf /run/circuitbreaker >/dev/null 2>&1 || true

  # Config and data, asked for separately and in that order: an operator who
  # keeps the data almost always wants the credentials that decrypt it, and
  # CB_VAULT_KEY lives in /etc/circuitbreaker/.env. Removing the config while
  # retaining the data would leave an unreadable database behind.
  if [ -d /etc/circuitbreaker ] || [ -d /var/lib/circuitbreaker ]; then
    echo ""
    _cb_phase cb_ui_teardown
    cb_confirm_destructive "Remove Circuit Breaker configuration and data (/etc/circuitbreaker, /var/lib/circuitbreaker)? This deletes the database and the vault key, and cannot be undone."
    case "$REPLY" in
      [yY]*)
        sudo rm -rf /etc/circuitbreaker /var/lib/circuitbreaker
        Show 0 "Configuration and data removed."
        # The account is only removed alongside the data it owns. Deleting it
        # while /var/lib/circuitbreaker survives would orphan every file in
        # there to a bare uid.
        if id breaker >/dev/null 2>&1; then
          sudo userdel breaker >/dev/null 2>&1 || true
          Show 0 "Service account 'breaker' removed."
        fi
        ;;
      *)
        Show 2 "Configuration retained at /etc/circuitbreaker"
        Show 2 "Data retained at /var/lib/circuitbreaker"
        ;;
    esac
  fi
fi

# ─── Native binary cleanup ──────────────────────────────────────────────────
if [ -f /usr/local/bin/circuit-breaker ] || [ -f /etc/systemd/system/circuit-breaker.service ]; then
  echo ""
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo -e " ${aCOLOUR[1]}Native Binary Cleanup${COLOUR_RESET}"
  echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
  echo ""

  # Stop systemd service
  if systemctl is-active --quiet circuit-breaker.service 2>/dev/null; then
    Show 2 "Stopping circuit-breaker service..."
    sudo systemctl stop circuit-breaker.service
    sudo systemctl disable circuit-breaker.service
    Show 0 "Service stopped and disabled."
  fi

  # Remove systemd unit
  if [ -f /etc/systemd/system/circuit-breaker.service ]; then
    sudo rm -f /etc/systemd/system/circuit-breaker.service
    sudo systemctl daemon-reload
    Show 0 "systemd unit removed."
  fi

  # Remove binary
  if [ -f /usr/local/bin/circuit-breaker ]; then
    sudo rm -f /usr/local/bin/circuit-breaker
    Show 0 "Binary removed."
  fi

  # Remove share directory
  if [ -d /usr/local/share/circuit-breaker ]; then
    sudo rm -rf /usr/local/share/circuit-breaker
    Show 0 "Share directory removed."
  fi

  # Config and data (ask first)
  echo ""
  if [ -d /etc/circuit-breaker ]; then
    _cb_phase cb_ui_teardown
    cb_confirm_destructive "Remove config (/etc/circuit-breaker)?"
    case "$REPLY" in
      [yY]*) sudo rm -rf /etc/circuit-breaker; Show 0 "Config removed." ;;
      *) Show 2 "Config retained at /etc/circuit-breaker" ;;
    esac
  fi

  if [ -d /var/lib/circuit-breaker ]; then
    _cb_phase cb_ui_teardown
    cb_confirm_destructive "Remove data (/var/lib/circuit-breaker)?"
    case "$REPLY" in
      [yY]*) sudo rm -rf /var/lib/circuit-breaker; Show 0 "Data removed." ;;
      *) Show 2 "Data retained at /var/lib/circuit-breaker" ;;
    esac
  fi
fi

# ─── macOS cleanup ──────────────────────────────────────────────────────────
if [ "$(uname -s)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/com.blkleg.circuitbreaker.plist"
  if [ -f "$PLIST" ]; then
    echo ""
    echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
    echo -e " ${aCOLOUR[1]}macOS Cleanup${COLOUR_RESET}"
    echo -e "${aCOLOUR[0]}─────────────────────────────────────────────────────${COLOUR_RESET}"
    echo ""

    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    Show 0 "launchd agent removed."

    if [ -d "$HOME/Library/Application Support/CircuitBreaker" ]; then
      _cb_phase cb_ui_teardown
      cb_confirm_destructive "Remove app data?"
      case "$REPLY" in
        [yY]*) rm -rf "$HOME/Library/Application Support/CircuitBreaker"; Show 0 "App data removed." ;;
        *) Show 2 "App data retained." ;;
      esac
    fi

    if [ -d "$HOME/.config/circuitbreaker" ]; then
      _cb_phase cb_ui_teardown
      cb_confirm_destructive "Remove config (~/.config/circuitbreaker)?"
      case "$REPLY" in
        [yY]*) rm -rf "$HOME/.config/circuitbreaker"; Show 0 "Config removed." ;;
        *) Show 2 "Config retained." ;;
      esac
    fi
  fi
fi

# ─── Config directory cleanup (API token, TLS config, install.conf, etc.) ────
if [ -d "$CB_CONFIG_DIR" ]; then
  rm -rf "$CB_CONFIG_DIR"
  Show 0 "Removed config directory: $CB_CONFIG_DIR"
fi

# ─── cb command ──────────────────────────────────────────────────────────────
if [ -f /usr/local/bin/cb ]; then
  sudo rm -f /usr/local/bin/cb
  Show 0 "Removed cb command."
fi

# Tear the live region down before this trailing banner block. cleanup is the
# last phase this script opens, and cb_phase_end re-arms the live region on
# its way out (it ends with a redraw) — so without this, the renderer's blind
# two-line rewind eats the first two lines printed below on its very next
# call, exactly like every other raw-output block above it.
_cb_phase cb_ui_teardown

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
