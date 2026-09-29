# Tier 2 Slice A2 — `tier2.yml`, `make verify-composed`, the Drift Guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Tier 2 one thing that can be run, named and required: a `tier2.yml` that runs the browser
and composed suites, a `make verify-composed` that runs the same commands on a laptop, and a guard that
fails when the two drift apart. The release and the release dry run call it in place of `browser-e2e.yml`,
**with the browser suite only**, because the release is not gated on the composed journey. The composed
journey also gets a rerun guard: it never runs again on the same inputs until the previous run's failures are
fixed or quarantined.

**Architecture:** Each suite's command moves into one script under `scripts/ci/` (`tier2-browser.sh`,
`tier2-agent-journey.sh`). The reusable workflows and the `make` targets both call that script, so P1
("one definition per gate") holds by construction and not only by a comparison test. `tier2.yml` is a
reusable, scheduled and dispatchable aggregator: a `plan` job validates the `suites` and `ref` inputs,
one call job per suite runs only when selected, and a `result` job gives a single verdict that treats a
selected-but-skipped suite as a failure. The plan and result logic live in a typed, tested
`scripts/ci/tier2_gate.py`, not inline YAML. The 03:00 nightly moves from `e2e.yml` to `tier2.yml`.
Every real composed run records a verdict artifact keyed by a fingerprint of the suite's inputs. The next run
looks up the verdict for its own fingerprint and refuses to start if that verdict failed and the failures were
neither fixed (fixing them would change the fingerprint) nor quarantined (register rows, which the journey then
deselects). That logic lives in `scripts/ci/composed_rerun_guard.py`.

**Tech Stack:** GitHub Actions reusable workflows, bash (`scripts/ci/lib/common.sh`), Python stdlib
(3.10 floor for `scripts/ci/`), pytest, GNU make.

**Spec:** [`docs/design/2026-09-27-tier2-composed-and-triage-design.md`](./2026-09-27-tier2-composed-and-triage-design.md)
— slice A2 of §9. Read D1, D2, §3.1, §3.3's paragraph on the `github` context in called workflows, §7.2 and
§7.4 before starting. Slice A1's plan ([`2026-09-27-tier2-slice-a1-plan.md`](./2026-09-27-tier2-slice-a1-plan.md))
shows the conventions this one follows.

**State at writing:** A1 merged as #184 and #185, and was proven on a real runner: `e2e.yml` dispatched on
`dev` at `f71d3fcc` (run 36348587627) ended `success`. `Composed agent journey — quarantined` printed
`SKIPPED (QUAR-001, expires 2026-12-21, 85 days left)`, and `Composed agent journey` was reported skipped.

## Maintainer decisions, 2026-09-27 (these supersede design §3.1 and §10.2)

1. **The release is not gated on the composed journey.** Getting that suite reliably green is a steep hill,
   and the release should not have to climb it. `release.yml` and `release-dry-run.yml` call `tier2.yml`
   with `suites: '["browser"]'`, and `test_the_release_does_not_gate_on_the_composed_journey` pins it. This
   *reaffirms* AGT-01's "deliberately NOT a release gate". The composed journey still runs nightly (through
   `tier2.yml`, whose default is the whole tier), on tag pushes and on agent PRs (through `e2e.yml`).
2. **The composed journey never runs twice without the previous failures being addressed.** "Addressed"
   means **fixed or quarantined**, the two outcomes CLAUDE.md rule 2 allows:
   - **Fixed:** something the suite exercises changed since the failed run, so the inputs fingerprint is
     different.
   - **Quarantined:** every failed test has a live row in `quarantine-register.csv` for
     `Composed Agent E2E / composed-journey`. The journey then deselects those tests, so the rerun doesn't
     simply fail on them again.

   Anything else stops the run in about a minute with a red `Composed agent journey — rerun guard` check.
   That check names the earlier run and its failed tests. There is no force switch. Task 6 implements this.

   **Loudly flagged, since it goes beyond the design:** individual tests in the composed suite become
   quarantinable. Until now a register row could only quarantine the whole suite, via `quarantined: true`.
   With the rerun guard, a row whose `scope` lists test names deselects exactly those tests whenever the
   suite actually runs. QUAR-001 is unaffected today, because the whole suite is still quarantined. To
   reverse: delete the `deselect` call in `tier2-agent-journey.sh`. The guard then treats a quarantined
   failure as addressed but still re-runs it, so every nightly reproduces it.

## Where this plan departs from the spec, and why

Each change below is small, and each one is recorded in the design doc as part of Task 7.

1. **The suite commands move into per-suite scripts.** D1 rejects one `tier2-composed.sh` that holds all
   three privileges. Per-suite scripts don't do that: each still runs in its own workflow and job. What the
   scripts replace is §7.3's "guard asserting `make verify-composed` and the workflow step invoke the same
   command". Comparing argv across YAML and a Makefile is brittle, because the two forms legitimately
   differ (`--shard`, `-p no:cacheprovider`, `$(E2E_ARGS)`). Calling one file is what `verify-fleet` →
   `fleet/dispatch.sh` already does, and `test_fleet_make_target.py` is the precedent for guarding it.
2. **`CI=1` is exported by `tier2-browser.sh`, not by the Makefile.** §3.1 puts it in the Makefile, but the
   script is the one place both paths share.
3. **`tier2.yml` pins its ref and does not carry `# scheduled-ref: default-branch-intentional`.** §7.2 says
   it carries the marker. The marker would exempt the file from `test_scheduled_workflows_pin_their_ref.py`,
   and that guard is exactly what proves a scheduled run tests `dev` (D2). `browser-e2e.yml` therefore gains
   the `ref` input that `composed-e2e.yml` already has, so both called workflows pin a ref and the guard
   passes on its merits.
4. **`tier2.yml` does not join `test_ci_evidence_retention.py`'s maps.** §7.4 says it does. Those maps list
   workflows that *execute a suite*, and `tier2.yml` executes none: its own jobs are `plan` and `result`.
   Its suites run in `browser-e2e.yml` and `composed-e2e.yml`, which are both registered already. B1 adds
   triage artifacts to `tier2.yml`, and the entry becomes owed then.
5. **`Tier 2 (composed)` joins `notify.yml`'s watched list here, not in Phase B.** This slice moves the
   nightly out of `e2e.yml`, which is already watched. Without this line a red nightly after A2 would post
   nothing to Discord.

## Global Constraints

- **Python** in `scripts/ci/`: stdlib only, snake_case, full type annotations (`disallow_untyped_defs`),
  docstrings on every public function. **Must run on Python 3.10**, which is the `ubuntu-22.04` runner's
  `python3` when no `setup-python` step is present (`test_ci_scripts_match_runner_python.py` and the vermin
  gate in Tier 0 enforce this). No `datetime.UTC`, no `tomllib`.
- New `scripts/ci/*.py` files are linted automatically: `CB_SCRIPTS := $(wildcard scripts/*.py scripts/ci/*.py)`
  (`Makefile:19`). No lint line to edit.
- **Bash** tier scripts: start with `#!/usr/bin/env bash\n`, contain `set -euo pipefail`, source
  `scripts/ci/lib/common.sh`, never use `|| true`, are executable (`git update-index --chmod=+x`), and join
  `TIER_SCRIPTS` in `tests/build/test_ci_script_contract.py`.
- **Workflows**: top-level `permissions: {}` in new files, with grants per job; every `${{ }}` that
  reaches a `run:` goes through `env:` and is quoted; actions pinned by tag (`actions/checkout@v5`);
  `persist-credentials: false` on every checkout; `# checkov:skip=CKV_GHA_7: <reason>` on every
  `workflow_dispatch` input, verified with `checkov -f <file> --framework github_actions`.
- **No `|| true` on a gate.** "Did not run" and "found nothing" must never be spelled the same way.
- **T2 is not a required check** (D2). `tests/build/required_checks.py` is not touched.
- **The composed suite stays quarantined** (`quarantined` default `true` in `composed-e2e.yml`). Fixing #162
  is out of scope (§8).
- **Commits**: `feat:` / `fix:` / `chore:` / `docs:`. End every message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and **no session link**.
- **Branch**: `feat/tier2-slice-a2` off `origin/dev`. Never push to `dev` or `main` directly.

## Review Focus

These seven inputs or conditions are implied by the spec and the maintainer decisions, but no task would
otherwise exercise them. Each line names the test that now pins it.

1. **A dispatch with a mistyped or malformed `suites`** (`["brwoser"]`, `browser`, `[]`) must fail red and
   name the value, not run zero suites and report green. → Task 3, `test_plan_rejects_*`.
2. **A selected suite that ends `skipped`** (a broken `needs` edge, or an `if:` typo) must make Tier 2 red,
   because a skipped job reads as satisfied to every consumer. → Task 3, `test_result_fails_when_a_selected_suite_was_skipped`.
3. **A `ref` input carrying a newline or shell metacharacters** must be rejected before it reaches
   `$GITHUB_OUTPUT`, where a newline would forge a second output. → Task 3, `test_plan_rejects_a_ref_that_could_forge_an_output`.
4. **A scheduled run tests `dev`, not `main`,** for both suites. → Task 3, `test_scheduled_run_tests_dev`,
   and Task 4, `test_tier2_passes_the_planned_ref_to_every_suite`.
5. **`make verify-composed` on a laptop while QUAR-001 is live** must print the register's SKIPPED line, not
   start a 75-minute suite that is known red. Its local default must not drift from the workflow's. → Task 2,
   `test_local_quarantine_default_matches_the_workflow`.
6. **A fork PR uploading a fake verdict artifact** could unblock a known failure, or block a clean tree.
   Only artifacts from runs of this repository are trusted. → Task 6,
   `test_pick_prefers_the_newest_trusted_unexpired_artifact`.
