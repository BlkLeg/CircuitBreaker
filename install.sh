#!/usr/bin/env bash
set -euo pipefail

# Circuit Breaker Native Installer
# Downloads a pre-built bundle from GitHub Releases and installs it.
# Usage: curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | sudo bash

# Every package operation in this installer sends its output to the install log,
# so anything that stops to ask a question stops *invisibly*: the prompt text
# goes to the log and the installer sits on a terminal that shows nothing but
# the last "▸ Installing ..." line. There is no timeout and no way for the
# operator to know what is being asked.
#
# Two things ask. debconf prompts on config-file conflicts and service
# restarts unless the frontend is noninteractive. needrestart, installed by
# default on Ubuntu Server since 22.04, hooks DPkg::Post-Invoke and asks which
# services to restart whenever it finds processes running against upgraded
# libraries — which is the normal state of a machine that has been updated but
# not rebooted, i.e. the machine most people install onto.
#
# Exported, so the setup.sh sourced later and every child process inherits them.
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---
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
  #
  # This assumes the two lines directly above the cursor are still the bar and
  # timer this renderer drew — there is no way to confirm that from here. A
  # terminal has no read-back for "what did I last print", so this function
  # cannot detect foreign output (a raw `echo`/`printf`, `clear`, a banner)
  # that landed between the last draw and this call; if that happened, this
  # rewind erases real output instead of its own. There is no general fix for
  # that inside the renderer — no heuristic here can distinguish "my own
  # redraw" from "somebody else's line that happens to be two lines up". The
  # only honest fix is at the call sites: anything that emits raw output after
  # a phase is open MUST call cb_ui_teardown first (cb_header, the
  # stage10_final_output banner, uninstall.sh's closing block all do).
  # tests/build/test_installer_live_region_discipline.py is the guard that
  # keeps those call sites honest; it is not a substitute for this function
  # being able to protect itself, because it can't.
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
# --- END INLINED deploy/lib/ui.sh ---

# GitHub repo for release downloads
CB_GITHUB_REPO="BlkLeg/CircuitBreaker"
CB_RELEASE_API="https://api.github.com/repos/${CB_GITHUB_REPO}/releases"

# Default values
CB_PORT=8088
CB_DATA_DIR=/var/lib/circuitbreaker
CB_FQDN=""
CB_CERT_TYPE="self-signed"
CB_EMAIL=""
CB_VERSION=""
CB_LOCAL_BUNDLE=""
# Air-gap mode. Seeded from the environment so `CB_AIRGAP=true bash install.sh`
# and `--airgap` mean the same thing, and so the variable that governs the
# running application also governs the installer that writes its config.
#
# The contract is deliberately absolute: in air-gap mode this installer makes no
# outbound request of any kind. It installs no packages, adds no apt/dnf
# repository, downloads no binary, and pulls no container image. It verifies
# that what it needs is already present and stops with an exact list of what is
# not. Anything softer would be a claim it cannot keep — "mostly offline" is the
# failure mode air-gapped operators are trying to avoid.
_cb_airgap_from_env="${CB_AIRGAP:-}"
CB_AIRGAP=false
case "$_cb_airgap_from_env" in
  true|True|TRUE|1|yes|on) CB_AIRGAP=true ;;
esac
unset _cb_airgap_from_env
# Seeded from the environment so `CB_VERBOSE=true bash install.sh` and
# `--verbose` mean the same thing.
_cb_verbose_from_env="${CB_VERBOSE:-}"
CB_VERBOSE=false
case "$_cb_verbose_from_env" in
  true|True|TRUE|1|yes|on) CB_VERBOSE=true ;;
esac
unset _cb_verbose_from_env
export CB_VERBOSE
UNATTENDED=false
UPGRADE_MODE=false
NO_TLS=false
FORCE_DEPS=false
DOCKER_AVAILABLE=false
INSTALL_DOCKER=true
SKIP_CHECKSUM=false
DOCKER_MODE=false

# UI Functions
cb_version() {
  cat /opt/circuitbreaker/share/VERSION 2>/dev/null || echo "installing"
}

# True when stdout is a terminal at least $1 columns wide.
#
# Call it directly, never as "$(cb_term_at_least ...)": command substitution
# replaces stdout with a pipe, and then `-t 1` is false however wide the real
# terminal is — which is how this check silently answered "too narrow"
# everywhere the first time round.
#
# tput is asked first because `curl | sudo bash` leaves stdin a pipe and stdout
# a terminal, which is the documented entry point and the case stty cannot
# measure. stty covers the minimal images that ship no ncurses-bin. Neither is
# ever written on a line of its own: without TERM tput exits non-zero, and
# `set -e` would turn that into an install that dies before its first line.
cb_term_at_least() {
  local want="$1" cols=""
  [[ -t 1 ]] || return 1
  cols="$(tput cols 2>/dev/null || true)"
  [[ -n "$cols" ]] || cols="$(stty size <&1 2>/dev/null | cut -d' ' -f2 || true)"
  [[ -n "$cols" ]] || cols="${COLUMNS:-}"
  [[ "$cols" =~ ^[0-9]+$ ]] || return 1
  (( cols >= want ))
}

# The installer banner: a hooded figure at a desk, drawn as a foreground
# silhouette over the topology view on the monitor behind it. 64 columns wide.
#
# printf '%s\n', not echo -e: the artwork is mostly backslashes and echo -e
# would eat them as escape sequences, tearing holes in the picture. The colours
# are therefore real escape characters ($'...') rather than the literal
# '\033[...' strings the rest of this installer hands to echo -e.
cb_logo() {
  local orange=$'\033[38;5;209m'
  local purple=$'\033[38;5;141m'
  local violet=$'\033[38;5;99m'
  local shade=$'\033[38;5;238m'
  local dim=$'\033[2m'
  local bold=$'\033[1m'
  local reset=$'\033[0m'

  printf '\n'
  printf '%s\n' "          ${purple}.--------------------------------------------.${reset}"
  printf '%s\n' "          ${purple}| ${dim}> topology --live          24 up  31 links ${purple}|${reset}"
  printf '%s\n' "          ${purple}|                                            |${reset}"
  printf '%s\n' "          ${purple}|    ${orange}o---o---o                  o---o---o    ${purple}|${reset}"
  printf '%s\n' "          ${purple}|     ${orange}\\  |  /                    \\  |  /     ${purple}|${reset}"
  printf '%s\n' "          ${purple}|        ${orange}o--------${violet}##########${orange}--------o        ${purple}|${reset}"
  printf '%s\n' "          ${purple}|       ${orange}/      ${violet}#${shade}##############${violet}#      ${orange}\\       ${purple}|${reset}"
  printf '%s\n' "          ${purple}|      ${orange}o     ${violet}#${shade}##################${violet}#     ${orange}o      ${purple}|${reset}"
  printf '%s\n' "          ${purple}|     ${orange}/     ${violet}#${shade}####################${violet}#     ${orange}\\     ${purple}|${reset}"
  printf '%s\n' "          ${purple}|    ${orange}o    ${violet}(#${shade}######################${violet}#)    ${orange}o    ${purple}|${reset}"
  printf '%s\n' "          ${purple}|         ${violet}(#${shade}######################${violet}#)         ${purple}|   ${dim}~${reset}"
  printf '%s\n' "          ${purple}'----------${violet}#${shade}######################${violet}#${purple}----------'  ${dim}(_)${reset}"
  printf '%s\n' "  ${dim}------------------${violet}#${shade}########################${violet}#${dim}------------------${reset}"
  printf '%s\n' "                   ${violet}============================${reset}"
  printf '%s\n' "              ${violet}#${shade}####################################${violet}#${reset}"
  printf '%s\n' "          ${violet}#${shade}############################################${violet}#${reset}"
  printf '%s\n' "        ${violet}#${shade}################################################${violet}#${reset}"
  printf '%s\n' "       ${violet}#${shade}##################################################${violet}#${reset}"
  printf '\n'
  printf '%s\n' "${bold}${orange}                  C I R C U I T _ B R E A K E R${reset}"

  # cb_version reports "installing" on a fresh host, where "Installer
  # installing" is not a version line worth printing.
  local ver sub
  ver="$(cb_version)"
  if [[ "$ver" == "installing" ]]; then
    ver=""
  fi
  sub="Installer"
  if [[ -n "$ver" ]]; then
    sub="Installer  v${ver}"
  fi
  # 66, not the 64 columns of ink: the figure is centred on a 66-wide canvas,
  # and these two lines have to sit under its axis rather than under the
  # widest row.
  printf '%*s%s%s%s\n\n' "$(( (66 - ${#sub}) / 2 ))" "" "${dim}" "$sub" "${reset}"
}

