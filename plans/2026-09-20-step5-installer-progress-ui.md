# Step 5 — Installer Progress UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 269 narration lines with seven headlines, a themed progress bar, and honest elapsed/remaining time — while making a failed install strictly more diagnosable than it is today.

**Architecture:** One new sourced Bash library, `deploy/lib/ui.sh`, holding an event API and a renderer that resolves its output mode once at startup. `cb_step`, `cb_ok`, `cb_section` and `cb_warn` are kept as aliases onto the new events, so all 269 existing call sites and the four test suites that stub them keep working unchanged. Stage functions gain phase boundaries only.

**Tech Stack:** Bash 5.x, ANSI escapes, `tput`/`stty`, pytest for the policy and behaviour suites.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §22, §23, §24.

**Depends on:** nothing technically. Sequenced after Steps 0–4 because a quiet installer is only trustworthy on a pipeline whose signals mean something.

## Global Constraints

- **The ASCII banner is untouched.** `cb_logo` in `install.sh` is unchanged byte for byte, and `tests/build/test_installer_banner_unchanged.py` (Task 6) enforces it. This is the one hard constraint on the whole plan.
- **No placeholders.** No `TODO`, bare `:` used as a stub, or unimplemented branch.
- **Backward compatible.** `cb_step`/`cb_ok`/`cb_section`/`cb_warn` keep their names and their observable behaviour under `--verbose`. Four existing suites stub them; none may need editing.
- **Air-gap is first-class.** The renderer makes no outbound call. The only new measurement source is the asset size already present in the release JSON the installer has fetched.
- Never hardcode credentials, tokens, signing material or vault keys.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan does not touch `apps/backend/src/app`, so `make verify` is the pre-push gate. It does **not** execute `install.sh`; see "What this plan does NOT cover".
- `install.sh` runs under `set -euo pipefail`. Every function added must be safe under `set -u`, and anything that can legitimately exit non-zero must be guarded with `|| true`.

## Background an implementer needs

`install.sh` (1341 lines) bootstraps and then sources `deploy/setup.sh` (2012 lines). Between them: 269 calls to `cb_step`/`cb_ok`/`cb_warn` under 21 `cb_section` headers. (There is no `cb_info` in this repo — do not add an alias for it.)

Every subprocess is already silenced — each `apt-get`, `initdb`, `systemctl start`, `nginx -t` and `openssl req` redirects to `$LOG_FILE`. **The noise is entirely our own narration**, which is why this is a rendering change and not a plumbing change.

`$LOG_FILE` changes value mid-run: it is `/tmp/cb-bootstrap.log` until `stage0_preflight` sets it to `${CB_DATA_DIR}/logs/install.log` and concatenates the bootstrap log in. The log sink must therefore read `$LOG_FILE` on every write rather than caching it.

Two existing helpers must be reused, not reimplemented: `cb_term_at_least` (which documents why it must never be called in a command substitution) and `cb_fail`'s diagnostics machinery (`CB_STAGE_DIAGS`, `CB_STAGE_HINTS`, `cb_env_redacted`).

## File Structure

| File | Responsibility |
|---|---|
| `deploy/lib/ui.sh` | The event API, mode resolution, all three renderers, the phase table and the ETA. Sourced by `install.sh` and re-sourced by `deploy/setup.sh`. |
| `install.sh` | Carries an inlined byte-identical copy of `ui.sh` (it is served raw from `main`, so it cannot source at runtime); adds `--verbose`; declares phase boundaries in `main`. |
| `scripts/ci/sync_installer_ui.py` | Regenerates that inlined block from the library. |
| `tests/build/test_installer_ui_inline_matches_library.py` | Fails the build if the pair drifts. |
| `deploy/setup.sh` | Declares phase boundaries inside the stage functions. |
| `tests/build/test_installer_phase_model.py` | Weights sum to 100; every runtime phase key is declared. |
| `tests/build/test_installer_render_modes.py` | Mode selection, no ANSI in plain, log completeness, warnings always visible. |
| `tests/build/test_installer_eta_monotonic.py` | The ETA never increases. |
| `tests/build/test_installer_failure_output.py` | Live region torn down before diagnostics; log tail replayed. |
| `tests/build/test_installer_banner_unchanged.py` | `cb_logo` is byte-identical. |

