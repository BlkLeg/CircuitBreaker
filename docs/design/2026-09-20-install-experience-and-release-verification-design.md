# Install experience and release verification

**Status:** proposed.
**Date:** 2026-09-20.
**Scope:** the native installer's presentation and diagnostics layer; the
packaging toolchain that produces what it installs; the release gates that
decide whether either is publishable.
**Relationship to prior work:** complements
`docs/design/2026-09-16-installation-diagnosis-simplification-plan.md`, which
addressed install *identity* and *diagnosis*. Extends
`docs/adr/0005-verification-tiers-and-platform-support.md` by proposing the
evidence that moves its Tier 2 row into force. Supersedes nothing.

---

## 0. Summary and verdict

The request was to make the installer concise: a themed progress bar, headlines
per step, elapsed and remaining time, diagnosability preserved. That work is
specified in full in **Part IV**.

Investigating it surfaced why the installer narrates 269 steps in the first
place, and the answer reframed the whole document. The installer is verbose in
proportion to how little the pipeline proves. Removing narration without adding
proof trades a slow, legible install for a fast, opaque one.

**The verdict, stated plainly:**

- **Supply-chain integrity and governance are already enterprise-grade.** cosign
  keyless signing, dual-format SBOMs, build provenance, vulnerability scanning
  ordered before signing, release-channel discipline, a requirement ledger with
  a blocker and exception register, and pinned distributor-published digests.
  Very little of this is typical for a self-hosted project.
- **Functional verification is not.** Every one of those controls passes on an
  artifact that does not run. v0.4.2 was signed, attested, SBOM'd, scanned,
  version-parity-checked, and empty.
- **Signal reliability is not.** Six documented incidents share one cause, and
  it is not insufficient testing.

The most uncomfortable finding is §1.7: **the project had already written this
gap down.** ADR 0005 records, in the row that governs it, that the arm64 job
"still asserts only that the binary prints a version," and that the only tier
guarantee in force today is *build only*. The map was accurate. Nothing acted
on it.

That changes what this document must be. It is not a plan to add rigour to a
project that lacks it. It is a plan to connect rigour that already exists and
is not load-bearing.

---

## 1. Findings

### 1.1 The installer's verbosity is self-inflicted, not leaked output

`install.sh` (1341 lines) bootstraps and then sources `deploy/setup.sh`
(2012 lines). Between them they make **269 calls** to `cb_step`, `cb_ok`,
`cb_warn` and `cb_info`, under **21 `cb_section` headers**.

Every subprocess is already silenced: each `apt-get`, `initdb`,
`systemctl start`, `nginx -t` and `openssl req` redirects to `$LOG_FILE`.
Nothing a package manager prints reaches the screen.

The noise is entirely our own and entirely under our control. The fix is a
rendering change, not a plumbing change.

### 1.2 The existing failure path is strong and must survive

`cb_fail` already does three things most installers do not: it runs
`CB_STAGE_DIAGS` — stage-scoped read-only diagnostics — *at failure time*
rather than printing commands for an operator to run; it prints
`CB_STAGE_HINTS`, ranked remediation in stage-specific terms; and it redacts
secrets from `/etc/circuitbreaker/.env` before display (`cb_env_redacted`).

Nothing in Part IV may weaken this. A quieter screen increases what the failure
path owes the operator, because the operator saw less on the way in.

### 1.3 The step helpers are an interface the tests already depend on

`tests/build/test_install_bundle_integrity.py`,
`test_installer_airgap_contract.py`, `test_pre_upgrade_backup.py` and
`test_install_docker_staging.py` all stub `cb_step`/`cb_ok`/`cb_section` and
assert on the stubbed output. **No test asserts on glyphs, colour or layout.**

This is the migration lever: keeping those names as the semantic API and
replacing only their implementation leaves 269 call sites and four suites
untouched.

### 1.4 PyInstaller `--onefile` has cost this project three separate times

1. **Silent amputation.** PyInstaller builds from a static import graph, so a
   module named only by a string is invisible and gets dropped.
   `scripts/build_native_release.py` carries three collectors written to recover
   from this — `_collect_migration_hidden_imports`,
   `_collect_asgi_target_hidden_imports`,
   `_collect_dynamic_import_hidden_imports` — one of which parses `start.py`'s
   AST to read a module name back out of a `uvicorn.run()` string argument.
   Each was written after a shipped failure.
