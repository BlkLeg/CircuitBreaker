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
# The identity file says which layout this is; the filesystem is only a
# fallback for a host that never wrote one. Since 2026-09-22 both native
# layouts install /opt/circuitbreaker, so its presence no longer distinguishes
# them — the unit names still do.
CB_IDENTITY_MODE_DETECTED=""
for _lib in /usr/local/lib/circuitbreaker/install-identity.sh /opt/circuitbreaker/deploy/lib/install-identity.sh \
            "$(dirname -- "$(readlink -f "$0")")/deploy/lib/install-identity.sh"; do
  if [ -f "$_lib" ]; then
    # shellcheck source=/dev/null
    . "$_lib"
    _identity="$(cb_find_install_identity 2>/dev/null || true)"
    if [ -n "$_identity" ] && cb_validate_install_identity_file "$_identity"; then
      CB_IDENTITY_MODE_DETECTED="$(sed -n 's/.*"mode"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$_identity" | head -n1)"
    fi
    break
  fi
done

CB_HAS_NATIVE=false
CB_HAS_PACKAGE=false
case "$CB_IDENTITY_MODE_DETECTED" in
  native|proxmox) CB_HAS_NATIVE=true ;;
  package)        CB_HAS_PACKAGE=true ;;
  *)
    [ -f /etc/systemd/system/circuitbreaker-backend.service ] || [ -f /etc/circuitbreaker/.env ] && CB_HAS_NATIVE=true
    [ -f /lib/systemd/system/circuit-breaker.service ] || [ -f /etc/systemd/system/circuit-breaker.service ] \
      || [ -f /etc/circuit-breaker/circuit-breaker.env ] && CB_HAS_PACKAGE=true
    ;;
esac

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

# ─── Host lifecycle lock ─────────────────────────────────────────────────────
#
# Removal conflicts with every other lifecycle operation — an install, an
# upgrade, a restore, a `cb` mutation, the npm coordinator's native helper —
# so it takes the one host-wide lock (deploy/lib/lifecycle.sh) before the
# first container stop below, and stops with 10 while anything else holds it.
# The library is inlined because this script is also curl-piped onto hosts
# whose deploy/lib it is about to remove, or never had. Contract:
# specs/install/lifecycle-contract.md §11.
# --- BEGIN INLINED deploy/lib/lifecycle.sh — regenerate with scripts/ci/sync_installer_ui.py ---
# shellcheck shell=bash
# Host-wide lifecycle lock and private state root.
#
# One lock serializes every lifecycle mutation on the host: the npm
# coordinator's native helper, install.sh, deploy/setup.sh, uninstall.sh,
# deploy/scripts/restore.sh and cb. It sits at a fixed path, independent of
# install identity, data directory and any npm cache, so nothing a caller
# chooses can split exclusion; journal records bind the installation identity
# instead. Contract: specs/install/lifecycle-contract.md. Plan:
# plans/2026-09-30-v0.4.7-npm-cli-03-lock-journal-events.md (Task 2).
#
# Layout, created only by root and never by read-only planning:
#   /var/lib/circuitbreaker-lifecycle/                0755
#   /var/lib/circuitbreaker-lifecycle/history.json    0644  redacted index, derived from the journals
#   /var/lib/circuitbreaker-lifecycle/private/        0700
#   /var/lib/circuitbreaker-lifecycle/private/lock    0600  flock(2) target; never removed or truncated
#   /var/lib/circuitbreaker-lifecycle/private/owner   0600  diagnostics only; never authority
#   /var/lib/circuitbreaker-lifecycle/private/operations/<operation id>/
#                                      journal.json   0600  authoritative, atomically replaced
#                                      sequence       0600  the operation's event sequence counter
#
# Journals and the index are written only by the native state utility,
# deploy/scripts/lifecycle-state.py, through cb_lifecycle_begin,
# cb_lifecycle_checkpoint and cb_lifecycle_state below (Task 3), and
# cb_lifecycle_emit spends an operation's event sequence (Task 4). The utility
# runs under a trusted Python 3.9+ interpreter (cb_lifecycle_python), and
# setup.sh keeps it, this library and the release trust material in the
# control plane /usr/local/lib/circuitbreaker, outside the release tree an
# update replaces.
#
# The lock is flock(2) on that one inode, held through an open file
# description. A nested installer/backup/restore call inherits the
# description (CB_LIFECYCLE_LOCK_FD) together with the operation it belongs to
# (CB_LIFECYCLE_OPERATION), and proves the descriptor really holds the lock
# before joining, so a claim in the environment alone grants nothing. Because
# a flock lasts until every holder of the description has closed it, a parent
# that dies leaves the lock held until each child it handed it to exits. A
# helper that must not hold it (a daemon, anything detached) is started
# through cb_lifecycle_run_unlocked or cb_lifecycle_spawn_unlocked.
#
# Within one shell, acquisitions nest: cb's restore runs its backup in the
# same process and both take the lock, so each acquire counts a level and only
# the release that matches the outermost acquire closes the descriptor. The
# count and the descriptor live in shell variables that are never exported;
# any copy that arrives through the environment is discarded by every acquire,
# bind and release, so a child proves a handed-down lock only through the
# handoff.
#
# CB_LIFECYCLE_ROOT relocates the tree for tests over disposable roots. It is
# honoured only when the effective uid is not 0; as root it is refused.
#
# Functions return the lifecycle exit codes below and never exit, and they
# are safe under `set -Eeuo pipefail` with an ERR trap. Call them in the shell
# that will run the mutation, not in a $(...) subshell: the descriptor lives
# in the calling process. Needs bash 4.1+, coreutils or busybox, flock(1) and
# /proc. Nothing in the owner record or the environment is ever evaluated.

