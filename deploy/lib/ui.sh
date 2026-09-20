# shellcheck shell=bash
#
# Circuit Breaker installer rendering.
#
# The installer used to narrate 269 individual steps, because narration was the
# only evidence anyone had that it worked. Every subprocess was already silenced
# — each apt-get, initdb and systemctl start redirects to $LOG_FILE — so all of
# that noise was ours, and all of it is replaced here by seven headlines, a bar
# and a clock.
#
# Three rules shaped this file:
#
#   * The log is a sink, not a side effect. Every event reaches $LOG_FILE at
#     full detail in every mode, so a quiet screen costs nothing diagnostically.
#   * The mode is resolved once. The old helpers re-decided "am I a TTY / should
#     I log this" at each call site, which is how four output modes drift apart
#     the first time someone adds a step.
#   * The screen is quiet exactly as long as nothing is wrong. On failure the
#     output gets LONGER: the ledger, the log tail the quiet mode hid, and then
#     the diagnostics cb_fail already ran.
#
# Sourced by install.sh before anything else, and re-sourced by deploy/setup.sh
# because that file is sourced into the same shell after the bundle lands.

# Idempotent: setup.sh re-sources this file in the same shell.
if [[ -n "${_CB_UI_LOADED:-}" ]]; then
  return 0
fi
_CB_UI_LOADED=true

# Palette, taken from the banner so the bar belongs to the same picture.
_CB_ORANGE=$'\033[38;5;209m'
_CB_VIOLET=$'\033[38;5;99m'
_CB_GREEN=$'\033[0;32m'
_CB_RED=$'\033[0;31m'
_CB_YELLOW=$'\033[1;33m'
_CB_BOLD=$'\033[1m'
_CB_DIM=$'\033[2m'
_CB_RESET=$'\033[0m'

CB_UI_MODE="plain"
_CB_LIVE_ON=false
_CB_LAST_RENDER=""
_CB_START_EPOCH=0
_CB_OPEN_PHASE=""
_CB_OPEN_HEADLINE=""
_CB_OPEN_START=0
_CB_OPEN_FRACTION=0
_CB_OPEN_TICKS=0
_CB_OPEN_TICKS_DONE=0
_CB_DONE_WEIGHT=0
_CB_LAST_ETA=-1
_CB_ETA_TEXT=""

# Phase weights, as percentages of a whole flow. They must sum to 100 and every
# key used at runtime must appear here; tests/build/test_installer_phase_model.py
# asserts both, per table.
#
# These are ratios of measured medians. A phase is a unit of elapsed time a user
# can FEEL, not a unit of implementation, which is why the 21 old install
# sections collapse unevenly: "Writing Service Scripts" was instant and
# "Installing Dependencies" is most of the wall clock.
#
# One table per flow. A phase is a unit of elapsed time a user can feel, so the
# three flows weight differently: an uninstall is dominated by stopping services
# and removing a data directory, an upgrade by its pre-upgrade backup.
declare -gA CB_PHASE_WEIGHTS_INSTALL=(
  [preflight]=2 [bundle]=12 [files]=6 [deps]=45 [database]=15 [services]=12 [start]=8
)
# The upgrade path runs through two functions in the same shell: install.sh's
# main() does its own preflight/download/stage-the-bundle before handing off to
# run_upgrade(), which then does its own checks, backup, apply and restart. All
# eight phases below are opened exactly once across that combined sequence —
# main()'s preflight/bundle/files are distinct keys from run_upgrade's
# upgrade_check/apply_bundle, precisely so the two functions' phases never
# collide on the same key and double-count weight. (They used to: main()'s
# preflight+bundle and run_upgrade's own preflight+bundle shared keys, so the
# live table summed to 125 for one run and the bar hit 100% before the upgrade
# actually finished. tests/build/test_installer_phase_model.py's
# test_upgrade_sequence_has_no_duplicate_keys and
# test_upgrade_sequence_sums_to_one_hundred pin the fix.)
declare -gA CB_PHASE_WEIGHTS_UPGRADE=(
  [preflight]=3 [bundle]=12 [files]=5
  [upgrade_check]=5 [backup]=35 [apply_bundle]=15 [apply]=15 [start]=10
)
declare -gA CB_PHASE_WEIGHTS_UNINSTALL=(
  [preflight]=10 [stop]=30 [remove]=40 [cleanup]=20
)

