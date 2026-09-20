# Install experience and release verification

**Status:** proposed.
**Date:** 2026-09-20.
**Scope:** the native installer's presentation and diagnostics layer; the
packaging toolchain that produces what it installs; the release gates that
decide whether either is publishable.
**Supersedes nothing.** Complements
`2026-09-16-installation-diagnosis-simplification-plan.md`, which addressed
install *identity* and *diagnosis*. This one addresses install *experience* and
*verification*.

---

## 0. Why this document has three parts

The request was to make the installer concise. Investigating it surfaced a
second problem that cannot honestly be separated from the first.

The installer narrates 269 individual steps because narration was the only
evidence anyone had that it worked. It is verbose in proportion to how little
the pipeline proves. Removing the narration without adding the proof would
trade a slow, legible install for a fast, opaque one — and v0.4.2 already
demonstrated what ships when proof is missing.

So this document specifies:

- **Part I — the install experience.** A phase model, a progress renderer, and
  a failure path that is strictly more diagnosable than today's.
- **Part II — the packaging toolchain.** Why PyInstaller `--onefile` costs more
  than it returns, what replaces it, and the measurements that decide.
- **Part III — release verification.** Why v0.4.2 shipped a binary with no
  application inside it and passed every blocking gate while doing so.

Part III is the load-bearing one. Parts I and II are improvements; Part III is
the reason the other two are worth doing.

---

## 1. Findings

### 1.1 The installer's verbosity is self-inflicted, not leaked output

`install.sh` (1341 lines) bootstraps and then sources `deploy/setup.sh`
(2012 lines). Between them they make **269 calls** to `cb_step`, `cb_ok`,
`cb_warn` and `cb_info`, organised under **21 `cb_section` headers**.

Every subprocess is already silenced. Each `apt-get`, `initdb`, `systemctl
start`, `nginx -t` and `openssl req` redirects to `$LOG_FILE`. Nothing a
package manager prints reaches the screen.

The noise is therefore entirely our own, and entirely under our control. That
is good news: the fix is a rendering change, not a plumbing change.

### 1.2 The existing failure path is strong and must survive

`cb_fail` already does three things that most installers do not:

- runs `CB_STAGE_DIAGS`, a stage-scoped set of read-only diagnostics, at
  failure time rather than printing commands for the operator to run;
- prints `CB_STAGE_HINTS`, ranked remediation, in stage-specific terms;
- redacts secrets from `/etc/circuitbreaker/.env` before showing it
  (`cb_env_redacted`).

Nothing in Part I may weaken this. The quiet screen increases what the failure
path owes the operator, because the operator will have seen less on the way in.

### 1.3 The step helpers are an interface the tests already depend on

`tests/build/test_install_bundle_integrity.py`,
`test_installer_airgap_contract.py`, `test_pre_upgrade_backup.py` and
`test_install_docker_staging.py` all stub `cb_step`/`cb_ok`/`cb_section` and
assert on the stubbed output. **No test asserts on glyphs, colour or layout.**

This is the migration lever. Keeping those names as the semantic API and
replacing only their implementation leaves 269 call sites and four test suites
untouched.

### 1.4 PyInstaller `--onefile` has cost this project three separate times

1. **Silent amputation.** PyInstaller builds from a static import graph, so any
   module named only by a string is invisible and gets dropped.
   `scripts/build_native_release.py` now carries three collectors written to
   recover from this — `_collect_migration_hidden_imports`,
   `_collect_asgi_target_hidden_imports`, `_collect_dynamic_import_hidden_imports`
   — one of which parses `start.py`'s AST to read a module name back out of a
   `uvicorn.run()` string argument. Each was written after a shipped failure.