---

### Task 1: The rendering library

**Files:**
- Create: `deploy/lib/ui.sh`

**Interfaces:**
- Produces, for every later task and for `deploy/setup.sh`:
  - `cb_ui_init` — resolve the mode; install the `EXIT` trap. Called once.
  - `cb_phase_begin <key> <headline>`
  - `cb_phase_end <key>`
  - `cb_progress <fraction>` — `0`–`1`, within the open phase
  - `cb_phase_tick` — advance by `1/n` of the open phase's declared sub-steps
  - `cb_detail <text>` — log always; screen only in `verbose`
  - `cb_note <text>` — log and screen in every mode
  - `cb_ui_teardown` — clear the live region
  - `cb_ui_ledger` — print the phase ledger, used by the failure path
  - Globals: `CB_UI_MODE` (`tty`|`plain`|`verbose`), `CB_PHASE_WEIGHTS`, `CB_PHASE_ORDER`

- [ ] **Step 1: Write the library**

Create `deploy/lib/ui.sh`:

```sh
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

# Phase weights, as percentages of a whole install. They must sum to 100 and
# every key used at runtime must appear here; tests/build/test_installer_phase_model.py
# asserts both.
#
# These are ratios of measured medians. A phase is a unit of elapsed time a user
# can FEEL, not a unit of implementation, which is why the 21 old sections
# collapse unevenly: "Writing Service Scripts" was instant and
# "Installing Dependencies" is most of the wall clock.
declare -gA CB_PHASE_WEIGHTS=(
  [preflight]=2
  [bundle]=12
  [files]=6
  [deps]=45
  [database]=15
  [services]=12
  [start]=8
)
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
_cb_render_eta() {
  local pct elapsed remaining open_weight budget open_elapsed
  pct="$(_cb_overall_percent)"
  elapsed=$(( $(date +%s) - _CB_START_EPOCH ))

  if [[ -n "${_CB_OPEN_PHASE}" ]]; then
    open_weight="${CB_PHASE_WEIGHTS[${_CB_OPEN_PHASE}]:-0}"
    open_elapsed=$(( $(date +%s) - _CB_OPEN_START ))
    # The budget a phase "should" take, if the whole install ran at the rate
    # implied by elapsed time so far. Doubling it is the overrun threshold.
    budget=$(( (elapsed * open_weight) / 100 + 1 ))
    if (( open_elapsed > budget * 2 )); then
      printf 'taking longer than expected'
      return 0
    fi
  fi

  if (( pct < 5 )); then
    printf 'estimating...'
    return 0
  fi

  remaining=$(( (elapsed * (100 - pct)) / pct ))
  if (( _CB_LAST_ETA >= 0 )) && (( remaining > _CB_LAST_ETA )); then
    remaining="${_CB_LAST_ETA}"
  fi
  _CB_LAST_ETA="$remaining"
  printf '~%s remaining' "$(_cb_human_duration "$remaining")"
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
```

- [ ] **Step 2: Syntax-check and shellcheck the library**

```bash
bash -n deploy/lib/ui.sh && echo "syntax OK"
shellcheck -x deploy/lib/ui.sh || true
```

Expected: `syntax OK`. Address any shellcheck error (not warning) it reports.

- [ ] **Step 3: Exercise it standalone in all three modes**

