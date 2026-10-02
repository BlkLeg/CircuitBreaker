#!/bin/bash
# nfpm scripts.postinstall — rpm %post, deb postinst, apk .post-install.
set -e

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
# The lock is root-only, so an entrypoint that is not root first re-runs
# itself through sudo (cb_lifecycle_elevate) and does the whole operation as
# root under the lock, rather than escalating step by step past it.
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
    $(( 0100000 ))) _CB_LC_TYPE="file" ;;
    $(( 0120000 ))) _CB_LC_TYPE="link" ;;
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
    want="file"
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
  # AppArmor can refuse lock calls on a descriptor opened before a policy
  # reload (seen in a Proxmox LXC); the kernel still lists this description's locks.
  flock -n "$fd" 2>/dev/null \
    || grep -qE '^lock:[[:space:]]+[0-9]+: FLOCK[[:space:]]+ADVISORY[[:space:]]+WRITE ' "/proc/$BASHPID/fdinfo/$fd" 2>/dev/null
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

# The variables a re-run through sudo carries from the operator's environment,
# besides HOME and the CB_LIFECYCLE_ELEVATED marker: terminal display, and the
# documented operator switches that must survive the re-run. CB_AIRGAP keeps
# `CB_AIRGAP=true bash install.sh` from making any outbound call as root;
# CB_VERBOSE is install.sh's documented environment form of --verbose;
# CB_ASSUME_YES is restore.sh's documented consent given in advance. Nothing
# else is carried: the paths, binaries and identity files that steer cb, the
# installers and restore.sh, secrets, and the CB_LIFECYCLE_ROOT test seam all
# stay behind, and as root they come only from root's own configuration.
CB_LIFECYCLE_ELEVATE_CARRY=(TERM NO_COLOR CB_AIRGAP CB_VERBOSE CB_ASSUME_YES)

