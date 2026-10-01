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
#   /var/lib/circuitbreaker-lifecycle/                0755  (history.json, Task 3)
#   /var/lib/circuitbreaker-lifecycle/private/        0700
#   /var/lib/circuitbreaker-lifecycle/private/lock    0600  flock(2) target; never removed or truncated
#   /var/lib/circuitbreaker-lifecycle/private/owner   0600  diagnostics only; never authority
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

# packages/cli/src/exit-codes.js; tests/build/test_lifecycle_lock.py keeps them equal.
CB_LIFECYCLE_EXIT_USAGE=2
CB_LIFECYCLE_EXIT_PERMISSION=6
CB_LIFECYCLE_EXIT_PREFLIGHT=7
CB_LIFECYCLE_EXIT_LOCKED=10

# The holding state of this shell. Never exported, never read from the
# environment: _FD is the descriptor, _ID its dev:inode, _PID the process that
# opened or joined it ($BASHPID, so a subshell is a different holder) and
# _DEPTH how many acquisitions in that process are still unreleased.
_CB_LIFECYCLE_STATE_VARS=(_CB_LIFECYCLE_LOCK_FD _CB_LIFECYCLE_LOCK_ID _CB_LIFECYCLE_LOCK_PID _CB_LIFECYCLE_LOCK_DEPTH)

# Drop any holding state that is exported: it came from a parent's
# environment (or was exported by hand), and proves nothing. Every public
# entry point runs this first.
_cb_lifecycle_forget_exported_state() {
  local name
  for name in "${_CB_LIFECYCLE_STATE_VARS[@]}"; do
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
  unset "${_CB_LIFECYCLE_STATE_VARS[@]}" CB_LIFECYCLE_LOCK_FD CB_LIFECYCLE_OPERATION
}

# In a subshell that is about to exec something that must not hold the lock:
# close the descriptor and drop the handoff variables.
_cb_lifecycle_drop_lock() {
  local fd
  for fd in "${_CB_LIFECYCLE_LOCK_FD:-}" "${CB_LIFECYCLE_LOCK_FD:-}"; do
    if [[ "$fd" =~ ^[1-9][0-9]{0,4}$ ]] && (( fd >= 3 )); then
      exec {fd}<&-
    fi
  done
  unset "${_CB_LIFECYCLE_STATE_VARS[@]}" CB_LIFECYCLE_LOCK_FD CB_LIFECYCLE_OPERATION
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
