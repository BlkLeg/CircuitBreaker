# shellcheck shell=bash
# Native release retention. Caller holds the lifecycle lock through health.
# Data recovery remains an explicit cb restore; no migration reversal is inferred.
CB_PREVIOUS_RELEASE=/opt/circuitbreaker.previous
# Root-owned, so rollback can trust the snapshot it restores; a HOME-relative
# default could land under a user's home when sudo keeps HOME.
CB_UPDATE_SNAPSHOT_DIR=/var/backups/circuitbreaker
_CB_RELEASE_MOVED=false
_CB_RELEASE_STOPPED=false
_CB_RELEASE_BACKUP=""

cb_release_stop_writers() {
  local worker
  for worker in discovery notification telemetry integration monitor_scheduler monitor_poll monitor_probe_dispatch; do
    systemctl stop "circuitbreaker-worker@${worker}" || return 7
  done
  systemctl stop circuitbreaker-backend || return 7
}

# Remove earlier trees under one path prefix (the previous, retained or failed
# release) so each update keeps one of each instead of a full release per run.
_cb_release_prune() {
  local tree
  for tree in "$1"*; do
    [[ -e "$tree" || -L "$tree" ]] || continue
    rm -rf -- "$tree" || return 7
  done
}

cb_release_prepare() {
  [[ "${UPGRADE_MODE:-false}" == true ]] || return 0
  [[ -d /opt/circuitbreaker && ! -L /opt/circuitbreaker ]] || return 7
  # Capture with the OLD runtime and schema, before stage0 installs new files.
  # The staged bundle's cb drives it: an installed cb older than 0.4.7 has no
  # native snapshot route and never reports the path on fd 4.
  local reference cli=/usr/local/bin/cb
  [[ -n "${CB_BUNDLE_DIR:-}" && -f "$CB_BUNDLE_DIR/deploy/cli/cb" ]] && cli="$CB_BUNDLE_DIR/deploy/cli/cb"
  reference="$(mktemp)" || return 7
  chmod 600 "$reference"
  mkdir -p "$CB_UPDATE_SNAPSHOT_DIR" && chmod 700 "$CB_UPDATE_SNAPSHOT_DIR" || return 7
  if ! CB_BACKUP_DIR="$CB_UPDATE_SNAPSHOT_DIR" bash "$cli" backup 4>"$reference"; then
    rm -f -- "$reference"
    echo 'Pre-update snapshot failed; release was not replaced.' >&2
    return 7
  fi
  IFS= read -r _CB_RELEASE_BACKUP < "$reference" || true
  rm -f -- "$reference"
  [[ -n "$_CB_RELEASE_BACKUP" && -s "$_CB_RELEASE_BACKUP" ]] || return 7
  printf 'Backup: %s\nRestore manually: sudo cb restore %q\n' "$_CB_RELEASE_BACKUP" "$_CB_RELEASE_BACKUP"
  _CB_RELEASE_STOPPED=true
  cb_release_stop_writers || return $?
  # The release about to move aside supersedes the older one; the older
  # snapshot itself stays in the snapshot directory.
  _cb_release_prune "$CB_PREVIOUS_RELEASE" || return 7
  mv -T -- /opt/circuitbreaker "$CB_PREVIOUS_RELEASE" || return 7
  _CB_RELEASE_MOVED=true
  if [[ -f /etc/circuitbreaker/install-identity.json ]]; then
    _cb_lifecycle_trusted_program /etc/circuitbreaker/install-identity.json || return 7
    cp -- /etc/circuitbreaker/install-identity.json "$CB_PREVIOUS_RELEASE/.cb-install-identity.json" || return 7
    chmod 644 "$CB_PREVIOUS_RELEASE/.cb-install-identity.json" || return 7
  fi
  (umask 077; printf '%s\n' "$_CB_RELEASE_BACKUP" > "$CB_PREVIOUS_RELEASE/.cb-backup-reference") || return 7
  # Rollback applies only while the release this one was replaced by is installed.
  (umask 077; printf '%s\n' "${CB_EXPECTED_VERSION:-}" > "$CB_PREVIOUS_RELEASE/.cb-replaced-by") || return 7
}

cb_release_restore_identity() {
  local saved=/opt/circuitbreaker/.cb-install-identity.json tmp
  [[ -f "$saved" ]] || return 0
  _cb_lifecycle_trusted_program "$saved" || return 9
  tmp="$(mktemp /etc/circuitbreaker/.install-identity.XXXXXXXX)" || return 9
  if ! cp -- "$saved" "$tmp" || ! chmod 644 "$tmp" || ! mv -T -- "$tmp" /etc/circuitbreaker/install-identity.json; then
    rm -f -- "$tmp"
    return 9
  fi
}

# Ready on /readyz and running the expected release. The API reports its
# version only to authenticated callers, so the version is the installed
# tree's: the services were just restarted from /opt/circuitbreaker.
cb_release_health() {
  local expected="$1" attempt installed
  [[ "$expected" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || return 7
  installed="$(cat /opt/circuitbreaker/share/VERSION 2>/dev/null)" || installed=""
  if [[ "$installed" != "$expected" ]]; then
    echo "Installed release is ${installed:-unknown}, expected $expected." >&2
    return 7
  fi
  for ((attempt=0; attempt<60; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/api/v1/readyz >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "Readiness/version check failed for $expected." >&2
  return 7
}

cb_release_revert_failed() {
  if [[ "$_CB_RELEASE_MOVED" != true ]]; then
    [[ "$_CB_RELEASE_STOPPED" == true ]] || return 0
    systemctl restart circuitbreaker.target circuitbreaker-backend || return 9
    cb_release_health "$(cat /opt/circuitbreaker/share/VERSION)" || return 9
    return 8
  fi
  # Retain the failed tree for diagnosis instead of deleting changed state.
  cb_release_stop_writers || return 9
  _cb_release_prune /opt/circuitbreaker.failed. || return 9
  local failed
  failed="$(mktemp -d /opt/circuitbreaker.failed.XXXXXXXX)" || return 9
  rmdir "$failed" || return 9
  if [[ -e /opt/circuitbreaker ]]; then
    [[ ! -L /opt/circuitbreaker ]] || return 9
    mv -T -- /opt/circuitbreaker "$failed" || return 9
  fi
  mv -T -- "$CB_PREVIOUS_RELEASE" /opt/circuitbreaker || return 9
  _CB_RELEASE_MOVED=false
  cb_release_restore_identity || return 9
  systemctl daemon-reload || return 9
  systemctl restart circuitbreaker.target circuitbreaker-backend || return 9
  printf 'Previous release restored. Database restoration is manual: sudo cb restore %q\n' "$_CB_RELEASE_BACKUP" >&2
  local previous
  previous="$(cat /opt/circuitbreaker/share/VERSION)" || return 9
  cb_release_health "$previous" || return 9
  return 8
}