cb_header() {
  # Tear the live region down before `clear` (and before the headline/box it
  # prints below). `clear` wipes the whole screen, which already destroys the
  # bar/timer line, but _CB_LIVE_ON never learns that: it is only cleared by
  # _cb_live_clear itself, and the next live redraw would otherwise open with
  # a blind two-line "rewind" onto content `clear` already erased. Guarded so
  # this still works if ui.sh was never sourced (cb_header runs from more
  # than one call site, including before any bundle exists).
  declare -f cb_ui_teardown >/dev/null 2>&1 && cb_ui_teardown

  # `clear` exits 1 when TERM is unset, and under `set -e` that aborts the whole
  # installer before it has printed a single line — the least diagnosable failure
  # this script can produce. TERM is unset in exactly the environments
  # --unattended exists for: Proxmox LXC provisioning, cloud-init, Ansible, CI,
  # and `ssh host 'bash install.sh'` without -t.
  clear 2>/dev/null || true

  # cb_ui_teardown above shows the cursor again (it's the same call the EXIT
  # trap uses to restore the terminal on exit). Re-hide it here so a tty
  # install's cursor stays hidden across the header instead of reappearing
  # for the rest of the run.
  [[ "${CB_UI_MODE:-}" == "tty" ]] && printf '\033[?25l'

  # cb_logo needs 64 columns. Narrower than that and every line of it wraps into
  # rubble; a piped or TTY-less install has no width to ask about at all. Both
  # fall back to the box, which fits in 46.
  if cb_term_at_least 66; then
    cb_logo
    return 0
  fi

  echo -e "${CYAN}${BOLD}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║         Circuit Breaker Installer        ║"
  echo "  ║                 $(cb_version)                 ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${RESET}"
}

# Read-only diagnostics run automatically by cb_fail, populated before each
# major stage alongside CB_STAGE_HINTS. Format: "Label::shell command".
# Nothing here may mutate state — these run unattended on the failure path, so
# retries, restarts and installs stay in CB_STAGE_HINTS for a human to decide.
CB_STAGE_DIAGS=()
CB_DIAG_LINES=50
_CB_DIAG_RUNNING=false

# /etc/circuitbreaker/.env holds the JWT secret, vault key and DB password.
# Printing it verbatim on a failure path puts them on the terminal — and into
# whatever the user pastes into an issue — so mask secrets and any credentials
# embedded in connection URLs before showing it.
cb_env_redacted() {
  local env_file=/etc/circuitbreaker/.env
  if [[ ! -r "$env_file" ]]; then
    echo "(not readable: $env_file)"
    return 0
  fi
  sed -E \
    -e 's/^([A-Za-z0-9_]*(SECRET|PASSWORD|PASSWD|TOKEN|KEY|CREDENTIAL)[A-Za-z0-9_]*)=.+$/\1=<redacted>/' \
    -e 's#^([A-Za-z0-9_]+)=([a-zA-Z][a-zA-Z0-9+.-]*://)[^:@/]+:[^@]*@#\1=\2<redacted>:<redacted>@#' \
    "$env_file"
}