```bash
cat > /tmp/ui-demo.sh <<'DEMO'
set -euo pipefail
LOG_FILE=/tmp/ui-demo.log; : > "$LOG_FILE"
source deploy/lib/ui.sh
cb_ui_init
cb_phase_begin preflight "Pre-flight checks"
cb_step "Checking privileges"; cb_ok "Running as root"
cb_phase_end preflight
cb_phase_begin deps "System dependencies"
cb_phase_steps 4
for i in 1 2 3 4; do cb_step "installing package $i"; cb_phase_tick; sleep 0.3; done
cb_warn "needrestart was suppressed"
cb_phase_end deps
cb_ui_teardown
DEMO
echo "--- tty (if this is a terminal) ---"; bash /tmp/ui-demo.sh
echo "--- plain (piped) ---";   bash /tmp/ui-demo.sh | cat
echo "--- verbose ---";         CB_VERBOSE=true bash /tmp/ui-demo.sh
echo "--- log contents ---";    cat /tmp/ui-demo.log
```

Expected: a bar and two headlines in the first; timestamped lines and **no escape characters** in the second; every `cb_step` line in the third; and the log containing every detail regardless of mode.

- [ ] **Step 4: Commit**

```bash
git add deploy/lib/ui.sh
git commit -m "feat: add the installer rendering library

One event API, one mode resolved at startup, three renderers and a log sink
that is always on. cb_step/cb_ok/cb_section/cb_warn are kept as aliases so all
269 existing call sites and the four suites that stub them keep working.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire `install.sh` — sourcing, `--verbose`, and the first three phases

**Files:**
- Modify: `install.sh`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces: `CB_VERBOSE` and `--verbose`; `phases preflight`, `bundle`, `files` opened and closed.

- [ ] **Step 1: Inline the library into `install.sh` — do NOT source it at runtime**

`install.sh` is served **raw from the `main` branch**. `pages.yml:60` is a bare
`cp install.sh _site/install.sh`, its own comment says "every documented command
curls raw.githubusercontent.com", and `docs/installation/quick-install.md:12` is
`curl -fsSL .../main/install.sh | bash`. **There is no assembly step on the
documented install path.** An `install.sh` that sources `deploy/lib/ui.sh` at
runtime therefore breaks every `curl | bash` install the moment it reaches main —
the bundle that would carry the library is exactly what has not been downloaded yet.

So the installer stays self-contained, which is what it already is. Add these two
markers to `install.sh`, immediately after the colour-code block:

```sh
# --- BEGIN INLINED deploy/lib/ui.sh — regenerate with scripts/ci/sync_installer_ui.py ---
# --- END INLINED deploy/lib/ui.sh ---
```

`deploy/lib/ui.sh` stays the source of truth: `deploy/setup.sh` and `uninstall.sh`
source it from `/opt/circuitbreaker/deploy/lib/ui.sh`, which the bundle ships and
which exists by the time either runs. `install.sh` gets a byte-identical copy
between the markers, kept in sync by Task 5. Do not write `_cb_source_ui`.

- [ ] **Step 2: Add the `--verbose` flag**

In the argument parser, beside `--unattended`:

```sh
    --verbose)
      CB_VERBOSE=true
      shift
      ;;
```

In the defaults block, beside `CB_AIRGAP`'s seeding, and using the same shape so the flag and the environment variable are one switch:

```sh
# Seeded from the environment so `CB_VERBOSE=true bash install.sh` and
# `--verbose` mean the same thing.
_cb_verbose_from_env="${CB_VERBOSE:-}"
CB_VERBOSE=false
case "$_cb_verbose_from_env" in
  true|True|TRUE|1|yes|on) CB_VERBOSE=true ;;
esac
unset _cb_verbose_from_env
export CB_VERBOSE
```

In `show_help`, after the `--unattended` line:

```sh
  echo "  --verbose              Print every step instead of a progress bar."
  echo "                         Also enabled by CB_VERBOSE=true. Implied off by"
  echo "                         --unattended, which uses plain timestamped lines."
```

- [ ] **Step 3: Initialise the renderer and open the first phases in `main`**

In `main`, immediately after `cb_require_native_root "$@"`:

```sh
  cb_ui_init