# Print the canonical path of $1 when it names a regular file outside /dev and
# /proc: absolute, with every symlink resolved. Returns 1 for anything else,
# including an empty or missing path.
_cb_lifecycle_canonical_file() {
  local path="${1:-}" resolved=""
  [[ -n "$path" ]] || return 1
  if command -v realpath >/dev/null 2>&1; then
    resolved="$(realpath -- "$path" 2>/dev/null)" || resolved=""
  fi
  if [[ -z "$resolved" ]] && command -v readlink >/dev/null 2>&1; then
    resolved="$(readlink -f -- "$path" 2>/dev/null)" || resolved=""
  fi
  case "$resolved" in
    /dev/* | /proc/*) return 1 ;;
    /*) ;;
    *) return 1 ;;
  esac
  [[ -f "$resolved" ]] || return 1
  printf '%s\n' "$resolved"
}

# Return 0 when canonical path $1 is a file this shell ($$, the script's own
# process even from a subshell) holds open. Bash keeps the script it runs open
# for as long as it runs (on fd 255, or lower under a small descriptor limit),
# so this is how a path is proven to be the script being executed; a script
# read from a pipe holds no such file. The kernel reports each open file by its
# resolved path, as _cb_lifecycle_canonical_file prints it.
_cb_lifecycle_shell_has_open() {
  local want="$1" fd target
  for fd in "/proc/$$/fd/"*; do
    target="$(readlink -- "$fd" 2>/dev/null)" || continue
    if [[ "$target" == "$want" ]]; then
      return 0
    fi
  done
  return 1
}

# Make sure this lifecycle entrypoint runs as root before it takes the lock:
# the lock is root-only, and an entrypoint that escalated step by step through
# sudo would make root changes without it. Not root, this re-runs script $1
# with arguments $2... through sudo, so it never returns.
#
# $1 must be the script bash is running, captured at its top level, where
# BASH_SOURCE is empty when bash reads the script from a pipe (inside a
# function it is the word "bash", which names whatever ./bash sits in the
# working directory). It is re-run, by its canonical path, only when it
# resolves to an absolute regular file that this shell holds open as the
# script it executes; otherwise nothing is re-run and it returns 6.
#
# The re-run gets sudo's own reset environment plus, through env(1), the
# CB_LIFECYCLE_ELEVATED marker, HOME (a Docker install is found through the
# operator's home, which sudo may reset) and the CB_LIFECYCLE_ELEVATE_CARRY
# allowlist. They are arguments to env, not sudo settings, so a sudoers rule
# without SETENV does not refuse them. A re-run that is still not root has met
# a sudo that does not elevate, and goes on only over the CB_LIFECYCLE_ROOT
# test seam, whose lock is the disposable one (a real sudo makes it root, where
# the seam is refused). Returns 0 as root, or 6 (with a message) when it cannot
# elevate: no script file to re-run (read from a pipe), a path that is not the
# running script, no sudo, or sudo refused. Call it before anything is changed.
cb_lifecycle_elevate() {
  local script="${1:-}" self="" name
  local -a carry=()
  if [[ $# -gt 0 ]]; then
    shift
  fi
  if [[ "$EUID" -eq 0 ]]; then
    return 0
  fi
  if [[ "${CB_LIFECYCLE_ELEVATED:-}" == 1 ]]; then
    if [[ -n "${CB_LIFECYCLE_ROOT:-}" ]]; then
      return 0
    fi
    _cb_lifecycle_say "sudo did not run this as root; nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if [[ -z "$script" ]]; then
    _cb_lifecycle_say "this needs root and was read from a pipe, so it cannot re-run itself; pipe it to 'sudo bash' instead. Nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  self="$(_cb_lifecycle_canonical_file "$script")" || self=""
  if [[ -z "$self" ]] || ! _cb_lifecycle_shell_has_open "$self"; then
    _cb_lifecycle_say "refusing to re-run a file that is not the script being run (a script read from a pipe cannot re-run itself); run it with sudo instead. Nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    _cb_lifecycle_say "this needs root and sudo is not installed; run it as root. Nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  if ! sudo -v; then
    _cb_lifecycle_say "sudo refused; run it again with sudo. Nothing was changed"
    return "$CB_LIFECYCLE_EXIT_PERMISSION"
  fi
  carry=("CB_LIFECYCLE_ELEVATED=1" "HOME=${HOME:-}")
  for name in "${CB_LIFECYCLE_ELEVATE_CARRY[@]}"; do
    if [[ -n "${!name:-}" ]]; then
      carry+=("${name}=${!name}")
    fi
  done
  exec sudo -- env "${carry[@]}" bash "$self" "$@"
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
    elif [[ "$key" == "done" || "$key" == total || "$key" == duration_ms ]]; then
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
  if [[ " $* " == *" state=applying "* ]]; then cb_lifecycle_mark_mutation; fi
}

# INT and TERM at the lock boundary (Task 5b). An entrypoint arms this once,
# right after it takes the lock, and marks its first change of the host:
#
#   cb_lifecycle_arm_interrupt          # installs the INT and TERM traps
#   cb_lifecycle_mark_mutation          # the next change is the first one
#
# A signal that arrives first has changed nothing: the trap exits 130 (INT) or
# 143 (TERM), which runs the entrypoint's own EXIT trap (its staging cleanup)
# and closes the lock descriptor with the process. One that arrives after the
# mark prints that the operation was interrupted after changes began and
# exits the same way, leaving the host for `cb doctor` to inspect. Either way
# an orchestrated operation (CB_LIFECYCLE_OPERATION) records the interruption
# as the contract's section 4 defines it: `interrupted`, closed with outcome
# interrupted, before the mark; `recovery_required` with cause interrupted
# after it. Bash runs a trap only once its foreground command has finished, so
# a child still mutating is waited for and the lock stays held until it exits;
# `wait` covers background children. The trap string ends in `exit`, which the
# library's functions never do. Arming again, as a nested acquire does, keeps
# the mark. Only INT and TERM reach it, so no other
# failure's status changes, and an existing ERR or EXIT trap is left alone.
cb_lifecycle_arm_interrupt() {
  _CB_LIFECYCLE_MUTATED="${_CB_LIFECYCLE_MUTATED-}"
  trap 'cb_lifecycle_interrupted INT; exit 130' INT
  trap 'cb_lifecycle_interrupted TERM; exit 143' TERM
}

cb_lifecycle_mark_mutation() {
  _CB_LIFECYCLE_MUTATED=1
}

# The body of the traps above, for signal name $1. Always returns 0.
cb_lifecycle_interrupted() {
  trap '' INT TERM
  wait 2>/dev/null || true
  if [[ -n "${_CB_LIFECYCLE_MUTATED:-}" ]]; then
    printf '%s\n' "Interrupted by $1 after changes began. Run 'cb doctor' (or re-run the command) to inspect what was changed." >&2
    if _cb_lifecycle_valid_operation "${CB_LIFECYCLE_OPERATION:-}"; then
      cb_lifecycle_checkpoint state=recovery_required cause=interrupted error_code=INTERRUPTED \
        "error_reason=interrupted by $1 after changes began" || true
    fi
  elif _cb_lifecycle_valid_operation "${CB_LIFECYCLE_OPERATION:-}"; then
    cb_lifecycle_checkpoint state=interrupted cause=interrupted outcome=interrupted || true
  fi
  return 0
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
    "lib/bundle-signature.sh bundle-signature.sh 644" \
    "lib/release-retention.sh release-retention.sh 644" "scripts/rollback-release.sh rollback-release.sh 755")
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
cb_lifecycle_lock_acquire "package postinstall" || exit $?
cb_lifecycle_arm_interrupt
cb_lifecycle_mark_mutation

# ── is this an upgrade? ─────────────────────────────────────────────────────
# Everything below the config/env section is identical either way; what differs
# is the closing act. A fresh install needs the "next steps" text and a service
# the operator starts once they have pointed CB_DB_URL somewhere. An upgrade
# needs the running service to come back on the new binary, and needs to name
# the backup preinstall.sh just took -- printing "Next steps: 1. Edit the env
# file" at an operator who has been running this for a year is noise that hides
# the one line that matters.
#
#   dpkg postinst : "configure" with the OLD version as $2 on upgrade, empty on install
#   rpm  %post    : 1 on a fresh install, 2 or more on upgrade
#   apk           : no argument
case "${1:-}" in
    configure) if [ -n "${2:-}" ]; then IS_UPGRADE=1; else IS_UPGRADE=0; fi ;;
    "")        IS_UPGRADE=0 ;;
    *)         if [ "$1" -ge 2 ] 2>/dev/null; then IS_UPGRADE=1; else IS_UPGRADE=0; fi ;;
esac

# Which packager invoked us. rpm is the one that runs the OLD package's %preun
# *after* this script, which is why the service restore below is not its job.
case "${1:-}" in
    configure) PACKAGER=deb ;;
    "")        PACKAGER=apk ;;
    *)         PACKAGER=rpm ;;
esac

# Overridable for the reason preinstall.sh and rollback.sh give for the same
# thing: a hook that can only read one hardcoded path cannot be exercised
# without installing a package as root, and this one decides whether the service
# comes back after an upgrade.
ENV_FILE="${CB_ENV_FILE:-/etc/circuit-breaker/circuit-breaker.env}"
UNIT_STATE_FILE="${CB_UNIT_STATE_FILE:-/run/circuit-breaker/pre-upgrade-unit-state}"
SERVICE_NAME="${CB_SERVICE_NAME:-circuit-breaker.service}"

# Create system user if it doesn't exist
if ! id -u circuitbreaker >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --home-dir /var/lib/circuit-breaker circuitbreaker
fi

# Create directories
mkdir -p /var/lib/circuit-breaker /var/lib/circuit-breaker/uploads \
         /var/log/circuit-breaker /etc/circuit-breaker
chown -R circuitbreaker:circuitbreaker /var/lib/circuit-breaker
chown circuitbreaker:circuitbreaker /var/log/circuit-breaker
chmod 750 /var/lib/circuit-breaker /var/log/circuit-breaker
chmod 755 /etc/circuit-breaker

# Install default config if not present
if [ ! -f /etc/circuit-breaker/config.toml ]; then
  if [ -f /usr/local/share/circuit-breaker/config.toml.default ]; then
    cp /usr/local/share/circuit-breaker/config.toml.default \
       /etc/circuit-breaker/config.toml
    chmod 640 /etc/circuit-breaker/config.toml
    chown root:circuitbreaker /etc/circuit-breaker/config.toml
  fi
fi

# Generate env file with secrets if not present
if [ ! -f "$ENV_FILE" ]; then
  VAULT_KEY=$(openssl rand -base64 32)
  NATS_TOKEN=$(openssl rand -hex 16)
  cat > "$ENV_FILE" <<EOF
# Circuit Breaker environment — auto-generated during install
CB_DB_URL=postgresql://circuitbreaker:changeme@127.0.0.1:5432/circuitbreaker
CB_VAULT_KEY=${VAULT_KEY}
CB_REDIS_URL=redis://127.0.0.1:6379/0
NATS_AUTH_TOKEN=${NATS_TOKEN}
STATIC_DIR=/opt/circuitbreaker/share/frontend
CB_SHARE_DIR=/opt/circuitbreaker/share
CB_ALEMBIC_INI=/opt/circuitbreaker/share/backend/alembic.ini
CB_AGENT_BINARIES_DIR=/opt/circuitbreaker/agent-binaries
CB_DATA_DIR=/var/lib/circuit-breaker
UPLOADS_DIR=/var/lib/circuit-breaker/uploads
# No forward proxy on a single-node host, and an empty CB_EGRESS_PROXY_URL is
# indistinguishable from an operator who meant to set one. The waiver records
# that running without a proxy is a decision; it waives that requirement alone.
CB_EGRESS_PROXY_URL=
CB_ALLOW_DIRECT_EGRESS=true
EOF
  chmod 600 "$ENV_FILE"
  chown root:circuitbreaker "$ENV_FILE"
fi

# Backfill CB_DATA_DIR into an env file that predates it.
#
# The block above writes the env only when it is absent, so without this an
# existing install upgrades straight back into the crash: the file it already
# has is precisely the one missing this line. Four modules fall back to `/data`
# when CB_DATA_DIR is unset -- the container path -- and the unit runs under
# ProtectSystem=strict, so the service starts, tries to write, and dies with
# `OSError: [Errno 30] Read-only file system: '/data'` on a loop. Found by the
# Tier 3 boot check (ADR 0005 Phase 2), which is the first thing in this
# project's history to install the package and start it on a clean host.
#
# /var/lib/circuit-breaker is not a new choice: the package already creates it,
# owns it to the service user, and the unit already grants it write access. The
# env simply never said so.
#
# UPLOADS_DIR is here for the same reason and was found the same way: fixing
# CB_DATA_DIR moved the crash one layer down to
# `FileNotFoundError: 'data/uploads'`. Its default is *relative*, so it resolves
# against the working directory -- and the unit sets none, so systemd runs the
# service from `/`. A relative default is invisible in review and fatal on a
# packaged host.
#
# CB_ALLOW_DIRECT_EGRESS is the third of the same kind, found by the first run of
# the Phase 3 tree: validate_core_dependencies() refuses to boot when
# CB_EGRESS_PROXY_URL is empty and the waiver is unset, so a host whose env file
# predates the gate stops starting the moment it upgrades onto a version that
# has it. Backfilling does not change what the host does -- it had no proxy
# before and made direct egress anyway -- it records that as the decision the
# gate asks for, which is the default deploy/setup.sh, docker-compose.yml and
# every shipped .env template already use. Each line added is echoed below, so
# the operator sees what was written rather than having it happen silently.
for _kv in \
  "CB_DATA_DIR=/var/lib/circuit-breaker" \
  "UPLOADS_DIR=/var/lib/circuit-breaker/uploads" \
  "CB_EGRESS_PROXY_URL=" \
  "CB_ALLOW_DIRECT_EGRESS=true"; do
  _key="${_kv%%=*}"
  if [ -f "$ENV_FILE" ] \
     && ! grep -q "^${_key}=" "$ENV_FILE"; then
    echo "${_kv}" >> "$ENV_FILE"
    echo "Added ${_kv} to the existing environment file."
  fi
done

# Write install identity (secret-free). Used by /usr/local/bin/cb.
_IDENTITY_VERSION="$(tr -d '[:space:]' </opt/circuitbreaker/share/VERSION 2>/dev/null || echo unknown)"
if [ -f /usr/local/lib/circuitbreaker/install-identity.sh ]; then
  # shellcheck source=/dev/null
  . /usr/local/lib/circuitbreaker/install-identity.sh
elif [ -f /usr/local/share/circuit-breaker/install-identity.sh ]; then
  # shellcheck source=/dev/null
  . /usr/local/share/circuit-breaker/install-identity.sh
fi
if command -v write_install_identity >/dev/null 2>&1; then
  write_install_identity /etc/circuit-breaker/install-identity.json \
    mode=package \
    runtime=pbs \
    version="${_IDENTITY_VERSION}" \
    config_path=/etc/circuit-breaker/config.toml \
    data_dir=/var/lib/circuit-breaker \
    env_file="$ENV_FILE" \
    cli_path=/usr/local/bin/cb \
    health_url=http://127.0.0.1:8000/api/v1/readyz \
    service_names="circuit-breaker.service,circuit-breaker-discovery.service,circuit-breaker-worker@notification.service,circuit-breaker-worker@telemetry.service,circuit-breaker-worker@integration.service,circuit-breaker-worker@monitor_scheduler.service,circuit-breaker-worker@monitor_poll.service,circuit-breaker-worker@monitor_probe_dispatch.service" \
    || true
fi

# Enable and reload systemd
systemctl daemon-reload
systemctl enable circuit-breaker.service

if [ "$IS_UPGRADE" -eq 1 ]; then
  # try-restart, not restart: it acts only on a unit that was already running,
  # so an upgrade cannot start a service the operator had deliberately stopped.
  # Without this the upgrade leaves the OLD binary running -- rpm replaces the
  # files underneath a live process and nothing tells systemd -- so the operator
  # sees a successful upgrade and a service still serving the previous version
  # until something restarts it.
  systemctl try-restart "$SERVICE_NAME"

  # ...which is not enough on deb, and that was ADR 0005 Phase 3's F13. dpkg runs
  # `old-prerm upgrade` BEFORE `new-preinst upgrade` (Policy 6.5) and this script
  # last, so on an upgrade from any released version the legacy prerm has already
  # stopped the service by the time we get here -- and try-restart acts only on a
  # unit that is already running, so it does nothing and the upgrade finishes with
  # the product down. The row caught it as "service is not running after the
  # upgrade", with the unit correctly enabled because the `systemctl enable` above
  # had undone the prerm's disable.
  #
  # Not on rpm: there the old %preun runs AFTER this script, so anything started
  # here is stopped again moments later. packaging/posttrans.sh owns that path,
  # and it is the only scriptlet that runs late enough to.
  #
  # preinstall.sh's stamp cannot be fully trusted here for the same ordering
  # reason: the legacy prerm stopped and disabled the unit before preinst could
  # look, so the stamp reads enabled=0 active=0 for a service that was running a
  # moment earlier. Enabled-and-not-active is the one state that ordering cannot
  # manufacture -- only a prerm that no-ops on upgrade leaves it -- so it is taken
  # as the operator having stopped the service on purpose, and is the single case
  # that suppresses the restore. Upgrading from a version predating slice 1's
  # prerm fix cannot distinguish "was running" from "was stopped" and restores the
  # service: that is Debian's own convention, and the safer of the two errors
  # against an upgrade that silently leaves the product down.
  if [ "$PACKAGER" != "rpm" ]; then
    _was_enabled=""
    _was_active=""
    if [ -f "$UNIT_STATE_FILE" ]; then
      while IFS='=' read -r _k _v; do
        case "$_k" in
          enabled) _was_enabled="$_v" ;;
          active)  _was_active="$_v" ;;
        esac
      done < "$UNIT_STATE_FILE"
      rm -f "$UNIT_STATE_FILE"
    fi
    if [ "$_was_enabled" = "1" ] && [ "$_was_active" = "0" ]; then
      echo "Circuit Breaker: leaving $SERVICE_NAME stopped — it was stopped before this upgrade."
    elif ! systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
      systemctl start "$SERVICE_NAME" >/dev/null 2>&1 || true
      echo "Circuit Breaker: restarted $SERVICE_NAME — the previous package's removal scriptlet stopped it during the upgrade."
    fi
  fi

  echo ""
  echo "Circuit Breaker upgraded successfully."
  echo ""
  # Name the newest pre-upgrade dump rather than a glob. This is the rollback
  # artifact preinstall.sh just wrote, and the operator who needs it is not in a
  # position to go looking.
  _latest_backup=""
  for _candidate in /var/lib/circuit-breaker/backups/pre-upgrade-*.sql; do
    [ -f "$_candidate" ] && _latest_backup="$_candidate"
  done
  if [ -n "$_latest_backup" ]; then
    echo "  Rolling back this upgrade:"
    echo "    1. sudo systemctl stop circuit-breaker"
    echo "    2. reinstall the previous package (dnf downgrade / apt install circuit-breaker=<old>)"
    echo "    3. sudo circuit-breaker-rollback $_latest_backup"
    echo ""
    echo "  Step 2 is not optional. Migrations have run, and the pre-upgrade dump"
    echo "  restores the OLD schema — the new binary cannot serve it."
  else
    echo "  No pre-upgrade backup was taken, so this upgrade cannot be rolled back."
    echo "  See docs/installation/upgrading.md."
  fi
  echo ""
else
  echo ""
  echo "Circuit Breaker installed successfully."
  echo ""
  echo "  Next steps:"
  echo "    1. Edit $ENV_FILE"
  echo "       - Set CB_DB_URL to your PostgreSQL connection string"
  echo "       - Ensure PostgreSQL, Redis, and NATS are running"
  echo "    2. sudo systemctl start circuit-breaker"
  echo "    3. Open http://localhost:8080"
  echo ""
fi