CB_LIFECYCLE_DEFAULT_ROOT="/var/lib/circuitbreaker-lifecycle"
# Where setup.sh installs this library, the state utility and the release
# trust material, and the interpreter tried first (ruling R13).
CB_LIFECYCLE_CONTROL_PLANE="/usr/local/lib/circuitbreaker"
CB_LIFECYCLE_SYSTEM_PYTHON="/usr/bin/python3"
# The directory of the file this library was read from (the control plane, a
# bundle's deploy/lib, or the script it is inlined in), so it finds the
# utility it was shipped with. Empty when bash read it from no regular file:
# piped (curl | bash) or from /dev/fd, BASH_SOURCE names no directory of its
# own, and the caller's working directory is never taken for one.
_CB_LIFECYCLE_LIB_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  _CB_LIFECYCLE_LIB_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || _CB_LIFECYCLE_LIB_DIR=""
  case "$_CB_LIFECYCLE_LIB_DIR" in
    /*) ;;
    *) _CB_LIFECYCLE_LIB_DIR="" ;;
  esac
  case "$_CB_LIFECYCLE_LIB_DIR/" in
    /dev/* | /proc/*) _CB_LIFECYCLE_LIB_DIR="" ;;
  esac
fi
export -n _CB_LIFECYCLE_LIB_DIR

# packages/cli/src/exit-codes.js; tests/build/test_lifecycle_lock.py keeps them equal.
CB_LIFECYCLE_EXIT_USAGE=2
CB_LIFECYCLE_EXIT_PERMISSION=6
CB_LIFECYCLE_EXIT_PREFLIGHT=7
CB_LIFECYCLE_EXIT_MANUAL=9
CB_LIFECYCLE_EXIT_LOCKED=10

# The holding state of this shell. Never exported, never read from the
# environment: _FD is the descriptor, _ID its dev:inode, _PID the process that
# opened or joined it ($BASHPID, so a subshell is a different holder) and
# _DEPTH how many acquisitions in that process are still unreleased.
_CB_LIFECYCLE_STATE_VARS=(_CB_LIFECYCLE_LOCK_FD _CB_LIFECYCLE_LOCK_ID _CB_LIFECYCLE_LOCK_PID _CB_LIFECYCLE_LOCK_DEPTH)
# What this shell resolved or last saw for its operation: the interpreter, the
# journal generation of its last acknowledged write, and whether a checkpoint
# it sent since went unacknowledged (_UNSURE). Never exported, never read from
# the environment either, and dropped with the lock.
_CB_LIFECYCLE_CACHE_VARS=(_CB_LIFECYCLE_PYTHON _CB_LIFECYCLE_GENERATION _CB_LIFECYCLE_GEN_OPERATION _CB_LIFECYCLE_GEN_UNSURE)

# Drop any holding state that is exported: it came from a parent's
# environment (or was exported by hand), and proves nothing. Every public
# entry point runs this first.
_cb_lifecycle_forget_exported_state() {
  local name
  for name in "${_CB_LIFECYCLE_STATE_VARS[@]}" "${_CB_LIFECYCLE_CACHE_VARS[@]}"; do
    if [[ "$(declare -p "$name" 2>/dev/null || true)" =~ ^declare\ -[a-zA-Z]*x ]]; then
      unset "$name"
    fi
  done
}

# Record that this process holds the lock through descriptor $1 (dev:inode $2)
# at nesting depth $3, keeping the record out of the environment even under
# `set -a`.
_cb_lifecycle_set_held() {
  _CB_LIFECYCLE_LOCK_FD="$1"
  _CB_LIFECYCLE_LOCK_ID="$2"
  _CB_LIFECYCLE_LOCK_PID="$BASHPID"
  _CB_LIFECYCLE_LOCK_DEPTH="$3"
  export -n "${_CB_LIFECYCLE_STATE_VARS[@]}"
}

# Succeeds when this very process (not a subshell or child of it) took or
# joined the lock and has not released every level yet.
_cb_lifecycle_held_here() {
  [[ -n "${_CB_LIFECYCLE_LOCK_FD:-}" && "${_CB_LIFECYCLE_LOCK_PID:-}" == "$BASHPID" ]] \
    && [[ "${_CB_LIFECYCLE_LOCK_DEPTH:-}" =~ ^[1-9][0-9]{0,5}$ ]]
}

_cb_lifecycle_say() {
  printf 'lifecycle lock: %s\n' "$*" >&2
}

# A plain absolute path: no empty, "." or ".." component, no trailing slash,
# and only characters that need no quoting in a message.
_cb_lifecycle_plain_path() {
  local path="$1"
  (( ${#path} <= 1024 )) || return 1
  [[ "$path" =~ ^(/[A-Za-z0-9._@+-]+)+$ ]] || return 1
  [[ "$path/" != */./* && "$path/" != */../* ]]
}

# Print the state root. Touches nothing on disk.
cb_lifecycle_root() {
  local seam="${CB_LIFECYCLE_ROOT:-}"
  if [[ -z "$seam" ]]; then
    printf '%s\n' "$CB_LIFECYCLE_DEFAULT_ROOT"
    return 0
  fi
  if [[ "$EUID" -eq 0 ]]; then
    _cb_lifecycle_say "CB_LIFECYCLE_ROOT is a test seam and is refused as root; the host lock is always $CB_LIFECYCLE_DEFAULT_ROOT"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  if ! _cb_lifecycle_plain_path "$seam"; then
    _cb_lifecycle_say "CB_LIFECYCLE_ROOT must be a plain absolute path"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  printf '%s\n' "$seam"
}

# The owners a state path may have: root, and the caller itself when it is not
# root (the disposable roots of the test seam). An unprivileged caller of the
# real root is refused before this is ever asked.
_cb_lifecycle_trusted_uid() {
  [[ "$1" == 0 ]] || { [[ "$EUID" -ne 0 && "$1" == "$EUID" ]]; }
}

# lstat $1 into _CB_LC_TYPE (dir, file, link, other), _CB_LC_PERM, _CB_LC_UID,
# _CB_LC_LINKS and _CB_LC_ID (dev:inode). Returns 1 when it cannot be read.
_cb_lifecycle_lstat() {
  local raw mode
  local -a f
  raw="$(stat -c '%f %u %h %d:%i' -- "$1" 2>/dev/null)" || return 1
  read -r -a f <<<"$raw"
  [[ "${#f[@]}" -eq 4 && "${f[0]}" =~ ^[0-9a-fA-F]{1,8}$ && "${f[1]}" =~ ^[0-9]+$ ]] || return 1
  [[ "${f[2]}" =~ ^[0-9]+$ && "${f[3]}" =~ ^[0-9]+:[0-9]+$ ]] || return 1
  mode=$(( 16#${f[0]} ))
  case $(( mode & 0170000 )) in
    $(( 0040000 ))) _CB_LC_TYPE=dir ;;
    $(( 0100000 ))) _CB_LC_TYPE=file ;;
    $(( 0120000 ))) _CB_LC_TYPE=link ;;
    *) _CB_LC_TYPE=other ;;
  esac
  _CB_LC_PERM=$(( mode & 07777 ))
  _CB_LC_UID="${f[1]}"
  _CB_LC_LINKS="${f[2]}"
  _CB_LC_ID="${f[3]}"
}

# Check one path of the tree. $2 is its role: ancestor, root, private or lock.
# Returns 0 when it is safe, 1 when it does not exist, and 6 (with a message)
# when it is a symlink, has an untrusted owner or the wrong type or mode.
_cb_lifecycle_check() {
  local path="$1" role="$2" want=dir noun=directory
  _cb_lifecycle_lstat "$path" || return 1
  if [[ "$_CB_LC_TYPE" == link ]]; then
    _cb_lifecycle_say "$path is a symbolic link; refusing to use it"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if ! _cb_lifecycle_trusted_uid "$_CB_LC_UID"; then
    _cb_lifecycle_say "$path is owned by uid $_CB_LC_UID, which is not trusted with the host lock"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if [[ "$role" == lock ]]; then
    want=file
    noun="regular file"
  fi
  if [[ "$_CB_LC_TYPE" != "$want" ]]; then
    _cb_lifecycle_say "$path is not a $noun"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  case "$role" in
    ancestor)
      # Group- or other-writable lets someone else swap what lies below,
      # unless the sticky bit is set by root (as on /tmp).
      if (( _CB_LC_PERM & 022 )) && ! (( (_CB_LC_PERM & 01000) && _CB_LC_UID == 0 )); then
        _cb_lifecycle_say "$path is writable by group or others"
        return "$CB_LIFECYCLE_EXIT_PERMISSION"
      fi
      ;;
    root)
      if (( _CB_LC_PERM & 022 )); then
        _cb_lifecycle_say "$path is writable by group or others"
        return "$CB_LIFECYCLE_EXIT_PERMISSION"
      fi
      ;;
    private)
      if (( (_CB_LC_PERM & 0777) != 0700 )); then
        _cb_lifecycle_say "$path must be mode 0700 (it is $(printf '%04o' "$_CB_LC_PERM"))"
        return "$CB_LIFECYCLE_EXIT_PERMISSION"
      fi
      ;;
    lock)
      if (( _CB_LC_PERM != 0600 )); then
        _cb_lifecycle_say "$path must be mode 0600 (it is $(printf '%04o' "$_CB_LC_PERM"))"
        return "$CB_LIFECYCLE_EXIT_PERMISSION"
      fi
      if (( _CB_LC_LINKS != 1 )); then
        _cb_lifecycle_say "$path has more than one name"
        return "$CB_LIFECYCLE_EXIT_PERMISSION"
      fi
      ;;
  esac
  return 0
}

# Make sure $1 (a directory, or the lock file) exists with the right role,
# creating it with its final mode when it is missing. $3 is the mode to create.
_cb_lifecycle_ensure() {
  local path="$1" role="$2" create_mode="$3" rc=0
  _cb_lifecycle_check "$path" "$role" || rc=$?
  [[ "$rc" -eq 1 ]] || return "$rc"
  if [[ ! -w "${path%/*}" ]]; then
    _cb_lifecycle_say "permission denied: cannot create $path"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  # umask 077 first, so no moment exists where the new path is looser.
  if [[ "$role" == lock ]]; then
    ( umask 077 && set -C && : >"$path" ) 2>/dev/null || true
  else
    ( umask 077 && mkdir -m "$create_mode" -- "$path" ) 2>/dev/null || true
  fi
  rc=0
  _cb_lifecycle_check "$path" "$role" || rc=$?
  if [[ "$rc" -eq 1 ]]; then
    _cb_lifecycle_say "cannot create $path"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  return "$rc"
}

# Validate every ancestor of root $1, then create or validate the root, the
# private directory and the lock file. Sets _CB_LC_LOCK_ID to the lock's dev:inode.
_cb_lifecycle_prepare() {
  local root="$1" dir="" part rc=0
  local -a parts
  IFS=/ read -r -a parts <<<"${root#/}"
  _cb_lifecycle_check / ancestor || rc=$?
  if [[ "$rc" -eq 1 ]]; then
    _cb_lifecycle_say "cannot inspect /"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  [[ "$rc" -eq 0 ]] || return "$rc"
  for part in "${parts[@]:0:${#parts[@]}-1}"; do
    if [[ ! -x "${dir:-/}" ]]; then
      _cb_lifecycle_say "permission denied: cannot enter ${dir:-/}"
      return "$CB_LIFECYCLE_EXIT_PERMISSION"
    fi
    dir="$dir/$part"
    rc=0
    _cb_lifecycle_check "$dir" ancestor || rc=$?
    if [[ "$rc" -eq 1 ]]; then
      _cb_lifecycle_say "$dir does not exist; the lifecycle state root is not created below a missing directory"
      return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
    fi
    [[ "$rc" -eq 0 ]] || return "$rc"
  done
  _cb_lifecycle_ensure "$root" root 0755 || return $?
  if [[ ! -x "$root" ]]; then
    _cb_lifecycle_say "permission denied: cannot enter $root"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  _cb_lifecycle_ensure "$root/private" private 0700 || return $?
  if [[ ! -x "$root/private" ]]; then
    _cb_lifecycle_say "permission denied: cannot enter $root/private"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  _cb_lifecycle_ensure "$root/private/lock" lock 0600 || return $?
  _CB_LC_LOCK_ID="$_CB_LC_ID"
}

# The dev:inode an open descriptor refers to, or nothing.
_cb_lifecycle_fd_id() {
  stat -L -c '%d:%i' -- "/dev/fd/$1" 2>/dev/null || true
}

# Succeeds when descriptor $1 is an open file description that holds the lock
# on $2, whose dev:inode is $3. Only a description that already holds it can
# take the lock while a fresh description of the same file is refused.
_cb_lifecycle_fd_holds() {
  local fd="$1" lock="$2" id="$3" probe
  [[ "$fd" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
  (( fd >= 3 )) || return 1
  [[ "$(_cb_lifecycle_fd_id "$fd")" == "$id" ]] || return 1
  { exec {probe}<"$lock"; } 2>/dev/null || return 1
  if flock -n "$probe" 2>/dev/null; then
    # The lock was free, so $fd held nothing.
    exec {probe}<&-
    return 1
  fi
  exec {probe}<&-
  flock -n "$fd" 2>/dev/null
}

# The start time of process $1 in clock ticks since boot (field 22 of
# /proc/PID/stat), which a recycled PID does not share.
_cb_lifecycle_start_ticks() {
  local line
  local -a f
  [[ "$1" =~ ^[1-9][0-9]{0,9}$ ]] || return 1
  { IFS= read -r line <"/proc/$1/stat"; } 2>/dev/null || return 1
  read -r -a f <<<"${line##*) }"
  [[ "${f[19]:-}" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "${f[19]}"
}

# A lock label names the command, never its arguments: "cb update", "install.sh".
_cb_lifecycle_valid_label() {
  (( ${#1} <= 64 )) && [[ "$1" =~ ^[a-z][a-z0-9._-]*( [a-z0-9][a-z0-9._-]*){0,3}$ ]]
}

# op-YYYYMMDD-NNN with a real calendar date (contract §1, Identifiers).
_cb_lifecycle_valid_operation() {
  local y m d days
  [[ "$1" =~ ^op-([0-9]{4})([0-9]{2})([0-9]{2})-[0-9]{3,9}$ ]] || return 1
  y=$(( 10#${BASH_REMATCH[1]} ))
  m=$(( 10#${BASH_REMATCH[2]} ))
  d=$(( 10#${BASH_REMATCH[3]} ))
  (( y >= 1 && m >= 1 && m <= 12 && d >= 1 )) || return 1
  case "$m" in
    2) if (( (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 )); then days=29; else days=28; fi ;;
    4 | 6 | 9 | 11) days=30 ;;
    *) days=31 ;;
  esac
  (( d <= days ))
}

# Read $1/owner into _CB_LC_OWNER_{PID,START,LABEL,SINCE,OPERATION}. Each line
# is matched against its own shape; nothing is evaluated. Returns 1 when the
# record is missing or incomplete.
_cb_lifecycle_read_owner() {
  local file="$1/owner" line key value n=0
  _CB_LC_OWNER_PID="" _CB_LC_OWNER_START="" _CB_LC_OWNER_LABEL="" _CB_LC_OWNER_SINCE="" _CB_LC_OWNER_OPERATION=""
  [[ -f "$file" && ! -L "$file" ]] || return 1
  {
    while (( n < 8 )) && IFS= read -r line; do
      n=$(( n + 1 ))
      key="${line%%=*}"
      value="${line#*=}"
      case "$key" in
        pid) if [[ "$value" =~ ^[1-9][0-9]{0,9}$ ]]; then _CB_LC_OWNER_PID="$value"; fi ;;
        start) if [[ "$value" =~ ^[0-9]{1,20}$ ]]; then _CB_LC_OWNER_START="$value"; fi ;;
        label) if _cb_lifecycle_valid_label "$value"; then _CB_LC_OWNER_LABEL="$value"; fi ;;
        since) if [[ "$value" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then _CB_LC_OWNER_SINCE="$value"; fi ;;
        operation) if _cb_lifecycle_valid_operation "$value"; then _CB_LC_OWNER_OPERATION="$value"; fi ;;
      esac
    done <"$file"
  } 2>/dev/null || return 1
  [[ -n "$_CB_LC_OWNER_PID" && -n "$_CB_LC_OWNER_START" && -n "$_CB_LC_OWNER_LABEL" && -n "$_CB_LC_OWNER_SINCE" ]]
}

# Atomically replace $1/owner: this process, $2 label, $3 operation, $4 since.
# Diagnostics only: the lock decides, never this record.
_cb_lifecycle_write_owner() {
  local private="$1" label="$2" operation="$3" since="$4" me="$BASHPID" ticks tmp
  ticks="$(_cb_lifecycle_start_ticks "$me")" || return 1
  # Only a lock holder writes here, so a leftover temporary is a crashed holder's.
  rm -f -- "$private"/.owner.* 2>/dev/null || true
  tmp="$(mktemp "$private/.owner.XXXXXX" 2>/dev/null)" || return 1
  if ! printf 'pid=%s\nstart=%s\neuid=%s\nlabel=%s\nsince=%s\noperation=%s\n' \
      "$me" "$ticks" "$EUID" "$label" "$since" "$operation" >"$tmp" 2>/dev/null \
    || ! chmod 600 -- "$tmp" 2>/dev/null \
    || ! mv -f -- "$tmp" "$private/owner" 2>/dev/null; then
    rm -f -- "$tmp" 2>/dev/null || true
    return 1
  fi
}

# Say who holds the lock, as far as the owner record shows it.
_cb_lifecycle_report_holder() {
  local private="$1" what
  if _cb_lifecycle_read_owner "$private"; then
    what="pid $_CB_LC_OWNER_PID, $_CB_LC_OWNER_LABEL, since $_CB_LC_OWNER_SINCE${_CB_LC_OWNER_OPERATION:+, operation $_CB_LC_OWNER_OPERATION}"
    if [[ "$(_cb_lifecycle_start_ticks "$_CB_LC_OWNER_PID" || true)" == "$_CB_LC_OWNER_START" ]]; then
      _cb_lifecycle_say "another lifecycle operation holds the host lock ($what)"
    else
      _cb_lifecycle_say "another lifecycle operation holds the host lock; the process that took it ($what) has exited and a process it started still holds it"
    fi
  else
    _cb_lifecycle_say "another lifecycle operation holds the host lock; its owner is not recorded"
  fi
  _cb_lifecycle_say "nothing was changed; run this again once it has finished"
}

# Join a lock handed down by a parent: CB_LIFECYCLE_LOCK_FD must hold the lock
# itself, and CB_LIFECYCLE_OPERATION must be the operation the lock's owner
# bound (both empty when it bound none).
_cb_lifecycle_inherit() {
  local private="$1" lock="$2" id="$3" fd="${CB_LIFECYCLE_LOCK_FD:-}" operation="${CB_LIFECYCLE_OPERATION:-}"
  if [[ -n "$operation" ]] && ! _cb_lifecycle_valid_operation "$operation"; then
    return 1
  fi
  _cb_lifecycle_fd_holds "$fd" "$lock" "$id" || return 1
  _cb_lifecycle_read_owner "$private" || return 1
  [[ "$_CB_LC_OWNER_OPERATION" == "$operation" ]] || return 1
  _cb_lifecycle_set_held "$fd" "$id" 1
  export CB_LIFECYCLE_LOCK_FD="$fd" CB_LIFECYCLE_OPERATION="$operation"
}

# Nest one more level on the lock this process already holds. The caller's
# operation context must still be the one the lock is bound to, exactly as a
# child's would; a different one is refused with 10 and changes nothing.
_cb_lifecycle_reenter() {
  local private="$1" lock="$2" id="$3" operation="${CB_LIFECYCLE_OPERATION:-}"
  if ! _cb_lifecycle_fd_holds "$_CB_LIFECYCLE_LOCK_FD" "$lock" "$id"; then
    return 1
  fi
  if ! _cb_lifecycle_read_owner "$private" || [[ "$_CB_LC_OWNER_OPERATION" != "$operation" ]]; then
    _cb_lifecycle_say "this process holds the host lock for another operation context (CB_LIFECYCLE_OPERATION); nothing was changed"
    return "$CB_LIFECYCLE_EXIT_LOCKED"
  fi
  _cb_lifecycle_set_held "$_CB_LIFECYCLE_LOCK_FD" "$id" $(( _CB_LIFECYCLE_LOCK_DEPTH + 1 ))
}

# Take the host lifecycle lock for the command named by label $1 (for
# example "cb update"; never its arguments). Joins the lock instead when this
# shell already holds it (one more nesting level, released by its own
# cb_lifecycle_lock_release) or a parent handed it down. On success the
# descriptor is exported for nested calls in CB_LIFECYCLE_LOCK_FD.
# Returns 0, 2 (usage), 6 (permission or an unsafe tree), 7 (the state root
# cannot be prepared) or 10 (another operation holds the lock), always before
# the caller has changed anything.
cb_lifecycle_lock_acquire() {
  local label="${1:-}" root private lock id fd rc=0 since
  _cb_lifecycle_forget_exported_state
  if ! _cb_lifecycle_valid_label "$label"; then
    _cb_lifecycle_say "internal error: a lock label is a plain command name"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  root="$(cb_lifecycle_root)" || return $?
  if [[ -z "${CB_LIFECYCLE_ROOT:-}" && "$EUID" -ne 0 ]]; then
    _cb_lifecycle_say "permission denied: the host lifecycle lock is root-only; run this command with sudo"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if ! command -v flock >/dev/null 2>&1; then
    _cb_lifecycle_say "flock(1) is required (util-linux or busybox)"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  _cb_lifecycle_prepare "$root" || return $?
  private="$root/private"
  lock="$private/lock"
  id="$_CB_LC_LOCK_ID"

  if _cb_lifecycle_held_here; then
    _cb_lifecycle_reenter "$private" "$lock" "$id" || rc=$?
    [[ "$rc" -eq 1 ]] || return "$rc"
    rc=0
  fi
  if [[ -n "${CB_LIFECYCLE_LOCK_FD:-}" ]]; then
    if _cb_lifecycle_inherit "$private" "$lock" "$id"; then
      return 0
    fi
    _cb_lifecycle_say "ignoring an unproven lock handoff (CB_LIFECYCLE_LOCK_FD); taking the lock normally"
  fi

  if ! { exec {fd}<"$lock"; } 2>/dev/null; then
    _cb_lifecycle_say "permission denied: cannot open $lock"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if [[ "$(_cb_lifecycle_fd_id "$fd")" != "$id" ]]; then
    exec {fd}<&-
    _cb_lifecycle_say "$lock changed while it was being opened"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  flock -n "$fd" 2>/dev/null || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    exec {fd}<&-
    if [[ "$rc" -eq 1 ]]; then
      _cb_lifecycle_report_holder "$private"
      return "$CB_LIFECYCLE_EXIT_LOCKED"
    fi
    _cb_lifecycle_say "flock(1) failed on $lock (status $rc)"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if ! _cb_lifecycle_write_owner "$private" "$label" "" "$since"; then
    exec {fd}<&-
    _cb_lifecycle_say "cannot record the lock owner in $private"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  _cb_lifecycle_set_held "$fd" "$id" 1
  export CB_LIFECYCLE_LOCK_FD="$fd" CB_LIFECYCLE_OPERATION=""
}

# Bind the held lock to operation $1, so nested calls join that operation
# only. Only the process that took the lock binds, once; binding the same
# operation again is a no-op. Returns 0, 2 (misuse) or 7 (cannot record it).
cb_lifecycle_lock_bind_operation() {
  local operation="${1:-}" me="$BASHPID" root private lock ticks
  if ! _cb_lifecycle_valid_operation "$operation"; then
    _cb_lifecycle_say "internal error: $(printf '%q' "$operation") is not an operation ID"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  root="$(cb_lifecycle_root)" || return $?
  private="$root/private"
  lock="$private/lock"
  _cb_lifecycle_forget_exported_state
  if ! { _cb_lifecycle_held_here && _cb_lifecycle_lstat "$lock" \
      && _cb_lifecycle_fd_holds "$_CB_LIFECYCLE_LOCK_FD" "$lock" "$_CB_LC_ID"; }; then
    _cb_lifecycle_say "internal error: binding an operation needs the held lock"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  ticks="$(_cb_lifecycle_start_ticks "$me" || true)"
  if ! _cb_lifecycle_read_owner "$private" || [[ "$_CB_LC_OWNER_PID" != "$me" || "$_CB_LC_OWNER_START" != "$ticks" ]]; then
    _cb_lifecycle_say "internal error: only the process that took the lock binds its operation"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  if [[ -n "$_CB_LC_OWNER_OPERATION" && "$_CB_LC_OWNER_OPERATION" != "$operation" ]]; then
    _cb_lifecycle_say "internal error: the lock is bound to $_CB_LC_OWNER_OPERATION already"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  if ! _cb_lifecycle_write_owner "$private" "$_CB_LC_OWNER_LABEL" "$operation" "$_CB_LC_OWNER_SINCE"; then
    _cb_lifecycle_say "cannot record the lock owner in $private"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  export CB_LIFECYCLE_OPERATION="$operation"
}

# Release one nesting level. Only the release matching this process's
# outermost acquire closes its copy of the lock descriptor; an inner one
# (cb restore's in-process backup, say) leaves the lock and the handoff
# variables exactly as they were. The lock file stays (one stable inode), and
# the lock is free once no other process still holds a copy: a child that
# inherited the descriptor keeps it held until it exits.
cb_lifecycle_lock_release() {
  local fd id
  _cb_lifecycle_forget_exported_state
  if _cb_lifecycle_held_here && (( _CB_LIFECYCLE_LOCK_DEPTH > 1 )); then
    _cb_lifecycle_set_held "$_CB_LIFECYCLE_LOCK_FD" "${_CB_LIFECYCLE_LOCK_ID:-}" $(( _CB_LIFECYCLE_LOCK_DEPTH - 1 ))
    return 0
  fi
  # The outermost level here, or a subshell's inherited copy, which is its own.
  fd="${_CB_LIFECYCLE_LOCK_FD:-}" id="${_CB_LIFECYCLE_LOCK_ID:-}"
  if [[ "$fd" =~ ^[1-9][0-9]{0,4}$ ]] && (( fd >= 3 )) && [[ -n "$id" && "$(_cb_lifecycle_fd_id "$fd")" == "$id" ]]; then
    exec {fd}<&-
  fi
  unset "${_CB_LIFECYCLE_STATE_VARS[@]}" "${_CB_LIFECYCLE_CACHE_VARS[@]}" CB_LIFECYCLE_LOCK_FD CB_LIFECYCLE_OPERATION
}

# In a subshell that is about to exec something that must not hold the lock:
# close the descriptor and drop the handoff variables. The event descriptor
# goes too, since an unlocked helper has no operation to emit for. Its stdout
# and stderr stay as the caller left them: the coordinator stops reading the
# step's output shortly after the step exits (packages/cli/src/events.js,
# NATIVE_DRAIN_MS), so a daemon that keeps them loses what it writes later
# and should be given its own log by the caller.
_cb_lifecycle_drop_lock() {
  local fd
  if _cb_lifecycle_event_fd_valid; then
    fd="$CB_LIFECYCLE_EVENT_FD"
    exec {fd}>&-
  fi
  for fd in "${_CB_LIFECYCLE_LOCK_FD:-}" "${CB_LIFECYCLE_LOCK_FD:-}"; do
    if [[ "$fd" =~ ^[1-9][0-9]{0,4}$ ]] && (( fd >= 3 )); then
      exec {fd}<&-
    fi
  done
  unset "${_CB_LIFECYCLE_STATE_VARS[@]}" "${_CB_LIFECYCLE_CACHE_VARS[@]}" CB_LIFECYCLE_LOCK_FD CB_LIFECYCLE_OPERATION \
    CB_LIFECYCLE_EVENT_FD
}

# Run a command in the foreground without the lock, so that nothing it leaves
# running (a daemon it forks, for example) holds it after this process exits.
cb_lifecycle_run_unlocked() {
  ( _cb_lifecycle_drop_lock && exec "$@" )
}

# Start a command in the background without the lock; $! is its PID. Use this
# rather than `cb_lifecycle_run_unlocked ... &`, whose background subshell
# would hold the descriptor for as long as the command runs.
cb_lifecycle_spawn_unlocked() {
  ( _cb_lifecycle_drop_lock && exec "$@" ) &
}

# --- The native state utility (Task 3) ---------------------------------------------------------

# Whether uid $1 may own a program this library runs: root only when $2 is
# set, otherwise the state tree's rule (root, and the caller when not root).
_cb_lifecycle_program_owner() {
  if [[ -n "${2:-}" ]]; then
    [[ "$1" == 0 ]]
  else
    _cb_lifecycle_trusted_uid "$1"
  fi
}

# Succeeds when every directory above $1 is a directory a trusted uid owns
# ($2 as for _cb_lifecycle_program_owner) that neither group nor others can
# write, unless it is sticky and root's (as /tmp is).
_cb_lifecycle_safe_dirs() {
  local path="$1" only_root="${2:-}" dir="" part
  local -a parts
  IFS=/ read -r -a parts <<<"${path#/}"
  for part in "" "${parts[@]:0:${#parts[@]}-1}"; do
    [[ -z "$part" ]] || dir="$dir/$part"
    _cb_lifecycle_lstat "${dir:-/}" || return 1
    [[ "$_CB_LC_TYPE" == dir ]] || return 1
    _cb_lifecycle_program_owner "$_CB_LC_UID" "$only_root" || return 1
    if (( _CB_LC_PERM & 022 )) && ! (( (_CB_LC_PERM & 01000) && _CB_LC_UID == 0 )); then
      return 1
    fi
  done
}

# Succeeds when $1 is a program this library may run: a regular file (or a
# symlink a trusted uid owns, to one) with a trusted owner, not writable by
# group or others, below safe directories. $2 set: root must own all of it.
_cb_lifecycle_trusted_program() {
  local path="$1" only_root="${2:-}" real
  [[ "$path" == /* ]] || return 1
  _cb_lifecycle_safe_dirs "$path" "$only_root" || return 1
  _cb_lifecycle_lstat "$path" || return 1
  real="$path"
  if [[ "$_CB_LC_TYPE" == link ]]; then
    _cb_lifecycle_program_owner "$_CB_LC_UID" "$only_root" || return 1
    real="$(readlink -f -- "$path" 2>/dev/null)" || return 1
    [[ "$real" == /* ]] || return 1
    _cb_lifecycle_safe_dirs "$real" "$only_root" || return 1
    _cb_lifecycle_lstat "$real" || return 1
  fi
  [[ "$_CB_LC_TYPE" == file ]] || return 1
  _cb_lifecycle_program_owner "$_CB_LC_UID" "$only_root" || return 1
  (( (_CB_LC_PERM & 022) == 0 ))
}

_cb_lifecycle_python_is_new_enough() {
  "$1" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

# Resolve the trusted interpreter for this transaction, before its first
# mutation (ruling R13): /usr/bin/python3 when root owns it and the
# directories above it, nobody else can write them, and it is 3.9 or newer;
# otherwise, for a fresh install only, the verified staged bundle's
# python/bin/python3, which the caller passes as $1. Sets _CB_LIFECYCLE_PYTHON.
# Returns 0, or 7 before anything has been changed.
cb_lifecycle_python() {
  local fresh="${1:-}"
  _cb_lifecycle_forget_exported_state
  if _cb_lifecycle_trusted_program "$CB_LIFECYCLE_SYSTEM_PYTHON" root \
    && _cb_lifecycle_python_is_new_enough "$CB_LIFECYCLE_SYSTEM_PYTHON"; then
    _CB_LIFECYCLE_PYTHON="$CB_LIFECYCLE_SYSTEM_PYTHON"
  elif [[ -n "$fresh" ]] && _cb_lifecycle_trusted_program "$fresh" && _cb_lifecycle_python_is_new_enough "$fresh"; then
    _CB_LIFECYCLE_PYTHON="$fresh"
  else
    _cb_lifecycle_say "no trusted Python 3.9 or newer: $CB_LIFECYCLE_SYSTEM_PYTHON must be root's, not writable by group or others, and at least 3.9${fresh:+ (and so must $fresh)}"
    _cb_lifecycle_say "nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  export -n _CB_LIFECYCLE_PYTHON
}

# Find the state utility and require that it is a trusted file. The library
# and the utility speak one protocol, so the copy shipped beside the file this
# library was read from comes first: next to it (the control plane), in its
# bundle's deploy/scripts, or in deploy/scripts below the script it is inlined
# in. The control plane comes last, and is the only place looked at when the
# library was read from no file (piped). A copy that is not trusted is passed
# over, never run. Sets _CB_LC_UTILITY. Returns 0, or 7 naming every copy
# passed over.
_cb_lifecycle_find_utility() {
  local dir="${_CB_LIFECYCLE_LIB_DIR:-}" candidate scripts="" passed=""
  if [[ -n "$dir" && -d "$dir/../scripts" ]]; then
    scripts="$(cd -P -- "$dir/../scripts" 2>/dev/null && pwd)" || scripts=""
  fi
  for candidate in "${dir:+$dir/lifecycle-state.py}" "${scripts:+$scripts/lifecycle-state.py}" \
      "${dir:+$dir/deploy/scripts/lifecycle-state.py}" "$CB_LIFECYCLE_CONTROL_PLANE/lifecycle-state.py"; do
    [[ "$candidate" == /* && -e "$candidate" ]] || continue
    if _cb_lifecycle_trusted_program "$candidate"; then
      _CB_LC_UTILITY="$candidate"
      return 0
    fi
    passed+="${passed:+, }$candidate"
  done
  if [[ -n "$passed" ]]; then
    _cb_lifecycle_say "no trusted lifecycle state utility: $passed is not trusted (its owner, its mode or a directory above it); refusing to run it"
  else
    _cb_lifecycle_say "the lifecycle state utility (lifecycle-state.py) is not installed"
  fi
  return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
}

# $1 as a JSON string. Byte by byte under LC_ALL=C, so UTF-8 passes through
# untouched (the utility refuses anything that is not UTF-8) and every
# control byte becomes a \u escape.
_cb_lifecycle_json_string() {
  local LC_ALL=C s="$1" out="" c code i
  for (( i = 0; i < ${#s}; i++ )); do
    c="${s:i:1}"
    case "$c" in
      '"') out+='\"' ;;
      '\') out+='\\' ;;
      [[:cntrl:]])
        printf -v code '%d' "'$c"
        printf -v c '\\u%04x' "$code"
        out+="$c"
        ;;
      *) out+="$c" ;;
    esac
  done
  printf '"%s"' "$out"
}

# The JSON request for utility request $1 from key=value arguments. Values
# are strings, except expected_generation.
_cb_lifecycle_request() {
  local json arg key value
  json="{\"request\":$(_cb_lifecycle_json_string "$1")"
  shift
  for arg in "$@"; do
    key="${arg%%=*}"
    value="${arg#*=}"
    if [[ "$arg" != *=* || ! "$key" =~ ^[a-z][a-z0-9_]{0,63}$ ]]; then
      _cb_lifecycle_say "internal error: a state request takes key=value arguments"
      return "$CB_LIFECYCLE_EXIT_USAGE"
    fi
    if [[ "$key" == expected_generation ]]; then
      if [[ ! "$value" =~ ^[1-9][0-9]{0,15}$ ]]; then
        _cb_lifecycle_say "internal error: expected_generation is a positive integer"
        return "$CB_LIFECYCLE_EXIT_USAGE"
      fi
      json+=",\"$key\":$value"
    elif [[ "$key" == done || "$key" == total || "$key" == duration_ms ]]; then
      if [[ ! "$value" =~ ^(0|[1-9][0-9]{0,15})$ ]]; then
        _cb_lifecycle_say "internal error: $key is a count"
        return "$CB_LIFECYCLE_EXIT_USAGE"
      fi
      json+=",\"$key\":$value"
    else
      json+=",\"$key\":$(_cb_lifecycle_json_string "$value")"
    fi
  done
  printf '%s}' "$json"
}

# Run state utility request $1 (inspect, begin, checkpoint, emit or list) with
# key=value members; its acknowledgement lines go to stdout and its exit code
# is returned. Prefer cb_lifecycle_begin and cb_lifecycle_checkpoint for
# writes: they bind the lock and track the generation.
#
# The utility writes a request's event to the event descriptor itself, once
# the record is durable and while it still holds its writer lock, so that
# every holder of the lock (this shell, a subshell, a child it handed the lock
# to) puts its events on the descriptor in sequence order. It sees the
# descriptor only when this library accepts it, and checks it again itself.
cb_lifecycle_state() {
  local request="${1:-}" json events="" rc=0
  if [[ $# -gt 0 ]]; then
    shift
  fi
  _cb_lifecycle_forget_exported_state
  if [[ -z "${_CB_LIFECYCLE_PYTHON:-}" ]]; then
    cb_lifecycle_python || return $?
  fi
  _cb_lifecycle_find_utility || return $?
  json="$(_cb_lifecycle_request "$request" "$@")" || return $?
  if _cb_lifecycle_event_fd_valid; then
    events="$CB_LIFECYCLE_EVENT_FD"
  fi
  CB_LIFECYCLE_EVENT_FD="$events" "$_CB_LIFECYCLE_PYTHON" -I -B "$_CB_LC_UTILITY" <<<"$json" || rc=$?
  return "$rc"
}

# Read an acknowledgement into _CB_LC_ACK_{OPERATION,GENERATION}, each line
# matched against its own shape; warnings go to stderr. Nothing in it is ever
# evaluated, and its `event` line is not emitted again: the utility has
# written it to the descriptor already.
_cb_lifecycle_read_ack() {
  local line key value
  _CB_LC_ACK_OPERATION="" _CB_LC_ACK_GENERATION=""
  while IFS= read -r line; do
    key="${line%%=*}"
    value="${line#*=}"
    case "$key" in
      operation_id) if _cb_lifecycle_valid_operation "$value"; then _CB_LC_ACK_OPERATION="$value"; fi ;;
      generation) if [[ "$value" =~ ^[1-9][0-9]{0,15}$ ]]; then _CB_LC_ACK_GENERATION="$value"; fi ;;
      warning) printf 'lifecycle state: warning: %s\n' "$value" >&2 ;;
    esac
  done <<<"$1"
}

# Remember generation $2 of operation $1 as this shell's last acknowledged
# view; $3 set means a checkpoint is now in flight, unacknowledged until
# remembered again.
_cb_lifecycle_remember_generation() {
  _CB_LIFECYCLE_GEN_OPERATION="$1"
  _CB_LIFECYCLE_GENERATION="$2"
  _CB_LIFECYCLE_GEN_UNSURE="${3:-}"
  export -n _CB_LIFECYCLE_GEN_OPERATION _CB_LIFECYCLE_GENERATION _CB_LIFECYCLE_GEN_UNSURE
}

# Whether CB_LIFECYCLE_EVENT_FD names a descriptor events may go to: 3 or
# above, not the lock, and a pipe, socket or file.
_cb_lifecycle_event_fd_valid() {
  local fd="${CB_LIFECYCLE_EVENT_FD:-}"
  [[ "$fd" =~ ^[1-9][0-9]{0,4}$ ]] && (( fd >= 3 )) || return 1
  [[ "$fd" != "${_CB_LIFECYCLE_LOCK_FD:-}" && "$fd" != "${CB_LIFECYCLE_LOCK_FD:-}" ]] || return 1
  [[ -p "/dev/fd/$fd" || -S "/dev/fd/$fd" || -f "/dev/fd/$fd" ]]
}

# Emit one progress, phase or diagnostic event of the operation the lock is
# bound to (ruling R15): key=value members type (phase, progress or
# diagnostic) and that type's members, phase status [duration_ms], phase done
# [total] unit, or level message [code]. The state utility spends the
# operation's next sequence on it and writes it to the descriptor under its
# writer lock, so events and checkpoints of nested native processes share one
# rising sequence and reach the descriptor in that order. Without a valid
# CB_LIFECYCLE_EVENT_FD nothing is emitted and nothing is written. Events are
# presentation: only a malformed event (2) is an error, and any other failure
# to emit one returns 0 so it never stops the operation.
cb_lifecycle_emit() {
  local op="${CB_LIFECYCLE_OPERATION:-}" out rc=0
  _cb_lifecycle_forget_exported_state
  _cb_lifecycle_event_fd_valid || return 0
  if ! _cb_lifecycle_valid_operation "$op"; then
    _cb_lifecycle_say "internal error: an event needs the operation the lock is bound to"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  out="$(cb_lifecycle_state emit operation_id="$op" "$@")" || rc=$?
  if [[ "$rc" -eq "$CB_LIFECYCLE_EXIT_USAGE" ]]; then
    return "$rc"
  fi
  return 0
}

# Start an operation under the lock this shell holds: the utility allocates
# its ID, writes its first durable record and emits its checkpoint event, then
# the lock is bound to it. Members are key=value: kind, action,
# adapter, and optionally plan_digest, identity_digest, source_version,
# source_artifact_digest, target_version, target_artifact_digest,
# recovery_operation_id, recovery_manifest_digest and evidence_check,
# evidence_result, evidence_detail. Returns the utility's code: 9 while an
# unfinished transaction (or, for a transaction, a record that requires
# inspection) exists, 7 when the record cannot be made durable.
cb_lifecycle_begin() {
  local out rc=0
  _cb_lifecycle_forget_exported_state
  if ! _cb_lifecycle_held_here; then
    _cb_lifecycle_say "internal error: an operation begins in the shell that holds the lock"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  if [[ -z "${_CB_LIFECYCLE_PYTHON:-}" ]]; then
    cb_lifecycle_python || return $?
  fi
  out="$(cb_lifecycle_state begin "$@")" || rc=$?
  _cb_lifecycle_read_ack "$out"
  [[ "$rc" -eq 0 ]] || return "$rc"
  if [[ -z "$_CB_LC_ACK_OPERATION" || "$_CB_LC_ACK_GENERATION" != 1 ]]; then
    _cb_lifecycle_say "internal error: the state utility did not acknowledge the operation"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  cb_lifecycle_lock_bind_operation "$_CB_LC_ACK_OPERATION" || return $?
  _cb_lifecycle_remember_generation "$_CB_LC_ACK_OPERATION" 1
}

# Record the next durable checkpoint of the operation the lock is bound to:
# key=value members state, and optionally step, cause, outcome, error_code
# with error_reason, recovery_operation_id with recovery_manifest_digest, and
# evidence_*. The utility emits the checkpoint event only once the record is
# durable.
#
# Under the held lock only this operation's own writers can move its journal:
# this shell, a subshell of it, or a child it handed the lock to (cb update ->
# restore.sh), whose view of the generation dies with it. So each checkpoint
# first learns the journal's current generation, and names it as the expected
# one: a writer that slips in between still makes this one stale (9). The one
# thing this shell cannot learn is whether a checkpoint it sent that went
# unacknowledged (7, or no answer) landed anyway. While the journal still has
# the generation this shell last saw, nothing landed and it goes on. Once the
# journal has moved past it, the record may be its own, so this and every
# later checkpoint of the operation from this shell is stale (9) and the
# caller stops before its next change, as for any failed checkpoint.
cb_lifecycle_checkpoint() {
  local op="${CB_LIFECYCLE_OPERATION:-}" out rc=0 current
  _cb_lifecycle_forget_exported_state
  if ! _cb_lifecycle_valid_operation "$op"; then
    _cb_lifecycle_say "internal error: a checkpoint needs the operation the lock is bound to"
    return "$CB_LIFECYCLE_EXIT_USAGE"
  fi
  if [[ -z "${_CB_LIFECYCLE_PYTHON:-}" ]]; then
    cb_lifecycle_python || return $?
  fi
  out="$(cb_lifecycle_state inspect operation_id="$op")" || return $?
  _cb_lifecycle_read_ack "$out"
  current="$_CB_LC_ACK_GENERATION"
  if [[ -z "$current" || "$_CB_LC_ACK_OPERATION" != "$op" ]]; then
    _cb_lifecycle_say "internal error: the state utility did not report $op"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  if [[ "${_CB_LIFECYCLE_GEN_OPERATION:-}" == "$op" && -n "${_CB_LIFECYCLE_GEN_UNSURE:-}" \
    && "$current" != "${_CB_LIFECYCLE_GENERATION:-}" ]]; then
    _cb_lifecycle_say "$op is at generation $current, past the $_CB_LIFECYCLE_GENERATION this shell last saw, and its last checkpoint here was not acknowledged: that record may be its own, so this checkpoint is stale; inspect the operation before changing anything"
    return "$CB_LIFECYCLE_EXIT_MANUAL"
  fi
  _cb_lifecycle_remember_generation "$op" "$current" in-flight
  out="$(cb_lifecycle_state checkpoint operation_id="$op" expected_generation="$current" "$@")" || rc=$?
  _cb_lifecycle_read_ack "$out"
  [[ "$rc" -eq 0 ]] || return "$rc"
  if [[ "$_CB_LC_ACK_OPERATION" != "$op" || -z "$_CB_LC_ACK_GENERATION" ]]; then
    _cb_lifecycle_say "internal error: the state utility did not acknowledge the checkpoint"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  _cb_lifecycle_remember_generation "$op" "$_CB_LC_ACK_GENERATION"
}

# Install the control plane from bundle deploy directory $1 into $2 (default
# /usr/local/lib/circuitbreaker): this library, the state utility and the
# release trust material (bundle-signature.sh, which embeds the release
# bundle keys). Outside the release tree, so replacing or removing the server
# never removes its recovery tools. Every source is checked before anything
# is written, and each file is replaced by an atomic rename. Directory 0755,
# files 0644, the utility 0755, all root's when run as root. Returns 0, 6 or 7.
cb_lifecycle_install_control_plane() {
  local src="${1:-}" dest="${2:-$CB_LIFECYCLE_CONTROL_PLANE}" item from name perm tmp
  local -a items=("lib/lifecycle.sh lifecycle.sh 644" "scripts/lifecycle-state.py lifecycle-state.py 755" \
    "lib/bundle-signature.sh bundle-signature.sh 644")
  for item in "${items[@]}"; do
    read -r from name perm <<<"$item"
    if [[ ! -f "$src/$from" || -L "$src/$from" ]]; then
      _cb_lifecycle_say "cannot install the lifecycle control plane: $src/$from is missing"
      return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
    fi
  done
  if [[ -L "$dest" ]] || { [[ -e "$dest" ]] && [[ ! -d "$dest" ]]; }; then
    _cb_lifecycle_say "$dest is not a directory; refusing to install into it"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if [[ ! -d "$dest" ]] && ! ( umask 022 && mkdir -p -- "$dest" ) 2>/dev/null; then
    _cb_lifecycle_say "cannot create $dest"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  if ! chmod 755 -- "$dest" 2>/dev/null || { [[ "$EUID" -eq 0 ]] && ! chown 0:0 -- "$dest" 2>/dev/null; }; then
    _cb_lifecycle_say "cannot make $dest root's, mode 0755"
    return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
  fi
  for item in "${items[@]}"; do
    read -r from name perm <<<"$item"
    if ! tmp="$(mktemp "$dest/.$name.XXXXXX" 2>/dev/null)"; then
      _cb_lifecycle_say "cannot write in $dest"
      return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
    fi
    if ! cp -- "$src/$from" "$tmp" 2>/dev/null || ! chmod "$perm" -- "$tmp" 2>/dev/null \
      || { [[ "$EUID" -eq 0 ]] && ! chown 0:0 -- "$tmp" 2>/dev/null; } \
      || ! mv -f -- "$tmp" "$dest/$name" 2>/dev/null; then
      rm -f -- "$tmp" 2>/dev/null || true
      _cb_lifecycle_say "cannot install $dest/$name"
      return "$CB_LIFECYCLE_EXIT_PREFLIGHT"
    fi
  done
}
# --- END INLINED deploy/lib/lifecycle.sh ---

# The lock is root-only. A native or packaged install is removed through root
# anyway, so without root that removal is refused here (6) rather than run
# half-unlocked through per-command sudo. A Docker-only host removed by a
# docker-group operator as themselves cannot take it and is told so instead
# (the contract's docker interim). Linux only: the lock needs flock(1).
if [ "$(uname -s)" = "Linux" ]; then
  if [ "$(id -u)" -eq 0 ] || [ -n "${CB_LIFECYCLE_ROOT:-}" ] \
    || [ "$CB_HAS_NATIVE" = "true" ] || [ "$CB_HAS_PACKAGE" = "true" ]; then
    _cb_lock_rc=0
    cb_lifecycle_lock_acquire "uninstall.sh" || _cb_lock_rc=$?
    if [ "$_cb_lock_rc" -ne 0 ]; then
      exit "$_cb_lock_rc"
    fi
  else
    Show 3 "Running without the host lifecycle lock: it is root-only, and this Docker-only removal runs as $(id -un)."
  fi
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
  #
  # The tmpfiles.d entry goes with it. It is what recreates /run/circuitbreaker
  # on every boot now that no unit declares it as a RuntimeDirectory, so leaving
  # it would have an uninstalled product recreating a directory — owned by a
  # `breaker` account this uninstaller has just deleted — at each boot.
  sudo rm -f /usr/lib/tmpfiles.d/circuitbreaker.conf >/dev/null 2>&1 || true
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
if [ "$CB_HAS_PACKAGE" = true ]; then
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

  # The package layout installs the runtime tree at the same root install.sh
  # uses; on a package host nothing else owns it.
  if [ -d /opt/circuitbreaker/python ]; then
    sudo rm -rf /opt/circuitbreaker
    Show 0 "Runtime tree removed."
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