```

The renderer is already defined: it was inlined between the markers at the top of
this same file, so there is nothing to source and nothing that can fail to load.

Then wrap the three bootstrap stages:

```sh
  cb_phase_begin preflight "Pre-flight checks"
  stage0_bootstrap_preflight
  cb_phase_end preflight

  LOG_FILE="/tmp/cb-bootstrap.log"
  echo "=== Bootstrap Log ===" > "$LOG_FILE"

  cb_phase_begin bundle "Downloading bundle"
  stage0_download_bundle
  cb_phase_end bundle

  cb_phase_begin files "Installing files"
  stage0_install_bundle
  cb_phase_end files
```

- [ ] **Step 4: Report real download progress**

In `stage0_download_bundle`, the release JSON already carries each asset's byte `size`. Capture it beside `tarball_url`, then run `curl` in the background and poll:

```sh
    # The release JSON already reports the asset size, so this costs one poll
    # loop and no extra request — which matters because the air-gap contract
    # forbids one. This is the most variable and most-watched phase; everything
    # else advances on declared sub-steps.
    local asset_size
    asset_size="$(printf '%s' "$release_json" \
      | jq -r --arg n "$tarball_name" '.assets[] | select(.name==$n) | .size')"

    curl -fsSL "$tarball_url" -o "/tmp/${tarball_name}" &
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
```

**Why the clamp matters.** `cb_progress` takes a decimal fraction, so an unclamped `0.100` parses as `0.10` and the bar jumps backwards to 10% on the final poll — which also trips the ETA's monotone clamp into freezing. `cb_phase_end` adds the phase's full weight immediately afterwards, so the bar never stalls visibly short.

- [ ] **Step 5: Verify the script still parses and the flag works**

```bash
bash -n install.sh && echo "syntax OK"
bash install.sh --help | grep -A2 verbose
```

Expected: `syntax OK`, and the `--verbose` help text.

- [ ] **Step 6: Run the existing installer policy suites**

Run: `pytest tests/build -k install -q`

Expected: pass. These suites stub `cb_step`/`cb_ok`, which the aliases preserve. **If one fails, do not edit the suite** — it is telling you a contract moved.

- [ ] **Step 7: Commit**

```bash
git add install.sh
git commit -m "feat: give install.sh phases, a progress bar and --verbose

The three bootstrap stages become the first three phases. The download phase
reports real byte progress against the asset size the release JSON already
carries, so the most variable and most-watched stretch moves honestly and costs
no extra request.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire `deploy/setup.sh` — the remaining four phases

**Files:**
- Modify: `install.sh` (`main`, the stage calls after `source setup.sh`)
- Modify: `deploy/setup.sh`

- [ ] **Step 1: Re-source the library in `deploy/setup.sh`**

At the top of `deploy/setup.sh`, before the first function:

```sh
# install.sh already sourced this, but setup.sh is also sourced directly by the
# upgrade path. The library guards against double-sourcing with _CB_UI_LOADED.
if [[ -r /opt/circuitbreaker/deploy/lib/ui.sh ]]; then
  # shellcheck source=lib/ui.sh
  source /opt/circuitbreaker/deploy/lib/ui.sh
fi
```

- [ ] **Step 2: Wrap the remaining stages in `install.sh::main`**

Replace the sequence from `stage1_bootstrap` through `stage8_start_services` with phase-wrapped groups. Keep every `CB_STAGE_HINTS` / `CB_STAGE_DIAGS` assignment exactly where it is — those arm the failure path and must not move.