cb_run_diagnostics() {
  # A diagnostic that itself calls cb_fail must not re-enter this loop.
  [[ "${_CB_DIAG_RUNNING}" == "true" ]] && return 0
  [[ ${#CB_STAGE_DIAGS[@]} -eq 0 ]] && return 0
  _CB_DIAG_RUNNING=true

  echo -e "\n  ${BOLD}Diagnostics${RESET} ${DIM}(collected automatically — no need to re-run these)${RESET}"
  local _entry _label _cmd _out
  for _entry in "${CB_STAGE_DIAGS[@]}"; do
    _label="${_entry%%::*}"
    _cmd="${_entry#*::}"
    echo -e "\n  ${CYAN}▸${RESET} ${_label}"
    # printf, not echo -e: a diagnostic command can legitimately contain a
    # backslash escape (printf '%s\n' in a loop, a sed expression), and echo -e
    # would interpret it here and print the command across several lines,
    # mangling the one thing an operator might want to copy.
    printf '    %b$ %s%b\n' "${DIM}" "${_cmd}" "${RESET}"
    _out="$(eval "${_cmd}" 2>&1 | tail -n "${CB_DIAG_LINES}")" || true
    if [[ -z "${_out}" ]]; then
      echo -e "    ${DIM}(no output)${RESET}"
    else
      printf '%s\n' "${_out}" | sed 's/^/    /'
    fi
    if [[ -n "${LOG_FILE:-}" ]]; then
      { echo "=== diagnostic: ${_label} — ${_cmd}"; printf '%s\n' "${_out}"; } \
        >> "${LOG_FILE}" 2>/dev/null || true
    fi
  done

  _CB_DIAG_RUNNING=false
}

cb_fail() {
  # Tear the live region down FIRST. Diagnostics interleaved with a redrawing
  # bar are unreadable, and this is the one moment the output has to be perfect.
  if declare -f cb_ui_teardown >/dev/null 2>&1; then
    cb_ui_teardown
  fi

  echo -e "\n  ${RED}✗  ERROR: $1${RESET}"
  if [[ -n "${2:-}" ]]; then
    echo -e "  ${YELLOW}→  $2${RESET}"
  fi

  # The context the quiet screen withheld, at the only moment it matters.
  if declare -f cb_ui_ledger >/dev/null 2>&1; then
    cb_ui_ledger
  fi

  # The subprocess output quiet mode hid. Before the armed diagnostics, because
  # it is the most likely place the actual cause is written.
  if declare -f cb_ui_log_tail >/dev/null 2>&1; then
    cb_ui_log_tail 30
  fi

  cb_run_diagnostics
  if [[ ${#CB_STAGE_HINTS[@]} -gt 0 ]]; then
    echo -e "\n  ${BOLD}Next steps:${RESET}"
    local _hint_i=1
    for _hint in "${CB_STAGE_HINTS[@]}"; do
      echo -e "    ${DIM}${_hint_i}.${RESET} ${_hint}"
      (( _hint_i++ ))
    done
  fi

  # Named explicitly, as the last lines. An operator should never have to
  # know to go and find these.
  echo ""
  echo -e "  ${BOLD}Full log:${RESET}  ${LOG_FILE:-/tmp/cb-bootstrap.log}"
  echo -e "  ${BOLD}Re-run with full output:${RESET}  bash install.sh --verbose"
  echo -e "  ${BOLD}Collect everything for an issue:${RESET}  cb diag bundle"
  echo ""
  exit 1
}

# Hint array populated before each major stage; cleared on success
CB_STAGE_HINTS=()

# stage8_start_services runs on both the fresh-install and the upgrade path,
# so both arm the same diagnostics here rather than only the one main() walks.
cb_arm_service_start_diagnostics() {
  CB_STAGE_HINTS=(
    "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
    "Manual start: systemctl start circuitbreaker.target"
    "Re-check anytime: cb doctor"
  )
  CB_STAGE_DIAGS=(
    "circuitbreaker-backend status::systemctl status circuitbreaker-backend --no-pager -l"
    "circuitbreaker-backend logs::journalctl -u circuitbreaker-backend --no-pager -n 50"
    "Health check::if [[ -x /usr/local/bin/cb ]]; then /usr/local/bin/cb doctor; else echo '(cb CLI not installed yet)'; fi"
    "Effective config (secrets redacted)::cb_env_redacted"
    "All Circuit Breaker logs::journalctl -u 'circuitbreaker-*' --no-pager -n 50"
    "nginx config test::nginx -t"
  )
}

# The names a template asks the installer to fill in: ${NAME}, braced, nothing else.
cb_template_vars() {
  grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' "$1" | sed 's/^\${//; s/}$//' | sort -u
}

# Literal find/replace, used by cb_render_template.
#
# Bash's own ${v//pat/rep} is not usable here: since 5.2 it treats `&` in the
# replacement as the matched text, so a value containing an ampersand — a proxy
# URL, an email — renders differently on Ubuntu 22.04 (bash 5.1) than on 24.04+
# (5.2+). The quoted ${rest%%"$needle"*} form below is literal on every version.
cb_replace_all() {
  local -n _buf="$1"
  local needle="$2" rep="$3" out="" rest="$_buf"
  while [[ "$rest" == *"$needle"* ]]; do
    out+="${rest%%"$needle"*}$rep"
    rest="${rest#*"$needle"}"
  done
  _buf="$out$rest"
}

# Render a template by substituting ${NAME}, copying every other byte through
# untouched.
#
# This replaced an `eval "cat <<EOF\n$(cat "$src")\nEOF"`, which expanded the
# ENTIRE file as shell — comments included. Two things followed from that, both
# of which shipped in v0.4.0:
#
#   * Backticks in prose executed as root. The nginx configs documented their
#     routing with `curl https://cb.example.com/install-agent.sh` and
#     `sha256sum -c`, so every install ran both — an outbound request on a
#     platform whose air-gap contract forbids one, and a `sha256sum -c` with no
#     argument, which reads stdin and blocks.
#   * An unset variable killed the installer. Under `set -u`, AGT-11's comment
#     "$TMPDIR/_MEI<random>" aborted every install on a host where TMPDIR was
#     unset, with `line 164: TMPDIR: unbound variable` and a half-written
#     systemd tree.
#
# The only defence an eval allowed was backslash-escaping every literal $ in
# every template (\$MAINPID, \$host). That is invisible to anyone editing a
# config file, unenforceable, and was already wrong in four files. Substitution
# needs no escaping: `$host`, `$MAINPID` and backticks are ordinary text now.
cb_render_template() {
  local src="$1" dest="$2" content name
  local missing=()

  content="$(cat "$src")"

  # A template asking for a variable the installer never set is a packaging bug.
  # Refusing beats rendering a config with a blank password or an empty data
  # directory, and naming the file and the variable beats `unbound variable`
  # pointing at a line number inside the renderer.
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    [[ -n "${!name+set}" ]] || missing+=("$name")
  done < <(cb_template_vars "$src")
  if (( ${#missing[@]} > 0 )); then
    cb_fail "Template ${src} needs variables the installer never set: ${missing[*]}" \
            "This is a packaging bug — the template and deploy/setup.sh disagree"
  fi

  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    cb_replace_all content "\${$name}" "${!name}"
  done < <(cb_template_vars "$src")

  printf '%s\n' "$content" > "$dest"
}

cb_require_native_root() {
  if [[ $EUID -eq 0 ]]; then
    return 0
  fi

  if command -v sudo >/dev/null 2>&1 && [[ -f "${BASH_SOURCE[0]}" ]]; then
    echo -e "  ${CYAN}▸${RESET} Elevating privileges with sudo for native installation..."
    exec sudo -E bash "${BASH_SOURCE[0]}" "$@"
  fi

  cb_fail "Root privileges required for native installation" \
    "Run: curl -fsSL https://raw.githubusercontent.com/${CB_GITHUB_REPO}/main/install.sh | sudo bash"
}

docker_target_user() {
  if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    echo "${SUDO_USER}"
    return 0
  fi
  id -un
}

docker_target_home() {
  local target_user
  target_user="$(docker_target_user)"
  if [[ "${target_user}" == "root" ]]; then
    echo "/root"
    return 0
  fi
  # `|| true` is load-bearing, and it is the same shape as the B50 fix at the end
  # of stage_docker_deploy. A bare assignment of a pipeline dies on the spot under
  # `set -euo pipefail` when getent exits 2 for an unknown key — cut still returns
  # 0, pipefail promotes the 2, errexit ends the run — so the cb_fail written for
  # exactly this case, two lines below, was unreachable. An operator installing
  # over sudo from an LDAP or SSSD account that NSS cannot resolve got exit 2 and
  # a blank screen instead of the name of the user that could not be found.
  # Absorb the status here and let the emptiness check below do the reporting.
  local user_home
  user_home="$(getent passwd "${target_user}" | cut -d: -f6 || true)"
  if [[ -z "${user_home}" ]]; then
    cb_fail "Failed to resolve user home" "Could not determine home directory for ${target_user}"
  fi
  echo "${user_home}"
}

cb_detect_pkg_mgr() {
  if [[ ! -f /etc/os-release ]]; then
    cb_fail "Cannot detect OS" "/etc/os-release not found"
  fi
  source /etc/os-release
  case "${ID}" in
    ubuntu|debian) echo "apt-get" ;;
    fedora|rhel|rocky|almalinux) echo "dnf" ;;
    arch) echo "pacman" ;;
    *) cb_fail "Unsupported OS: ${ID}" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux, Arch" ;;
  esac
}

cb_install_docker_if_missing() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    cb_ok "Docker engine and compose plugin detected"
    return 0
  fi

  cb_step "Installing Docker (engine + compose plugin)"
  local pkg_mgr
  pkg_mgr="$(cb_detect_pkg_mgr)"

  if [[ $EUID -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
      cb_fail "Docker not found and sudo is unavailable" \
        "Install Docker manually, then rerun: bash install.sh --docker"
    fi
  fi

  local root_prefix=()
  if [[ $EUID -ne 0 ]]; then
    root_prefix=(sudo)
  fi

  if [[ "${pkg_mgr}" == "apt-get" ]]; then
    "${root_prefix[@]}" apt-get update -y -q >/dev/null 2>&1
    "${root_prefix[@]}" apt-get install -y -q ca-certificates curl gnupg >/dev/null 2>&1
    "${root_prefix[@]}" install -m 0755 -d /etc/apt/keyrings
    curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 "https://download.docker.com/linux/${ID}/gpg" | "${root_prefix[@]}" gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    "${root_prefix[@]}" chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
      | "${root_prefix[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null
    "${root_prefix[@]}" apt-get update -y -q >/dev/null 2>&1
    "${root_prefix[@]}" apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null 2>&1
  elif [[ "${pkg_mgr}" == "dnf" ]]; then
    "${root_prefix[@]}" dnf -y -q install dnf-plugins-core >/dev/null 2>&1
    "${root_prefix[@]}" dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo >/dev/null 2>&1
    "${root_prefix[@]}" dnf -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null 2>&1
  else
    "${root_prefix[@]}" pacman -Sy --noconfirm --needed docker docker-compose >/dev/null 2>&1
  fi

  "${root_prefix[@]}" systemctl enable --now docker >/dev/null 2>&1 || cb_fail "Failed to start Docker daemon" "Check: sudo systemctl status docker"

  if [[ $EUID -eq 0 ]]; then
    cb_warn "Docker installed as root; compose commands will run as root in this session"
  else
    local current_user
    current_user="$(id -un)"
    "${root_prefix[@]}" usermod -aG docker "${current_user}" >/dev/null 2>&1 || true
    cb_warn "Added ${current_user} to docker group. Run 'newgrp docker' or re-login if compose fails with permission errors."
  fi
  cb_ok "Docker installed"
}

cb_install_helper_daemon() {
  local install_dir="$1"

  cb_step "Installing cb-helperd (privileged host helper)"
  local root_prefix=()
  if [[ $EUID -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
      cb_warn "sudo unavailable — skipping cb-helperd install (LAN discovery and auto-repair need it)"
      return 0
    fi
    root_prefix=(sudo)
  fi

  "${root_prefix[@]}" mkdir -p /opt/circuitbreaker/deploy/helper /etc/circuitbreaker /run/circuitbreaker
  "${root_prefix[@]}" cp "${install_dir}/deploy/helper/cb_helperd.py" /opt/circuitbreaker/deploy/helper/cb_helperd.py
  "${root_prefix[@]}" cp "${install_dir}/deploy/systemd/cb-helperd.service" /etc/systemd/system/cb-helperd.service

  # The mono image's breaker user is a fixed uid=1000 (Dockerfile.mono) —
  # always correct for the Docker deploy path regardless of the host user
  # running this installer.
  "${root_prefix[@]}" bash -c "cat > /etc/circuitbreaker/helper.conf" <<EOF
AUTHORIZED_UID=1000
COMPOSE_DIR=${install_dir}
EOF
  "${root_prefix[@]}" chmod 640 /etc/circuitbreaker/helper.conf

  "${root_prefix[@]}" systemctl daemon-reload
  "${root_prefix[@]}" systemctl enable --now cb-helperd >/dev/null 2>&1 \
    || cb_warn "cb-helperd failed to start — check: systemctl status cb-helperd"
  cb_ok "cb-helperd installed and running"
}

cb_generate_secret_base64() {
  openssl rand -base64 "$1" | tr -d '\n'
}

cb_generate_secret_hex() {
  openssl rand -hex "$1" | tr -d '\n'
}

stage_docker_deploy() {
  cb_header
  cb_section "Docker Compose Deployment"

  cb_install_docker_if_missing

  local target_user
  local target_home
  target_user="$(docker_target_user)"
  target_home="$(docker_target_home)"
  local install_dir="${target_home}/.circuitbreaker"

  # --version pins the compose file, the root helper daemon and the image to a
  # single revision. It used to be parsed and then ignored on this path: the
  # assets came from main and the image from :latest, so an operator who asked
  # for 1.0.0 could end up running main's compose file against whatever :latest
  # pointed at, with a cb_helperd.py from a third revision running as root.
  # Unset still means main + :latest, the rolling default. A bad --version now
  # fails loudly on the first curl below (404 on the tag) instead of quietly
  # installing main.
  #
  # The leading v is stripped first so `--version v1.2.3` and `--version 1.2.3`
  # agree: the git tag carries the v, the registry tag does not.
  local version="${CB_VERSION#v}"
  local ref="main"
  if [[ -n "${version}" ]]; then
    ref="v${version}"
  fi
  local base_url="https://raw.githubusercontent.com/${CB_GITHUB_REPO}/${ref}"

  cb_step "Preparing install directory"
  mkdir -p "${install_dir}/docker"
  # The .env written below holds the vault key, the JWT secret, the database
  # password and the NATS token. It was created with a plain cp under the
  # caller's umask, which is 022 on every distro this installer supports, so it
  # landed 0644 — every account on the host could read the key that decrypts
  # every stored credential and the secret that mints admin sessions. Tighten
  # the directory before anything is written into it and create the file under
  # a 077 umask, rather than chmod'ing afterwards, so there is no window in
  # which the secrets are world readable. Nothing needs group or other access:
  # docker compose reads .env as target_user, who owns the tree after the
  # chown below, and cb-helperd runs as root.
  chmod 700 "${install_dir}"
  cb_ok "Install directory: ${install_dir}"

  cb_step "Downloading official compose assets"
  # Every fetch is checked. `curl -fsSL` prints nothing on a 404 and the script
  # runs under `set -e`, so an unchecked fetch aborts the installer with exit 22
  # and a blank screen, half-way through a half-populated install directory. That
  # is reachable in normal use now that --version selects the ref: a tag that does
  # not exist 404s on the very first asset, and "the installer printed nothing and
  # stopped" is the least actionable failure this script can produce.
  mkdir -p "${install_dir}/deploy/helper" "${install_dir}/deploy/systemd"
  local asset
  for asset in \
    "docker-compose.yml:${install_dir}/docker-compose.yml" \
    "docker/docker-compose.socket.yml:${install_dir}/docker/docker-compose.socket.yml" \
    ".env.example:${install_dir}/.env.example" \
    "deploy/helper/cb_helperd.py:${install_dir}/deploy/helper/cb_helperd.py" \
    "deploy/systemd/cb-helperd.service:${install_dir}/deploy/systemd/cb-helperd.service"
  do
    local remote="${asset%%:*}"
    local dest="${asset#*:}"
    if ! curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 "${base_url}/${remote}" -o "${dest}"; then
      if [[ -n "${version}" ]]; then
        cb_fail "Could not download ${remote} at ref ${ref}" \
                "Is v${version} a published release? Check https://github.com/${CB_GITHUB_REPO}/releases, or drop --version to install from main."
      else
        cb_fail "Could not download ${remote} from ${base_url}" \
                "Check network access to raw.githubusercontent.com, then re-run."
      fi
    fi
  done
  cb_ok "Compose assets downloaded"

  cb_step "Creating .env with sensible defaults"
  if [[ ! -f "${install_dir}/.env" ]]; then
    # Subshell so the tightened umask applies to the cp that creates the file
    # and nothing else; the appends below inherit the resulting 0600.
    (umask 077; cp "${install_dir}/.env.example" "${install_dir}/.env")
    {
      echo ""
      echo "# Generated by install.sh --docker"
      echo "CB_DB_PASSWORD=$(cb_generate_secret_base64 24)"
      echo "CB_VAULT_KEY=$(cb_generate_secret_base64 32)"
      echo "CB_JWT_SECRET=$(cb_generate_secret_hex 32)"
      echo "NATS_AUTH_TOKEN=$(cb_generate_secret_base64 24)"
      # docker-compose.yml resolves the image as ${CB_IMAGE:-...:${CB_TAG:-latest}},
      # so writing the tag here is what stops the image drifting away from the
      # compose file and helper fetched from ${ref} above.
      if [[ -n "${version}" ]]; then
        echo "CB_TAG=${version}"
      fi
    } >> "${install_dir}/.env"
    cb_ok "Generated ${install_dir}/.env"
  else
    cb_ok "Preserving existing ${install_dir}/.env"
    # Repair an .env left 0644 by an install from before the umask above.
    chmod 600 "${install_dir}/.env"
    if [[ -n "${version}" ]]; then
      cb_warn "Your existing .env was kept, so the image tag was not changed — set CB_TAG=${version} in ${install_dir}/.env by hand, then re-run: cd ${install_dir} && docker compose up -d"
    fi
  fi

  if [[ "${target_user}" != "$(id -un)" ]]; then
    chown -R "${target_user}:${target_user}" "${install_dir}" 2>/dev/null || true
  fi

  cb_step "Starting stack with docker compose"
  (
    cd "${install_dir}" && docker compose up -d
  ) || cb_fail "Docker Compose deployment failed" "Run: cd ${install_dir} && docker compose logs --tail=80"
  cb_ok "Docker stack is running"

  cb_install_helper_daemon "${install_dir}"

  # Host-side install identity (operator tooling on the Docker host).
  local identity_lib=""
  for identity_lib in \
    "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)/deploy/lib/install-identity.sh" \
    /usr/local/lib/circuitbreaker/install-identity.sh
  do
    [[ -f "$identity_lib" ]] && break
    identity_lib=""
  done
  local host_identity_dir="${target_home}/.circuit-breaker"
  mkdir -p "${host_identity_dir}"
  if [[ -n "$identity_lib" ]]; then
    # shellcheck source=/dev/null
    source "$identity_lib"
    local mono_version="${version:-latest}"
    write_install_identity "${host_identity_dir}/install-identity.json" \
      mode=mono \
      version="$mono_version" \
      data_dir=/data \
      env_file="${install_dir}/.env" \
      container_name=circuitbreaker \
      compose_file="${install_dir}/docker-compose.yml" \
      cli_path=/usr/local/bin/cb \
      health_url=http://127.0.0.1:8080/api/v1/readyz \
      || cb_warn "Could not write host install identity"
    # Legacy install.conf for one-release compatibility.
    cat > "${host_identity_dir}/install.conf" <<EOF
CB_MODE=docker
CB_CONTAINER=circuitbreaker
CB_PORT=8080
CB_DATA_DIR=/data
CB_INSTALL_DIR=${install_dir}
CB_COMPOSE_FILE=${install_dir}/docker-compose.yml
EOF
    # Install host cb from checkout when available.
    local repo_cb
    repo_cb="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)/cb"
    if [[ -f "$repo_cb" ]]; then
      install -Dm755 "$repo_cb" /usr/local/bin/cb 2>/dev/null \
        || sudo install -Dm755 "$repo_cb" /usr/local/bin/cb 2>/dev/null \
        || cb_warn "Could not install /usr/local/bin/cb — copy ${repo_cb} manually"
    fi
  fi

  # Everything below this line is the payoff for everything above it — the
  # install directory, the access URLs, the commands the operator needs next —
  # and nothing here is allowed to abort. This lookup in particular is cosmetic:
  # it only decides which address the URLs are printed with, and nothing
  # downstream consumes it.
  #
  # It used to be a bare assignment, and it killed the installer here, after
  # `docker compose up -d` had returned and cb-helperd was installed. `ip route
  # get 1.1.1.1` exits non-zero when iproute2 is absent and on any host with no
  # route to that address — an air-gapped LAN deployment, which is squarely this
  # product's audience. The 2>/dev/null hides the message but not the status,
  # `pipefail` promotes it past the awk that would otherwise have returned a
  # clean 0, and `set -e` then ended the run. The operator saw the stack come up
  # and then a silent exit 2 with no summary at all, and the reasonable
  # conclusion from that screen is that the install failed — followed by tearing
  # down a deployment that was in fact working.
  #
  # `|| true` inside the substitution absorbs the pipeline's status before
  # errexit can see it; the empty result then takes the localhost fallback. The
  # fallback is spelled as an `if` rather than the shorter `[[ ... ]] && ...`
  # because that form returns 1 whenever the address *was* found, and it is one
  # edit away from being the last command in this function — at which point the
  # successful case would abort the installer instead of the failing one.
  local host_ip=""
  host_ip="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {print $7; exit}' || true)"
  if [[ -z "${host_ip}" ]]; then
    host_ip="localhost"
  fi

  echo ""
  cb_ok "Docker deployment complete"
  echo -e "  ${BOLD}Install directory:${RESET} ${install_dir}"
  echo -e "  ${BOLD}Access URLs:${RESET} https://${host_ip}/ or http://${host_ip}/"
  echo -e "  ${BOLD}Health:${RESET} http://${host_ip}/api/v1/readyz"
  echo -e "  ${BOLD}Next:${RESET} open the Access URL and complete first-run setup (cb setup-token)."
  echo -e "  ${BOLD}Useful commands:${RESET}"
  echo -e "    cb info"
  echo -e "    cb doctor"
  echo -e "    cb setup"
  echo -e "    cd ${install_dir} && docker compose ps"
  echo -e "    cd ${install_dir} && docker compose logs -f"
  echo -e "    cd ${install_dir} && docker compose -f docker-compose.yml -f docker/docker-compose.socket.yml up -d"
}


stage0_bootstrap_preflight() {
  cb_header
  cb_section "Bootstrap Pre-flight Checks"

  # Privilege confirmation
  cb_step "Checking privileges"
  if [[ $EUID -ne 0 ]]; then
    cb_fail "Root privileges required" "Run as root: bash install.sh"
  fi
  cb_ok "Running as root"

  # OS Detection
  cb_step "Detecting operating system"
  if [[ ! -f /etc/os-release ]]; then
    cb_fail "Cannot detect OS" "/etc/os-release not found"
  fi
  source /etc/os-release
  OS_ID="$ID"

  case "$OS_ID" in
    ubuntu|debian) PKG_MGR="apt-get" ;;
    fedora|rhel|rocky|almalinux) PKG_MGR="dnf" ;;
    arch) PKG_MGR="pacman" ;;
    *) cb_fail "Unsupported OS: $OS_ID" "Supported: Ubuntu, Debian, Fedora, RHEL, Rocky, AlmaLinux, Arch" ;;
  esac
  cb_ok "OS: $OS_ID ($PKG_MGR)"

  # Architecture detection
  cb_step "Detecting architecture"
  case "$(uname -m)" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    *) cb_fail "Unsupported architecture: $(uname -m)" "Supported: x86_64, aarch64" ;;
  esac
  cb_ok "Architecture: $(uname -m) ($ARCH)"

  # Ensure curl, jq, and openssl are installed (bundle download + secret
  # generation in stage1 both run before stage2 installs base tools)
  cb_step "Checking required tools"
  local need_install=false
  for tool in curl jq openssl; do
    if ! command -v "$tool" &>/dev/null; then
      need_install=true
      break
    fi
  done

  # This preflight runs before stage2, so it is the first place an air-gapped
  # install could quietly reach for a package mirror. It must not: report what
  # is missing and stop, the same way cb_airgap_verify_dependencies does later.
  if [[ "$need_install" == "true" ]] && [[ "$CB_AIRGAP" == "true" ]]; then
    local _missing_core=()
    for tool in curl jq openssl; do
      command -v "$tool" &>/dev/null || _missing_core+=("$tool")
    done
    cb_fail "Air-gap install needs these before it can start, and they are not present: ${_missing_core[*]}" \
            "Install them from your local mirror or media, then re-run — air-gap mode installs nothing"
  fi

  if [[ "$need_install" == "true" ]]; then
    cb_step "Installing curl, jq, and openssl"
    if [[ "$PKG_MGR" == "apt-get" ]]; then
      $PKG_MGR update -y -q >/dev/null 2>&1 \
        || cb_fail "apt-get update failed" "Check network/apt sources, then re-run"
      $PKG_MGR install -y -q curl jq openssl >/dev/null 2>&1 \
        || cb_fail "Failed to install curl/jq/openssl" "Run: apt-get install -y curl jq openssl"
    elif [[ "$PKG_MGR" == "pacman" ]]; then
      pacman -Sy --noconfirm --needed curl jq openssl >/dev/null 2>&1 \
        || cb_fail "Failed to install curl/jq/openssl" "Run: pacman -Sy curl jq openssl"
    else
      $PKG_MGR install -y -q curl jq openssl >/dev/null 2>&1 \
        || cb_fail "Failed to install curl/jq/openssl" "Run: ${PKG_MGR} install -y curl jq openssl"
    fi
  fi
  for tool in curl jq openssl; do
    command -v "$tool" &>/dev/null \
      || cb_fail "Required tool still missing: $tool" "Install it manually and re-run"
  done
  cb_ok "curl, jq, and openssl available"
}


# Choose the release a default install (no --version) should fetch.
#
# Reads the /releases list JSON on stdin -- newest first, as the API returns
# it -- and prints the chosen release object, or nothing if there is none.
#
# This deliberately does not ask /releases/latest. That endpoint answers with
# whatever carries the "Latest release" badge, and v1.0.0-rc.1 and rc.2 were
# published before release.yml learned to pass --prerelease (GOV-20), so both
# are recorded as stable and rc.2 still holds the badge. A default install
# therefore fetched the rc.2 bundle: it reported its version as 1.0.0-rc.2,
# and it predates the gh#104 PyInstaller fix, so every Proxmox connection
# failed with "No module named 'proxmoxer.backends'". Picking from the list
# here makes the choice independent of that stale metadata.
#
# The rule is the newest non-draft release, release candidates included; the
# caller warns loudly when the winner is one. Preferring stable unconditionally
# would install v0.3.4 for the whole 1.0.0-rc window -- a pre-1.0 build months
# older than the one README.md documents, which is the same "user silently gets
# an ancient build" failure this selection exists to prevent.
#
# KNOWN LIMITATION, stated plainly rather than wished away: this rule prefers
# the newest release including candidates, permanently, not just before GA.
# Once v1.0.0 is stable, publishing v1.0.1-rc.1 makes that candidate the newest
# release and a default `curl | bash` fetches it again. Closing that properly
# needs a real per-channel ordering, and doing it here would mean a semver
# comparator written in bash -- avoiding exactly that is why the signed update
# manifest is designed the way it is. The manifest publishes ordered per-channel
# release lists, which turns "the newest stable" into a list lookup instead of a
# version comparison. Resolve this when that lands; do not hand-roll it here.
# tests/build/test_install_release_selection.py pins the current behaviour,
# including the post-GA shape, so a future change to this rule is deliberate.
cb_pick_release() {
  jq '[.[] | select(.draft == false)] | first // empty' 2>/dev/null || true
}

# Verify a downloaded bundle against the release's SHA256SUMS asset.
#
# $1 is the release JSON from the GitHub API, $2 the tarball's asset name; the
# tarball itself is expected at /tmp/$2, where the caller downloaded it.
#
# This used to fetch "${tarball_url}.sha256", an asset no release has ever
# published: release.yml builds one SHA256SUMS for the whole release
# (`find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} +`) and
# uploads it alongside the artifacts. The fetch therefore 404'd every time --
# and because the verification hung off an `elif curl ...` with no `else`, that
# 404 skipped the check without printing a word. Every `curl | bash` install
# unpacked and ran an unverified tarball as root while reporting success. So
# this function fails closed: anything short of a matching hash stops the
# install, and only --skip-checksum may waive it.
cb_verify_bundle_checksum() {
  local release_json="$1"
  local tarball_name="$2"

  if [[ "$SKIP_CHECKSUM" == "true" ]]; then
    cb_warn "Skipping SHA256 verification (--skip-checksum)"
    return 0
  fi

  cb_step "Verifying checksum"

  # `|| true` for the same reason as docker_target_home's getent: `echo` cannot
  # fail, so this pipeline's status is jq's, and jq exits 2 on a body it cannot
  # parse — a truncated or proxy-mangled response that still arrived with a 200,
  # which is exactly what `curl -fsSL` hands back. As a bare assignment under
  # `set -euo pipefail` that ended the install on this line, so the cb_fail
  # below never ran and the operator could not tell whether an unverifiable
  # bundle had been refused or the installer had simply crashed. Stopping is
  # correct here — this function is deliberately fail-closed — but it has to
  # stop *out loud*. An unparseable body leaves checksum_url empty and falls
  # into the same branch as a release that publishes no SHA256SUMS at all.
  local checksum_url
  checksum_url=$(echo "$release_json" | jq -r '.assets[] | select(.name=="SHA256SUMS") | .browser_download_url' || true)
  if [[ -z "$checksum_url" ]] || [[ "$checksum_url" == "null" ]]; then
    cb_fail "Could not determine the SHA256SUMS asset for release v${CB_VERSION}" \
      "The release publishes none, or the API response could not be parsed. Refusing to install a bundle that cannot be verified — pass --skip-checksum only for a bundle you already trust"
  fi

  curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 -o /tmp/cb-SHA256SUMS "$checksum_url" \
    || cb_fail "Could not download SHA256SUMS for release v${CB_VERSION}" \
               "Check internet connectivity and re-run, or pass --skip-checksum only for a bundle you already trust"

  # Pick out the one line covering our tarball and check that line alone.
  #
  # Deliberately not `sha256sum --ignore-missing -c SHA256SUMS`: that flag
  # exits 0 when *none* of the listed files are present, so a SHA256SUMS that
  # simply never mentions our tarball would "verify" — swapping in a foreign
  # bundle plus an authentic checksum file for some other release defeats it.
  # Selecting the line first turns "not listed" into its own failure. The
  # comparison is on awk's second field rather than a substring, because
  # SHA256SUMS also lists ./<tarball>.asc, which contains the tarball name.
  #
  # release.yml runs its `find . -maxdepth 1` from dist/release/, so every
  # entry is written in ./<name> form; the check runs from /tmp, where the
  # bundle was downloaded, so those relative paths resolve.
  local expected_line
  expected_line=$(awk -v want="./${tarball_name}" '$2 == want { print; exit }' /tmp/cb-SHA256SUMS)
  rm -f /tmp/cb-SHA256SUMS
  if [[ -z "$expected_line" ]]; then
    cb_fail "Release v${CB_VERSION} publishes no checksum for ${tarball_name}" \
      "Refusing to install a bundle that cannot be verified — pass --skip-checksum only for a bundle you already trust"
  fi

  if (cd /tmp && printf '%s\n' "$expected_line" | sha256sum -c - >/dev/null 2>&1); then
    cb_ok "SHA256 checksum verified"
  else
    cb_fail "SHA256 mismatch — the bundle may be corrupted or tampered with" \
      "Re-run to download it again, or pass --skip-checksum only for a bundle you already trust"
  fi
}

stage0_download_bundle() {
  cb_section "Downloading Circuit Breaker Bundle"

  if [[ -n "$CB_LOCAL_BUNDLE" ]]; then
    # Local bundle mode (Proxmox helper pre-downloaded it)
    cb_step "Using local bundle"
    if [[ ! -f "$CB_LOCAL_BUNDLE" ]]; then
      cb_fail "Local bundle not found" "$CB_LOCAL_BUNDLE"
    fi
    CB_BUNDLE_TARBALL="$CB_LOCAL_BUNDLE"
    cb_ok "Local bundle: $CB_LOCAL_BUNDLE"
  else
    # Query GitHub for release
    cb_step "Querying GitHub for release"
    local release_json
    if [[ -n "$CB_VERSION" ]]; then
      release_json=$(curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 "${CB_RELEASE_API}/tags/v${CB_VERSION}" 2>/dev/null) \
        || cb_fail "Release v${CB_VERSION} not found" "Check: https://github.com/${CB_GITHUB_REPO}/releases"
    else
      # Select from the release list rather than trusting the badge -- see
      # cb_pick_release for why /releases/latest cannot be used here.
      local releases_json
      releases_json=$(curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 "${CB_RELEASE_API}" 2>/dev/null) \
        || cb_fail "Failed to fetch the release list" "Check internet connectivity or specify --version <version>"
      release_json=$(printf '%s' "$releases_json" | cb_pick_release)
      if [[ -z "$release_json" ]] || [[ "$release_json" == "null" ]]; then
        cb_fail "No installable release found" "Check https://github.com/${CB_GITHUB_REPO}/releases or specify --version <version>"
      fi
      if [[ "$(printf '%s' "$release_json" | jq -r '.prerelease')" == "true" ]]; then
        # Not "no stable release yet": see cb_pick_release's known limitation.
        # The newest release wins whether or not a stable one exists, so this
        # message must not claim there is none.
        cb_warn "Installing release candidate $(printf '%s' "$release_json" | jq -r '.tag_name') - the newest published release. Use --version <version> to pick a specific one."
      fi
    fi

    # ${tag#v}, not `tr -d v`: `tr` deletes every v in the string, not the
    # leading one. Harmless for today's tags, wrong for any tag with a v
    # elsewhere in it (a -dev or -preview suffix, a codename).
    CB_VERSION=$(echo "$release_json" | jq -r '.tag_name')
    CB_VERSION="${CB_VERSION#v}"
    if [[ -z "$CB_VERSION" ]] || [[ "$CB_VERSION" == "null" ]]; then
      cb_fail "Failed to parse release version" "GitHub API may be rate-limited"
    fi
    cb_ok "Release: v${CB_VERSION}"

    local tarball_name="circuit-breaker_${CB_VERSION}_linux_${ARCH}.tar.gz"
    local tarball_url
    tarball_url=$(echo "$release_json" | jq -r ".assets[] | select(.name==\"${tarball_name}\") | .browser_download_url")
    if [[ -z "$tarball_url" ]] || [[ "$tarball_url" == "null" ]]; then
      cb_fail "Bundle not found for ${ARCH}" "Asset ${tarball_name} missing from release v${CB_VERSION}"
    fi

    cb_step "Downloading ${tarball_name}"
    # The release JSON already reports the asset size, so this costs one poll
    # loop and no extra request — which matters because the air-gap contract
    # forbids one. This is the most variable and most-watched phase; everything
    # else advances on declared sub-steps.
    local asset_size
    asset_size="$(printf '%s' "$release_json" \
      | jq -r --arg n "$tarball_name" '.assets[] | select(.name==$n) | .size')"

    curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 15 "$tarball_url" -o "/tmp/${tarball_name}" &
    local curl_pid=$!
    if [[ "$asset_size" =~ ^[0-9]+$ ]] && (( asset_size > 0 )); then
      while kill -0 "$curl_pid" 2>/dev/null; do
        local got pct
        got="$(stat -c '%s' "/tmp/${tarball_name}" 2>/dev/null || echo 0)"
        pct=$(( (got * 100) / asset_size ))
        # Clamped to 99: cb_progress takes a decimal fraction, so "0.100" would
        # parse as 0.10 and the bar would jump BACKWARDS to 10% on the last
        # poll. cb_phase_end supplies the final weight a moment later.
        (( pct > 99 )) && pct=99
        (( pct < 0 )) && pct=0
        cb_progress "0.$(printf '%02d' "$pct")"
        sleep 1
      done
    fi
    wait "$curl_pid" || cb_fail "Download failed" "$tarball_url"
    cb_ok "Downloaded $(du -h "/tmp/${tarball_name}" | cut -f1)"

    cb_verify_bundle_checksum "$release_json" "$tarball_name"

    CB_BUNDLE_TARBALL="/tmp/${tarball_name}"
  fi

  # Extract bundle
  #
  # --no-same-owner --no-same-permissions: as real root, GNU tar defaults to
  # --same-owner/--same-permissions, replicating the *build host's* uid/gid
  # and exact mode bits onto this machine. That is wrong on its own merits —
  # bundle contents should end up owned by whatever stage0_install_bundle
  # below decides (root:root, 755), never by whatever uid happened to build
  # the tarball — and it is also fragile: some rootful-container filesystems
  # refuse the redundant directory chmod tar issues to restore that exact
  # archived mode ("Cannot change mode to rwxr-xr-x: Operation not
  # permitted"), which otherwise aborts extraction outright. Dropping both is
  # safe because stage0_install_bundle unconditionally chowns/chmods every
  # subtree it copies from here.
  cb_step "Extracting bundle"
  rm -rf /tmp/cb-bundle
  mkdir -p /tmp/cb-bundle
  tar -xzf "$CB_BUNDLE_TARBALL" -C /tmp/cb-bundle --no-same-owner --no-same-permissions \
    || cb_fail "Bundle extraction failed" "Tarball may be corrupted: $CB_BUNDLE_TARBALL — re-run to re-download"
  CB_BUNDLE_DIR="/tmp/cb-bundle"
  if [[ ! -f "${CB_BUNDLE_DIR}/circuit-breaker" ]]; then
    cb_fail "Bundle is missing the circuit-breaker binary" "Bundle layout unexpected — check release assets for v${CB_VERSION:-unknown}"
  fi
  cb_ok "Bundle extracted"
}


stage0_install_bundle() {
  cb_section "Installing Bundle"

  # Create target directory structure
  mkdir -p /opt/circuitbreaker/bin
  mkdir -p /opt/circuitbreaker/share
  mkdir -p /opt/circuitbreaker/deploy
  mkdir -p /opt/circuitbreaker/scripts

  # Copy binary
  cb_step "Installing binary"
  cp -f "${CB_BUNDLE_DIR}/circuit-breaker" /opt/circuitbreaker/bin/circuit-breaker \
    || cb_fail "Failed to install binary" "Check disk space: df -h /opt"
  chmod 755 /opt/circuitbreaker/bin/circuit-breaker
  chown root:root /opt/circuitbreaker/bin/circuit-breaker
  cb_ok "Binary installed to /opt/circuitbreaker/bin/"

  # Copy share assets (frontend, backend/migrations, VERSION, etc.)
  cb_step "Installing application assets"
  cp -rf "${CB_BUNDLE_DIR}/share/." /opt/circuitbreaker/share/ \
    || cb_fail "Failed to install application assets" "Check disk space: df -h /opt"
  chown -R root:root /opt/circuitbreaker/share/
  chmod -R 755 /opt/circuitbreaker/share/
  cb_ok "Assets installed to /opt/circuitbreaker/share/"

  # Copy deploy infrastructure (config templates, systemd, nginx, cli)
  if [[ -d "${CB_BUNDLE_DIR}/deploy" ]]; then
    cp -rf "${CB_BUNDLE_DIR}/deploy/." /opt/circuitbreaker/deploy/
    chown -R root:root /opt/circuitbreaker/deploy/
    cb_ok "Deploy templates installed"
  fi

  # Copy agent binaries (absent in bundles built before this feature —
  # guarded so upgrading from an older release tarball degrades gracefully
  # instead of failing the install)
  if [[ -d "${CB_BUNDLE_DIR}/agent-binaries" ]]; then
    mkdir -p /opt/circuitbreaker/agent-binaries
    cp -rf "${CB_BUNDLE_DIR}/agent-binaries/." /opt/circuitbreaker/agent-binaries/
    chown -R root:root /opt/circuitbreaker/agent-binaries/
    cb_ok "Agent binaries installed"
  fi

  # Cleanup
  rm -rf /tmp/cb-bundle
  if [[ -z "$CB_LOCAL_BUNDLE" ]] && [[ -n "${CB_BUNDLE_TARBALL:-}" ]]; then
    rm -f "$CB_BUNDLE_TARBALL"
  fi
}


# Parse command-line arguments
show_help() {
  echo "Circuit Breaker Native Installer"
  echo ""
  echo "Usage: bash install.sh [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --port <number>        HTTP port (default: 8088)"
  echo "  --fqdn <domain>        Fully qualified domain name (optional)"
  echo "  --cert-type <type>     Certificate type: self-signed or letsencrypt (default: self-signed)"
  echo "  --email <address>      Email for Let's Encrypt notifications"
  echo "  --data-dir <path>      Data directory (default: /var/lib/circuitbreaker)"
  echo "  --no-tls               Skip TLS cert generation"
  echo "  --version <version>    Install specific version (default: latest)"
  echo "  --local-bundle <path>  Use a pre-downloaded bundle tarball"
  echo "  --unattended           Skip all prompts, use defaults (for Proxmox LXC)"
  echo "  --verbose              Print every step instead of a progress bar."
  echo "                         Also enabled by CB_VERBOSE=true. Implied off by"
  echo "                         --unattended, which uses plain timestamped lines."
  echo "  --upgrade              Force upgrade mode even if install not detected"
  echo "  --force-deps           Force reinstall dependencies in upgrade mode"
  echo "  --docker               Compose-only deployment (installs Docker if missing)"
  echo "  --skip-checksum        Skip SHA256 bundle verification (for a local bundle you already trust)"
  echo "  --airgap               Offline install: make no outbound request at all."
  echo "                         Installs no packages, adds no repository, downloads"
  echo "                         nothing. Requires --local-bundle and every dependency"
  echo "                         already present; lists what is missing and stops."
  echo "                         Also enabled by CB_AIRGAP=true in the environment."
  echo "  --help                 Show this help message"
  echo ""
  exit 0
}

# Preserve original args: the parser below consumes $@, but
# cb_require_native_root must re-exec with the full flag set under sudo.
CB_ORIG_ARGS=("$@")

while [[ $# -gt 0 ]]; do
  case $1 in
    --port)
      CB_PORT="$2"
      shift 2
      ;;
    --fqdn)
      CB_FQDN="$2"
      shift 2
      ;;
    --cert-type)
      CB_CERT_TYPE="$2"
      shift 2
      ;;
    --email)
      CB_EMAIL="$2"
      shift 2
      ;;
    --data-dir)
      CB_DATA_DIR="$2"
      shift 2
      ;;
    --no-tls)
      NO_TLS=true
      shift
      ;;
    --version)
      CB_VERSION="$2"
      shift 2
      ;;
    --local-bundle)
      CB_LOCAL_BUNDLE="$2"
      shift 2
      ;;
    --airgap)
      CB_AIRGAP=true
      shift
      ;;
    --unattended)
      UNATTENDED=true
      shift
      ;;
    --verbose)
      CB_VERBOSE=true
      shift
      ;;
    --upgrade)
      UPGRADE_MODE=true
      shift
      ;;
    --force-deps)
      FORCE_DEPS=true
      shift
      ;;
    --docker)
      DOCKER_MODE=true
      shift
      ;;
    --skip-checksum)
      SKIP_CHECKSUM=true
      shift
      ;;
    --help)
      show_help
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run with --help for usage information"
      exit 1
      ;;
  esac