7. **A `--deselect` whose node-id prefix is wrong deselects nothing and says nothing,** so the quarantine
   would silently not apply and the rerun would fail again. → Task 6,
   `test_deselect_args_actually_deselect_a_real_test`, which asks pytest against the real suite file.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ci/tier2-browser.sh` | **Create.** The one definition of the Playwright invocation. Optional shard argument. |
| `scripts/ci/tier2-agent-journey.sh` | **Create.** The one definition of the composed pytest invocation. Extra arguments pass through to pytest. |
| `scripts/ci/tier2_gate.py` | **Create.** `plan` (inputs → suites and ref) and `result` (`toJSON(needs)` → verdict). Pure. |
| `tests/build/test_tier2_gate.py` | **Create.** Unit tests for `tier2_gate.py`. |
| `scripts/ci/composed_rerun_guard.py` | **Create.** Fingerprints the suite's inputs, records a verdict per real run, refuses to repeat an unaddressed failure, and lists quarantined tests to deselect. |
| `tests/build/test_composed_rerun_guard.py` | **Create.** Every row of the "addressed" table, fork-artifact rejection, and a real pytest check that deselection deselects. |
| `tests/build/test_tier2_wiring.py` | **Create.** Tests that the workflows, the Makefile and the scripts agree (P1, suites, schedule, AGT-01). |
| `.github/workflows/tier2.yml` | **Create.** `name: Tier 2 (composed)`. Schedule, dispatch, call. `plan` → `browser`/`composed` → `result`. |
| `.github/workflows/browser-e2e.yml` | **Modify.** Adds a `ref` input and pins the checkout to it. Its run step calls `tier2-browser.sh`. |
| `.github/workflows/composed-e2e.yml` | **Modify.** Its run step calls `tier2-agent-journey.sh` (Task 1). A `rerun-guard` job gates the journey, and the journey records its verdict (Task 6). |
| `.github/workflows/e2e.yml` | **Modify.** Drops `schedule` and the `ref` redirect that only existed for it. Header updated. |
| `.github/workflows/release.yml`, `release-dry-run.yml` | **Modify.** The `browser-e2e` job becomes `tier2`, with `suites: '["browser"]'` and narrowed permissions. |
| `.github/workflows/notify.yml` | **Modify.** Adds `Tier 2 (composed)` to the watched list. |
| `Makefile` | **Modify.** Adds `verify-composed`, `-browser` and `-agent` targets, plus `CB_COMPOSED_QUARANTINED`; `e2e-local` calls the script. |
| `tests/build/test_ci_script_contract.py` | **Modify.** Two names join `TIER_SCRIPTS`. |
| `docs/design/2026-09-27-tier2-composed-and-triage-design.md`, `CLAUDE.md`, `.claude/skills/cb-build-test/SKILL.md` | **Modify.** Status line, deviations, and the new target. |

---

## Task 1: One script per suite, and both callers use it

**Files:**
- Create: `scripts/ci/tier2-browser.sh`, `scripts/ci/tier2-agent-journey.sh`
- Create: `tests/build/test_tier2_wiring.py`
- Modify: `.github/workflows/browser-e2e.yml` (the `Run Playwright suite` step, ~line 105)
- Modify: `.github/workflows/composed-e2e.yml` (the `Run the composed journey` step, ~line 104)
- Modify: `Makefile` (`e2e-local`, ~lines 515-545)
- Modify: `tests/build/test_ci_script_contract.py:80`

**Interfaces:**
- Produces: `scripts/ci/tier2-browser.sh [SHARD]`, where SHARD matches `^[0-9]+/[0-9]+$`, and any other
  argument count or shape exits 2. `scripts/ci/tier2-agent-journey.sh [PYTEST_ARGS...]`.
- Produces: `tests/build/test_tier2_wiring.py` with helpers `_load(name) -> dict`,
  `_run_blocks(workflow: dict) -> list[str]` and `_recipe(target) -> str`. Tasks 2, 4 and 5 add tests to
  this file.

- [ ] **Step 1: Write the failing tests**

`tests/build/test_tier2_wiring.py`:

```python
"""Tier 2's suites have exactly one definition each, and every caller uses it.

Design D1 keeps the three suites in separate reusable workflows, and in exchange
P1 is enforced here: the workflow step and the `make` target both call the same
scripts/ci script, and neither may re-inline the command. The failure this
prevents is a laptop run and a CI run that differ in the flags they pass. Nobody
sees that until one of them goes red and the other does not.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAKEFILE = REPO_ROOT / "Makefile"
BROWSER_SCRIPT = "scripts/ci/tier2-browser.sh"
AGENT_SCRIPT = "scripts/ci/tier2-agent-journey.sh"


def _load(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _run_blocks(workflow: dict) -> list[str]:
    blocks: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and "run" in step:
                blocks.append(str(step["run"]))
    return blocks


def _recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n|#[^\n]*\n|\n)*)", text, re.M)
    assert match, f"no {target} target in the Makefile"
    return match.group(1)


def test_browser_workflow_calls_the_script_and_inlines_nothing():
    runs = _run_blocks(_load("browser-e2e.yml"))
    assert any(BROWSER_SCRIPT in r for r in runs), f"browser-e2e.yml never calls {BROWSER_SCRIPT}"
    inlined = [r for r in runs if "playwright test" in r]
    assert not inlined, f"browser-e2e.yml re-inlines the suite; call {BROWSER_SCRIPT}: {inlined}"


def test_composed_workflow_calls_the_script_and_inlines_nothing():
    runs = _run_blocks(_load("composed-e2e.yml"))
    assert any(AGENT_SCRIPT in r for r in runs), f"composed-e2e.yml never calls {AGENT_SCRIPT}"
    inlined = [r for r in runs if "test_agent_e2e.py" in r]
    assert not inlined, f"composed-e2e.yml re-inlines the journey; call {AGENT_SCRIPT}: {inlined}"


def test_e2e_local_calls_the_script_and_inlines_nothing():
    recipe = _recipe("e2e-local")
    assert AGENT_SCRIPT in recipe
    assert "test_agent_e2e.py" not in recipe, "e2e-local re-inlines the pytest command"


def test_agent_script_seed_matches_the_workflow():
    """The script defaults CB_E2E_SEED for the laptop; composed-e2e.yml pins it for
    CI (test_ci_evidence_retention.py requires that). The two must be one value."""
    script = (REPO_ROOT / AGENT_SCRIPT).read_text(encoding="utf-8")
    match = re.search(r'CB_E2E_SEED="\$\{CB_E2E_SEED:-(\d+)\}"', script)
    assert match, f"{AGENT_SCRIPT} no longer defaults CB_E2E_SEED"
    step = next(
        s for s in _load("composed-e2e.yml")["jobs"]["composed-journey"]["steps"]
        if AGENT_SCRIPT in str(s.get("run", ""))
    )
    assert str(step["env"]["CB_E2E_SEED"]) == match.group(1)


@pytest.mark.parametrize("shard", ["1/2; rm -rf /", "1", "a/b", "1/2 3/4"])
def test_browser_script_rejects_a_malformed_shard_before_doing_anything(shard):
    result = subprocess.run(
        ["bash", str(REPO_ROOT / BROWSER_SCRIPT), *shard.split(" ")],
        capture_output=True, text=True, cwd=REPO_ROOT, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2, result.stderr
    assert "shard" in result.stderr.lower()


def test_browser_script_forces_the_ci_reporter():
    """playwright.config.ts writes junit.xml only when process.env.CI is set."""
    assert 'export CI="${CI:-1}"' in (REPO_ROOT / BROWSER_SCRIPT).read_text(encoding="utf-8")
```

In `tests/build/test_ci_script_contract.py:80`:

```python
TIER_SCRIPTS = [
    "tier0-static.sh",
    "tier1-unit.sh",
    "tier2-browser.sh",
    "tier2-agent-journey.sh",
    "tier3-artifact.sh",
]
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py tests/build/test_ci_script_contract.py -q`
Expected: FAIL. The scripts are missing, and the three `*_calls_the_script_*` tests report the inlined
commands.

- [ ] **Step 3: Write the two scripts**

`scripts/ci/tier2-browser.sh`:

```bash
#!/usr/bin/env bash
# Tier 2 — browser E2E. The one definition of how the Playwright suite runs.
# Called per shard by browser-e2e.yml inside the Playwright container, and for
# the whole suite by `make verify-composed-browser` on a laptop. Design D1/P1:
# tests/build/test_tier2_wiring.py fails if either caller re-inlines it.
#
# Usage: tier2-browser.sh [SHARD]      SHARD is N/M, e.g. 1/2
set -euo pipefail

# Validate before anything else runs: the shard reaches the command line, and a
# malformed one should cost nothing and say what was wrong.
if [[ $# -gt 1 ]] || { [[ $# -eq 1 ]] && ! [[ $1 =~ ^[0-9]+/[0-9]+$ ]]; }; then
  printf '::error::tier2-browser.sh takes at most one shard argument of the form N/M, got: %q\n' "$*" >&2
  exit 2
fi

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

# playwright.config.ts keys its JUnit reporter, retries, workers, forbidOnly and
# reuseExistingServer on process.env.CI. GitHub sets CI=true. A laptop does not,
# and without it a local run writes no junit.xml and behaves unlike CI, which is
# the drift P1 forbids.
export CI="${CI:-1}"

cb::require_tool npx
cb::require_file apps/frontend/node_modules "run 'cd apps/frontend && npm ci' first"

shard_args=()
if [[ $# -eq 1 ]]; then
  shard_args=(--shard="$1")
fi

# The visual-* projects carry the REL-18 baselines (docs/testing-visual-baselines.md).
# They are separate projects so a stale baseline fails the visual gate and not the
# functional one.
mkdir -p "$CB_REPO_ROOT/artifacts"
cd apps/frontend
npx playwright test "${shard_args[@]}" \
  --project=chromium \
  --project=firefox \
  --project=webkit \
  --project=mobile-chrome \
  --project=visual-desktop \
  --project=visual-mobile \
  2>&1 | tee "$CB_REPO_ROOT/artifacts/playwright.log"
```

`scripts/ci/tier2-agent-journey.sh`:

```bash
#!/usr/bin/env bash
# Tier 2 — composed agent journey. The one definition of the pytest invocation.
# Called by composed-e2e.yml on the runner, and by `make e2e-local` inside the
# uid-1001 runner container. Extra arguments go to pytest (E2E_ARGS='-k name').
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

# composed-e2e.yml pins these at step level too, and
# tests/build/test_tier2_wiring.py fails if the seed values disagree.
export CB_E2E_SEED="${CB_E2E_SEED:-20260826}"
export PYTHONHASHSEED="${PYTHONHASHSEED:-0}"
# Each test tears its own stack down in a `finally`, so the logs that explain a
# failure are written here from inside `_down()`, while containers still exist.
export CB_E2E_DIAGNOSTICS_DIR="${CB_E2E_DIAGNOSTICS_DIR:-$CB_REPO_ROOT/diagnostics}"

cb::require_tool python3
cb::require_tool docker "the journey composes its own stack"

mkdir -p "$CB_E2E_DIAGNOSTICS_DIR"
cd apps/agent/e2e
# -p no:cacheprovider: under `make e2e-local` the runner is uid 1001 and the
# worktree's .pytest_cache belongs to the developer, so pytest's end-of-session
# cache write dies with EACCES after every test has run. That turns a completed
# run into a traceback. CI wants no cross-run cache either.
python3 -m pytest test_agent_e2e.py -v \
  --junitxml=junit-agent-e2e.xml \
  --timeout=3600 \
  -p no:cacheprovider \
  "$@" \
  2>&1 | tee "$CB_E2E_DIAGNOSTICS_DIR/composed-journey.log"
```

Then run:
```bash
chmod +x scripts/ci/tier2-browser.sh scripts/ci/tier2-agent-journey.sh
git add scripts/ci/tier2-browser.sh scripts/ci/tier2-agent-journey.sh
git update-index --chmod=+x scripts/ci/tier2-browser.sh scripts/ci/tier2-agent-journey.sh
```

- [ ] **Step 4: Point the three callers at the scripts**

`browser-e2e.yml`: replace the whole `Run Playwright suite` step (its comment block stays above it) with:

```yaml
      - name: Run Playwright suite
        shell: bash
        env:
          SHARD: ${{ matrix.shard }}/${{ strategy.job-total }}
        run: scripts/ci/tier2-browser.sh "${SHARD}"
```

`composed-e2e.yml`: keep the `Run the composed journey` step's `env:` block exactly as it is, and replace
its `run:` with:

```yaml
        run: scripts/ci/tier2-agent-journey.sh
```

`Makefile` `e2e-local`: delete the three lines `-e CB_E2E_SEED=20260826 \`, `-e PYTHONHASHSEED=0 \` and
`-e CB_E2E_DIAGNOSTICS_DIR=$(CURDIR)/diagnostics \`, because the script defaults all three to the same
values. Then replace the final two recipe lines (`sh -c 'mkdir -p ... exec pytest test_agent_e2e.py ...'`)
with:

```make
	  sh -c 'mkdir -p "$$HOME" && exec bash $(CURDIR)/scripts/ci/tier2-agent-journey.sh $(E2E_ARGS)'
```

Move the `# -p no:cacheprovider` comment that follows the target into a single line above `e2e-local`:
`# The pytest flags, -p no:cacheprovider included, live in scripts/ci/tier2-agent-journey.sh.`

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py tests/build/test_ci_script_contract.py tests/build/test_ci_evidence_retention.py -q`
Expected: PASS. `test_ci_evidence_retention.py` still passes because the seed `env:` stayed on the step.

- [ ] **Step 6: Prove the browser script works in real browsers**

Changing `browser-e2e.yml` means the browser E2E is the covering suite (CLAUDE.md rule 1), and nothing
under `tests/build` runs it.

Run: `cd apps/frontend && npx playwright install --with-deps chromium && cd - && scripts/ci/tier2-browser.sh 1/2`
Expected: shard 1 runs, `apps/frontend/playwright-report/junit.xml` exists (proof that `CI=1` took effect),
and `artifacts/playwright.log` holds the output. Webkit or firefox may be missing from the laptop. In that
case say so in the PR and rely on Task 8's CI run for those projects, rather than calling it a pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/tier2-browser.sh scripts/ci/tier2-agent-journey.sh tests/build/test_tier2_wiring.py \
  tests/build/test_ci_script_contract.py .github/workflows/browser-e2e.yml .github/workflows/composed-e2e.yml Makefile
git commit -m "refactor(ci): give each Tier 2 suite one script that CI and make both call

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: `make verify-composed`

**Files:**
- Modify: `Makefile` (new targets beside `verify-full`, ~line 400)
- Modify: `tests/build/test_tier2_wiring.py`

**Interfaces:**
- Consumes: `tier2-browser.sh` and `e2e-local` from Task 1. `scripts/ci/quarantine_notice.py --check NAME`
  from A1, which exits non-zero when the register does not justify the skip.
- Produces: `make verify-composed`, `make verify-composed-browser`, `make verify-composed-agent`, and
  `CB_COMPOSED_QUARANTINED ?= 1`.

- [ ] **Step 1: Write the failing tests** (append to `test_tier2_wiring.py`)

```python
def test_verify_composed_runs_both_suites_and_is_documented():
    text = MAKEFILE.read_text(encoding="utf-8")
    line = re.search(r"^verify-composed:([^\n]*)$", text, re.M)
    assert line, "no verify-composed target"
    deps, _, help_text = line.group(1).partition("##")
    assert set(deps.split()) == {"verify-composed-browser", "verify-composed-agent"}
    assert "Tier 2" in help_text, "verify-composed must say what it is in `make help`"


def test_verify_composed_browser_calls_the_script():
    assert BROWSER_SCRIPT in _recipe("verify-composed-browser")


def test_verify_composed_agent_honours_the_register_or_runs_the_real_suite():
    recipe = _recipe("verify-composed-agent")
    assert "quarantine_notice.py" in recipe
    assert '"Composed Agent E2E / composed-journey"' in recipe
    assert "$(MAKE) e2e-local" in recipe


def test_local_quarantine_default_matches_the_workflow():
    """composed-e2e.yml defaults `quarantined` to true, so a laptop must default to
    the same. Otherwise `make verify-composed` starts a 75-minute suite that is
    known red, or skips one that CI runs."""
    workflow = _load("composed-e2e.yml")
    triggers = workflow.get("on", workflow.get(True))
    ci_default = bool(triggers["workflow_call"]["inputs"]["quarantined"]["default"])
    match = re.search(r"^CB_COMPOSED_QUARANTINED\s*\?=\s*(\d)\s*$", MAKEFILE.read_text(encoding="utf-8"), re.M)
    assert match, "Makefile has no `CB_COMPOSED_QUARANTINED ?= 0|1`"
    assert (match.group(1) == "1") == ci_default
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py -q -k "verify_composed or quarantine_default"`
Expected: FAIL, because the targets don't exist yet.

- [ ] **Step 3: Add the targets** after `verify-full` in `Makefile`, and add all three to that section's
`.PHONY` line (or add a `.PHONY` line above them if the section has none)

```make
# T2. Not part of `verify`: the browser suite builds the production frontend and
# drives four browsers, and the composed journey takes up to 75 minutes. Each
# target calls the same scripts/ci script the workflow does (design D1/P1;
# tests/build/test_tier2_wiring.py enforces it). Browsers must be installed
# locally: `cd apps/frontend && npx playwright install --with-deps`.
#
# CB_COMPOSED_QUARANTINED mirrors composed-e2e.yml's `quarantined` default, and
# the wiring test fails if they disagree. While QUAR-001 is live the agent half
# prints the register row and exits 0, as CI does. Set it to 0 to run the suite.
CB_COMPOSED_QUARANTINED ?= 1

verify-composed: verify-composed-browser verify-composed-agent ## Tier 2 — browser E2E + composed agent journey (CB_COMPOSED_QUARANTINED=0 lifts QUAR-001)

verify-composed-browser: ## Tier 2 — the Playwright suite, all projects, unsharded
	scripts/ci/tier2-browser.sh

verify-composed-agent: ## Tier 2 — the composed agent journey, or its register row while quarantined
	@if [ "$(CB_COMPOSED_QUARANTINED)" = "1" ]; then \
	  python3 scripts/ci/quarantine_notice.py --check "Composed Agent E2E / composed-journey"; \
	else \
	  $(MAKE) e2e-local; \
	fi
```

- [ ] **Step 4: Run the tests and the quarantined path for real**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py -q && make verify-composed-agent; echo "exit=$?"`
Expected: tests pass. Make prints `SKIPPED (QUAR-001, expires 2026-12-21, N days left)` and `exit=0`.

Then run `make help | grep verify-composed`. Expected: three lines.

- [ ] **Step 5: Commit**

```bash
git add Makefile tests/build/test_tier2_wiring.py
git commit -m "feat(make): verify-composed runs Tier 2 on a laptop through the CI scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: `tier2_gate.py` — plan and result

**Files:**
- Create: `scripts/ci/tier2_gate.py`
- Create: `tests/build/test_tier2_gate.py`

**Interfaces:**
- Produces, importable from `scripts/ci`:
  - `KNOWN_SUITES: tuple[str, ...] = ("browser", "composed")`
  - `DEFAULT_SUITES: tuple[str, ...] = ("browser", "composed")`
  - `SCHEDULED_REF: str = "dev"`
  - `class PlanError(ValueError)`
  - `parse_suites(raw: str) -> list[str]`: sorted and de-duplicated; empty input means `DEFAULT_SUITES`.
  - `resolve_ref(event_name: str, requested: str) -> str`
  - `judge(results: Mapping[str, Mapping[str, object]], suites: Sequence[str]) -> list[str]`: a list of
    problems, where empty means pass.
  - `main(argv: Sequence[str] | None = None) -> int`, with subcommands:
    - `plan`: reads env `SUITES`, `REF`, `EVENT_NAME` and appends `suites=<json>` and `ref=<ref>` to
      `$GITHUB_OUTPUT` when that is set, and always prints them.
    - `result`: reads env `RESULTS` (`toJSON(needs)`) and `SUITES`.
- The workflow's call-job ids **equal** the suite names (`browser`, `composed`), and the plan job id is `plan`.
  `judge` relies on this. Task 4's wiring test enforces it.

- [ ] **Step 1: Write the failing tests**

`tests/build/test_tier2_gate.py`:

```python
"""tier2_gate.py: the two Tier 2 decisions that must not live in workflow YAML."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from tier2_gate import (  # noqa: E402
    DEFAULT_SUITES,
    KNOWN_SUITES,
    PlanError,
    judge,
    main,
    parse_suites,
    resolve_ref,
)