```sh
    cb_phase_begin deps "System dependencies"
    cb_phase_steps 2
    # ... existing CB_STAGE_HINTS / CB_STAGE_DIAGS for stage1 ...
    stage1_bootstrap
    cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    # ... existing air-gap / networked hint blocks for stage2 ...
    stage2_dependencies
    cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    cb_phase_end deps

    cb_phase_begin database "Preparing database"
    cb_phase_steps 2
    # ... existing postgres hints/diags ...
    stage3_configure_postgres
    cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    # ... existing pgbouncer hints/diags ...
    stage3_configure_pgbouncer
    cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    cb_phase_end database

    cb_phase_begin services "Services and networking"
    cb_phase_steps 9
    stage4_write_systemd_units; cb_phase_tick
    # ... existing redis hints/diags ...
    stage3_configure_redis; cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    # ... existing nats hints/diags ...
    stage3_configure_nats; cb_phase_tick
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    stage3_configure_nginx; cb_phase_tick
    stage3_configure_docker_proxy; cb_phase_tick
    write_wait_for_services_script; cb_phase_tick
    write_service_scripts; cb_phase_tick
    stage6_apply_binary; cb_phase_tick
    stage9_install_cb_cli; cb_phase_tick
    stage9_write_install_identity
    cb_phase_end services

    cb_phase_begin start "Starting Circuit Breaker"
    cb_arm_service_start_diagnostics
    stage8_start_services
    CB_STAGE_HINTS=(); CB_STAGE_DIAGS=()
    cb_phase_end start

    stage10_final_output
```

- [ ] **Step 3: Remove the 21 `cb_section` calls from `deploy/setup.sh`**

Each `cb_section "..."` is now an alias onto `cb_detail`, so it logs and prints nothing on screen — which is correct and requires no edit. **Leave them in place.** Deleting 21 lines across a 2012-line file risks a mistake for no benefit, and the log keeps its section markers.

- [ ] **Step 4: Verify both scripts parse**

```bash
bash -n install.sh && bash -n deploy/setup.sh && echo "syntax OK"
```

Expected: `syntax OK`.

- [ ] **Step 5: Assert the phase keys match the table**

```bash
grep -oE 'cb_phase_(begin|end) [a-z]+' install.sh | awk '{print $2}' | sort -u
grep -oE '\[[a-z]+\]=' deploy/lib/ui.sh | tr -d '[]=' | sort -u
```

Expected: the two lists are identical. Task 6's test asserts this mechanically; this is the manual check before you get there.

- [ ] **Step 6: Run the installer suites**

Run: `pytest tests/build -q`

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add install.sh deploy/setup.sh
git commit -m "feat: collapse the 21 installer sections into seven phases

Each phase is a unit of elapsed time a user can feel rather than a unit of
implementation, so the bar advances proportionally instead of lurching. Every
CB_STAGE_HINTS and CB_STAGE_DIAGS assignment stays exactly where it was — they
arm the failure path and moving them would weaken it.

The cb_section calls stay too: they are aliases onto the log sink now, so the
log keeps its section markers at no screen cost.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The failure path

**Files:**
- Modify: `install.sh` — `cb_fail`

- [ ] **Step 1: Extend `cb_fail`**

Replace `cb_fail`'s body, keeping every existing behaviour and adding four things in order:

```sh
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

  # Named explicitly, as the last two lines. An operator should never have to
  # know to go and find these.
  echo ""
  echo -e "  ${BOLD}Full log:${RESET}  ${LOG_FILE:-/tmp/cb-bootstrap.log}"
  echo -e "  ${BOLD}Re-run with full output:${RESET}  bash install.sh --verbose"
  echo ""
  exit 1
}
```

- [ ] **Step 2: Verify the ordering by inspection**

```bash
sed -n '/^cb_fail()/,/^}/p' install.sh | grep -n 'teardown\|ledger\|log_tail\|run_diagnostics\|Full log'
```

Expected, in this order: `teardown`, `ledger`, `log_tail`, `run_diagnostics`, `Full log`.

- [ ] **Step 3: Verify it parses**

```bash
bash -n install.sh && echo "syntax OK"
```

- [ ] **Step 4: Commit**