done

# Air-gap mode promises no outbound request, and resolving a release from the
# GitHub API is one. Checked here, before anything is created, so an operator who
# forgot to stage a bundle is told immediately rather than after a user, a
# directory tree and a set of secrets already exist on the host.
if [[ "$CB_AIRGAP" == "true" ]] && [[ -z "$CB_LOCAL_BUNDLE" ]]; then
  echo "  --airgap requires --local-bundle <path>." >&2
  echo "  Air-gap mode downloads nothing, so the release tarball must already be" >&2
  echo "  on this host. Copy circuit-breaker_<version>_linux_<arch>.tar.gz across" >&2
  echo "  and re-run with --local-bundle /path/to/that/tarball." >&2
  exit 1
fi

# Compose deployment is an outbound path by construction: it fetches the compose
# files from raw.githubusercontent.com and `docker compose up -d` pulls images
# from ghcr.io. There is no honest way to run it with no network, so refuse the
# combination rather than run it and call the result air-gapped.
if [[ "$CB_AIRGAP" == "true" ]] && [[ "$DOCKER_MODE" == "true" ]]; then
  echo "  --airgap cannot be combined with --docker." >&2
  echo "  Compose deployment downloads the compose files and pulls container" >&2
  echo "  images, both of which air-gap mode forbids. Use the native install" >&2
  echo "  (drop --docker) with --local-bundle, or mirror the images yourself" >&2
  echo "  and run docker compose by hand." >&2
  exit 1