def test_empty_suites_means_the_whole_default_tier():
    assert parse_suites("") == sorted(DEFAULT_SUITES)
    assert parse_suites("   ") == sorted(DEFAULT_SUITES)


def test_suites_are_sorted_and_deduplicated():
    assert parse_suites('["composed","browser","browser"]') == ["browser", "composed"]


@pytest.mark.parametrize(
    "raw",
    ['["brwoser"]', "browser", "[]", '"browser"', '[1]', '["browser", null]', "{}"],
)
def test_plan_rejects_unknown_or_malformed_suites(raw):
    with pytest.raises(PlanError):
        parse_suites(raw)


def test_plan_names_the_unknown_suite():
    with pytest.raises(PlanError, match="brwoser"):
        parse_suites('["browser","brwoser"]')


def test_default_suites_are_all_known():
    assert set(DEFAULT_SUITES) <= set(KNOWN_SUITES)


def test_scheduled_run_tests_dev():
    assert resolve_ref("schedule", "") == "dev"
    assert resolve_ref("schedule", "main") == "dev"


@pytest.mark.parametrize("event", ["workflow_dispatch", "push", "workflow_call"])
def test_other_events_honour_the_requested_ref(event):
    assert resolve_ref(event, "") == ""
    assert resolve_ref(event, "feat/tier2-slice-a2") == "feat/tier2-slice-a2"
    assert resolve_ref(event, "v0.4.5") == "v0.4.5"


@pytest.mark.parametrize("ref", ["dev\nsuites=[]", "dev;rm -rf /", "$(id)", "a b", "x" * 256])
def test_plan_rejects_a_ref_that_could_forge_an_output(ref):
    with pytest.raises(PlanError):
        resolve_ref("workflow_dispatch", ref)


def _needs(**results: str) -> dict:
    return {job: {"result": outcome, "outputs": {}} for job, outcome in results.items()}


def test_result_passes_when_selected_succeed_and_unselected_skip():
    assert judge(_needs(plan="success", browser="success", composed="skipped"), ["browser"]) == []
    assert judge(_needs(plan="success", browser="success", composed="success"), ["browser", "composed"]) == []


def test_result_fails_when_a_selected_suite_was_skipped():
    problems = judge(_needs(plan="success", browser="skipped", composed="success"), ["browser", "composed"])
    assert problems == ["browser: skipped (expected success)"]


def test_result_fails_when_an_unselected_suite_ran():
    problems = judge(_needs(plan="success", browser="success", composed="success"), ["browser"])
    assert problems == ["composed: success (expected skipped)"]


def test_result_fails_when_a_known_suite_is_missing_from_needs():
    problems = judge(_needs(plan="success", browser="success"), ["browser"])
    assert problems == ["composed: None (expected skipped)"]


def test_result_reports_only_the_plan_when_the_plan_failed():
    assert judge(_needs(plan="failure", browser="skipped", composed="skipped"), []) == ["plan: failure"]


def test_main_plan_writes_github_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("SUITES", '["browser"]')
    monkeypatch.setenv("REF", "")
    monkeypatch.setenv("EVENT_NAME", "schedule")
    assert main(["plan"]) == 0
    assert out.read_text().splitlines() == ['suites=["browser"]', "ref=dev"]


def test_main_plan_fails_loudly_without_writing_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("SUITES", '["brwoser"]')
    monkeypatch.setenv("REF", "")
    monkeypatch.setenv("EVENT_NAME", "workflow_dispatch")
    assert main(["plan"]) == 1
    assert not out.exists()
    assert "::error::" in capsys.readouterr().out


def test_main_result_exit_codes(monkeypatch):
    monkeypatch.setenv("SUITES", '["browser","composed"]')
    monkeypatch.setenv("RESULTS", json.dumps(_needs(plan="success", browser="success", composed="success")))
    assert main(["result"]) == 0
    monkeypatch.setenv("RESULTS", json.dumps(_needs(plan="success", browser="failure", composed="success")))
    assert main(["result"]) == 1
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_tier2_gate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tier2_gate'`.

- [ ] **Step 3: Implement `scripts/ci/tier2_gate.py`**