```bash
git add install.sh
git commit -m "feat: make a failed install more diagnosable, not less

Failure output gets LONGER under a quiet installer, which is the point: the
screen is quiet exactly as long as nothing is wrong. Tears down the live region
first, prints the phase ledger, replays the 30 log lines the quiet mode hid,
then runs the diagnostics cb_fail already armed, then names the log path and
the verbose re-run.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Keep the inlined copy and the library byte-identical

**Files:**
- Create: `scripts/ci/sync_installer_ui.py`
- Create: `tests/build/test_installer_ui_inline_matches_library.py`

**Why a pair, and why pinned.** `install.sh` must be self-contained (Task 2 Step 1),
and `deploy/setup.sh`/`uninstall.sh` need the same renderer from the installed
bundle. That is two copies, and CLAUDE.md rule 5 is explicit: dependencies pinned
in two places move together, and the guard goes in rather than only the fix.
`tests/build/test_playwright_image_matches_package.py` is the existing precedent.

**No workflow changes.** `release.yml` and `pages.yml` are untouched — the whole
point of inlining at rest rather than at release time is that the documented
`curl | bash` path runs no assembly step.

- [ ] **Step 1: Write the sync script**

`scripts/ci/sync_installer_ui.py` reads `deploy/lib/ui.sh`, replaces everything
between the two markers in `install.sh` with it, and writes `install.sh` back.
`--check` reports drift and exits 1 without writing. Full type annotations and a
docstring on every public function; mypy runs with `disallow_untyped_defs`.

- [ ] **Step 2: Run it and confirm `install.sh` still parses**

```bash
.venv/bin/python scripts/ci/sync_installer_ui.py
bash -n install.sh && echo "syntax OK"
.venv/bin/python scripts/ci/sync_installer_ui.py --check && echo "in sync"
```

Expected: `syntax OK` then `in sync`.

- [ ] **Step 3: Write the byte-identity test**

`tests/build/test_installer_ui_inline_matches_library.py` extracts the block
between the markers in `install.sh` and asserts it equals `deploy/lib/ui.sh`
exactly. The failure message must name the sync command. Include a test that the
markers exist at all, so the suite cannot pass vacuously if someone deletes them.

- [ ] **Step 4: Prove it has teeth**

Append a line to `deploy/lib/ui.sh`, run the test, confirm it fails naming the
sync command, then re-run the sync and confirm green.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/sync_installer_ui.py tests/build/test_installer_ui_inline_matches_library.py install.sh
git commit -m "feat: pin the installer's inlined renderer to the library

install.sh is served raw from main — pages.yml does a bare cp and the documented
command curls raw.githubusercontent.com — so it cannot source the renderer at
runtime without breaking every curl|bash install. It carries an inlined copy
instead, and a byte-identity test fails the build if the pair drifts.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The test suites

**Files:**
- Create: `tests/build/test_installer_phase_model.py`
- Create: `tests/build/test_installer_render_modes.py`
- Create: `tests/build/test_installer_eta_monotonic.py`
- Create: `tests/build/test_installer_failure_output.py`
- Create: `tests/build/test_installer_banner_unchanged.py`

- [ ] **Step 1: The banner test — write it first**

This is the mechanical guarantee of the plan's one hard constraint.

```python
"""cb_logo is not to be touched.

The artwork was the one part of the installer explicitly excluded from this
redesign. It is pinned by content hash rather than by eye, because "I did not
mean to change it" is not a property a reviewer can check on a 20-line block of
backslashes.

To change the banner deliberately: update EXPECTED_SHA256 in the same commit,
and say in the message why.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "install.sh"

EXPECTED_SHA256 = "REPLACE_WITH_THE_HASH_PRINTED_BY_STEP_2"


def _logo_source() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    match = re.search(r"^cb_logo\(\) \{\n(.*?)^\}$", text, re.DOTALL | re.MULTILINE)
    assert match, "cb_logo() not found in install.sh"
    return match.group(1)


def test_the_banner_is_unchanged() -> None:
    digest = hashlib.sha256(_logo_source().encode("utf-8")).hexdigest()
    assert digest == EXPECTED_SHA256, (
        f"cb_logo() changed (sha256 {digest}).\n"
        "The ASCII art is explicitly out of scope for the installer redesign. "
        "If this change is deliberate, update EXPECTED_SHA256 in this file in "
        "the same commit and say why in the message."
    )
```

- [ ] **Step 2: Compute and paste the real hash**

```bash
python3 - <<'PY'
import hashlib, re, pathlib
text = pathlib.Path("install.sh").read_text()
body = re.search(r"^cb_logo\(\) \{\n(.*?)^\}$", text, re.DOTALL | re.MULTILINE).group(1)
print(hashlib.sha256(body.encode()).hexdigest())
PY
```

Paste the printed digest into `EXPECTED_SHA256`, replacing the placeholder string. **The placeholder must not survive this step** — run `grep REPLACE_WITH tests/build/test_installer_banner_unchanged.py` and confirm it returns nothing.

- [ ] **Step 3: The phase model test**

```python
"""The weights must sum to 100 and cover every phase the installer opens.

