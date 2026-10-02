# shellcheck shell=bash
# Native release retention. Caller holds the lifecycle lock through health.
# Data recovery remains an explicit cb restore; no migration reversal is inferred.
CB_PREVIOUS_RELEASE=/opt/circuitbreaker.previous
_CB_RELEASE_MOVED=false
_CB_RELEASE_BACKUP=""

cb_release_stop_writers() {
  local worker
  for worker in discovery notification telemetry integration monitor_scheduler monitor_poll monitor_probe_dispatch; do
    systemctl stop "circuitbreaker-worker@${worker}" || return 7
  done
  systemctl stop circuitbreaker-backend || return 7
}

cb_release_prepare() {
  [[ "${UPGRADE_MODE:-false}" == true ]] || return 0
  [[ -d /opt/circuitbreaker && ! -L /opt/circuitbreaker ]] || return 7
  # Capture using the OLD builder and schema, before stage0 installs new files.
  local reference
  reference="$(mktemp)" || return 7
  chmod 600 "$reference"
  if ! /usr/local/bin/cb backup 4>"$reference"; then
    rm -f -- "$reference"
    echo 'Pre-update snapshot failed; release was not replaced.' >&2
    return 7
  fi
  IFS= read -r _CB_RELEASE_BACKUP < "$reference" || true
  rm -f -- "$reference"
  [[ -n "$_CB_RELEASE_BACKUP" && -s "$_CB_RELEASE_BACKUP" ]] || return 7
  printf 'Backup: %s\nRestore manually: sudo cb restore %q\n' "$_CB_RELEASE_BACKUP" "$_CB_RELEASE_BACKUP"
  cb_release_stop_writers || return $?
  if [[ -e "$CB_PREVIOUS_RELEASE" || -L "$CB_PREVIOUS_RELEASE" ]]; then
    [[ -d "$CB_PREVIOUS_RELEASE" && ! -L "$CB_PREVIOUS_RELEASE" ]] || return 7
    # Keep earlier recovery artifacts; never erase a sole recovery point.
    local archived
    archived="$(mktemp -d /opt/circuitbreaker.retained.XXXXXXXX)" || return 7
    rmdir "$archived" || return 7
    mv -T -- "$CB_PREVIOUS_RELEASE" "$archived" || return 7
  fi
  mv -T -- /opt/circuitbreaker "$CB_PREVIOUS_RELEASE" || return 7
  _CB_RELEASE_MOVED=true
  (umask 077; printf '%s\n' "$_CB_RELEASE_BACKUP" > "$CB_PREVIOUS_RELEASE/.cb-backup-reference") || return 7
}

cb_release_health() {
  local expected="$1" attempt body
  [[ "$expected" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || return 7
  for ((attempt=0; attempt<60; attempt++)); do
    if curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/api/v1/readyz >/dev/null; then
      body="$(curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/api/v1/health)" || body=""
      if printf '%s' "$body" | /usr/bin/python3 -I -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("version") == sys.argv[1] else 1)' "$expected"; then
        return 0
      fi
    fi
    sleep 2
  done
  echo "Readiness/version check failed for $expected." >&2
  return 7
}

cb_release_revert_failed() {
  [[ "$_CB_RELEASE_MOVED" == true ]] || return 0
  # Retain the failed tree for diagnosis instead of deleting changed state.
  cb_release_stop_writers || return 9
  local failed
  failed="$(mktemp -d /opt/circuitbreaker.failed.XXXXXXXX)" || return 9
  rmdir "$failed" || return 9
  if [[ -e /opt/circuitbreaker ]]; then
    [[ ! -L /opt/circuitbreaker ]] || return 9
    mv -T -- /opt/circuitbreaker "$failed" || return 9
  fi
  mv -T -- "$CB_PREVIOUS_RELEASE" /opt/circuitbreaker || return 9
  _CB_RELEASE_MOVED=false
  systemctl daemon-reload || return 9
  systemctl restart circuitbreaker.target circuitbreaker-backend || return 9
  printf 'Previous release restored. Database restoration is manual: sudo cb restore %q\n' "$_CB_RELEASE_BACKUP" >&2
  local previous
  previous="$(cat /opt/circuitbreaker/share/VERSION)" || return 9
  cb_release_health "$previous" || return 9
  return 8
}