```python
"""Tier 2's two decisions that must not live in workflow YAML.

`plan` turns the caller's inputs into the list of suites to run and the ref they
check out. `result` turns `toJSON(needs)` into one verdict for the tier.

Both are here rather than inline in tier2.yml so they can be tested: a dispatch
that names a suite Tier 2 does not have must fail and name it, not run zero
suites and report green, and a selected suite that ends `skipped` must fail the
tier, because a skipped job reads as satisfied to every consumer of a run.

Pure: environment and argv in, stdout and $GITHUB_OUTPUT out. Runs on the
runner's system Python (3.10 on ubuntu-22.04).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence

# The call-job ids in tier2.yml are these names exactly, and
# tests/build/test_tier2_wiring.py fails if a suite job is added there without
# being added here, or the reverse. "mono" joins in slice A3.
KNOWN_SUITES: tuple[str, ...] = ("browser", "composed")
DEFAULT_SUITES: tuple[str, ...] = ("browser", "composed")

# `schedule` fires only from the default branch's copy of the workflow, and
# `main` trails the integration branch, so the nightly tests `dev` (design D2).
SCHEDULED_REF = "dev"

# A branch, tag or SHA, and nothing that could end an output line or reach a shell.
_REF = re.compile(r"[A-Za-z0-9._/-]{0,255}")


class PlanError(ValueError):
    """The inputs name something Tier 2 cannot run."""


def parse_suites(raw: str) -> list[str]:
    """Return the requested suites, sorted and de-duplicated. Empty input means the default set."""
    text = raw.strip()
    if not text:
        return sorted(DEFAULT_SUITES)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"suites must be a JSON array of names, got {text!r} ({exc.msg})") from exc
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise PlanError(f"suites must be a non-empty JSON array of strings, got {text!r}")
    unknown = sorted(set(value) - set(KNOWN_SUITES))
    if unknown:
        raise PlanError(f"unknown suite(s) {unknown}; Tier 2 knows {list(KNOWN_SUITES)}")
    return sorted(set(value))


def resolve_ref(event_name: str, requested: str) -> str:
    """Return the ref the suites check out: `dev` on a schedule, otherwise the requested ref."""
    if event_name == "schedule":
        return SCHEDULED_REF
    if not _REF.fullmatch(requested):
        raise PlanError(f"ref {requested!r} is not a plain branch, tag or SHA")
    return requested


def judge(results: Mapping[str, Mapping[str, object]], suites: Sequence[str]) -> list[str]:
    """Return one problem per job whose result contradicts the plan. An empty list means Tier 2 passed."""
    plan = results.get("plan", {}).get("result")
    if plan != "success":
        return [f"plan: {plan}"]
    problems: list[str] = []
    for suite in KNOWN_SUITES:
        outcome = results.get(suite, {}).get("result")
        expected = "success" if suite in suites else "skipped"
        if outcome != expected:
            problems.append(f"{suite}: {outcome} (expected {expected})")
    return problems


def _plan() -> int:
    try:
        suites = parse_suites(os.environ.get("SUITES", ""))
        ref = resolve_ref(os.environ.get("EVENT_NAME", ""), os.environ.get("REF", ""))
    except PlanError as exc:
        print(f"::error::Tier 2 plan: {exc}")
        return 1
    lines = [f"suites={json.dumps(suites, separators=(',', ':'))}", f"ref={ref}"]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("".join(f"{line}\n" for line in lines))
    for line in lines:
        print(line)
    return 0


def _result() -> int:
    results = json.loads(os.environ["RESULTS"])
    raw_suites = os.environ.get("SUITES", "")
    suites: list[str] = json.loads(raw_suites) if raw_suites else []
    for job, detail in sorted(results.items()):
        print(f"{job}: {detail.get('result')}")
    problems = judge(results, suites)
    for problem in problems:
        print(f"::error::Tier 2 did not pass: {problem}")
    if not problems:
        print(f"Tier 2 green: {', '.join(suites)}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `plan` or `result` subcommand and return its exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "result"))
    args = parser.parse_args(argv)
    return _plan() if args.command == "plan" else _result()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests, lint and the runner-Python gate**

Run: `.venv/bin/pytest tests/build/test_tier2_gate.py tests/build/test_ci_scripts_match_runner_python.py -q && make lint`
Expected: PASS. If vermin reports a minimum above 3.10, fix the construct it names. Don't raise the floor.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/tier2_gate.py tests/build/test_tier2_gate.py
git commit -m "feat(ci): tier2_gate.py plans the suites and judges the tier

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: `tier2.yml`, and the nightly moves into it

**Files:**
- Create: `.github/workflows/tier2.yml`
- Modify: `.github/workflows/browser-e2e.yml` (`on: workflow_call`, checkout, run manifest)
- Modify: `.github/workflows/e2e.yml` (drop `schedule`, drop the `ref:` redirect, update the header)
- Modify: `.github/workflows/notify.yml:20-33`
- Modify: `tests/build/test_tier2_wiring.py`

**Interfaces:**
- Consumes: `tier2_gate.py plan|result` and its env contract (Task 3). `composed-e2e.yml` inputs `ref`
  and `quarantined` (A1).
- Produces: `tier2.yml` `workflow_call` inputs `suites: string, default ""` and `ref: string, default ""`.
  Job ids `plan`, `browser`, `composed`, `result`. `browser-e2e.yml` gains input `ref: string, default ""`.

- [ ] **Step 1: Write the failing tests** (append to `test_tier2_wiring.py`)

```python
import json
import sys

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
from tier2_gate import KNOWN_SUITES  # noqa: E402

_GATED = re.compile(r"contains\(fromJSON\(needs\.plan\.outputs\.suites\),\s*'([a-z0-9-]+)'\)")


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True)) or {}


def test_tier2_is_named_and_triggered_as_the_design_says():
    workflow = _load("tier2.yml")
    assert workflow["name"] == "Tier 2 (composed)"
    triggers = _triggers(workflow)
    assert set(triggers) >= {"schedule", "workflow_dispatch", "workflow_call"}
    assert triggers["schedule"] == [{"cron": "0 3 * * *"}]


def test_every_suite_job_is_gated_on_its_own_name_and_the_sets_agree():
    jobs = _load("tier2.yml")["jobs"]
    gated = {}
    for job_id, job in jobs.items():
        match = _GATED.search(str(job.get("if", "")))
        if match:
            gated[job_id] = match.group(1)
    assert all(job_id == suite for job_id, suite in gated.items()), gated
    assert set(gated.values()) == set(KNOWN_SUITES), (
        f"tier2.yml gates {sorted(gated.values())} but tier2_gate.py knows {sorted(KNOWN_SUITES)}"
    )


def test_result_job_needs_the_plan_and_every_suite_and_always_runs():
    result = _load("tier2.yml")["jobs"]["result"]
    assert set(result["needs"]) == {"plan", *KNOWN_SUITES}
    assert "always()" in str(result["if"])


def test_tier2_passes_the_planned_ref_to_every_suite():
    jobs = _load("tier2.yml")["jobs"]
    for suite in KNOWN_SUITES:
        assert jobs[suite]["with"]["ref"] == "${{ needs.plan.outputs.ref }}", suite


def test_tier2_runs_serially_without_cancelling():
    concurrency = _load("tier2.yml")["concurrency"]
    assert concurrency["cancel-in-progress"] is False


def test_the_nightly_has_exactly_one_home():
    """One cron cannot live in two files: both would run the composed suite."""
    assert "schedule" not in _triggers(_load("e2e.yml"))


def test_the_composed_journey_is_still_scheduled():
    """AGT-01: the composed journey runs on a schedule. Moving the cron must not drop it."""
    tier2 = _load("tier2.yml")
    assert "schedule" in _triggers(tier2)
    assert tier2["jobs"]["composed"]["uses"] == "./.github/workflows/composed-e2e.yml"