A weight table that does not sum to 100 makes the bar stop short or saturate
early; a phase opened at runtime that the table does not know makes it jump.
Both are the "confidently wrong" failure the ETA rules exist to avoid, arriving
by a different route.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"
INSTALLER = REPO_ROOT / "install.sh"


def _declared_weights() -> dict[str, int]:
    text = UI.read_text(encoding="utf-8")
    block = re.search(r"declare -gA CB_PHASE_WEIGHTS=\((.*?)\)", text, re.DOTALL)
    assert block, "CB_PHASE_WEIGHTS not found in deploy/lib/ui.sh"
    return {key: int(value) for key, value in re.findall(r"\[(\w+)\]=(\d+)", block.group(1))}


def _used_phase_keys() -> set[str]:
    text = INSTALLER.read_text(encoding="utf-8")
    return set(re.findall(r"cb_phase_(?:begin|end)\s+([a-z_]+)", text))


def test_weights_sum_to_one_hundred() -> None:
    weights = _declared_weights()
    total = sum(weights.values())
    assert total == 100, f"phase weights sum to {total}, not 100: {weights}"


def test_every_runtime_phase_is_declared() -> None:
    declared = set(_declared_weights())
    used = _used_phase_keys()
    assert used, "no cb_phase_begin/end calls found in install.sh"
    undeclared = used - declared
    assert not undeclared, (
        f"install.sh opens phases {sorted(undeclared)} that CB_PHASE_WEIGHTS "
        "does not declare, so they contribute no weight and the bar jumps."
    )


def test_every_declared_phase_is_used() -> None:
    declared = set(_declared_weights())
    unused = declared - _used_phase_keys()
    assert not unused, (
        f"CB_PHASE_WEIGHTS declares {sorted(unused)}, which install.sh never "
        "opens, so the bar can never reach 100%."
    )