# The live table. cb_ui_use_weights swaps it; the renderer only ever reads this.
declare -gA CB_PHASE_WEIGHTS=()

cb_ui_use_weights() {
  local table="$1" key
  local -n _source="$table"
  CB_PHASE_WEIGHTS=()
  for key in "${!_source[@]}"; do
    CB_PHASE_WEIGHTS["$key"]="${_source[$key]}"
  done
  _cb_log "ui: weights=${table}"
}

declare -ga CB_PHASE_ORDER=(preflight bundle files deps database services start)

# Completed phases, for the ledger: "key|headline|seconds".
declare -ga _CB_LEDGER=()

# True when stdout is a terminal at least $1 columns wide.
#
# Deliberately a copy of install.sh's cb_term_at_least rather than a call to it:
# this file is sourced before that function is guaranteed to exist, and the
# comment there explains why it must never be invoked in a command substitution
# (a pipe replaces stdout and `-t 1` then answers for the pipe).
_cb_ui_term_at_least() {
  local want="$1" cols=""
  [[ -t 1 ]] || return 1
  cols="$(tput cols 2>/dev/null || true)"
  [[ -n "$cols" ]] || cols="$(stty size <&1 2>/dev/null | cut -d' ' -f2 || true)"
  [[ -n "$cols" ]] || cols="${COLUMNS:-}"
  [[ "$cols" =~ ^[0-9]+$ ]] || return 1
  (( cols >= want ))
}