2. **Runtime extraction is a P0 containment slice.**
   `specs/1.0.0/slices/agt-3-pyinstaller-containment.md` (requirement AGT-11,
   issue #101) exists solely to bound `_MEI*` accumulation: ownership markers,
   disk budgets, symlink-attack handling, crash-loop cleanup, rollback and
   uninstall paths.
3. **The cost multiplies per process.** `circuitbreaker-backend.service` and
   every `circuitbreaker-worker@.service` instance execute the same ~98 MiB
   binary as separate processes. Each extracts its own private copy on every
   start and every restart. Both unit files already carry the mitigation
   inline: `ExecStartPre=/bin/sh -c 'mkdir -p "/var/lib/circuitbreaker/run/%N"
   && rm -rf "/var/lib/circuitbreaker/run/%N"/_MEI*'`.

Item 1 is a correctness hazard. Items 2 and 3 are an operational tax paid
forever.

### 1.5 The release pipeline proves the artifact's identity, never its function

This is the finding that explains v0.4.2.

`release.yml` gates publication behind `artifact-smoke.yml`. That workflow
installs the candidate `.deb` on a clean host and asserts, in order:

- `/usr/local/bin/circuit-breaker --version` equals the release version;
- the shipped `VERSION` file equals the release version;
- the systemd unit and `share/` tree are present;
- a message broker resolved onto `PATH`;
- uninstall removes what it installed.

Every one of those assertions passes on a binary with no application in it.

`apps/backend/src/app/start.py` resolves `--version` at line 322–323:

```python
args = build_parser().parse_args(argv)
if args.version:
    print(resolve_app_version())
```

`resolve_app_version` is imported at line 60 from `app.core.config` and reads
the `VERSION` file embedded by `--add-data`. The function returns and the
process exits **before** line 370 (`from app.startup.schema import
run_alembic_upgrade`) and line 380 (`uvicorn.run("app.main:app", ...)`) are
ever reached.

So the only execution the blocking gate performs is the one code path that
cannot observe whether the application was packaged. v0.4.2 shipped, passed,
published, and died on every native host with:

```
ERROR: Error loading ASGI app. Could not import module "app.main".
```

The gate was not weak by accident. It was measuring artifact *parity*, which is
what it was written for (GOV-09, GOV-20, ACC-17). Nothing was measuring
artifact *viability*.

### 1.6 The gate that would have caught it exists, and is not wired in

`scripts/ci/tier3-artifact.sh` is a genuinely thorough verification. It
installs the candidate, runs `systemctl start circuit-breaker`, polls `/livez`,
polls `/readyz` to HTTP 200 with a 180-second budget, asserts the readiness
check payload, probes `/health`, walks bootstrap token retrieval, creates a
monitor, reads its history, inspects worker units, exercises encrypted backup
and restore, and on upgrade rows performs the documented rollback and asserts
the pre-upgrade state returned.

It is invoked from exactly one place: `scripts/ci/fleet/dispatch.sh`.

`dispatch.sh` appears in **no GitHub workflow**. Tier 3 runs manually, by an
operator, against a personal QEMU fleet. The evidence directories under
`artifacts/diagnostics/tier3-*` are from v0.4.0.

This is the same pattern the 2026-09-16 plan identified in §1.3 for diagnosis:
*"These capabilities are spread across shell scripts, container startup,
backend endpoints, systemd probes, and CLI implementations."* Strong parts, no
chain. Releases are not going wrong because the project lacks verification
machinery. They are going wrong because the machinery is not connected to the
thing that publishes.

### 1.7 The flagship install path is verified by nothing, anywhere

`scripts/ci/fleet/matrix.yaml` declares four rows:

| id | format | arch | tier | mode |
|---|---|---|---|---|
| fedora-rpm-amd64 | rpm | amd64 | 1 | install |
| fedora-rpm-amd64-upgrade | rpm | amd64 | 1 | upgrade |
| debian-deb-amd64 | deb | amd64 | 1 | install |
| debian-deb-amd64-upgrade | deb | amd64 | 1 | upgrade |

There is no `tarball` row and no `arm64` row. `artifact-smoke.yml` tests only
the `.deb`.

The native tarball — `circuit-breaker_<version>_linux_<arch>.tar.gz`, the
artifact `install.sh` downloads, the one behind the documented
`curl -fsSL … | sudo bash` entry point and the screenshot that prompted this
work — is exercised by no automated gate at any tier.

`install.sh` itself is never executed in CI. `pages.yml` publishes it;
`release.yml` attaches it; `tests/build/*` greps its text for policy
violations. Nothing runs it.

**CLAUDE.md's "What the gates do NOT cover" table is therefore incomplete.** It
names Browser E2E and Composed Agent E2E. It must also name the installer and
the native binary's boot.

---

## 2. Goals and non-goals

### Goals

1. A successful install prints roughly seven headlines, a themed progress bar
   with a percentage, and elapsed/remaining time.
2. A failed install is *more* diagnosable than today, not less.
3. One renderer serves install, upgrade and uninstall.
4. The artifact a user receives cannot be published without something having
   executed the application inside it.
5. The native tarball path gains automated coverage at some tier.
6. The `_MEI` extraction tax is eliminated rather than further contained.

### Non-goals

- Touching the ASCII banner. `cb_logo` is unchanged, byte for byte.
- Rewriting the installer in another language.
- Changing the air-gap contract, the template renderer, or the
  `debconf`/`needrestart` suppression.
- Bringing the `--docker` compose path into the new renderer. Compose prints
  its own pull progress; contesting the screen with it is not worth it.
- Replacing PostgreSQL, Redis, NATS, nginx or systemd.
- Adding a hosted service or requiring internet access at runtime.

---

# Part I — The install experience

## 3. Phase model

The 21 sections collapse to seven phases. A phase is a unit of *elapsed time a
user can feel*, not a unit of implementation.

| # | Headline | Weight | Folds in |
|---|---|---|---|
| 1 | Pre-flight checks | 2 | `stage0_bootstrap_preflight`, `stage0_preflight` |
| 2 | Downloading bundle | 12 | release query, download, SHA256 verify, extract |
| 3 | Installing files | 6 | `stage0_install_bundle`, `stage1_bootstrap` (user, directories) |
| 4 | System dependencies | 45 | `stage2_dependencies` |
| 5 | Preparing database | 15 | `stage3_configure_postgres`, `stage3_configure_pgbouncer` |
| 6 | Services and networking | 12 | Redis, NATS, nginx, TLS, Docker proxy, `cb-helperd`, systemd units, service scripts, `stage6_apply_binary`, CLI, install identity |
| 7 | Starting Circuit Breaker | 8 | `stage8_start_services` |

**The weights above are placeholders.** They are ratios of measured medians and
must be replaced by real figures from the calibration run in §9.1 before this
ships. A test asserts they sum to 100 and that every phase key used at runtime
appears in the table.

Conditional work (TLS skipped under `--no-tls`, Docker proxy, `cb-helperd`,
air-gap dependency verification instead of installation) lives inside a phase
and redistributes that phase's weight. It never adds or removes a headline —
which is why the accumulating-headline model was chosen over a fixed checklist.

Upgrade and uninstall each get their own, shorter phase table.

## 4. Rendering architecture

### 4.1 Why bash, and why in-process

`install.sh` runs from `curl -fsSL … | sudo bash` against a host where nothing
is installed — the download phase is precisely the phase during which no helper
binary and no Python exists. The renderer must be bash, sourced, in-process.

### 4.2 Event API

A new `deploy/lib/ui.sh`, sourced by `install.sh` before anything else and
re-sourced by `deploy/setup.sh`:

```
cb_phase_begin <key> <headline>   # opens a phase; starts its clock
cb_phase_end   <key>              # closes it; prints the ✓ line with duration
cb_progress    <0..1>             # fractional progress within the open phase
cb_detail      <text>             # log always; screen only in verbose
cb_note        <text>             # log and screen in every mode
cb_fail        <msg> [remedy]     # unchanged public contract
```

`cb_step` and `cb_ok` are retained as thin aliases onto `cb_detail`, and
`cb_section` as an alias onto `cb_phase_begin`. **This is deliberate and is the
whole migration strategy:** the 269 existing call sites keep working and keep
writing to the log, the four test suites that stub them keep passing, and the
change to each stage function is limited to adding phase boundaries and
occasional `cb_progress` calls.

`cb_warn` maps to `cb_note`, because a warning the quiet mode swallowed would
be a regression.

### 4.3 Sinks

The renderer resolves its mode **once**, at startup, and dispatches every event
to two sinks: the log sink, always, at full detail; and one screen sink.

| Mode | Selected when | Screen behaviour |
|---|---|---|
| `tty` | stdout is a TTY ≥ 66 columns, `TERM` usable, not `--verbose` | Headlines accumulate; bar and timer pinned below |
| `plain` | not a TTY, or `--unattended`, or `CI=true`, or `TERM=dumb`, or `NO_COLOR` set, or width < 66 | One timestamped line per phase transition and per `cb_note`. No ANSI, no redraw |
| `verbose` | `--verbose` or `CB_VERBOSE=true` | Today's behaviour exactly: every `cb_detail` printed, no bar |

`--verbose` is a new flag. It is added to `install.sh`'s argument parser, to
`show_help`, and to `uninstall.sh`; `CB_VERBOSE=true` is the environment
equivalent, seeded the same way `CB_AIRGAP` is, so the flag and the variable
are one switch. `--unattended` implies `plain`, never `verbose`.

One switch, three modes, and the log independent of all of them. The current
design re-decides "am I a TTY / should I log this" at each call site, which is
how the modes would drift apart the first time someone adds a step.

### 4.4 Screen mechanics

- The live region is the bottom two lines: bar with percentage, then
  `Xm Ys elapsed · ~Xm Ys remaining`.
- Redraw is `\r`, `\033[K`, `\033[1A` — never `clear`, and never absolute
  cursor positioning. Throttled to 10 Hz, and skipped entirely if the rendered
  string is unchanged.
- Width is re-read on `SIGWINCH`; the bar is sized to `min(32, cols - 28)`.
- A completed phase is printed *above* the live region by tearing the region
  down, emitting the permanent line, and redrawing. Scrollback therefore
  contains the headline transcript and nothing else.
- An `EXIT` trap tears the live region down on every path, including
  interruption, so no terminal is left with a half-drawn bar or a hidden
  cursor. The cursor is hidden with `\033[?25l` only after the trap is
  installed.
- Colours reuse the banner's palette: orange `38;5;209` for the filled bar and
  the active marker, violet `38;5;99` for the track, dim for timings.

### 4.5 Progress and ETA

Overall progress is `Σ(completed weights) + (open weight × phase fraction)`,
over 100.

Phase fraction comes from three sources, in order of preference:

1. **Real measurement** where it is free. The GitHub release JSON already
   reports each asset's `size`, so phase 2 polls the partial file against that
   number. This is the most variable and most-watched phase, and it costs one
   background poll loop.
2. **Declared sub-steps.** A phase may declare `n` sub-steps; each
   `cb_phase_tick` advances the fraction by `1/n`.
3. **Nothing.** The fraction stays 0 and the phase contributes its weight only
   on completion.

ETA is `elapsed / progress − elapsed`, subject to three rules that exist so it
cannot lie:

- It is **clamped monotone non-increasing**. A displayed estimate never grows.
- It shows `estimating…` while overall progress is under 5%.
- It shows `taking longer than expected` — not a number — once the open phase
  has run past twice its weighted budget. A slow Debian mirror must degrade to
  honest silence rather than to a confident wrong number.

## 5. The failure path

`cb_fail`'s contract, its diagnostics and its hint ranking are unchanged. The
renderer adds four things around it:

1. **Tear down the live region first.** Diagnostics must never interleave with
   a redrawing bar.
2. **Print the phase ledger.** Completed phases with durations, the failed
   phase marked `✗`, remaining phases dimmed. This is the context the quiet
   screen withheld, delivered at the only moment it matters.
3. **Replay the log tail.** The last 30 lines of `$LOG_FILE` — the subprocess
   output quiet mode hid — printed before the armed diagnostics. Today an
   operator has to know to go and `tail` it.
4. **Name the log path and the verbose re-run explicitly**, as the last two
   lines on screen:

```
   Full log:  /var/lib/circuitbreaker/logs/install.log
   Re-run with full output:  bash install.sh --verbose
```

Failure output gets *longer* under this design, not shorter. That asymmetry is
the point: the screen is quiet exactly as long as nothing is wrong.

One unresolved sequencing detail, handled explicitly: before
`deploy/setup.sh` is sourced, `$LOG_FILE` is `/tmp/cb-bootstrap.log`; after
`stage0_preflight` it is `${CB_DATA_DIR}/logs/install.log` and the bootstrap
log is concatenated in. The log sink reads `$LOG_FILE` indirectly on every
write rather than caching it, so a failure on either side of the handover
replays the right file.

## 6. Upgrade and uninstall

Both source the same `ui.sh` and declare their own phase tables. `uninstall.sh`
(476 lines) gains four phases; `run_upgrade` gains five, with its pre-upgrade
backup as a phase of its own since it dominates elapsed time.

`--docker` is out of scope (§2). It keeps today's helpers, which continue to
work because the aliases in §4.2 preserve them.

---

# Part II — The packaging toolchain

## 7. Position

`--onefile` is the wrong default for a service that runs seven long-lived
processes from one binary. The extraction it performs at every process start is
what AGT-3 exists to contain, and containment is a permanent tax on a cost that
did not need to be incurred.

Two candidates, in increasing order of both benefit and effort.

### 7.1 `--onedir` — remove the extraction

PyInstaller emits a directory: the launcher plus `_internal/`. Nothing is
extracted at runtime; the tree is read at its install location.

**Removes:** all `_MEI` accumulation, the `ExecStartPre` cleanup in every unit,
the disk-budget and symlink-attack surface AGT-3 was written for, and the
per-process startup extraction cost across backend and all workers.

**Does not remove:** the hidden-import hazard of §1.4 item 1. The static import
graph is unchanged, so all three collectors stay and so does the failure class
that produced v0.4.2.

**Cost.** It is not free, and early discussion of this option understated it. The bundle
layout changes, so `nfpm.yaml`'s file lists, `install.sh`'s binary staging,
`stage6_apply_binary`, the AppImage and PKGBUILD recipes, and the `ExecStartPre`
lines in `circuitbreaker-backend.service` and `circuitbreaker-worker@.service`
all move together. It changes no application code.

### 7.2 python-build-standalone + relocatable venv — remove the failure class

Ship a standalone CPython 3.12 build and a real `site-packages` tree installed
from `apps/backend/requirements.txt`, launched by a small shim that sets
`PYTHONHOME`/`sys.path` and executes `app.start`.

**Removes:** everything in §7.1, *plus* the hidden-import hazard entirely.
There is no import graph to analyse because the packages are present as
packages. All three collectors, including the AST parser, delete. A future
rename of `main.py` cannot silently empty the artifact.

**Costs:** a new build path in `build_native_release.py`; a larger uncompressed
tree (offset by better compression and no duplicate extraction); a CPython
build to track and pin; `resolve_app_version`'s `sys._MEIPASS` branch
(`app/core/config.py:28`, `app/startup/paths.py:57`) needs a non-frozen
equivalent.

### 7.3 Rejected: Nuitka

Trades the import-graph hazard for a C toolchain in the release matrix and
substantially longer builds, on both architectures. Wrong trade for this
project's constraints.

## 8. The decision is deferred to measurement

**This spec does not commit to §7.1 or §7.2.** Build wall-clock, cold-start
latency, installed size and compressed artifact size have not been measured for
any of the three configurations, and CLAUDE.md is explicit that a gate's output
is not evidence for a thing the gate did not execute. Asserting numbers here
would be the same error in a different costume.

The implementation plan's first task is a benchmark of all three
configurations, on both architectures, reporting:

| Metric | Why |
|---|---|
| Build wall-clock | Release pipeline cost |
| Compressed artifact size | What users download |
| Installed size | Homelab disk, often a VM |
| Cold start to `/livez` | Per-process extraction cost, ×7 |
| Warm restart to `/livez` | What a crash loop actually costs |
| Collector line count deleted | Direct proxy for the §1.4.1 hazard |

Decision rule, fixed in advance so the result cannot be rationalised: **adopt
§7.2 unless it regresses compressed artifact size by more than 40% or build
wall-clock by more than 50%; otherwise adopt §7.1.** Either way, `--onefile`
does not survive.

---

# Part III — Release verification

This part is independent of Parts I and II and should ship first. It is the
smallest change with the largest effect on the problem actually being reported.

## 9. Changes

### 9.1 A self-test that resolves what the runtime resolves

Add `--selftest` to `start.py`. It:

1. resolves the ASGI target the way uvicorn does —
   `importlib.import_module("app.main")` then `getattr(module, "app")` — reading
   the target string from the same place `uvicorn.run` is given it, so the two
   cannot diverge;
2. imports every worker module in `app.workers.main._TYPE_MAP`;
3. imports the Alembic environment and enumerates revisions;
4. prints a one-line summary and exits 0, or names the first failed import and
   exits 1.

It touches no database, no Redis, no NATS, no network, and no filesystem beyond
the bundle. It runs in seconds. It is precisely the assertion that v0.4.2
needed and nobody had.

### 9.2 The build cannot emit an amputated binary

`build_native_release.py` executes the freshly built binary with `--selftest`
before it stages the bundle, and fails the build on a non-zero exit.

This is the highest-value line in the document. It moves detection from *after
publication* to *before the artifact is uploaded*, and it is roughly ten lines.

### 9.3 `artifact-smoke.yml` executes the application

Add, after the existing version-parity assertions:

```yaml
- name: Assert the installed binary can load the application it serves
  run: /usr/local/bin/circuit-breaker --selftest
```

Blocking, no services required, seconds of runtime. §9.2 and §9.3 are
deliberately redundant: one guards the build, one guards the artifact after it
has survived packaging, transport and installation.

### 9.4 The tarball gets a smoke row

`artifact-smoke.yml` gains a job that unpacks
`circuit-breaker_<version>_linux_<arch>.tar.gz`, runs the bundled binary's
`--selftest`, and asserts the bundle layout `install.sh` depends on:
`bin/circuit-breaker`, `deploy/setup.sh`, `share/VERSION`, `manifest.json`.

This is the first automated coverage the flagship install path has ever had.

### 9.5 `install.sh` is executed in CI

A workflow job that runs the real installer, end to end, in a privileged
container or VM against a locally staged bundle:

```
bash install.sh --local-bundle <candidate> --unattended --no-tls
```

then polls `/livez` and `/readyz` and asserts the phase ledger reached its
final phase. It runs on pull requests that touch `install.sh`, `deploy/`, or
`scripts/build_native_release.py`, and on the release branch.

This is the largest new piece of work in Part III and the one most likely to be
flaky, because it depends on systemd inside CI. The implementation plan must
decide between a privileged container with systemd and a nested VM, and must
make the choice on a measured flake rate rather than on preference. If neither
is acceptable, the fallback is to add a `format: tarball` row to
`matrix.yaml` and accept that this path stays Tier 3 manual — but that fallback
must be a recorded decision, not a silent omission.

### 9.6 Tier 3 is reachable from CI

`dispatch.sh` gains a `workflow_dispatch` entry point so a release candidate
can trigger the fleet run without an operator at a terminal, and the release
checklist records the tier 3 evidence commit for the candidate. Wiring tier 3
as a *blocking* release gate is out of scope — it needs a hosted fleet — but
"manual and invisible" becomes "manual and requested by the pipeline".

### 9.7 CLAUDE.md's coverage table is corrected

Two rows are added to *What the gates do NOT cover*:

| Suite | Covers | How to run it |
|---|---|---|
| Installer journey | `install.sh` end to end on a real host | `bash install.sh --local-bundle … --unattended` |
| Artifact self-test | that the packaged binary contains the application | `circuit-breaker --selftest` |

And the existing "Rules for claiming something is verified" gains a sixth rule:

> 6. **A binary that answers `--version` has not been shown to run.** Version
>    parity is an identity check. The only evidence that an artifact works is
>    something importing or starting the application inside it.

---

## 10. Testing

| Area | Test | Location |
|---|---|---|
| Phase weights sum to 100; every runtime phase key is declared | unit | `tests/build/test_installer_phase_model.py` |
| Mode selection: TTY, non-TTY, `--unattended`, `CI`, `NO_COLOR`, `TERM=dumb`, narrow terminal | table-driven | `tests/build/test_installer_render_modes.py` |
| No ANSI byte is emitted in `plain` mode | regression | same |
| Every `cb_detail` reaches the log in every mode | regression | same |
| `cb_warn`/`cb_note` reaches the screen in every mode | regression | same |
| ETA never increases across a synthetic event sequence | property | `tests/build/test_installer_eta_monotonic.py` |
| `cb_fail` tears down the live region before diagnostics | regression | `tests/build/test_installer_failure_output.py` |
| `cb_fail` replays the log tail, from either `$LOG_FILE` value | regression | same |
| `--selftest` fails when `app.main` is unimportable | unit | `apps/backend/tests/test_selftest.py` |
| `--selftest` fails when a worker in `_TYPE_MAP` is unimportable | unit | same |
| The banner is byte-identical to today | regression | `tests/build/test_installer_banner_unchanged.py` |
| Existing four suites that stub `cb_step`/`cb_ok` | unchanged, must stay green | as-is |

The banner test is not decoration. It is the mechanical guarantee of the one
constraint stated at the outset.

## 11. Risks

| Risk | Mitigation |
|---|---|
| ANSI redraw misbehaves on an untested terminal | `plain` is the default whenever anything about the terminal is uncertain; the bar is opt-out via `NO_COLOR` and `--verbose` |
| A quiet install hides a warning someone needed | `cb_warn` maps to `cb_note`, which prints in every mode |
| Weights drift as stages change | Weights live in one table with a summing test; recalibrated whenever a phase is added |
| ETA is wrong on slow mirrors | Monotone clamp plus `taking longer than expected` instead of a number |
| §9.5 is flaky in CI | Decide container-vs-VM on measured flake rate; recorded fallback in §9.5 |
| Packaging change breaks a package format not covered by CI | §9.4 covers the tarball; AppImage and PKGBUILD remain manual and are named as such |
| Part I lands without Part III | Sequencing in §12 puts Part III first |

## 12. Sequencing

Each numbered step below is a separate implementation plan. This document is
too large for one plan, and the parts have no shared state: Part III changes CI
and one entrypoint flag, Part II changes the build script and packaging
recipes, Part I changes shell rendering. They can be planned and reviewed
independently, in this order.

1. **Part III §9.1–9.3** — `--selftest`, build-time gate, smoke gate. Small,
   independent, and it closes the v0.4.2 failure class. Ship first.
2. **Part III §9.4, §9.7** — tarball smoke row, CLAUDE.md correction.
3. **Part II §8** — benchmark, then adopt §7.1 or §7.2 by the stated rule.
4. **Part I §4** — `ui.sh` and the native install path.
5. **Part I §6** — upgrade and uninstall.
6. **Part III §9.5–9.6** — installer journey in CI, tier 3 dispatch.

Steps 1 and 2 are worth doing even if nothing else in this document ships.

---

## 13. Open questions

1. §9.5: privileged container with systemd, or nested VM? Decide on measured
   flake rate.
2. ~~Should `--selftest` be reachable from `cb doctor`?~~ **Resolved: yes.**
   `cb doctor` gains a check that shells out to `circuit-breaker --selftest`, so
   an operator diagnosing a host runs the same assertion the release gate runs.
   It would have turned a v0.4.2 support thread into one command. Folded into
   §9.1.
3. Does the AppImage path need its own §9.4-style row, or does it stay
   manual-with-a-recorded-gap?
4. §3's weights are placeholders by construction. They are resolved by the
   §9-adjacent calibration run, not by judgement — the implementation plan must
   not let them ship unmeasured.