2. **Runtime extraction is a P0 containment slice.**
   `specs/1.0.0/slices/agt-3-pyinstaller-containment.md` (AGT-11, issue #101)
   exists solely to bound `_MEI*` accumulation: ownership markers, disk budgets,
   symlink-attack handling, crash-loop cleanup, rollback and uninstall paths.
3. **The cost multiplies per process.** `circuitbreaker-backend.service` and
   every `circuitbreaker-worker@.service` instance execute the same ~98 MiB
   binary as separate processes, each extracting a private copy on every start
   and restart. Both units already carry the mitigation inline:
   `ExecStartPre=/bin/sh -c 'mkdir -p "/var/lib/circuitbreaker/run/%N" && rm -rf "/var/lib/circuitbreaker/run/%N"/_MEI*'`.

Item 1 is a correctness hazard. Items 2 and 3 are an operational tax paid
forever.

### 1.5 The release pipeline proves the artifact's identity, never its function

`release.yml` gates publication behind `artifact-smoke.yml`, which installs the
candidate `.deb` on a clean host and asserts: `--version` matches the release;
the shipped `VERSION` file matches; the unit and `share/` tree exist; a broker
resolved onto `PATH`; uninstall removes what it installed.

**Every one of those passes on a binary with no application in it.**

`apps/backend/src/app/start.py` resolves `--version` at lines 322–323:

```python
args = build_parser().parse_args(argv)
if args.version:
    print(resolve_app_version())
```

`resolve_app_version` is imported at line 60 from `app.core.config` and reads
the `VERSION` file embedded by `--add-data`. The process exits **before** line
370 (`from app.startup.schema import run_alembic_upgrade`) and line 380
(`uvicorn.run("app.main:app", ...)`) are reached.

The only execution the blocking gate performs is the one code path that cannot
observe whether the application was packaged. v0.4.2 shipped, passed,
published, and died on every native host with:

```
ERROR: Error loading ASGI app. Could not import module "app.main".
```

The gate was not weak by accident. It measures artifact *parity*, which is what
GOV-09, GOV-20 and ACC-17 asked it for. Nothing measured artifact *viability*.

### 1.6 The gate that would have caught it exists, and is not wired in

`scripts/ci/tier3-artifact.sh` installs the candidate, runs
`systemctl start circuit-breaker`, polls `/livez`, polls `/readyz` to HTTP 200
against a 180-second budget, asserts the readiness payload, probes `/health`,
walks bootstrap token retrieval, creates a monitor, reads its history, inspects
worker units, exercises encrypted backup and restore, and on upgrade rows
performs the documented rollback and asserts the pre-upgrade state returned.

It is invoked from exactly one place: `scripts/ci/fleet/dispatch.sh`, which
appears in **no GitHub workflow**. Tier 3 runs manually, against a personal
QEMU fleet. The evidence under `artifacts/diagnostics/tier3-*` is from v0.4.0.

### 1.7 The project had already written this gap down

This is the finding that matters most.

`docs/adr/0005-verification-tiers-and-platform-support.md` declares four tiers
and — unusually, and to its credit — a table stating which guarantees are
actually *in force*:

| Tier | Guarantee | State per ADR 0005 |
|---|---|---|
| 1 | install, boot, upgrade, roll back — deb/rpm amd64 | **Not in force**, not reachable before 0.5.0 |
| 2 | install and boot — deb/rpm arm64 | **Not in force.** "That job still asserts only that the binary prints a version." |
| 3 | build only — apk, AppImage, tarball, `pkg.tar.zst` | **In force** |

The ADR names the v0.4.2 defect precisely, in the row that governs it, before
v0.4.2 was cut. It also states three repo-wide rules, the first of which is
**"a gate may not pass by not running."**

So the position today is: **the only tier guarantee in force is that the code
compiles.** Nothing published promises that any artifact boots — and the
documentation is correct to say so.

This is not a project that lacks rigour. It is a project whose rigour produced
an accurate map of its own gaps, and then shipped through one of them. The
remedy is therefore not more discipline; it is making the map load-bearing.

### 1.8 The headline install path is served by a build-only artifact

`docs/installation/quick-install.md` leads with:

```
curl -fsSL https://raw.githubusercontent.com/BlkLeg/CircuitBreaker/main/install.sh | bash
```

That path installs the **tarball**, which ADR 0005 places at Tier 3 — *guaranteed
to build only*. `artifact-smoke.yml` tests the `.deb` alone.
`scripts/ci/fleet/matrix.yaml` declares four rows, all deb/rpm, all amd64, with
no tarball row. `install.sh` itself is never executed in CI: `pages.yml`
publishes it, `release.yml` attaches it, `tests/build/*` greps its text, and
nothing runs it.

The two statements are individually honest and jointly indefensible: the most
prominently documented way to install Circuit Breaker is the way with the
weakest guarantee attached. Either the tarball's tier rises or the
documentation stops leading with it. §17 chooses.

### 1.9 Six incidents, one cause

v0.4.2 was described as one bad release in a pattern. The pattern is real and
narrower than "not enough testing":

| # | Incident | What it actually was |
|---|---|---|
| 1 | v0.4.2 shipped a binary with no application | Gate green for the wrong reason (§1.5) |
| 2 | v0.4.0 failed `artifact-smoke` after every package and image had been built — recorded in that workflow's own comments | Cheap disproof ordered after expensive work |
| 3 | Nightly E2E characterised three-week-old `main` for nine-plus consecutive runs, because `schedule` loads workflow YAML from the default branch | The signal measured the wrong code |
| 4 | Roughly eight of ten composed-agent E2E failures traced to one harness bug — a bind-mounted Postgres that never reset — so failures read as product defects | The signal cried wolf |
| 5 | PR #141: `make verify-full` offered as evidence for a Playwright bump that gate never executes, and a genuinely red Browser E2E written off as "stale runs" | A true signal discounted |
| 6 | `security_scan.sh` truncates a fixed report path with no lock, so concurrent gate runs interleave into one garbled artifact | Evidence unreliable even when the decision was right |

Incidents 3, 4 and 6 destroy trust in signals. Incident 5 is what trained
distrust produces. Incidents 1 and 2 are gates returning green without having
asked the question.

**An untrusted signal is operationally equivalent to no signal.**

### 1.10 What is already strong

Stated for fairness and because it bounds the work:

| Practice | State |
|---|---|
| Artifact signing | cosign keyless via OIDC |
| SBOM | syft, CycloneDX **and** SPDX, backend and frontend |
| Build provenance | buildx `--provenance=true --sbom=true` |
| Vulnerability scan before signing | Trivy on the image, deliberately ordered before cosign |
| Pre-release channel discipline | `release_channel.py` — an RC can never move `latest` (GOV-20) |
| Version parity | `check_version_parity.py`, asserted end-to-end in `artifact-smoke` |
| Requirement governance | `specs/1.0.0/release-control/` — requirement ledger, blocker register, exception register, validated by `validate_v1_release_control.py` |
| Pinned inputs | `matrix.yaml` pins distributor-published digests, with a written refusal of locally computed ones |
| Honest tier accounting | ADR 0005's *in force* column |

None of it is wasted, and none of it addresses §1.5.

## 2. Diagnosis

Three defects, in dependency order:

1. **Signals are not trustworthy**, so they are discounted (§1.9).
2. **Gates verify identity, not viability**, so a green pipeline is compatible
   with a non-functional artifact (§1.5, §1.7).
3. **The installer narrates because nothing else proves anything**, so it is
   verbose where it should be quiet and quiet where it should be loud (§1.1).

Fixing 3 without 2 produces a confident, silent, unverified install. Fixing 2
without 1 adds gates to a system that already discounts them. The sequencing in
§30 follows from this and is the document's main structural claim.

## 3. Goals and non-goals

### Goals

1. A successful install prints roughly seven headlines, a themed progress bar
   with a percentage, and elapsed/remaining time.
2. A failed install is *more* diagnosable than today, not less.
3. One renderer serves install, upgrade and uninstall.
4. No artifact can be published without something having executed the
   application inside it.
5. Every signal is either trusted or explicitly quarantined — never ignored.
6. ADR 0005's Tier 2 row moves into force, and the tarball's tier and its
   documentation agree.
7. The `_MEI` extraction tax is eliminated rather than further contained.

### Non-goals

- Touching the ASCII banner. `cb_logo` is unchanged, byte for byte.
- Rewriting the installer in another language.
- Changing the air-gap contract, the template renderer, or the
  `debconf`/`needrestart` suppression.
- Bringing the `--docker` compose path into the new renderer. Compose prints its
  own pull progress; contesting the screen with it is not worth it.
- Moving ADR 0005's **Tier 1** row into force. That needs a `0.4.0 → 0.5.0`
  upgrade row and a hosted fleet; it is named here and left to 0.5.0.
- Replacing PostgreSQL, Redis, NATS, nginx or systemd.
- Adding a hosted service or requiring internet access at runtime.

---

# Part I — Signal trust

Nothing else in this document is safe to land first. Part II adds five gates;
added to a system where red is routinely discounted, gates add noise rather
than confidence.

## 4. A flake and quarantine policy

There is none today: no quarantine list, no rerun policy, no flake tracking. A
single `continue-on-error` in `baseline.yml` is the entire mechanism.

**Policy.** A red required check has exactly two permitted outcomes: it is
fixed, or it is quarantined with a named owner and an expiry date. There is no
third option, and "probably flaky" is not an outcome.

**Mechanism.** `tests/QUARANTINE.md`, a table of `suite | reason | owner |
opened | expires | issue`. Quarantine is a file in the repo, reviewed like
code — not a habit of mind. The exception register under
`specs/1.0.0/release-control/` already models this shape for requirements;
this adopts it for signals.

**Enforcement.** `tests/build/test_quarantine_register.py` asserts that no
entry is past its expiry, that every entry names an owner and an issue, and
that the register parses. An expired entry fails the build, which is the only
property that makes an expiry date mean anything.

**Doctrine.** CLAUDE.md's rule 2 — "never dismiss a red check as stale, flaky,
or pre-existing without proving it" — gains teeth: the proof, or a quarantine
entry, are the only two ways past a red check.

**Acceptance:** incidents 3, 4 and 5 of §1.9 each map to a quarantine entry or
a fix, and neither can recur silently.

## 5. A guard against the scheduled-workflow ref hazard

Incident 3 is silent, recurring, and invisible in a run log unless someone
reads the checkout line. A `schedule` event loads workflow YAML from the
**default branch**, so `e2e.yml`'s redirect to `dev` never executed for
nine-plus consecutive nightlies while `main` trailed.

CLAUDE.md rule 5 applies directly: *when a bump breaks a pairing like this, add
the guard rather than only fixing the instance.*

**Mechanism.** `tests/build/test_scheduled_workflows_pin_their_ref.py`: any
workflow carrying a `schedule:` trigger must either check out an explicit
`ref`, or carry a marker comment declaring default-branch execution
intentional. Both are legitimate; silence is not.

**Acceptance:** a workflow that would repeat incident 3 fails the build.

## 6. Cheapest disproof first

State the principle and apply it: *a gate that can disprove publishability runs
before any gate that costs more.*

Incident 2 is what its absence costs — v0.4.0 failed `artifact-smoke` after
every package and every image had already been built, on both architectures.

**Application.** §9 puts the cheapest possible disproof — does this binary
contain the application? — inside the job that produced the binary, before
staging, before packaging, before the image matrix. It runs in seconds and it
gates everything downstream.

## 7. A gate may not pass by not asking

ADR 0005 states three repo-wide rules, beginning with *"a gate may not pass by
not running."* v0.4.2 passed a gate that ran.

**Add a fourth rule to ADR 0005:** *a gate may not pass by not asking.* A gate
must execute the property it claims to verify. Version parity is an identity
check and is evidence of identity only; it is never evidence that an artifact
functions.

This is one sentence in an ADR, and it is the sentence that would have made
§1.7's honest accounting actionable rather than merely accurate.

---

# Part II — Release verification

## 8. `--selftest`: resolve what the runtime resolves

Add `--selftest` to `start.py`. It:

1. resolves the ASGI target exactly as uvicorn does —
   `importlib.import_module("app.main")`, then `getattr(module, "app")` —
   reading the target string from the same place `uvicorn.run` is given it, so
   the two cannot diverge;
2. imports every worker module in `app.workers.main._TYPE_MAP`;
3. imports the Alembic environment and enumerates revisions;
4. prints a one-line summary and exits 0, or names the first failed import and
   exits 1.

It touches no database, no Redis, no NATS, no network, and no filesystem beyond
the bundle. It runs in seconds. It is precisely the assertion v0.4.2 needed.

`cb doctor` gains a check that shells out to it, so an operator diagnosing a
host runs the same assertion the release gate runs. That turns a v0.4.2 support
thread into one command.

**Acceptance:** `--selftest` exits non-zero on a binary built with
`app.main` excluded, and exits zero on a correct one. Both directions are
tested (§28).

## 9. The build cannot emit an amputated binary

`build_native_release.py` executes the freshly built binary with `--selftest`
before staging the bundle, and fails the build on a non-zero exit.

This is the highest-value change in the document and it is roughly ten lines.
It moves detection from *after publication* to *before the artifact exists*,
and because every package format wraps this same binary, **one check covers the
tarball, deb, rpm, apk, AppImage and `pkg.tar.zst` simultaneously.**

**Acceptance:** a deliberately amputated build fails in `build.yml`, not in
`artifact-smoke`, and not in the field.

## 10. `artifact-smoke.yml` executes the application

After the existing version-parity assertions:

```yaml
- name: Assert the installed binary can load the application it serves
  run: /usr/local/bin/circuit-breaker --selftest
```

Blocking, no services required, seconds of runtime, on both `amd64` and the
existing `ubuntu-22.04-arm` runner.

§9 and §10 are deliberately redundant: one guards the build, the other guards
the artifact after it has survived packaging, transport and installation. They
fail for different reasons and both are cheap.

## 11. The tarball gets a smoke row

`artifact-smoke.yml` gains a job that unpacks
`circuit-breaker_<version>_linux_<arch>.tar.gz`, runs the bundled binary's
`--selftest`, and asserts the bundle layout `install.sh` depends on:
`bin/circuit-breaker`, `deploy/setup.sh`, `share/VERSION`, `manifest.json`.

This is the first automated coverage the flagship install path has ever had.

## 12. Post-publication verification

Nothing verifies artifacts *after* they are published, from the URLs users
actually fetch. Add a job that runs after `publish`:

- download the tarball from the GitHub Release download URL;
- verify it against the published `SHA256SUMS`;
- run `--selftest` on the binary inside it;
- run `install.sh` release discovery against the live API and confirm it
  resolves the new version.

It is the last line of defence and the only check that exercises the real
distribution path — release asset naming, checksum publication, API
propagation, and `install.sh`'s own discovery logic. Had it existed, v0.4.2
would have been caught within minutes of publication even if every other change
here were absent.

**Acceptance:** the job fails if any published artifact is missing, mismatched
against `SHA256SUMS`, or non-functional.

## 13. The installer journey in CI

A job that runs the real installer end to end, in a privileged container or VM,
against a locally staged bundle:

```
bash install.sh --local-bundle <candidate> --unattended --no-tls
```

then polls `/livez` and `/readyz` and asserts the phase ledger reached its final
phase. Triggered on pull requests touching `install.sh`, `deploy/` or
`scripts/build_native_release.py`, and on the release branch.

This is the largest new piece of work here and the most likely to be flaky,
because it needs systemd inside CI. **Recommendation:** try a privileged
`podman` container with systemd as PID 1 first and measure flake rate over
twenty consecutive runs; fall back to a nested VM only if it fails. The choice
is made on the measured rate, not on preference — and whichever is chosen, §4's
quarantine policy is already in place to keep a flaky new suite from training
everyone to ignore red.

**Recorded fallback.** If neither is acceptable, add a `format: tarball` row to
`matrix.yaml` and accept that this path stays Tier 3 manual. That fallback is a
decision to be written down, not a silent omission.

## 14. Tier 3 reachable from CI

`dispatch.sh` gains a `workflow_dispatch` entry point so a release candidate can
trigger the fleet run without an operator at a terminal, and the release
checklist (§16) records the tier 3 evidence commit for the candidate.

Making tier 3 a *blocking* gate is out of scope — it needs a hosted fleet — but
"manual and invisible" becomes "manual and requested by the pipeline."

## 15. Moving ADR 0005's Tier 2 row into force

ADR 0005 states Tier 2 enters force when "the §8.2 L2 job extends
`artifact-smoke.yml`'s `ubuntu-22.04-arm` run to the full boot-and-exercise
contract."

§10 is not that. §10 adds import-level proof to the arm64 run, which is a
genuine advance over `--version` but falls short of boot-and-exercise. Two
honest options, and this document picks the second:

1. Declare §10 sufficient for Tier 2. **Rejected** — it redefines a published
   promise downward to match what was built, which is exactly the failure mode
   ADR 0005's *in force* column exists to prevent.
2. **Build the boot-and-exercise job.** Extend `artifact-smoke.yml`'s arm64 leg
   to start the service against containerised Postgres, Redis and NATS, and
   poll `/readyz` to 200 — a subset of `tier3-artifact.sh`'s contract, running
   on a GitHub-hosted runner. When it passes against a candidate, update ADR
   0005's last column in the same commit, as that ADR requires.

**Acceptance:** ADR 0005's Tier 2 row reads *in force*, changed by the commit
that adds the evidence.

## 16. Per-release control

`specs/1.0.0/release-control/` is strong governance scoped to one future
milestone. v0.4.2 shipped with no equivalent. The gap between the rigour of
`specs/1.0.0/` and how 0.4.2 actually shipped **is** the disjointedness being
reported.

Add a generated per-release checklist — generated, not hand-written, because a
hand-written one is a signal that can be discounted. For the candidate it
asserts:

- every required check green, or quarantined with an unexpired entry (§4);
- `--selftest` passed on every published artifact (§9, §10, §11, §12);
- tier 3 evidence commit recorded, or explicitly waived with a reason (§14);
- ADR 0005's tier table matches the evidence that exists (§15);
- CHANGELOG entry present;
- version parity green across every artifact format.

`scripts/release_checklist.py` emits it and exits non-zero if any row is
unsatisfied. `release.yml` runs it before `publish`.

## 17. Documentation alignment

§1.8 found the headline install path served by a build-only artifact. Once §11,
§12 and §13 land, the tarball is verified at install-and-boot level and the
contradiction resolves upward rather than by weakening the documentation.

Until then — and this is the interim state that must not be skipped —
`docs/installation/quick-install.md` carries an accurate line about what is
guaranteed, and `docs/release/1.0.0-support-contract.md` continues to publish
no tier language, as ADR 0005 already requires.

**Acceptance:** no documentation page promises more than ADR 0005's *in force*
column supports, checked by `tests/build/test_docs_match_tier_table.py`.

## 18. CLAUDE.md corrections

Two rows added to *What the gates do NOT cover*:

| Suite | Covers | How to run it |
|---|---|---|
| Installer journey | `install.sh` end to end on a real host | `bash install.sh --local-bundle … --unattended` |
| Artifact self-test | that the packaged binary contains the application | `circuit-breaker --selftest` |

And a sixth rule under *Rules for claiming something is verified*:

> 6. **A binary that answers `--version` has not been shown to run.** Version
>    parity is an identity check. The only evidence that an artifact works is
>    something importing or starting the application inside it.

---

# Part III — The packaging toolchain

## 19. Position

`--onefile` is the wrong default for a service that runs seven long-lived
processes from one binary. The extraction it performs at every process start is
what AGT-3 exists to contain, and containment is a permanent tax on a cost that
need not have been incurred.

## 20. Candidates

### 20.1 `--onedir` — remove the extraction

PyInstaller emits a directory: launcher plus `_internal/`. Nothing is extracted
at runtime.

**Removes:** all `_MEI` accumulation, the `ExecStartPre` cleanup in every unit,
the disk-budget and symlink-attack surface AGT-3 was written for, and the
per-process extraction cost across backend and all workers.

**Does not remove:** the hidden-import hazard (§1.4 item 1). The static import
graph is unchanged, so all three collectors stay and so does the failure class
that produced v0.4.2.

**Cost.** Not free, and early discussion understated it. The bundle layout
changes, so `nfpm.yaml`'s file lists, `install.sh`'s binary staging,
`stage6_apply_binary`, the AppImage and PKGBUILD recipes, and the
`ExecStartPre` lines in `circuitbreaker-backend.service` and
`circuitbreaker-worker@.service` all move together. No application code
changes.

### 20.2 python-build-standalone + relocatable venv — remove the failure class

Ship a standalone CPython 3.12 build and a real `site-packages` installed from
`apps/backend/requirements.txt`, launched by a shim that sets
`PYTHONHOME`/`sys.path` and executes `app.start`.

**Removes:** everything in §20.1, *plus* the hidden-import hazard entirely.
There is no import graph to analyse because the packages are present as
packages. All three collectors, including the AST parser, delete. A future
rename of `main.py` cannot silently empty the artifact.

**Costs:** a new build path in `build_native_release.py`; a larger uncompressed
tree; a CPython build to track and pin; and `resolve_app_version`'s
`sys._MEIPASS` branch (`app/core/config.py:28`, `app/startup/paths.py:57`)
needs a non-frozen equivalent.

### 20.3 Rejected: Nuitka

Trades the import-graph hazard for a C toolchain in the release matrix and
substantially longer builds on both architectures. Wrong trade here.

## 21. The decision is deferred to measurement

**This spec does not commit to §20.1 or §20.2.** Build wall-clock, cold-start
latency, installed size and compressed artifact size have not been measured for
any of the three configurations, and CLAUDE.md is explicit that a gate's output
is not evidence for a thing the gate did not execute. Asserting numbers here
would be the same error in a different costume.

The implementation plan's first task is a benchmark of all three, on both
architectures:

| Metric | Why |
|---|---|
| Build wall-clock | Release pipeline cost |
| Compressed artifact size | What users download |
| Installed size | Homelab disk, often a VM |
| Cold start to `/livez` | Per-process extraction cost, ×7 |
| Warm restart to `/livez` | What a crash loop actually costs |
| Collector line count deleted | Direct proxy for the §1.4.1 hazard |

**Decision rule, fixed in advance so the result cannot be rationalised:** adopt
§20.2 unless it regresses compressed artifact size by more than 40% or build
wall-clock by more than 50%; otherwise adopt §20.1. Either way, `--onefile`
does not survive.

Note that §9 is independent of this decision and protects whichever is chosen.

---

# Part IV — The install experience

This is the originally requested work, specified in full. §30 sequences it
after Parts I–III, for the reason given in §2.

## 22. Phase model

The 21 sections collapse to seven phases. A phase is a unit of *elapsed time a
user can feel*, not a unit of implementation.

| # | Headline | Weight | Folds in |
|---|---|---|---|
| 1 | Pre-flight checks | 2 | `stage0_bootstrap_preflight`, `stage0_preflight` |
| 2 | Downloading bundle | 12 | release query, download, SHA256 verify, extract |
| 3 | Installing files | 6 | `stage0_install_bundle`, `stage1_bootstrap` |
| 4 | System dependencies | 45 | `stage2_dependencies` |
| 5 | Preparing database | 15 | `stage3_configure_postgres`, `stage3_configure_pgbouncer` |
| 6 | Services and networking | 12 | Redis, NATS, nginx, TLS, Docker proxy, `cb-helperd`, systemd units, service scripts, `stage6_apply_binary`, CLI, install identity |
| 7 | Starting Circuit Breaker | 8 | `stage8_start_services` |

**The weights are placeholders** — ratios of estimated medians. They are
replaced by measured figures from a calibration run before this ships, and
`tests/build/test_installer_phase_model.py` asserts they sum to 100 and that
every phase key used at runtime appears in the table.

Conditional work (TLS skipped under `--no-tls`, Docker proxy, `cb-helperd`,
air-gap verification instead of installation) lives inside a phase and
redistributes that phase's weight. It never adds or removes a headline — which
is why the accumulating-headline model was chosen over a fixed checklist.

Upgrade and uninstall each get their own, shorter phase table.

## 23. Rendering architecture

### 23.1 Why bash, and why in-process

`install.sh` runs from `curl -fsSL … | sudo bash` against a host where nothing
is installed — the download phase is precisely the phase during which no helper
binary and no Python exists. The renderer must be bash, sourced, in-process.

### 23.2 Event API

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
`cb_section` onto `cb_phase_begin`. **This is the migration strategy:** 269
existing call sites keep working and keep writing to the log, the four suites
that stub them keep passing, and each stage function changes only by gaining
phase boundaries and occasional `cb_progress` calls.

`cb_warn` maps to `cb_note` — a warning the quiet mode swallowed would be a
regression.

### 23.3 Sinks

The renderer resolves its mode **once**, at startup, and dispatches every event
to two sinks: the log, always, at full detail; and one screen sink.

| Mode | Selected when | Screen behaviour |
|---|---|---|
| `tty` | stdout is a TTY ≥ 66 columns, `TERM` usable, not `--verbose` | Headlines accumulate; bar and timer pinned below |
| `plain` | not a TTY, or `--unattended`, or `CI=true`, or `TERM=dumb`, or `NO_COLOR`, or width < 66 | One timestamped line per phase transition and per `cb_note`. No ANSI, no redraw |
| `verbose` | `--verbose` or `CB_VERBOSE=true` | Today's behaviour exactly: every `cb_detail` printed, no bar |

`--verbose` is a new flag, added to `install.sh`'s argument parser, to
`show_help`, and to `uninstall.sh`; `CB_VERBOSE=true` is the environment
equivalent, seeded the way `CB_AIRGAP` is, so the flag and the variable are one
switch. `--unattended` implies `plain`, never `verbose`.

One switch, three modes, and the log independent of all of them. The current
design re-decides "am I a TTY / should I log this" at each call site, which is
how modes drift apart the first time someone adds a step.

### 23.4 Screen mechanics

- The live region is the bottom two lines: bar with percentage, then
  `Xm Ys elapsed · ~Xm Ys remaining`.
- Redraw is `\r`, `\033[K`, `\033[1A` — never `clear`, never absolute cursor
  positioning. Throttled to 10 Hz and skipped when the rendered string is
  unchanged.
- Width is re-read on `SIGWINCH`; the bar is sized to `min(32, cols - 28)`.
- A completed phase is printed *above* the live region by tearing the region
  down, emitting the permanent line, and redrawing. Scrollback therefore
  contains the headline transcript and nothing else.
- An `EXIT` trap tears the live region down on every path, including
  interruption, so no terminal is left with a half-drawn bar or hidden cursor.
  The cursor is hidden with `\033[?25l` only after the trap is installed.
- Colours reuse the banner palette: orange `38;5;209` for the filled bar and
  active marker, violet `38;5;99` for the track, dim for timings.

### 23.5 Progress and ETA

Overall progress is `Σ(completed weights) + (open weight × phase fraction)`,
over 100.

Phase fraction comes from three sources, in order of preference:

1. **Real measurement where it is free.** The GitHub release JSON already
   reports each asset's `size`, so phase 2 polls the partial file against that
   number — the most variable and most-watched phase, for one background poll
   loop.
2. **Declared sub-steps.** A phase may declare `n` sub-steps; each
   `cb_phase_tick` advances the fraction by `1/n`.
3. **Nothing.** The fraction stays 0 and the phase contributes its weight only
   on completion.

ETA is `elapsed / progress − elapsed`, subject to three rules that exist so it
cannot lie:

- **Clamped monotone non-increasing.** A displayed estimate never grows.
- Shows `estimating…` while overall progress is under 5%.
- Shows `taking longer than expected` — not a number — once the open phase has
  run past twice its weighted budget. A slow Debian mirror degrades to honest
  silence rather than a confident wrong number.

## 24. The failure path

`cb_fail`'s contract, diagnostics and hint ranking are unchanged. The renderer
adds four things around it:

1. **Tear down the live region first**, so diagnostics never interleave with a
   redrawing bar.
2. **Print the phase ledger** — completed phases with durations, the failed
   phase marked `✗`, remaining phases dimmed. This is the context the quiet
   screen withheld, delivered at the only moment it matters.
3. **Replay the log tail** — the last 30 lines of `$LOG_FILE`, the subprocess
   output quiet mode hid, before the armed diagnostics. Today an operator has to
   know to go and `tail` it.
4. **Name the log path and the verbose re-run**, as the last two lines:

```
   Full log:  /var/lib/circuitbreaker/logs/install.log
   Re-run with full output:  bash install.sh --verbose
```

Failure output gets *longer* under this design. That asymmetry is the point:
the screen is quiet exactly as long as nothing is wrong.

One sequencing detail, handled explicitly: before `deploy/setup.sh` is sourced,
`$LOG_FILE` is `/tmp/cb-bootstrap.log`; after `stage0_preflight` it is
`${CB_DATA_DIR}/logs/install.log` with the bootstrap log concatenated in. The
log sink reads `$LOG_FILE` indirectly on every write rather than caching it, so
a failure on either side of the handover replays the right file.

## 25. Upgrade and uninstall

Both source the same `ui.sh` and declare their own phase tables. `uninstall.sh`
(476 lines) gains four phases; `run_upgrade` gains five, with its pre-upgrade
backup as a phase of its own since it dominates elapsed time.

`--docker` is out of scope (§3). It keeps today's helpers, which continue to
work because the §23.2 aliases preserve them.

**Rollback coverage.** `tier3-artifact.sh` exercises upgrade *and documented
rollback* for deb and rpm. The tarball path has `run_upgrade` with a
pre-upgrade backup and no test that restoring it works. A tarball
upgrade-and-rollback row is added wherever §13 lands.

## 26. `cb diag bundle`

§24 improves what a failed install prints. The enterprise norm is that an
operator can hand over one redacted file.

Add `cb diag bundle`: install log, `cb doctor --json`, `--selftest` output, unit
states, recent journal for `circuitbreaker-*`, the install identity record, and
`cb_env_redacted` output, as a single tarball with secrets stripped by the
existing redaction helpers. `cb_fail` names it as the last suggestion on the
failure path.

**Acceptance:** `tests/build/test_diag_bundle_redaction.py` asserts no secret
pattern survives into the bundle.

---

# Part V — Delivery

## 27. Coverage matrix

What verifies each artifact, today and after this work. "Boot" means the
service started and `/readyz` returned 200.

| Artifact | Today | After | ADR 0005 tier |
|---|---|---|---|
| tarball (amd64) | build only | build + self-test + bundle layout + installer journey + post-publish | 3 → install-and-boot |
| tarball (arm64) | build only | build + self-test | 3 |
| deb amd64 | build + `--version` + install/uninstall; boot only via manual tier 3 | + self-test; + boot in `artifact-smoke` | 1 (not in force) |
| deb arm64 | build + `--version` | + self-test + boot (§15) | 2 → in force |
| rpm amd64 | build; boot only via manual tier 3 | + self-test | 1 (not in force) |
| rpm arm64 | build | + self-test | 2 |
| apk | build only | + self-test (via §9) | 3 |
| AppImage | build only | + self-test (via §9) | 3 |
| `pkg.tar.zst` | build only | + self-test (via §9) | 3 |
| mono image | built, started via compose in `dev-ci`, composed agent E2E, Trivy | unchanged | n/a |

Every "+ self-test (via §9)" row is free: those formats wrap the same binary,
so one build-time check covers them all. That is the argument for §9 in one
line.

**Remaining declared gaps after this work**, recorded rather than hidden: apk,
AppImage and `pkg.tar.zst` are never installed or booted anywhere; rpm arm64 is
never booted; Tier 1's upgrade-and-rollback row still needs `0.4.0 → 0.5.0`.

## 28. Testing

| Area | Test | Location |
|---|---|---|
| Quarantine register parses; no expired entry; every entry has owner + issue | unit | `tests/build/test_quarantine_register.py` |
| Scheduled workflows pin a ref or declare intent | policy | `tests/build/test_scheduled_workflows_pin_their_ref.py` |
| `--selftest` fails when `app.main` is unimportable | unit | `apps/backend/tests/test_selftest.py` |
| `--selftest` fails when a worker in `_TYPE_MAP` is unimportable | unit | same |
| `--selftest` passes on a correct build | unit | same |
| Docs promise no more than ADR 0005's in-force column | policy | `tests/build/test_docs_match_tier_table.py` |
| Release checklist fails on an unsatisfied row | unit | `tests/build/test_release_checklist.py` |
| Phase weights sum to 100; every runtime phase key is declared | unit | `tests/build/test_installer_phase_model.py` |
| Mode selection: TTY, non-TTY, `--unattended`, `CI`, `NO_COLOR`, `TERM=dumb`, narrow | table-driven | `tests/build/test_installer_render_modes.py` |
| No ANSI byte emitted in `plain` mode | regression | same |
| Every `cb_detail` reaches the log in every mode | regression | same |
| `cb_warn`/`cb_note` reaches the screen in every mode | regression | same |
| ETA never increases across a synthetic event sequence | property | `tests/build/test_installer_eta_monotonic.py` |
| `cb_fail` tears down the live region before diagnostics | regression | `tests/build/test_installer_failure_output.py` |
| `cb_fail` replays the log tail, from either `$LOG_FILE` value | regression | same |
| No secret pattern survives into `cb diag bundle` | security | `tests/build/test_diag_bundle_redaction.py` |
| The banner is byte-identical to today | regression | `tests/build/test_installer_banner_unchanged.py` |
| Existing four suites that stub `cb_step`/`cb_ok` | unchanged, must stay green | as-is |

The banner test is not decoration. It is the mechanical guarantee of the one
constraint stated at the outset.

## 29. Risks

| Risk | Mitigation |
|---|---|
| Quarantine becomes a dumping ground | Expiry dates are enforced by a failing test; an entry cannot be renewed silently |
| §13 is flaky in CI | Decide container-vs-VM on measured flake rate over 20 runs; §4 is already in place so a flaky suite cannot train people to ignore red; recorded fallback in §13 |
| ANSI redraw misbehaves on an untested terminal | `plain` is the default whenever anything about the terminal is uncertain; opt-out via `NO_COLOR` and `--verbose` |
| A quiet install hides a warning someone needed | `cb_warn` maps to `cb_note`, which prints in every mode |
| Weights drift as stages change | One table, a summing test, recalibrated whenever a phase is added |
| ETA is wrong on slow mirrors | Monotone clamp plus `taking longer than expected` instead of a number |
| Packaging change breaks a format CI does not install | §27 records exactly which formats those are; §9 covers all of them at import level |
| Part IV lands without Parts I–II | §30 sequences it last, and the reason is recorded in §2 |

## 30. Sequencing

Each step is a separate implementation plan. This document is too large for one
plan, and the parts share no state: Part I changes CI policy and adds two policy
tests; Part II changes CI and one entrypoint flag; Part III changes the build
script and packaging recipes; Part IV changes shell rendering.

| Step | Work | Rationale |
|---|---|---|
| 0 | §4 quarantine policy, §5 scheduled-ref guard, §7 the fourth ADR rule | Without these, added gates add noise. Non-negotiable prerequisite |
| 1 | §8 `--selftest` + `cb doctor`, §9 build-time gate, §10 smoke gate | Closes the v0.4.2 class at three points. Small, independent, covers every format |
| 2 | §11 tarball smoke row, §12 post-publication verification, §18 CLAUDE.md | First real coverage of the flagship path |
| 3 | §15 Tier 2 into force, §16 per-release control, §17 docs alignment | Makes release readiness assertable rather than felt |
| 4 | §21 benchmark, then §20.1 or §20.2 by the stated rule | Removes the hazard class at source |
| 5 | §22–§24 `ui.sh` and the native install path | **The originally requested change** |
| 6 | §25 upgrade and uninstall, §26 `cb diag bundle` | |
| 7 | §13 installer journey in CI, §14 tier 3 dispatch, §25 tarball rollback row | Largest and most flake-prone; lands on a foundation that can tell flake from failure |

Steps 0 and 1 are worth doing even if nothing else here ships. Step 5 is the
requested work; it is last among the substantive changes because a quiet
installer is only trustworthy on a pipeline whose signals mean something, and
because steps 0–2 are small, cheap and independently valuable.

## 31. Open questions

1. **§13: privileged `podman` container with systemd, or nested VM?** Decide on
   measured flake rate over twenty consecutive runs. Recommendation is to try
   the container first.
2. **Do apk, AppImage and `pkg.tar.zst` ever need install-and-boot coverage?**
   §27 records them as permanently Tier 3 under this plan. If any of them is
   actually used by a meaningful number of people, that is a support decision
   and belongs in ADR 0005, not here.
3. **Should §12's post-publication job be able to yank a release?** It detects a
   bad publication minutes after the fact. Automatically marking the GitHub
   Release as a draft is possible and is a blast-radius decision, not a
   technical one.