def test_browser_e2e_checks_out_the_ref_it_was_given():
    workflow = _load("browser-e2e.yml")
    assert _triggers(workflow)["workflow_call"]["inputs"]["ref"]["default"] == ""
    checkouts = [
        s for s in workflow["jobs"]["browser-e2e"]["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert checkouts and all(s["with"]["ref"] == "${{ inputs.ref }}" for s in checkouts)


def test_notify_watches_tier2():
    watched = _triggers(_load("notify.yml"))["workflow_run"]["workflows"]
    assert "Tier 2 (composed)" in watched
```

Put the new imports at the top of the file with the others, not in the middle.

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py -q`
Expected: FAIL, because `tier2.yml` does not exist yet.

- [ ] **Step 3: Give `browser-e2e.yml` a `ref` input**

Replace `on:\n  workflow_call:` with:

```yaml
on:
  workflow_call:
    inputs:
      # tier2.yml's nightly loads from the default branch but tests `dev`
      # (design D2). Empty means the ref that triggered the caller, which is
      # what ci.yml, dev-ci.yml and the release get, unchanged.
      ref:
        description: "Ref to check out. Empty means the ref that triggered the caller."
        required: false
        type: string
        default: ""
```

Change the checkout to:

```yaml
      - uses: actions/checkout@v5
        with:
          ref: ${{ inputs.ref }}
          persist-credentials: false
```

Add `REQUESTED_REF: ${{ inputs.ref }}` to the `Record the run manifest` step's `env:` (create the block if
it has none), and add this line inside the `{ ... }` group after `commit=`:

```bash
            echo "requested_ref=${REQUESTED_REF:-<triggering ref>}"
```

`GITHUB_SHA` is the caller's commit, so on a nightly `commit=` names `main` while the tree is `dev`. The
new line is what tells a reader which tree the run actually tested.

- [ ] **Step 4: Write `.github/workflows/tier2.yml`**

```yaml
name: Tier 2 (composed)

# T2 of the verification ladder (docs/design/2026-09-27-tier2-composed-and-triage-design.md):
# browser E2E and the composed agent journey, with the mono image smoke joining
# in slice A3. Each suite keeps its own reusable workflow (design D1); this file
# only chooses which to run and gives the tier one verdict.
#
# Three ways in:
#   schedule          — the nightly, moved here from e2e.yml. It loads from the
#                       default branch and tests `dev` (design D2); tier2_gate.py
#                       makes that decision, not an inline expression.
#   workflow_dispatch — a manual run of the whole tier or part of it.
#   workflow_call     — the release and the release dry run. Inside a called
#                       workflow the `github` context is the CALLER's, so no event
#                       test can tell "the nightly" from "the release"; inputs do.
#
# Not a required check (D2). A red T2 blocks a release and reports nightly.
on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:
    inputs:
      # checkov:skip=CKV_GHA_7: selects which existing suites run, and nothing
      # about what is built. tier2_gate.py rejects any name it does not know.
      suites:
        description: 'JSON array of suites, e.g. ["browser"]. Empty runs the whole tier.'
        required: false
        type: string
        default: ""
      # checkov:skip=CKV_GHA_7: chooses the tree under test. tier2_gate.py rejects
      # anything but a plain branch, tag or SHA.
      ref:
        description: "Ref to test. Empty means the ref this run was dispatched on."
        required: false
        type: string
        default: ""
  workflow_call:
    inputs:
      suites:
        description: "JSON array of suites. Empty runs the whole tier."
        required: false
        type: string
        default: ""
      ref:
        description: "Ref to test. Empty means the caller's ref."
        required: false
        type: string
        default: ""

# A manual dispatch and the nightly must not interleave: B1's triage will read
# one run's artifacts as one run. Queue rather than cancel, because a cancelled
# nightly is a night with no signal. `github.workflow` is the caller's name when
# this is called, so a release queues only behind its own earlier run.
concurrency:
  group: tier2-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

permissions: {}

jobs:
  plan:
    name: Plan
    runs-on: ubuntu-22.04
    timeout-minutes: 5
    permissions:
      contents: read
    outputs:
      suites: ${{ steps.plan.outputs.suites }}
      ref: ${{ steps.plan.outputs.ref }}
    steps:
      # Pinned the same way the suites are, so a nightly reads `dev`'s copy of
      # the plan logic alongside `dev`'s tree (test_scheduled_workflows_pin_their_ref.py).
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}
          persist-credentials: false
          sparse-checkout: scripts/ci
      - id: plan
        shell: bash
        env:
          SUITES: ${{ inputs.suites }}
          REF: ${{ inputs.ref }}
          EVENT_NAME: ${{ github.event_name }}
        run: python3 scripts/ci/tier2_gate.py plan

  browser:
    name: Browser E2E
    needs: plan
    if: contains(fromJSON(needs.plan.outputs.suites), 'browser')
    permissions:
      contents: read
    uses: ./.github/workflows/browser-e2e.yml
    with:
      ref: ${{ needs.plan.outputs.ref }}

  # `quarantined` is left to composed-e2e.yml's own default (true), so QUAR-001
  # is reported by its register row until the day that default flips.
  composed:
    name: Composed Agent E2E
    needs: plan
    if: contains(fromJSON(needs.plan.outputs.suites), 'composed')
    permissions:
      contents: read
    uses: ./.github/workflows/composed-e2e.yml
    with:
      ref: ${{ needs.plan.outputs.ref }}

  # The tier's one verdict. always(), so that a failed plan or a skipped suite
  # still produces an answer. A selected suite that ended `skipped` is a failure
  # here, because everything downstream reads `skipped` as satisfied.
  result:
    name: Tier 2 result
    needs: [plan, browser, composed]
    if: always()
    runs-on: ubuntu-22.04
    timeout-minutes: 5
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}
          persist-credentials: false
          sparse-checkout: scripts/ci
      - shell: bash
        env:
          RESULTS: ${{ toJSON(needs) }}
          SUITES: ${{ needs.plan.outputs.suites }}
        run: python3 scripts/ci/tier2_gate.py result
```

- [ ] **Step 5: Hand the nightly over in `e2e.yml`**

Delete the `schedule:` block (`- cron: "0 3 * * *"`). Delete the `ref:` line in `with:` together with its
three-line comment, because nothing schedules this file any more. The `quarantined` expression stays. In
the header, replace the paragraph that begins "The suite itself now lives in composed-e2e.yml" with:

```yaml
# The suite itself lives in composed-e2e.yml, and its nightly lives in tier2.yml
# (slice A2 of docs/design/2026-09-27-tier2-composed-and-triage-design.md).
# This file keeps the triggers that belong to the agent specifically: a tag
# push, and pull requests that touch the agent. The release calls tier2.yml
# with the browser suite only; the composed journey is not a release gate.
```

In the AGT-01 paragraph at the top of the header, change "runs per RC (tag push) and nightly." to "runs per
RC (tag push) and nightly (through tier2.yml since slice A2)." Leave the rest of that paragraph as it is:
"deliberately NOT a release gate" stays true, and the maintainer reaffirmed it on 2026-09-27.

**Why this ordering is safe:** a `schedule` event reads the default branch's copy of each file. Until this
branch reaches `main`, `main`'s `e2e.yml` keeps its cron and `main` has no `tier2.yml`. At promotion both
change in the same commit, so the nightly neither doubles nor disappears.

- [ ] **Step 6: Watch the new workflow in `notify.yml`**

Add `- Tier 2 (composed)` after `- Composed Agent E2E` in the `workflows:` list.

- [ ] **Step 7: Run the wiring tests, every guard that reads workflows, and checkov**

```bash
.venv/bin/pytest tests/build/test_tier2_wiring.py tests/build/test_scheduled_workflows_pin_their_ref.py \
  tests/build/test_workflow_job_graph.py tests/build/test_workflow_run_blocks.py \
  tests/build/test_workflow_wiring_resolves.py tests/build/test_quarantine_notice.py \
  tests/build/test_discord_notify.py tests/build/test_ci_evidence_retention.py -q
checkov -f .github/workflows/tier2.yml -f .github/workflows/browser-e2e.yml -f .github/workflows/e2e.yml \
  --framework github_actions
```

Expected: every test passes, and checkov reports 0 failed. If `test_workflow_job_graph.py` or
`test_workflow_run_blocks.py` objects to a construct in `tier2.yml`, change `tier2.yml` to satisfy the
guard. Don't change the guard to accept it.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/tier2.yml .github/workflows/browser-e2e.yml .github/workflows/e2e.yml \
  .github/workflows/notify.yml tests/build/test_tier2_wiring.py
git commit -m "feat(ci): tier2.yml runs Tier 2 as one thing and takes over the nightly

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: The release and the dry run call Tier 2

**Files:**
- Modify: `.github/workflows/release.yml:185-196` (job) and `:445` (`needs` of `release`)
- Modify: `.github/workflows/release-dry-run.yml:107-110` (job) and `:529` (`needs` of `summary`)
- Modify: `tests/build/test_tier2_wiring.py`

**Interfaces:**
- Consumes: `tier2.yml` `workflow_call` inputs `suites` and `ref` (Task 4), and `KNOWN_SUITES` (Task 3).

- [ ] **Step 1: Write the failing tests** (append to `test_tier2_wiring.py`)

```python
def _tier2_callers() -> dict[str, dict]:
    callers = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in (_load(path.name).get("jobs") or {}).items():
            if str((job or {}).get("uses", "")) == "./.github/workflows/tier2.yml":
                callers[f"{path.name}:{job_id}"] = job
    return callers


def test_the_release_path_calls_tier2_and_not_browser_e2e_directly():
    for name in ("release.yml", "release-dry-run.yml"):
        jobs = _load(name)["jobs"]
        assert jobs["tier2"]["uses"] == "./.github/workflows/tier2.yml", name
        direct = [j for j, job in jobs.items() if str(job.get("uses", "")).endswith("browser-e2e.yml")]
        assert not direct, f"{name} still calls browser-e2e.yml directly from {direct}"


def test_every_tier2_caller_passes_real_suites():
    callers = _tier2_callers()
    assert callers, "nothing calls tier2.yml"
    for where, job in callers.items():
        raw = (job.get("with") or {}).get("suites", "")
        if raw == "":
            continue
        suites = json.loads(raw)
        assert suites and set(suites) <= set(KNOWN_SUITES), f"{where} passes {suites}"


def test_the_release_does_not_gate_on_the_composed_journey():
    """Maintainer decision 2026-09-27 (A2 plan): the release is not gated on the
    composed journey. `suites` is passed explicitly, because the tier's default
    includes composed, so omitting it would silently start gating."""
    for name in ("release.yml", "release-dry-run.yml"):
        raw = _load(name)["jobs"]["tier2"]["with"]["suites"]
        assert json.loads(raw) == ["browser"], f"{name} passes {raw}"


def test_tier2_callers_grant_read_only():
    for where, job in _tier2_callers().items():
        assert job.get("permissions") == {"contents": "read"}, where


def test_release_waits_for_tier2():
    assert "tier2" in _load("release.yml")["jobs"]["release"]["needs"]
    assert "tier2" in _load("release-dry-run.yml")["jobs"]["summary"]["needs"]
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_tier2_wiring.py -q -k "release or caller"`
Expected: FAIL.

- [ ] **Step 3: Rewire `release.yml`**

Replace the `browser-e2e:` job and the comment paragraph directly above it (the one ending "browser-e2e.yml's
header records what closing that half would take.") with:

```yaml
  # Tier 2 gates the candidate, with the browser suite only. The composed agent
  # journey is deliberately NOT a release gate (AGT-01, reaffirmed by the
  # maintainer 2026-09-27): it runs nightly through tier2.yml and on tag pushes
  # through e2e.yml, and its rerun guard keeps a known failure from being
  # re-run until it is fixed or quarantined. `suites` must stay explicit: the
  # tier's default includes composed.
  #
  # Read-only on purpose: this workflow's top-level token can write releases and
  # packages, and a test suite needs neither. Check runs read
  # `Tier 2 / Browser E2E / browser-e2e (shard 1/2)`, three levels of nesting,
  # inside GitHub's limit of four (design §7.4).
  tier2:
    name: Tier 2
    if: github.event_name == 'workflow_dispatch' && inputs.channel == 'candidate'
    needs: [version, gate]
    permissions:
      contents: read
    uses: ./.github/workflows/tier2.yml
    with:
      suites: '["browser"]'
```

In the `release` job, change `needs: [version, build, artifact-smoke, browser-e2e, installer-journey, image-merge, runtime-parity]`
by replacing `browser-e2e` with `tier2`. Then run `grep -n "browser-e2e\|Browser E2E" .github/workflows/release.yml`,
and update any other `needs:` or `needs.browser-e2e` reference and any comment still describing the old job.

- [ ] **Step 4: Rewire `release-dry-run.yml`**

```yaml
  tier2:
    name: Tier 2
    needs: version
    permissions:
      contents: read
    uses: ./.github/workflows/tier2.yml
    with:
      suites: '["browser"]'
```

In `summary.needs`, replace `browser-e2e` with `tier2`. `summary` requires every result to be `success`.
The `tier2` job's result is `success` when `Tier 2 result` passes, because a skipped job inside a called
workflow does not fail the call. That behaviour is exactly what Task 8's dry run proves on a real runner.

- [ ] **Step 5: Run the tests and checkov**

```bash
.venv/bin/pytest tests/build/ -q
checkov -f .github/workflows/release.yml -f .github/workflows/release-dry-run.yml --framework github_actions
```

Expected: the whole repo-policy suite passes, and checkov reports no new failures compared with
`git stash; checkov ...; git stash pop` on the same two files.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/release-dry-run.yml tests/build/test_tier2_wiring.py
git commit -m "feat(release): gate the candidate through Tier 2, browser suite only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: The composed journey's rerun guard

Maintainer decision 2 says a composed run may not follow a failed one on the same inputs until those failures
are fixed or quarantined. The guard sits inside `composed-e2e.yml`, so every caller gets it: `e2e.yml`'s tag
push and agent PRs, `tier2.yml`'s nightly, and any manual dispatch. **There is no force switch.**

**Files:**
- Create: `scripts/ci/composed_rerun_guard.py`
- Create: `tests/build/test_composed_rerun_guard.py`
- Modify: `scripts/ci/tier2-agent-journey.sh` (deselect quarantined tests)
- Modify: `.github/workflows/composed-e2e.yml` (new `rerun-guard` job, plus verdict recording in `composed-journey`)

**Interfaces:**
- Consumes: `quarantine_notice.REGISTER`, `quarantine_notice.RegisterError` and
  `quarantine_notice.rows_for_check(register: Path, check: str) -> list[dict[str, str]]` (A1). Register
  column `scope` holds comma-separated test names, and `expiry` holds an ISO date.
- Produces, importable from `scripts/ci`:
  - `CHECK = "Composed Agent E2E / composed-journey"`
  - `NODE_PREFIX = "apps/agent/e2e/test_agent_e2e.py::"`. Pytest's rootdir is the repo root
    (`pytest.ini`), so this is the only prefix `--deselect` matches. Checked 2026-09-27:
    `--deselect test_agent_e2e.py::…` deselected 0 of 16 tests, and the full prefix deselected 1.
  - `SUITE_INPUTS: tuple[str, ...]`
  - `ARTIFACT_PREFIX = "composed-journey-verdict-"`
  - `fingerprint(listing: str) -> str` and `git_listing(root: Path, rev: str = "HEAD") -> str`
  - `quarantined_tests(register: Path, today: date) -> frozenset[str]`
  - `failed_tests_from_junit(path: Path) -> list[str]`
  - `@dataclass(frozen=True) class Verdict: fingerprint: str; sha: str; run_url: str; outcome: str; failed_tests: tuple[str, ...]`,
    with `to_json() -> str` and `Verdict.from_json(text: str) -> Verdict`, which raises `ValueError`
  - `decide(previous: Verdict | None, quarantined: frozenset[str]) -> tuple[bool, str]`
  - `pick_verdict_artifact(listing: Mapping[str, object], repo_id: int) -> dict[str, object] | None`
  - `deselect_args(quarantined: frozenset[str]) -> list[str]`
  - `main(argv) -> int`, with subcommands `fingerprint`, `check`, `record` and `deselect`

**How "addressed" is decided (one place, `decide`):**

| Previous verdict for this fingerprint | Allowed? | Message |
|---|---|---|
| none (first run, or its artifact expired after 90 days) | yes | `no earlier verdict for these inputs` |
| `success` | yes | `last run on these inputs passed: <url>` |
| `failure`, no test-level failures (a crash or timeout) | **no** | `… failed with no test-level failure recorded; only a change to the suite's inputs addresses it` |
| `failure`, and every failed test is quarantined | yes | `all failures from <url> are quarantined: …` |
| `failure`, and some failed test is not quarantined | **no** | `failures from <url> are unaddressed: …; fix them or quarantine them` |

A changed input is never looked up at all, because the artifact name carries the fingerprint. That is what
makes "fixed" cost nothing to detect.

**Trust:** the artifacts API lists artifacts from every run in the repository, including `pull_request` runs
from forks. A fork controls its own copy of the workflow and could upload a fake verdict under any name, which
would either unblock a failure or block a clean tree. `pick_verdict_artifact` therefore accepts only artifacts
whose `workflow_run.head_repository_id` equals this repository's id. It also skips expired artifacts and picks
the newest by `created_at` explicitly, instead of trusting the API's ordering.

- [ ] **Step 1: Write the failing tests**

`tests/build/test_composed_rerun_guard.py`:

```python
"""The composed journey never runs twice on the same inputs with its failures unaddressed."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from composed_rerun_guard import (  # noqa: E402
    ARTIFACT_PREFIX,
    CHECK,
    NODE_PREFIX,
    SUITE_INPUTS,
    Verdict,
    decide,
    deselect_args,
    failed_tests_from_junit,
    fingerprint,
    git_listing,
    pick_verdict_artifact,
    quarantined_tests,
)

HEADER = "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
TODAY = date(2026, 9, 27)


def _register(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "register.csv"
    path.write_text(HEADER + "".join(f"{row}\n" for row in rows), encoding="utf-8")
    return path


def _row(scope: str, expiry: str = "2026-12-21", check: str = CHECK) -> str:
    return f'Q-1,{check},"{scope}",why,owner,#1,2026-09-01,{expiry},'


def _verdict(outcome: str, *failed: str) -> Verdict:
    return Verdict("fp", "abc123", "https://example.invalid/run/1", outcome, tuple(failed))


# ── fingerprint ─────────────────────────────────────────────────────────────
def test_fingerprint_is_stable_and_input_sensitive():
    assert fingerprint("a\nb\n") == fingerprint("a\nb\n")
    assert fingerprint("a\nb\n") != fingerprint("a\nc\n")
    assert len(fingerprint("x")) == 16


def test_every_suite_input_exists_in_the_tree():
    """A renamed input would silently narrow the fingerprint: a fix under the new
    path would no longer count as a fix."""
    listing = git_listing(REPO_ROOT)
    for path in SUITE_INPUTS:
        # A directory shows as `<tab>path/…`, a file as `<tab>path<newline>`. A bare
        # prefix test would let `docker` match `docker-compose.yml`.
        assert f"\t{path}/" in listing or f"\t{path}\n" in listing, (
            f"{path} is in SUITE_INPUTS but not in the tree"
        )


def test_git_listing_fails_loudly_outside_a_repo(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        git_listing(tmp_path)


# ── register ────────────────────────────────────────────────────────────────
def test_quarantined_tests_reads_live_rows_for_this_check_only(tmp_path):
    register = _register(
        tmp_path,
        _row("test_a, test_b"),
        _row("test_old", expiry="2026-09-26"),
        _row("test_other", check="Browser E2E / browser-e2e"),
    )
    assert quarantined_tests(register, TODAY) == frozenset({"test_a", "test_b"})


def test_a_row_expiring_today_is_still_live(tmp_path):
    assert quarantined_tests(_register(tmp_path, _row("test_a", expiry="2026-09-27")), TODAY) == {"test_a"}


# ── junit ───────────────────────────────────────────────────────────────────
def test_failed_tests_from_junit(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite>'
        '<testcase name="test_pass"/>'
        '<testcase name="test_fail"><failure message="x"/></testcase>'
        '<testcase name="test_err"><error message="y"/></testcase>'
        '<testcase name="test_skip"><skipped/></testcase>'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )
    assert failed_tests_from_junit(junit) == ["test_err", "test_fail"]


def test_missing_junit_means_no_test_level_failures(tmp_path):
    assert failed_tests_from_junit(tmp_path / "absent.xml") == []


# ── decide ──────────────────────────────────────────────────────────────────
def test_first_run_is_allowed():
    allowed, why = decide(None, frozenset())
    assert allowed and "no earlier verdict" in why


def test_a_pass_allows_the_next_run():
    assert decide(_verdict("success"), frozenset())[0]


def test_an_unaddressed_failure_blocks_and_names_the_tests():
    allowed, why = decide(_verdict("failure", "test_a", "test_b"), frozenset({"test_a"}))
    assert not allowed
    assert "test_b" in why and "https://example.invalid/run/1" in why


def test_a_fully_quarantined_failure_is_addressed():
    assert decide(_verdict("failure", "test_a", "test_b"), frozenset({"test_a", "test_b"}))[0]


def test_parametrised_names_match_their_base_row():
    assert decide(_verdict("failure", "test_a[x-1]"), frozenset({"test_a"}))[0]


def test_a_failure_without_test_names_can_only_be_fixed():
    allowed, why = decide(_verdict("failure"), frozenset({"test_a"}))
    assert not allowed and "change to the suite's inputs" in why


# ── verdict JSON ────────────────────────────────────────────────────────────
def test_verdict_round_trips():
    verdict = _verdict("failure", "test_a")
    assert Verdict.from_json(verdict.to_json()) == verdict


@pytest.mark.parametrize("text", ["", "{}", '{"outcome": "maybe"}', "[1]"])
def test_a_malformed_verdict_is_an_error_not_a_pass(text):
    with pytest.raises(ValueError):
        Verdict.from_json(text)


# ── artifact choice ─────────────────────────────────────────────────────────
def _artifact(created: str, repo_id: int = 7, expired: bool = False) -> dict:
    return {
        "name": ARTIFACT_PREFIX + "fp",
        "created_at": created,
        "expired": expired,
        "archive_download_url": f"https://api.invalid/{created}",
        "workflow_run": {"head_repository_id": repo_id},
    }


def test_pick_prefers_the_newest_trusted_unexpired_artifact():
    listing = {"artifacts": [
        _artifact("2026-09-25T00:00:00Z"),
        _artifact("2026-09-27T00:00:00Z", repo_id=999),        # a fork: never trusted
        _artifact("2026-09-26T12:00:00Z", expired=True),
        _artifact("2026-09-26T00:00:00Z"),
    ]}
    assert pick_verdict_artifact(listing, 7)["created_at"] == "2026-09-26T00:00:00Z"


def test_pick_returns_none_when_nothing_is_trusted():
    assert pick_verdict_artifact({"artifacts": [_artifact("2026-09-27T00:00:00Z", repo_id=999)]}, 7) is None


# ── deselection really deselects ────────────────────────────────────────────
def test_deselect_args_use_the_rootdir_relative_prefix():
    assert deselect_args(frozenset({"test_b", "test_a"})) == [
        f"--deselect={NODE_PREFIX}test_a",
        f"--deselect={NODE_PREFIX}test_b",
    ]


def test_deselect_args_actually_deselect_a_real_test():
    """A --deselect whose prefix is wrong deselects nothing and says nothing.
    This asks pytest itself, against the real suite file."""
    e2e = REPO_ROOT / "apps" / "agent" / "e2e"

    def collected(*extra: str) -> str:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "test_agent_e2e.py", "--collect-only", "-q", *extra],
            cwd=e2e, capture_output=True, text=True, check=True,
        ).stdout
        return out.strip().splitlines()[-1]

    real_test = "test_agent_zero_configuration_discovery_import_and_replay"
    assert "(1 deselected)" in collected(*deselect_args(frozenset({real_test}))), collected()
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/pytest tests/build/test_composed_rerun_guard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'composed_rerun_guard'`.

- [ ] **Step 3: Implement `scripts/ci/composed_rerun_guard.py`**

```python
"""The composed journey never runs twice on the same inputs with its failures unaddressed.

Maintainer decision, 2026-09-27 (Tier 2 slice A2 plan). Every real run records
a verdict artifact named after a fingerprint of the suite's inputs. The next
run looks up the verdict for its own fingerprint and refuses to start when that
verdict failed and the failures were neither

  fixed        — anything under SUITE_INPUTS changed, so the fingerprint is new
                 and there is no verdict to find, or
  quarantined  — every failed test has a live register row for CHECK, which the
                 journey then deselects (`deselect`).

These are the two outcomes CLAUDE.md rule 2 permits. There is deliberately no
force switch.

Subcommands:
  fingerprint  print the fingerprint of HEAD's suite inputs
  check        fetch the previous verdict (gh api) and exit 1 if unaddressed
  record       write this run's verdict from JUnit and the step outcome
  deselect     print one --deselect argument per quarantined test

Runs on the runner's system Python (3.10 on ubuntu-22.04).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quarantine_notice import REGISTER, RegisterError, rows_for_check  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = "Composed Agent E2E / composed-journey"
# pytest.ini at the repo root makes node ids rootdir-relative. A bare
# `test_agent_e2e.py::` prefix deselects nothing, silently.
NODE_PREFIX = "apps/agent/e2e/test_agent_e2e.py::"
ARTIFACT_PREFIX = "composed-journey-verdict-"

# What the journey exercises: the agent and its E2E harness, the backend and
# the mono image it runs in, and the suite's own invocation. A change under any
# of these counts as an attempt to fix a failure. apps/frontend is left out on
# purpose: the journey drives the API, and counting every UI commit as a "fix"
# would let a known failure re-run nightly on dev.
SUITE_INPUTS: tuple[str, ...] = (
    ".github/workflows/composed-e2e.yml",
    "Dockerfile.mono",
    "apps/agent",
    "apps/backend",
    "docker",
    "scripts/ci/tier2-agent-journey.sh",
)

_OUTCOMES = ("success", "failure")


@dataclass(frozen=True)
class Verdict:
    """One real run of the journey, keyed by the inputs it ran on."""

    fingerprint: str
    sha: str
    run_url: str
    outcome: str
    failed_tests: tuple[str, ...]

    def to_json(self) -> str:
        """Serialise for the verdict artifact."""
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Verdict:
        """Parse a verdict artifact. Anything malformed raises ValueError: an
        unreadable verdict is a gate that did not evaluate, never a pass."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"verdict is not JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("verdict is not a JSON object")
        try:
            verdict = cls(
                fingerprint=str(data["fingerprint"]),
                sha=str(data["sha"]),
                run_url=str(data["run_url"]),
                outcome=str(data["outcome"]),
                failed_tests=tuple(str(name) for name in data["failed_tests"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"verdict is missing or mistypes a field: {exc}") from exc
        if verdict.outcome not in _OUTCOMES:
            raise ValueError(f"verdict outcome {verdict.outcome!r} is not one of {_OUTCOMES}")
        return verdict


def git_listing(root: Path, rev: str = "HEAD") -> str:
    """Return `git ls-tree -r` of SUITE_INPUTS at `rev`: blob ids and paths, content-addressed."""
    return subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--full-tree", rev, "--", *SUITE_INPUTS],
        capture_output=True, text=True, check=True,
    ).stdout


def fingerprint(listing: str) -> str:
    """Return a short, stable digest of a `git_listing`."""
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()[:16]


def quarantined_tests(register: Path, today: date) -> frozenset[str]:
    """Return the test names that live register rows for CHECK quarantine. A row is live through its expiry day."""
    names: set[str] = set()
    for row in rows_for_check(register, CHECK):
        try:
            expiry = date.fromisoformat(row["expiry"].strip())
        except ValueError as exc:
            raise RegisterError(f"{row['quarantine_id']}: unparseable expiry {row['expiry']!r}") from exc
        if expiry >= today:
            names.update(name.strip() for name in row["scope"].split(",") if name.strip())
    return frozenset(names)


def failed_tests_from_junit(path: Path) -> list[str]:
    """Return the sorted names of test cases with a <failure> or <error>. A missing file means none were recorded."""
    if not path.is_file():
        return []
    failed = {
        case.get("name", "")
        for case in ET.parse(path).getroot().iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    }
    return sorted(name for name in failed if name)


def _base(name: str) -> str:
    return name.split("[", 1)[0]


def decide(previous: Verdict | None, quarantined: frozenset[str]) -> tuple[bool, str]:
    """Return (allowed, reason) for running the journey after `previous` on the same inputs."""
    if previous is None:
        return True, "no earlier verdict for these inputs"
    if previous.outcome == "success":
        return True, f"last run on these inputs passed: {previous.run_url}"
    if not previous.failed_tests:
        return False, (
            f"{previous.run_url} failed with no test-level failure recorded (a crash or timeout); "
            "only a change to the suite's inputs addresses it"
        )
    unaddressed = [name for name in previous.failed_tests if _base(name) not in quarantined]
    if unaddressed:
        return False, (
            f"failures from {previous.run_url} are unaddressed: {', '.join(unaddressed)}; "
            f"fix them (any change under {', '.join(SUITE_INPUTS)}) or quarantine them "
            f"(a register row for {CHECK!r} naming each test)"
        )
    return True, f"all failures from {previous.run_url} are quarantined: {', '.join(previous.failed_tests)}"


def pick_verdict_artifact(listing: Mapping[str, object], repo_id: int) -> dict[str, object] | None:
    """Return the newest unexpired verdict artifact produced by a run of THIS repository, or None."""
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    trusted = [
        artifact for artifact in artifacts
        if isinstance(artifact, dict)
        and not artifact.get("expired")
        and (artifact.get("workflow_run") or {}).get("head_repository_id") == repo_id
    ]
    return max(trusted, key=lambda artifact: str(artifact["created_at"]), default=None)


def deselect_args(quarantined: frozenset[str]) -> list[str]:
    """Return one pytest --deselect argument per quarantined test, sorted."""
    return [f"--deselect={NODE_PREFIX}{name}" for name in sorted(quarantined)]


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _gh_api(path: str) -> bytes:
    return subprocess.run(["gh", "api", path], capture_output=True, check=True).stdout


def _fetch_previous(repo: str, repo_id: int, fp: str) -> Verdict | None:
    listing = json.loads(_gh_api(f"repos/{repo}/actions/artifacts?name={ARTIFACT_PREFIX}{fp}&per_page=100"))
    artifact = pick_verdict_artifact(listing, repo_id)
    if artifact is None:
        return None
    archive = zipfile.ZipFile(io.BytesIO(_gh_api(str(artifact["archive_download_url"]))))
    return Verdict.from_json(archive.read("verdict.json").decode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand and return its exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fingerprint")
    sub.add_parser("check")
    record = sub.add_parser("record")
    record.add_argument("--junit", type=Path, required=True)
    record.add_argument("--out", type=Path, required=True)
    sub.add_parser("deselect")
    args = parser.parse_args(argv)

    if args.command == "fingerprint":
        print(fingerprint(git_listing(REPO_ROOT)))
        return 0
    if args.command == "deselect":
        quarantined = quarantined_tests(REGISTER, _today())
        if quarantined:
            print(f"quarantined, deselected: {', '.join(sorted(quarantined))}", file=sys.stderr)
        for arg in deselect_args(quarantined):
            print(arg)
        return 0
    if args.command == "record":
        verdict = Verdict(
            fingerprint=os.environ["FINGERPRINT"],
            # The checked-out tree, not GITHUB_SHA: on a nightly those differ (D2).
            sha=subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip(),
            run_url=os.environ["RUN_URL"],
            outcome="success" if os.environ["OUTCOME"] == "success" else "failure",
            failed_tests=tuple(failed_tests_from_junit(args.junit)),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(verdict.to_json(), encoding="utf-8")
        print(verdict.to_json())
        return 0
    # check
    fp = fingerprint(git_listing(REPO_ROOT))
    previous = _fetch_previous(os.environ["REPO"], int(os.environ["REPO_ID"]), fp)
    if previous is not None and previous.fingerprint != fp:
        print(f"::error::verdict artifact for {fp} records fingerprint {previous.fingerprint}")
        return 1
    allowed, reason = decide(previous, quarantined_tests(REGISTER, _today()))
    print(f"inputs fingerprint: {fp}")
    if allowed:
        print(f"rerun guard: allowed — {reason}")
        return 0
    print(f"::error::Composed journey NOT RUN — {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

`check` has no try/except around the API, on purpose. If the verdict lookup itself fails, the guard job goes
red with a traceback, and the journey doesn't run. A lookup that could fail open would let a known failure
re-run on nothing more than a GitHub API blip, which is the thing this guard exists to prevent.

- [ ] **Step 4: Deselect quarantined tests in `tier2-agent-journey.sh`**

Insert this after the `cb::require_tool docker …` line:

```bash
# Tests with a live quarantine-register row are deselected, so a quarantined
# failure does not simply fail again on the rerun its row permits
# (composed_rerun_guard.py). An assignment, not a process substitution, so a
# broken register fails this script instead of silently deselecting nothing.
deselect_out="$(python3 "$CB_REPO_ROOT/scripts/ci/composed_rerun_guard.py" deselect)"
deselect=()
if [[ -n $deselect_out ]]; then
  mapfile -t deselect <<<"$deselect_out"
fi
```

Then add `"${deselect[@]}" \` on the line before `"$@" \` in the pytest call.

- [ ] **Step 5: Wire the guard into `composed-e2e.yml`**

Add this job above `composed-journey`:

```yaml
  # ── The rerun guard ────────────────────────────────────────────────────────
  # The journey may not run again on the same inputs while the previous run's
  # failures are unaddressed: neither fixed (which changes the fingerprint)
  # nor quarantined (register rows, which tier2-agent-journey.sh deselects).
  # See scripts/ci/composed_rerun_guard.py. There is no force switch.
  rerun-guard:
    name: Composed agent journey — rerun guard
    if: ${{ !inputs.quarantined }}
    runs-on: ubuntu-22.04
    timeout-minutes: 5
    permissions:
      actions: read      # list and download earlier verdict artifacts
      contents: read
    outputs:
      fingerprint: ${{ steps.fingerprint.outputs.fingerprint }}
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ inputs.ref }}
          persist-credentials: false
      # An assignment on its own line: `echo "x=$(cmd)"` would swallow a failing cmd.
      - id: fingerprint
        shell: bash
        run: |
          fp="$(python3 scripts/ci/composed_rerun_guard.py fingerprint)"
          echo "fingerprint=${fp}" >> "$GITHUB_OUTPUT"
      - name: Refuse to repeat an unaddressed failure
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
          REPO_ID: ${{ github.repository_id }}
        run: python3 scripts/ci/composed_rerun_guard.py check