_cb_ui_columns() {
  local cols=""
  cols="$(tput cols 2>/dev/null || true)"
  [[ -n "$cols" ]] || cols="${COLUMNS:-80}"
  [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
  printf '%s' "$cols"
}

# Every event lands here, at full detail, in every mode. Read $LOG_FILE on each
# call rather than caching it: it is /tmp/cb-bootstrap.log until
# stage0_preflight moves it to ${CB_DATA_DIR}/logs/install.log, and a cached
# value would send half the run to a file that gets deleted.
_cb_log() {
  [[ -n "${LOG_FILE:-}" ]] || return 0
  printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$1" >> "${LOG_FILE}" 2>/dev/null || true
}

cb_ui_init() {
  _CB_START_EPOCH="$(date +%s)"

  if [[ "${CB_VERBOSE:-false}" == "true" ]]; then
    CB_UI_MODE="verbose"
  elif [[ "${UNATTENDED:-false}" == "true" ]] \
    || [[ "${CI:-}" == "true" ]] \
    || [[ -n "${NO_COLOR:-}" ]] \
    || [[ "${TERM:-dumb}" == "dumb" ]] \
    || ! _cb_ui_term_at_least 66; then
    CB_UI_MODE="plain"
  else
    CB_UI_MODE="tty"
  fi

  _cb_log "ui: mode=${CB_UI_MODE}"

  if [[ "${CB_UI_MODE}" == "tty" ]]; then
    # Installed before the cursor is hidden, so an interrupt can never leave a
    # terminal with no cursor.
    trap 'cb_ui_teardown' EXIT
    printf '\033[?25l'
  fi
}

cb_ui_teardown() {
  if [[ "${CB_UI_MODE}" == "tty" ]]; then
    _cb_live_clear
    printf '\033[?25h'
  fi
}

_cb_live_clear() {
  [[ "${_CB_LIVE_ON}" == "true" ]] || return 0
  # Cursor sits at the end of the timer line. Clear it, step up to the bar line,
  # clear that. Never `clear`, and never absolute positioning: this runs inside
  # somebody's scrollback, not on a screen we own.
  printf '\r\033[K'
  printf '\033[1A\r\033[K'
  _CB_LIVE_ON=false
  _CB_LAST_RENDER=""
}

_cb_overall_percent() {
  local open_weight=0 pct
  if [[ -n "${_CB_OPEN_PHASE}" ]]; then
    open_weight="${CB_PHASE_WEIGHTS[${_CB_OPEN_PHASE}]:-0}"
  fi
  # Integer arithmetic throughout: bash has no floats, and a percentage is an
  # integer anyway. _CB_OPEN_FRACTION is held in hundredths.
  pct=$(( _CB_DONE_WEIGHT + (open_weight * _CB_OPEN_FRACTION) / 100 ))
  (( pct > 100 )) && pct=100
  (( pct < 0 )) && pct=0
  printf '%s' "$pct"
}

_cb_human_duration() {
  local total="$1" minutes seconds
  minutes=$(( total / 60 ))
  seconds=$(( total % 60 ))
  if (( minutes > 0 )); then
    printf '%dm %02ds' "$minutes" "$seconds"
  else
    printf '%ds' "$seconds"
  fi
}

# Remaining time, subject to the three rules that stop it lying:
#   * clamped monotone non-increasing — a displayed estimate never grows;
#   * "estimating..." below 5%, where the divisor is noise;
#   * "taking longer than expected" — not a number — once the open phase has run
#     past twice its weighted budget. A slow Debian mirror degrades to honest
#     silence rather than to a confident wrong number.
#
# Written as a state update, not a printer: the monotone clamp needs to persist
# _CB_LAST_ETA across calls, and a function invoked as `$(...)` runs in a
# subshell, so any assignment it makes dies with that subshell. This function
# is therefore always called directly (never inside a command substitution),
# and _cb_render_eta below is left as a pure printer of the text it leaves in
# _CB_ETA_TEXT.
_cb_update_eta() {
  local pct elapsed remaining open_weight open_elapsed projected_total expected_phase
  pct="$(_cb_overall_percent)"
  elapsed=$(( $(date +%s) - _CB_START_EPOCH ))

  # Below 5% overall, the divisor behind any estimate — including the overrun
  # budget below — is noise: one phase's early seconds dominate `elapsed`
  # before anything has finished. Every run starts here, so the overrun check
  # must run AFTER this guard, not before it — otherwise the pessimistic
  # message is the first thing a TTY user ever sees, a few seconds into
  # preflight, every single time.
  if (( pct < 5 )); then
    _CB_ETA_TEXT='estimating...'
    return 0
  fi

  if [[ -n "${_CB_OPEN_PHASE}" ]]; then
    open_weight="${CB_PHASE_WEIGHTS[${_CB_OPEN_PHASE}]:-0}"
    open_elapsed=$(( $(date +%s) - _CB_OPEN_START ))
    # The budget a phase "should" take, projected from a whole-run estimate
    # rather than from elapsed-so-far. Budgeting off raw `elapsed` collapses
    # for the phase currently open: elapsed is almost entirely that phase's
    # own time, so "elapsed * open_weight / 100" is roughly open_elapsed
    # itself and the overrun ratio trips almost immediately regardless of the
    # phase's actual weight. Projecting the total run length from the rate
    # observed so far (elapsed * 100 / pct) and taking this phase's share of
    # THAT projected total gives a budget that reflects the whole flow, not
    # just what has happened inside this one phase.
    projected_total=$(( (elapsed * 100) / pct ))
    expected_phase=$(( (projected_total * open_weight) / 100 + 1 ))
    # An absolute floor alongside the relative one: a low-weight phase has a
    # small expected_phase, so the 2x ratio alone can still trip within a
    # couple of seconds of ordinary noise. Nothing is reported "taking longer
    # than expected" before the open phase itself has run at least 30s.
    if (( open_elapsed >= 30 )) && (( open_elapsed > expected_phase * 2 )); then
      _CB_ETA_TEXT='taking longer than expected'
      return 0
    fi
  fi

  remaining=$(( (elapsed * (100 - pct)) / pct ))
  if (( _CB_LAST_ETA >= 0 )) && (( remaining > _CB_LAST_ETA )); then
    remaining="${_CB_LAST_ETA}"
  fi
  _CB_LAST_ETA="$remaining"
  _CB_ETA_TEXT="~$(_cb_human_duration "$remaining") remaining"
}

# Pure printer: prints whatever _cb_update_eta last computed. Safe to call
# from inside a command substitution because it writes nothing.
_cb_render_eta() {
  printf '%s' "${_CB_ETA_TEXT}"
}

_cb_render_live() {
  local pct cols width filled empty bar elapsed
  pct="$(_cb_overall_percent)"
  cols="$(_cb_ui_columns)"
  width=$(( cols - 28 ))
  (( width > 32 )) && width=32
  (( width < 10 )) && width=10
  filled=$(( (pct * width) / 100 ))
  empty=$(( width - filled ))
  elapsed=$(( $(date +%s) - _CB_START_EPOCH ))

  bar=""
  (( filled > 0 )) && bar+="${_CB_ORANGE}$(printf '█%.0s' $(seq 1 "$filled"))${_CB_RESET}"
  (( empty > 0 )) && bar+="${_CB_VIOLET}$(printf '░%.0s' $(seq 1 "$empty"))${_CB_RESET}"

  printf '  %s  %3d%%\n' "$bar" "$pct"
  printf '  %s%s elapsed · %s%s' \
    "${_CB_DIM}" "$(_cb_human_duration "$elapsed")" "$(_cb_render_eta)" "${_CB_RESET}"
}

# Redraw only when the rendered text actually changed. The timer changes once a
# second and the percentage only when it crosses an integer, so this is well
# under the 10 Hz ceiling the design asks for while costing no timer plumbing.
_cb_live_draw() {
  [[ "${CB_UI_MODE}" == "tty" ]] || return 0
  local rendered
  # _cb_update_eta must run here, in the current shell: _cb_render_live below
  # is captured with $(...), and anything a subshell assigns is gone the
  # instant that subshell exits.
  _cb_update_eta
  rendered="$(_cb_render_live)"
  [[ "$rendered" == "${_CB_LAST_RENDER}" ]] && return 0
  _cb_live_clear
  printf '%s' "$rendered"
  _CB_LAST_RENDER="$rendered"
  _CB_LIVE_ON=true
}

cb_phase_begin() {
  local key="$1" headline="$2"
  _CB_OPEN_PHASE="$key"
  _CB_OPEN_HEADLINE="$headline"
  _CB_OPEN_START="$(date +%s)"
  _CB_OPEN_FRACTION=0
  _CB_OPEN_TICKS=0
  _CB_OPEN_TICKS_DONE=0
  _cb_log "phase begin: ${key} — ${headline}"

  case "${CB_UI_MODE}" in
    tty)
      _cb_live_clear
      printf '  %s▸%s %s\n' "${_CB_ORANGE}" "${_CB_RESET}" "$headline"
      _cb_live_draw
      ;;
    plain|verbose)
      printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$headline"
      ;;
  esac
}

