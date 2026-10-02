#!/usr/bin/env bash
# Roll back only the release retained by the last native installer update.
set -Eeuo pipefail
restore_data=false
npm_result=false
for arg in "$@"; do
  case "$arg" in
    --restore-data) restore_data=true ;;
    --npm-result) npm_result=true ;;
    *) echo 'Usage: rollback-release.sh [--restore-data] [--npm-result]' >&2; exit 2 ;;
  esac
done
[[ "$EUID" -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 6; }
source /usr/local/lib/circuitbreaker/lifecycle.sh
cb_lifecycle_lock_acquire 'native rollback' || exit $?
cb_lifecycle_arm_interrupt
lib=/usr/local/lib/circuitbreaker/release-retention.sh
_cb_lifecycle_trusted_program "$lib" || exit 5
# shellcheck source=/dev/null
source "$lib"
[[ -d "$CB_PREVIOUS_RELEASE" && ! -L "$CB_PREVIOUS_RELEASE" ]] || { echo 'No previous update release is retained.' >&2; exit 3; }
_cb_lifecycle_trusted_program "$CB_PREVIOUS_RELEASE/share/VERSION" || exit 5
_cb_lifecycle_trusted_program "$CB_PREVIOUS_RELEASE/.cb-backup-reference" || exit 5
previous="$(cat "$CB_PREVIOUS_RELEASE/share/VERSION")"
backup="$(cat "$CB_PREVIOUS_RELEASE/.cb-backup-reference")"
[[ "$previous" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || exit 5
[[ "$backup" == /* && -s "$backup" && ! -L "$backup" ]] || exit 7
_cb_lifecycle_trusted_program "$backup" || exit 5
current="$(cat /opt/circuitbreaker/share/VERSION)"
_cb_lifecycle_trusted_program "$CB_PREVIOUS_RELEASE/.cb-replaced-by" || { echo 'The retained release does not record which update replaced it. Nothing was changed.' >&2; exit 3; }
[[ "$(cat "$CB_PREVIOUS_RELEASE/.cb-replaced-by")" == "$current" ]] || { echo "The retained release was not replaced by the installed $current (the last update may have stopped before replacing it). Nothing was changed; run sudo cb doctor." >&2; exit 3; }
cb_lifecycle_begin kind=legacy action=rollback adapter=native "source_version=$current" "target_version=$previous" || exit $?
cb_lifecycle_mark_mutation
finish() {
  local status=$? outcome=committed code=""
  trap - EXIT
  if [[ "$status" -eq 0 ]]; then
    cb_lifecycle_checkpoint state=committed outcome=committed || status=9
  fi
  if [[ "$status" -ne 0 ]]; then
    outcome=recovery_required
    code=MANUAL
    cb_lifecycle_checkpoint state=recovery_required cause=apply_failed error_code=MANUAL 'error_reason=rollback stopped; inspect retained releases and snapshots' || true
    cb_lifecycle_checkpoint state=recovery_required outcome=manual error_code=MANUAL 'error_reason=rollback stopped; inspect retained releases and snapshots' || true
    echo 'Rollback needs inspection. Run sudo cb doctor; snapshots and release trees are retained.' >&2
  fi
  if [[ "$npm_result" == true ]]; then
    /usr/bin/python3 -I -c 'import json,sys
op,outcome,current,target,code=sys.argv[1:]
r=dict(schema_version=1,action="rollback",operation_id=op,outcome=outcome,current_version=current if outcome=="committed" else None,target_version=target,recovery_available=True)
if code:r["error"]=dict(code=code,reason="Inspect retained releases and snapshots with cb doctor.")
print("CIRCUITBREAKER_RESULT="+json.dumps(r))' "$CB_LIFECYCLE_OPERATION" "$outcome" "$previous" "$previous" "$code"
  fi
  exit "$status"
}
trap finish EXIT
# Snapshot current state using the CURRENT builder before restoring old data.
mkdir -p "$CB_UPDATE_SNAPSHOT_DIR" && chmod 700 "$CB_UPDATE_SNAPSHOT_DIR" || exit 7
CB_BACKUP_DIR="$CB_UPDATE_SNAPSHOT_DIR" /usr/local/bin/cb backup || exit 7
if [[ "$restore_data" == true ]]; then
  /usr/local/bin/cb restore --yes "$backup" || exit 9
else
  printf 'Retaining current data. To restore the pre-update snapshot explicitly: sudo cb restore %q\n' "$backup"
fi
cb_release_stop_writers || exit 9
_cb_release_prune /opt/circuitbreaker.retained. || exit 9
retained="$(mktemp -d /opt/circuitbreaker.retained.XXXXXXXX)"
rmdir "$retained"
mv -T -- /opt/circuitbreaker "$retained"
mv -T -- "$CB_PREVIOUS_RELEASE" /opt/circuitbreaker
cb_release_restore_identity || exit 9
systemctl daemon-reload
systemctl restart circuitbreaker.target circuitbreaker-backend
cb_lifecycle_checkpoint state=checking
cb_release_health "$previous" || exit 9
printf 'Rolled back to %s. Current-state safety snapshot and replaced release are retained.\n' "$previous"