```

In `composed-journey`:
- Add `needs: rerun-guard`. Keep its `if: ${{ !inputs.quarantined }}`: a job whose `needs` failed is skipped
  anyway, so the explicit `if` is only there for readers.
- Give the `Run the composed journey` step `id: journey` and `timeout-minutes: 65`. A step timeout still
  lets the steps after it run, while the job's own 75-minute timeout would not, and the verdict has to be
  recorded when the journey hangs.
- After `Upload diagnostics`, add:

```yaml
      # The verdict the next run's guard reads. Recorded only when the journey
      # actually ran: an install step failing before it is an infrastructure
      # problem, not a verdict on these inputs.
      - name: Record the verdict for these inputs
        if: ${{ !cancelled() && steps.journey.outcome != 'skipped' }}
        shell: bash
        env:
          FINGERPRINT: ${{ needs.rerun-guard.outputs.fingerprint }}
          OUTCOME: ${{ steps.journey.outcome }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          python3 scripts/ci/composed_rerun_guard.py record \
            --junit apps/agent/e2e/junit-agent-e2e.xml --out verdict/verdict.json

      - name: Upload the verdict
        if: ${{ !cancelled() && steps.journey.outcome != 'skipped' }}
        uses: actions/upload-artifact@v7
        with:
          name: composed-journey-verdict-${{ needs.rerun-guard.outputs.fingerprint }}
          path: verdict/verdict.json
          if-no-files-found: error
          retention-days: 90
```

Add these wiring tests to `test_composed_rerun_guard.py`:

```python
def _composed() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((REPO_ROOT / ".github/workflows/composed-e2e.yml").read_text(encoding="utf-8"))


def test_the_journey_cannot_start_without_the_guard():
    jobs = _composed()["jobs"]
    assert jobs["composed-journey"]["needs"] == "rerun-guard"
    assert jobs["rerun-guard"]["permissions"] == {"actions": "read", "contents": "read"}


def test_the_verdict_is_named_by_the_guards_fingerprint():
    steps = _composed()["jobs"]["composed-journey"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload the verdict")
    assert upload["with"]["name"] == ARTIFACT_PREFIX + "${{ needs.rerun-guard.outputs.fingerprint }}"
    assert "steps.journey.outcome != 'skipped'" in upload["if"]


def test_the_journey_step_times_out_before_the_job_does():
    job = _composed()["jobs"]["composed-journey"]
    step = next(s for s in job["steps"] if s.get("id") == "journey")
    assert step["timeout-minutes"] < job["timeout-minutes"]


def test_the_guard_has_no_force_switch():
    """Maintainer decision 2026-09-27: no override input."""
    triggers = _composed().get("on", _composed().get(True))
    assert set(triggers["workflow_call"]["inputs"]) == {"ref", "quarantined"}
```

- [ ] **Step 6: Run everything that reads these files**

```bash
.venv/bin/pytest tests/build/test_composed_rerun_guard.py tests/build/test_tier2_wiring.py \
  tests/build/test_ci_evidence_retention.py tests/build/test_quarantine_notice.py \
  tests/build/test_scheduled_workflows_pin_their_ref.py tests/build/test_ci_scripts_match_runner_python.py -q
make lint
checkov -f .github/workflows/composed-e2e.yml --framework github_actions
scripts/ci/tier2-agent-journey.sh --collect-only -q | tail -1
```

Expected: all tests pass, lint is clean, and checkov reports 0 failed. The last command prints
`13/16 tests collected (3 deselected)`, which shows QUAR-001's three tests deselected through the real
script. `--collect-only` starts no containers.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/composed_rerun_guard.py tests/build/test_composed_rerun_guard.py \
  scripts/ci/tier2-agent-journey.sh .github/workflows/composed-e2e.yml
git commit -m "feat(ci): never re-run the composed journey on unaddressed failures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Documentation follows the code

**Files:**
- Modify: `docs/design/2026-09-27-tier2-composed-and-triage-design.md`
- Modify: `CLAUDE.md` ("What the gates do NOT cover" table)
- Modify: `.claude/skills/cb-build-test/SKILL.md`

- [ ] **Step 1: Design doc**

- Line 4: `**Status:** Approved in design; slices A1 and A2 implemented`.
- §7.2 first bullet: replace "The file carries `# scheduled-ref: default-branch-intentional`" with "The file
  pins every checkout's ref instead of carrying the `default-branch-intentional` marker, so
  `test_scheduled_workflows_pin_their_ref.py` checks it rather than exempting it (A2 plan, deviation 3)".
- §7.3: replace the P1 drift guard bullet with "`tests/build/test_tier2_wiring.py`: each suite has one
  script under `scripts/ci/`, called by both the workflow and the `make` target, and neither re-inlines it."
- §7.4: after "`tier2.yml` joins the same maps in A2", add "— deferred to B1, since `tier2.yml` executes no
  suite until its triage jobs exist (A2 plan, deviation 4)".
- §3.2 table, `notify.yml` row: append "Landed early, in A2, because A2 moves the watched nightly."
- §3.1, the `release.yml, release-dry-run.yml` row: replace the "Decided 2026-09-27: the release runs the
  whole tier" text with "**Superseded 2026-09-27 by the maintainer:** the release calls `tier2.yml` with
  `["browser"]` only. The composed journey is not a release gate (AGT-01 stands), because making it reliably
  green is a steep hill that should not block releases. Whether A3 adds `"mono"` to the release is decided in
  A3."
- §10, item 2: prefix it with "**Superseded** (see §3.1):".
- Add a §3.4, "The composed journey's rerun guard", with three sentences and a link to
  `scripts/ci/composed_rerun_guard.py`'s docstring: what "addressed" means, that there is no force switch,
  and that register rows now quarantine individual composed tests by deselection.

- [ ] **Step 2: CLAUDE.md**

Add this row to the "What the gates do NOT cover" table, directly under the heading row:

```markdown
| Tier 2 (composed) | browser E2E + composed agent journey, as CI runs them | `make verify-composed` (nightly: `tier2.yml`) |
```

- [ ] **Step 3: cb-build-test skill**

Add one line where the skill lists the `make verify*` targets:
`make verify-composed` — Tier 2: the browser suite and the composed journey through the same
`scripts/ci/tier2-*.sh` scripts CI calls; `CB_COMPOSED_QUARANTINED=0` lifts QUAR-001 locally. In CI, the
composed journey will not re-run on the same inputs after a failure until each failed test is fixed or has a
register row (`scripts/ci/composed_rerun_guard.py`). Local runs are not guarded, since they are how a fix gets
made.

- [ ] **Step 4: Check the docs guards, then commit**

Run: `.venv/bin/pytest tests/build/test_plan_references.py tests/build/test_repo_governance.py -q`
Expected: PASS.

```bash
git add docs/design/2026-09-27-tier2-composed-and-triage-design.md CLAUDE.md .claude/skills/cb-build-test/SKILL.md
git commit -m "docs: record Tier 2 slice A2 and make verify-composed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Prove it before the pull request

CLAUDE.md rule 1 says to name the suite that exercises a change and run it. `make verify` runs no workflow
and no browser. The covering evidence for this slice is:

- the repo-policy suite;
- a real browser run through the new script (Task 1, Step 6);
- a real composed run through the new script;
- a real run of `tier2.yml` via the release dry run;
- the rerun guard both allowing and blocking, on a real runner (Step 6).

**Files:** none. This task produces evidence, not code.

- [ ] **Step 1: The local gates**

Run: `make lint && make verify`
Expected: PASS. No file under `apps/backend/src/app` changed, so `verify-full` is not owed. The PR body
must still say that neither gate executes a workflow.

- [ ] **Step 2: The composed script, unquarantined, on one test**

This proves `e2e-local` → `tier2-agent-journey.sh` runs pytest inside the runner container, without paying
75 minutes for a suite that is known red:

```bash
.venv/bin/pytest apps/agent/e2e/test_agent_e2e.py --collect-only -q | head -20
```

Pick one collected test that is **not** among QUAR-001's three
(`test_agent_zero_configuration_discovery_import_and_replay`,
`test_agent_discovery_capability_disable_cancels_and_late_findings_die`,
`test_agent_discovery_reconnects_per_agent_and_requeues_only_changes`), then:

```bash
make e2e-local E2E_ARGS="-k <that test's name>"
ls -l apps/agent/e2e/junit-agent-e2e.xml diagnostics/composed-journey.log
```

Expected: the test passes, and both files exist (the junit file is new for local runs). Record the headless
box's podman/Ryuk settings from the `headless-box-toolchain` memory if the run needs them.

- [ ] **Step 3: Push, and confirm the remote has it**

```bash
git push -u origin feat/tier2-slice-a2
git ls-remote --heads origin feat/tier2-slice-a2
```

Expected: one line whose SHA equals `git rev-parse HEAD`. Do not dispatch anything until it does (rule 4).

- [ ] **Step 4: Run `tier2.yml` for real, through the release dry run**

`tier2.yml` cannot be dispatched by name before it exists on the default branch. `release-dry-run.yml` does
exist there, and it runs the branch's copy of every file it calls, which is the same `workflow_call` path the
release uses:

```bash
gh workflow run release-dry-run.yml --ref feat/tier2-slice-a2
sleep 15 && gh run list --workflow release-dry-run.yml --limit 1 --json databaseId,headSha,status
```

Then read the jobs from the API, not from a summary view (memory: `gh pr checks` under-reports):

```bash
gh run view <id> --json jobs --jq '.jobs[] | "\(.name): \(.conclusion)"' | grep -E "Tier 2|Dry run"
```

Expected:
- `Tier 2 / Plan: success`;
- both `Tier 2 / Browser E2E / browser-e2e (shard N/2): success`;
- no `Tier 2 / Composed Agent E2E / …` jobs at all, because the release doesn't select composed (maintainer
  decision 1);
- `Tier 2 / Tier 2 result: success`, whose log shows `composed: skipped`, which is expected for an
  unselected suite.

The dry run's own `summary` shows `tier2: success`. The release dry run has never been run before. If an
unrelated leg (image, installer, staged publication) goes red, the Tier 2 jobs above are still the evidence
for this slice, but that red leg is a finding. Record it and raise it with the maintainer. Don't wave it off
as pre-existing without reproducing it on `dev` (rule 2).

- [ ] **Step 5: Force the failure path once**

This proves `Tier 2 result` fails when the plan fails. It needs a caller that passes a bad `suites`, which
only a temporary commit can provide:

```bash
sed -i "s/suites: '\[\"browser\"\]'/suites: '[\"brwoser\"]'/" .github/workflows/release-dry-run.yml
git commit -am "test: force an unknown Tier 2 suite (revert before PR)"
git push && git ls-remote --heads origin feat/tier2-slice-a2
gh workflow run release-dry-run.yml --ref feat/tier2-slice-a2
```

Expected: `Tier 2 / Plan` fails with `::error::Tier 2 plan: unknown suite(s) ['brwoser']`, both suites are
skipped, `Tier 2 result` fails with `plan: failure`, and the dry run's summary is red. Cancel the rest of the
run once `Tier 2 result` has concluded. Then remove the commit:

```bash
git revert --no-edit HEAD && git push
```

(The history then shows the experiment and its revert. That's acceptable on a feature branch, and the PR
diff is clean.)

- [ ] **Step 6: Prove the rerun guard allows, records and blocks on a real runner**

The block path needs a failed verdict. A full unquarantined run takes 75 minutes and, with QUAR-001's three
tests now deselected, may pass. So force a cheap failure on a temporary commit. Both runs below share that
commit, and therefore its fingerprint:

```bash
python3 - <<'EOF'
from pathlib import Path
p = Path(".github/workflows/composed-e2e.yml")
t = p.read_text()
t = t.replace("OUTCOME: ${{ steps.journey.outcome }}", "OUTCOME: failure  # TEMP: rerun-guard proof")
t = t.replace('CB_E2E_SEED: "20260826"',
              'CB_E2E_SEED: "20260826"\n          PYTEST_ADDOPTS: "-k test_agent_uninstall_marks_server_revoked_and_removes_local_files"  # TEMP', 1)
p.write_text(t)
EOF
git commit -am "test: force a failed composed verdict (revert before PR)"
git push && git ls-remote --heads origin feat/tier2-slice-a2
gh workflow run e2e.yml --ref feat/tier2-slice-a2 -f quarantined=false
```

Expected for run A:
- `rerun guard` succeeds with `allowed — no earlier verdict for these inputs`;
- the journey runs the one selected test;
- `Record the verdict` writes `"outcome": "failure"`, with `"failed_tests": []`. If that test genuinely
  failed, the list names it instead. Either way run B must block, with the matching message from Task 6's
  table;
- an artifact `composed-journey-verdict-<fp>` exists.

When run A has finished, dispatch the same command again (run B). Expected: `rerun guard` **fails** within
about a minute with `::error::Composed journey NOT RUN — <run A url> failed with no test-level failure
recorded …`, and `Composed agent journey` is reported skipped.

Then remove the temporary commit with `git revert --no-edit HEAD && git push`. The reverted tree has a
different fingerprint, so the forced verdict never matches real inputs.

Optional, and worth the 75 minutes before QUAR-001 is lifted: dispatch once more with `-f quarantined=false`
on the reverted head. That shows whether the 13 unquarantined tests pass, and it records the first real
verdict.

- [ ] **Step 7: Open the pull request into `dev`**

The body must state:
- **the two maintainer decisions, verbatim from this plan, at the top**, including the per-test quarantine
  flag;
- which suites ran, with the run IDs from Steps 4, 5 and 6;
- that the scheduled and `workflow_dispatch` paths of `tier2.yml` **cannot run until the file is on `main`**,
  so they are unproven by this PR;
- the post-promotion check below.

End the body with the attribution line and no session link.

- [ ] **Step 8: After the next `dev` → `main` promotion (not part of this PR's merge)**

```bash
gh workflow run tier2.yml --ref dev
```

Expected: `Plan` reports `ref=` (a dispatch on `dev` tests `dev`), both suites run, and `Tier 2 result`
passes. The next morning, confirm the 03:00 UTC run exists, its `Plan` log shows `ref=dev`, and `e2e.yml` had
no scheduled run that night.

---

## Self-Review

**Spec coverage (§9 A2 row, §3.1, §7.3, §7.4):**
- `tier2.yml` aggregator: Task 4. The suites input and `contains(fromJSON(...))` gating use the plan output,
  with the reason given in Task 3.
- Concurrency group: Task 4.
- `make verify-composed` with `CI=1`: Task 2, plus Task 1 (deviation 2).
- Drift guard: Tasks 1 and 2 (deviation 1).
- Release and dry run call it with `["browser"]` (maintainer decision 1): Task 5.
- Nightly moves from `e2e.yml`: Task 4, Step 5.
- `suites` values are real: Task 5 test.
- Scheduled-ref: Task 4, pinned rather than marked (deviation 3).
- Evidence-retention maps: deviation 4.
- `notify.yml`: Task 4 (deviation 5).
- Check-name nesting: Task 5 comment.
- Maintainer decision 1 (no release gating on composed): Task 5, with its test.
- Maintainer decision 2 (no rerun without the failures addressed): Task 6. It is proven on a runner in
  Task 8, Step 6.
- Out of scope, confirmed untouched: `required_checks.py`, #162, mono smoke (A3), triage (B1+), the
  `triage` input (arrives with B1's jobs, because gating on an input nothing reads is dead code today).

**Placeholder scan:** Task 8, Step 2 asks the executor to pick a test name from `--collect-only` output.
That's deliberate, because the collected names are the source of truth and the command to get them is given.
There are no TBDs.

**Type consistency:** `KNOWN_SUITES`, `DEFAULT_SUITES`, `parse_suites`, `resolve_ref`, `judge` and `main`
have the same names and signatures in Tasks 3, 4 and 5. The job ids `plan`, `browser`, `composed` and
`result` match between `tier2.yml`, `judge()` and the wiring tests. Env names `SUITES`, `REF`, `EVENT_NAME`
and `RESULTS` match between the YAML and `_plan`/`_result`.

**Review Focus:** all seven lines map to a named test, in Tasks 2, 3, 4 and 6.