# Declare how many sub-steps the open phase has, so cb_phase_tick can advance
# the fraction without every stage inventing its own arithmetic.
cb_phase_steps() {
  _CB_OPEN_TICKS="$1"
  _CB_OPEN_TICKS_DONE=0
}

cb_phase_tick() {
  (( _CB_OPEN_TICKS > 0 )) || return 0
  _CB_OPEN_TICKS_DONE=$(( _CB_OPEN_TICKS_DONE + 1 ))
  (( _CB_OPEN_TICKS_DONE > _CB_OPEN_TICKS )) && _CB_OPEN_TICKS_DONE="${_CB_OPEN_TICKS}"
  _CB_OPEN_FRACTION=$(( (_CB_OPEN_TICKS_DONE * 100) / _CB_OPEN_TICKS ))
  _cb_live_draw
}

# Fraction of the open phase, as a decimal between 0 and 1 with at most two
# decimal places, e.g. `cb_progress 0.42`. Used where a real measurement exists
# — the download polls the partial file against the asset size the release JSON
# already reported.
cb_progress() {
  local raw="$1" whole fraction
  whole="${raw%%.*}"
  fraction="${raw#*.}"
  [[ "$fraction" == "$raw" ]] && fraction="0"
  fraction="${fraction}00"
  fraction="${fraction:0:2}"
  if [[ "$whole" == "1" ]]; then
    _CB_OPEN_FRACTION=100
  else
    _CB_OPEN_FRACTION=$(( 10#${fraction} ))
  fi
  _cb_live_draw
}

cb_phase_end() {
  local key="$1" seconds
  seconds=$(( $(date +%s) - _CB_OPEN_START ))
  _CB_DONE_WEIGHT=$(( _CB_DONE_WEIGHT + ${CB_PHASE_WEIGHTS[${key}]:-0} ))
  _CB_LEDGER+=("${key}|${_CB_OPEN_HEADLINE}|${seconds}")
  _cb_log "phase end: ${key} (${seconds}s)"

  case "${CB_UI_MODE}" in
    tty)
      _cb_live_clear
      # Reprint the headline as a completed line, replacing the ▸ marker.
      printf '  %s✓%s %-42s %s%s%s\n' \
        "${_CB_GREEN}" "${_CB_RESET}" "${_CB_OPEN_HEADLINE}" \
        "${_CB_DIM}" "$(_cb_human_duration "$seconds")" "${_CB_RESET}"
      ;;
    plain|verbose)
      printf '[%s] %s — done in %s\n' \
        "$(date '+%H:%M:%S')" "${_CB_OPEN_HEADLINE}" "$(_cb_human_duration "$seconds")"
      ;;
  esac

  _CB_OPEN_PHASE=""
  _CB_OPEN_HEADLINE=""
  _CB_OPEN_FRACTION=0

  [[ "${CB_UI_MODE}" == "tty" ]] && _cb_live_draw
  return 0
}