```

- [ ] **Step 4: The render-mode test**

```python
"""One switch, three modes, and the log independent of all of them.

The old helpers re-decided "am I a TTY / should I log this" at each call site,
which is how output modes drift apart the first time someone adds a step. These
assertions run the real library in a subshell and read what it produced.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UI = REPO_ROOT / "deploy" / "lib" / "ui.sh"

ANSI = re.compile(r"\033\[")

SCRIPT = """
set -euo pipefail
LOG_FILE="$1"; : > "$LOG_FILE"
source "{ui}"
cb_ui_init
cb_phase_begin preflight "Pre-flight checks"
cb_step "a quiet detail"
cb_warn "a loud warning"
cb_phase_end preflight
cb_ui_teardown
"""


def _run(tmp_path: Path, env: dict[str, str]) -> tuple[str, str]:
    log = tmp_path / "install.log"
    script = tmp_path / "drive.sh"
    script.write_text(SCRIPT.format(ui=UI))
    completed = subprocess.run(
        ["bash", str(script), str(log)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "TERM": "dumb", **env},
        check=True,
    )
    return completed.stdout, log.read_text(encoding="utf-8")


def test_plain_mode_emits_no_ansi(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {})
    assert not ANSI.search(stdout), (
        "plain mode emitted ANSI escapes. This output goes to CI logs, "
        "cloud-init consoles and `ssh host 'bash install.sh'` — none of which "
        "render them."
    )


def test_details_reach_the_log_in_every_mode(tmp_path: Path) -> None:
    for env in ({}, {"CB_VERBOSE": "true"}):
        _, log = _run(tmp_path, env)
        assert "a quiet detail" in log, f"detail lost from the log with env={env}"


def test_details_stay_off_the_screen_unless_verbose(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {})
    assert "a quiet detail" not in stdout


def test_verbose_puts_details_on_the_screen(tmp_path: Path) -> None:
    stdout, _ = _run(tmp_path, {"CB_VERBOSE": "true"})
    assert "a quiet detail" in stdout


def test_warnings_are_visible_in_every_mode(tmp_path: Path) -> None:
    """A warning the quiet mode swallowed would be a regression."""
    for env in ({}, {"CB_VERBOSE": "true"}, {"CI": "true"}, {"NO_COLOR": "1"}):
        stdout, log = _run(tmp_path, env)
        assert "a loud warning" in stdout, f"warning lost from the screen with env={env}"
        assert "a loud warning" in log, f"warning lost from the log with env={env}"
```

- [ ] **Step 5: The ETA and failure-output tests**

Create `tests/build/test_installer_eta_monotonic.py` driving `_cb_render_eta` across a synthetic sequence of `_CB_DONE_WEIGHT` values and asserting the parsed seconds never increase, and `tests/build/test_installer_failure_output.py` asserting — by reading `cb_fail`'s body out of `install.sh` — that `cb_ui_teardown`, `cb_ui_ledger` and `cb_ui_log_tail` all appear **before** `cb_run_diagnostics`, and that the body names both `Full log:` and `--verbose`.

Write these following the idiom of Step 4: drive the real shell, read the real output, and assert on behaviour rather than on source text wherever behaviour is observable.

- [ ] **Step 6: Run everything**

```bash
pytest tests/build -q
make lint
make verify
```

Expected: all pass, and `grep -r REPLACE_WITH tests/` returns nothing.

- [ ] **Step 7: Commit**

```bash
git add tests/build/
git commit -m "test: pin the installer's phases, modes, ETA, failure path and banner

The banner test is the mechanical guarantee of the one hard constraint on this
redesign: cb_logo is pinned by content hash, because 'I did not mean to change
it' is not a property a reviewer can check on 20 lines of backslashes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `pytest tests/build -q`, `make lint`, `make verify` pass.
- [ ] `bash -n install.sh`, `bash -n deploy/setup.sh`, `bash -n deploy/lib/ui.sh` all clean.
- [ ] The three-mode demo (Task 1 Step 3) behaves correctly in tty, plain and verbose.
- [ ] `grep -r REPLACE_WITH tests/` returns nothing.
- [ ] `.venv/bin/python scripts/ci/sync_installer_ui.py --check` exits 0.
- [ ] `install.sh` still parses after inlining, and contains no `source`/`.` of `deploy/lib/ui.sh`.
- [ ] The four pre-existing suites that stub `cb_step`/`cb_ok` pass **unedited**.
- [ ] `cb_logo` is byte-identical — the banner test passes against the hash computed from the current tree.

## What this plan does NOT cover

**Nothing here runs `install.sh` against a real host.** `make verify` does not, `pytest tests/build` does not, and the demo script in Task 1 exercises the library in isolation rather than the installer. The covering suite for this change is the installer journey job, which is Step 7 of the design and does not exist yet.

Until it does, this plan's changes are verified by: shell syntax checks, the library driven directly in three modes, policy tests over the phase model and failure-path ordering, and a manual install on a throwaway VM. **Do the manual install before merging, and say in the PR which distro it was.** Reporting this plan complete on `make verify` alone is precisely the failure CLAUDE.md rule 1 exists to prevent.