fi
# Sourced setup.sh shares this shell, but exporting keeps the value consistent
# for anything the installer runs as a child process.
export CB_AIRGAP

# Global vars set during execution
PKG_MGR=""
OS_ID=""
OS_VERSION=""
ARCH=""
LOG_FILE=""
PG_BIN_DIR=""
CB_BUNDLE_TARBALL=""
CB_BUNDLE_DIR=""


# ============================================================================
# MAIN EXECUTION — all stage functions are defined in deploy/setup.sh
# ============================================================================

main() {
  if [[ "${DOCKER_MODE}" == "true" ]]; then
    stage_docker_deploy
    exit 0
  fi

  cb_require_native_root "$@"

  # Set and truncate before cb_ui_init: _cb_log no-ops on an empty LOG_FILE,
  # and cb_ui_init's own "ui: mode=" line plus everything stage0_bootstrap_
  # preflight logs during the "preflight" phase below would otherwise reach
  # no file at all. This must not be re-truncated later — the handover to
  # ${CB_DATA_DIR}/logs/install.log in stage0_preflight (deploy/setup.sh)
  # folds this file's contents in rather than dropping them.
  LOG_FILE="/tmp/cb-bootstrap.log"
  echo "=== Bootstrap Log ===" > "$LOG_FILE"

  cb_ui_init

  if [[ "${UPGRADE_MODE}" == "true" ]]; then
    cb_ui_use_weights CB_PHASE_WEIGHTS_UPGRADE
  else
    cb_ui_use_weights CB_PHASE_WEIGHTS_INSTALL
  fi

  cb_phase_begin preflight "Pre-flight checks"
  stage0_bootstrap_preflight
  cb_phase_end preflight

  cb_phase_begin bundle "Downloading bundle"
  stage0_download_bundle
  cb_phase_end bundle

  cb_phase_begin files "Installing files"
  stage0_install_bundle
  cb_phase_end files

  if [[ -f /opt/circuitbreaker/deploy/setup.sh ]]; then
    source /opt/circuitbreaker/deploy/setup.sh

    # Always run full preflight — sets OS_VERSION, ARCH, PG_BIN_DIR, LOG_FILE
    stage0_preflight

    # Merge bootstrap log into final install log
    if [[ -f /tmp/cb-bootstrap.log ]] && [[ "$LOG_FILE" != "/tmp/cb-bootstrap.log" ]]; then
      cat /tmp/cb-bootstrap.log >> "$LOG_FILE"
      rm -f /tmp/cb-bootstrap.log
    fi

    if [[ "$UPGRADE_MODE" == "true" ]]; then
      run_upgrade
      exit 0
    fi

    # Full Fresh Install Flow
    cb_phase_begin deps "System dependencies"
    cb_phase_steps 2
    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "Retry: bash install.sh --unattended"
    )
    CB_STAGE_DIAGS=(
      "Install log (tail)::tail -n 50 ${LOG_FILE}"
      "Disk space::df -h ${CB_DATA_DIR} /opt /var"
    )
    stage1_bootstrap
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()

    # The dependency stage fails for opposite reasons in the two modes, and its
    # diagnostics are executed, not just printed -- so the networked hints and
    # the reachability probe must not arm in air-gap mode, where making that
    # request would itself break the contract the flag promises.
    if [[ "$CB_AIRGAP" == "true" ]]; then
      CB_STAGE_HINTS=(
        "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
        "Air-gap installs nothing: stage the listed packages from your local mirror or media, then re-run"
        "The nats-server binary ships as the circuit-breaker-nats package published beside the release tarball"
      )
      CB_STAGE_DIAGS=(
        "Install log (tail)::tail -n 50 ${LOG_FILE}"
        "Dependencies found locally::for b in curl jq openssl git wget gpg lsof nc setcap pgbouncer redis-server nginx nmap nats-server pg_ctl; do printf '%-16s %s\\n' \"\$b\" \"\$(command -v \"\$b\" || echo MISSING)\"; done"
      )
    else
      CB_STAGE_HINTS=(
        "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
        "Check internet: curl -I https://github.com"
        "Retry with fresh deps: bash install.sh --force-deps"
        "Manual package check: ${PKG_MGR} install -y postgresql-15 redis nginx pgbouncer"
      )
      CB_STAGE_DIAGS=(
        "Install log (tail)::tail -n 50 ${LOG_FILE}"
        "Network reachability::curl -sS -o /dev/null -w 'github.com -> HTTP %{http_code} in %{time_total}s\\n' -m 10 https://github.com"
      )
    fi
    stage2_dependencies
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()
    cb_phase_end deps

    cb_phase_begin database "Preparing database"
    cb_phase_steps 3
    # stage4 FIRST, because that is where it already is (install.sh:1720, before
    # postgres). Phases are assigned without moving any call: a rendering change
    # must not reorder installation steps, and writing the unit files after the
    # database is configured would do exactly that.
    stage4_write_systemd_units
    cb_phase_tick

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "PostgreSQL status: systemctl status circuitbreaker-postgres"
      "PostgreSQL logs: journalctl -u circuitbreaker-postgres -n 30"
      "Check disk space: df -h ${CB_DATA_DIR}"
      "Retry: bash install.sh --force-deps"
    )
    CB_STAGE_DIAGS=(
      "circuitbreaker-postgres status::systemctl status circuitbreaker-postgres --no-pager -l"
      "circuitbreaker-postgres logs::journalctl -u circuitbreaker-postgres --no-pager -n 40"
      "Install log (tail)::tail -n 40 ${LOG_FILE}"
      "Disk space::df -h ${CB_DATA_DIR}"
    )
    stage3_configure_postgres
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "pgbouncer status: systemctl status circuitbreaker-pgbouncer"
      "pgbouncer logs: journalctl -u circuitbreaker-pgbouncer -n 30"
    )
    CB_STAGE_DIAGS=(
      "circuitbreaker-pgbouncer status::systemctl status circuitbreaker-pgbouncer --no-pager -l"
      "circuitbreaker-pgbouncer logs::journalctl -u circuitbreaker-pgbouncer --no-pager -n 40"
      "Install log (tail)::tail -n 40 ${LOG_FILE}"
    )
    stage3_configure_pgbouncer
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()
    cb_phase_end database

    cb_phase_begin services "Services and networking"
    cb_phase_steps 8
    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "Redis status: systemctl status circuitbreaker-redis"
      "Redis logs: journalctl -u circuitbreaker-redis -n 30"
      "Port check: ss -tlnp | grep 6379"
    )
    CB_STAGE_DIAGS=(
      "circuitbreaker-redis status::systemctl status circuitbreaker-redis --no-pager -l"
      "circuitbreaker-redis logs::journalctl -u circuitbreaker-redis --no-pager -n 40"
      "Redis data dir::ls -ld ${CB_DATA_DIR}/redis"
      "Install log (tail)::tail -n 40 ${LOG_FILE}"
    )
    stage3_configure_redis
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()

    CB_STAGE_HINTS=(
      "Full log: tail -50 ${CB_DATA_DIR}/logs/install.log"
      "NATS status: systemctl status circuitbreaker-nats"
      "NATS logs: journalctl -u circuitbreaker-nats -n 30"
      "NATS binary: ls -la /opt/circuitbreaker/bin/nats-server"
    )
    CB_STAGE_DIAGS=(
      "circuitbreaker-nats status::systemctl status circuitbreaker-nats --no-pager -l"
      "circuitbreaker-nats logs::journalctl -u circuitbreaker-nats --no-pager -n 40"
      "NATS binary::ls -la /opt/circuitbreaker/bin/nats-server /usr/local/bin/nats-server 2>&1"
      "Install log (tail)::tail -n 40 ${LOG_FILE}"
    )
    stage3_configure_nats
    cb_phase_tick
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()

    stage3_configure_nginx
    cb_phase_tick
    stage3_configure_docker_proxy
    cb_phase_tick
    write_wait_for_services_script
    cb_phase_tick
    write_service_scripts
    cb_phase_tick
    stage6_apply_binary
    cb_phase_tick
    stage9_install_cb_cli
    cb_phase_tick
    stage9_write_install_identity
    cb_phase_end services

    cb_phase_begin start "Starting Circuit Breaker"
    cb_arm_service_start_diagnostics
    stage8_start_services
    CB_STAGE_HINTS=()
    CB_STAGE_DIAGS=()
    cb_phase_end start

    stage10_final_output
  else
    cb_fail "Setup scripts not found" "Check bundle structure at /opt/circuitbreaker/deploy/"
  fi
}

# Run main with the original argument list (safe under set -u on old bash)
main ${CB_ORIG_ARGS[@]+"${CB_ORIG_ARGS[@]}"}