# Log always; screen only in verbose. This is where the 269 old narration lines
# land, which is why nothing is lost by making the screen quiet.
cb_detail() {
  _cb_log "detail: $1"
  if [[ "${CB_UI_MODE}" == "verbose" ]]; then
    printf '    %s%s%s\n' "${_CB_DIM}" "$1" "${_CB_RESET}"
  fi
}

# Log and screen in EVERY mode. A warning the quiet mode swallowed would be a
# regression, so cb_warn maps here rather than to cb_detail.
cb_note() {
  _cb_log "note: $1"
  case "${CB_UI_MODE}" in
    tty)
      _cb_live_clear
      printf '  %s⚠%s  %s\n' "${_CB_YELLOW}" "${_CB_RESET}" "$1"
      _cb_live_draw
      ;;
    *)
      printf '[%s] warning: %s\n' "$(date '+%H:%M:%S')" "$1"
      ;;
  esac
}

# The context the quiet screen withheld, delivered at the only moment it
# matters. Called by cb_fail before the armed diagnostics run.
cb_ui_ledger() {
  local entry key headline seconds
  printf '\n  %sInstall progress%s\n' "${_CB_BOLD}" "${_CB_RESET}"
  for entry in ${_CB_LEDGER[@]+"${_CB_LEDGER[@]}"}; do
    key="${entry%%|*}"
    headline="${entry#*|}"
    seconds="${headline##*|}"
    headline="${headline%|*}"
    printf '    %s✓%s %-42s %s%s%s\n' \
      "${_CB_GREEN}" "${_CB_RESET}" "$headline" \
      "${_CB_DIM}" "$(_cb_human_duration "$seconds")" "${_CB_RESET}"
  done
  if [[ -n "${_CB_OPEN_HEADLINE}" ]]; then
    printf '    %s✗%s %s\n' "${_CB_RED}" "${_CB_RESET}" "${_CB_OPEN_HEADLINE}"
  fi
}

# The subprocess output quiet mode hid. Today an operator has to know to go and
# tail it; on the failure path they should not have to.
cb_ui_log_tail() {
  local lines="${1:-30}"
  [[ -n "${LOG_FILE:-}" ]] || return 0
  [[ -r "${LOG_FILE}" ]] || return 0
  printf '\n  %sLast %s lines of the install log%s\n' \
    "${_CB_BOLD}" "$lines" "${_CB_RESET}"
  tail -n "$lines" "${LOG_FILE}" 2>/dev/null | sed 's/^/    /' || true
}

# ── Backward-compatible aliases ──────────────────────────────────────────────
#
# 269 call sites across install.sh and deploy/setup.sh use these three names, and four
# suites in tests/build/ stub them and assert on the stubbed output. Keeping the
# names as the semantic API is the entire migration strategy: nothing else has
# to change at once, and no existing test needs editing.
cb_step() { cb_detail "$1"; }
cb_ok()   { cb_detail "$1"; }
cb_warn() { cb_note "$1"; }
cb_section() { cb_detail "section: $1"; }
