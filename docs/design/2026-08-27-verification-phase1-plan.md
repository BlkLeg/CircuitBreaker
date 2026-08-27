# Verification Phase 1 — T0/T1 Extraction and the Pre-Push Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `make verify` a complete, offline, trustworthy pre-push gate whose every check has exactly one definition that GitHub Actions also calls.

**Architecture:** Each CI gate body moves out of workflow YAML into `scripts/ci/`, backed by a small shared bash library that makes "tool missing" a failure rather than a silent pass. The workflows become thin callers, so a gate cannot drift between local and CI without the diff showing it. `.husky/pre-push` — which already exists and runs `make lint` — is upgraded to run the full gate.

**Tech Stack:** bash (POSIX-ish, `set -euo pipefail`), GNU make, pytest (repo-policy tests in `tests/build/`), husky, ruff, mypy, ESLint, vitest, `scripts/security_scan.sh`.

**Spec:** `docs/design/2026-08-27-verification-strategy-design.md` (ADR: `docs/adr/0005-verification-tiers-and-platform-support.md`)

## Global Constraints

- **T1 wall-clock budget: 4 minutes.** Hard constraint (§4). If exceeded, T1 contents are reduced — the budget is not relaxed.
- **P1 — one definition per gate.** A gate body may not live in workflow YAML. `scripts/security_scan.sh` is the existing precedent to follow.
- **P2 / R4 — fail closed.** A missing tool is a failed gate (exit 127). An informational step that did not run prints `SKIPPED (<reason>)`; it may never be silent.
- **No `|| true` on a gate line.** Informational steps must use `cb::skipped`.
- **R5 — every custom pytest mark must be registered in the config that governs it.** Root `pytest.ini` carries `filterwarnings = error`, so an unregistered mark is a collection failure.
- **Evidence layout:** `artifacts/<tier>/{junit,logs}/`. Already used by dev-ci.yml; keep it.
- Backend commands run through `.venv/bin/*` from the repo root, as the Makefile and workflows already do.
- Shell scripts live at `scripts/ci/`, are `chmod +x`, and start with `#!/usr/bin/env bash` + `set -euo pipefail`.

---

### Task 1: Shared CI shell library

**Files:**
- Create: `scripts/ci/lib/common.sh`
- Test: `tests/build/test_ci_script_contract.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `cb::section <title>`, `cb::require_tool <tool> [hint]` (exit 127 when absent), `cb::require_file <path> [hint]`, `cb::skipped <what> <reason>`, `cb::evidence_dir <tier>` (echoes an existing dir), and `$CB_REPO_ROOT`.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_ci_script_contract.py
"""Phase 1 of ADR 0005: the contract every scripts/ci gate script must satisfy.

These are the rules that make `make verify` trustworthy. A gate that can pass
because a tool is missing is not a gate (design P2/R4), and a gate body that
lives in workflow YAML can only ever run in CI (P1).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "scripts" / "ci"
COMMON = CI_DIR / "lib" / "common.sh"


def _bash(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", snippet], capture_output=True, text=True, cwd=REPO_ROOT
    )


def test_common_lib_exists():
    assert COMMON.is_file(), f"{COMMON} is missing"


def test_require_tool_fails_closed_on_a_missing_tool():
    """P2: 'the scanner was not installed' must never be spelled the same as
    'the scanner found nothing'."""
    result = _bash(
        f'source "{COMMON}"; cb::require_tool definitely-not-a-real-tool-xyz; echo REACHED'
    )
    assert result.returncode == 127, result.stderr
    assert "REACHED" not in result.stdout
    assert "definitely-not-a-real-tool-xyz" in result.stderr


def test_require_tool_passes_for_a_present_tool():
    result = _bash(f'source "{COMMON}"; cb::require_tool bash; echo REACHED')
    assert result.returncode == 0, result.stderr
    assert "REACHED" in result.stdout


def test_skipped_marker_is_unmistakable():
    """R4: an informational step that did not run says so."""
    result = _bash(f'source "{COMMON}"; cb::skipped ESLint "no node_modules"')
    assert result.returncode == 0, result.stderr
    assert "SKIPPED" in result.stdout
    assert "no node_modules" in result.stdout


def test_repo_root_resolves_to_this_repo():
    result = _bash(f'source "{COMMON}"; printf "%s" "$CB_REPO_ROOT"')
    assert Path(result.stdout).resolve() == REPO_ROOT
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: FAIL — `test_common_lib_exists` asserts on a missing file, and the `_bash` tests fail with `source: no such file`.

- [ ] **Step 3: Write the library**

```bash
# scripts/ci/lib/common.sh
# Shared helpers for the scripts/ci gate scripts (ADR 0005, Phase 1).
#
# Sourced, never executed. The rules encoded here are the ones that make
# `make verify` worth trusting:
#
#   * cb::require_tool exits 127 rather than letting a gate pass because the
#     tool that implements it was not installed. security_scan.sh already
#     applies this to Gitleaks — "a gate that 'passes' because the scanner is
#     absent is not a gate" — and issue #106 is what it looks like when a
#     section does not.
#   * cb::skipped is the ONLY sanctioned way to record that an informational
#     step did not run. `|| true` is not, because it spells "did not run" and
#     "found nothing" identically.

# shellcheck shell=bash

CB_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export CB_REPO_ROOT
CB_EVIDENCE_ROOT="${CB_EVIDENCE_ROOT:-$CB_REPO_ROOT/artifacts}"
export CB_EVIDENCE_ROOT

cb::section() {
    printf '\n\033[1m▸ %s\033[0m\n' "$1"
}

cb::require_tool() {
    local tool=$1 hint=${2:-}
    if command -v "$tool" >/dev/null 2>&1; then
        return 0
    fi
    printf '::error::required tool not found: %s%s\n' \
        "$tool" "${hint:+ — $hint}" >&2
    exit 127
}

cb::require_file() {
    local path=$1 hint=${2:-}
    if [ -e "$path" ]; then
        return 0
    fi
    printf '::error::required path not found: %s%s\n' \
        "$path" "${hint:+ — $hint}" >&2
    exit 127
}

cb::skipped() {
    printf 'SKIPPED (%s): %s\n' "$2" "$1"
}

cb::evidence_dir() {
    local dir="$CB_EVIDENCE_ROOT/$1"
    mkdir -p "$dir/junit" "$dir/logs"
    printf '%s' "$dir"
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/lib/common.sh tests/build/test_ci_script_contract.py
git commit -m "feat(ci): shared gate library that fails closed on a missing tool

ADR 0005 Phase 1. cb::require_tool exits 127 rather than letting a gate pass
because the tool implementing it was absent, and cb::skipped is the only
sanctioned way to record an informational step that did not run — '|| true'
spells that identically to 'found nothing', which is issue #106."
```

---

### Task 2: Tier 0 — static gate script

**Files:**
- Create: `scripts/ci/tier0-static.sh`
- Modify: `.github/workflows/dev-ci.yml` (the `lint` job, lines 42–96 — replace the six inline gate steps with one call)
- Test: `tests/build/test_ci_script_contract.py` (extend)

**Interfaces:**
- Consumes: `cb::section`, `cb::require_tool`, `cb::evidence_dir`, `$CB_REPO_ROOT` from Task 1.
- Produces: `scripts/ci/tier0-static.sh`, exit 0 on success, evidence in `artifacts/tier0/`.

- [ ] **Step 1: Write the failing test**

Append to `tests/build/test_ci_script_contract.py`:

```python
TIER_SCRIPTS = ["tier0-static.sh"]


def test_tier_scripts_exist_and_are_executable():
    for name in TIER_SCRIPTS:
        script = CI_DIR / name
        assert script.is_file(), f"{script} is missing"
        assert script.stat().st_mode & 0o111, f"{script} is not executable"


def test_tier_scripts_use_strict_bash():
    for name in TIER_SCRIPTS:
        text = (CI_DIR / name).read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env bash\n"), name
        assert "set -euo pipefail" in text, name


def test_tier_scripts_do_not_swallow_gate_failures():
    """No `|| true` on a gate. cb::skipped exists for the informational case."""
    for name in TIER_SCRIPTS:
        for lineno, line in enumerate(
            (CI_DIR / name).read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "|| true" not in stripped, f"{name}:{lineno}: {stripped}"


def test_workflow_calls_the_tier0_script_rather_than_inlining_it():
    """P1: a gate defined in YAML can only ever run in CI."""
    workflow = (REPO_ROOT / ".github/workflows/dev-ci.yml").read_text(encoding="utf-8")
    assert "scripts/ci/tier0-static.sh" in workflow
    assert "ruff check src/app" not in workflow, (
        "ruff is a tier-0 gate; its command belongs in tier0-static.sh, not in the workflow"
    )
    assert "mypy src/app" not in workflow, (
        "mypy is a tier-0 gate; its command belongs in tier0-static.sh, not in the workflow"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: FAIL — `tier0-static.sh is missing`, and the workflow assertions fail because the commands are still inline.

- [ ] **Step 3: Write the script**

```bash
#!/usr/bin/env bash
# Tier 0 — static gates. Pure analysis of the checked-out tree: no database, no
# services, no network. Everything here was previously inline in dev-ci.yml's
# `lint` job, which meant it could only ever run in CI (ADR 0005, P1).
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

EVIDENCE="$(cb::evidence_dir tier0)"

cb::require_tool python3
cb::require_file .venv/bin/ruff "run 'make install' to build the dev virtualenv"
cb::require_file .venv/bin/mypy "run 'make install' to build the dev virtualenv"
cb::require_file .venv/bin/pytest "run 'make install' to build the dev virtualenv"

cb::section "Alembic revision graph (single head)"
( cd apps/backend && PYTHONPATH=src "$CB_REPO_ROOT/.venv/bin/python" -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
heads = ScriptDirectory.from_config(cfg).get_heads()
assert len(heads) == 1, f'expected 1 Alembic head, got: {heads!r}'
print('Alembic head:', heads[0])
" )

cb::section "Repo policy tests (tests/build)"
.venv/bin/pytest tests/build \
    --junitxml="$EVIDENCE/junit/repo-policy.xml" \
    2>&1 | tee "$EVIDENCE/logs/repo-policy.log"

cb::section "Ruff"
( cd apps/backend && "$CB_REPO_ROOT/.venv/bin/ruff" check src/app )

cb::section "Mypy"
( cd apps/backend && PYTHONPATH=src "$CB_REPO_ROOT/.venv/bin/mypy" src/app )

cb::section "1.0.0 release-control ledger"
python3 scripts/validate_v1_release_control.py

cb::section "ESLint"
# Fail closed rather than informational: unlike the security gate's copy of this
# step (issue #106), ESLint IS a tier-0 gate here, so a missing node_modules is
# a setup error the developer must fix, not a result.
cb::require_file apps/frontend/node_modules \
    "run 'cd apps/frontend && npm ci' first"
( cd apps/frontend && npm run lint )

cb::section "Tier 0 complete"
```

Then `chmod +x scripts/ci/tier0-static.sh`.

- [ ] **Step 4: Replace the inline steps in the workflow**

In `.github/workflows/dev-ci.yml`, delete the `Alembic revision graph (single head)`, `Repo policy tests (tests/build)`, `Ruff check`, `Mypy`, `Validate 1.0.0 release-control ledger` and `ESLint` steps, keeping their explanatory comments by moving them into the script where they belong. Leave `Install Python deps` and `Install frontend deps` in place — they are setup, not gates. In their place:

```yaml
      - name: Tier 0 — static gates
        env:
          CB_DB_URL: postgresql://cb_ci:cb_ci@127.0.0.1:5432/cb_ci
        run: scripts/ci/tier0-static.sh
```

- [ ] **Step 5: Run the script and the tests**

Run: `scripts/ci/tier0-static.sh && .venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: the script exits 0 and prints six `▸` sections; the contract tests PASS.

- [ ] **Step 6: Verify the workflow still parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/dev-ci.yml')); print('dev-ci.yml parses')"`
Expected: `dev-ci.yml parses`

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/tier0-static.sh .github/workflows/dev-ci.yml tests/build/test_ci_script_contract.py
git commit -m "refactor(ci): tier 0 gates move out of workflow YAML

ADR 0005 Phase 1, P1. Ruff, mypy, the Alembic head check, the repo-policy
suite, the release-control ledger and ESLint were defined in dev-ci.yml, so
they could only ever run in CI and a local equivalent was a reimplementation
rather than the same gate. A policy test now fails if any of them drifts back
into the workflow."
```

---

### Task 3: Close #106 — the security gate's ESLint section

**Files:**
- Modify: `scripts/security_scan.sh:170-175`
- Test: `tests/build/test_security_scan_contract.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this script predates the library and keeps its own conventions).
- Produces: no new interface; `security_scan.sh` gains a `SKIPPED (...)` marker in section 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_security_scan_contract.py
"""Issue #106: a scanner that did not run must not read as a scanner that
found nothing.

security_scan.sh already gets this right for Gitleaks — absent binary, gate
failure, explicit message. Section 4 (ESLint) is informational by design, which
is fine; what is not fine is that a missing binary produced a raw
`sh: 1: eslint: not found` inside the report with no marker distinguishing it
from a clean run.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "security_scan.sh"


def test_eslint_section_marks_a_missing_binary_as_skipped():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("## 4. ESLint")
    end = text.index("## 5. Hadolint")
    section = text[start:end]
    assert "ESLint skipped" in section, (
        "the ESLint section must emit an explicit skipped marker when the "
        "binary is absent (issue #106)"
    )


def test_every_informational_section_can_say_it_did_not_run():
    """Hadolint already does this; ESLint must too. Guards the class."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Hadolint skipped" in text
    assert "ESLint skipped" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_security_scan_contract.py -v`
Expected: FAIL — `test_eslint_section_marks_a_missing_binary_as_skipped`, because the section is a bare `|| true`.

- [ ] **Step 3: Fix the section**

Replace `scripts/security_scan.sh` lines 170–175 with:

```bash
# ── 4. ESLint + security (Frontend) — informational only ────────────────────
echo "## 4. ESLint + security (Frontend)" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"
echo "Running ESLint (includes eslint-plugin-security)..."
# Informational, not a gate — the Lint job runs ESLint as a real gate. But an
# informational section still has to distinguish "ran and was clean" from "never
# ran", which this one did not: CI installs no frontend dependencies for the
# Security Gate job, so every run recorded a bare `sh: 1: eslint: not found`
# that read exactly like a clean scan (#106). Follows the Hadolint section's
# shape below rather than inventing a second convention.
if [ -x "$REPO_ROOT/apps/frontend/node_modules/.bin/eslint" ]; then
    (cd apps/frontend && npm run lint) >> "$REPO_ROOT/$REPORT_FILE" 2>&1 || true
else
    echo "ESLint skipped (frontend dependencies not installed; run 'npm ci' in apps/frontend)." >> "$REPORT_FILE"
fi
echo "\`\`\`" >> "$REPORT_FILE"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/build/test_security_scan_contract.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Verify the real script still runs**

Run: `./scripts/security_scan.sh --gate; echo "exit=$?"`
Expected: the report's section 4 now contains either real ESLint output or the `ESLint skipped (...)` line — never a bare `eslint: not found`. Confirm with:
`sed -n '/## 4. ESLint/,/## 5. Hadolint/p' security_scan_report.md`

- [ ] **Step 6: Commit**

```bash
git add scripts/security_scan.sh tests/build/test_security_scan_contract.py
git commit -m "fix(security): the gate reported a missing eslint as a clean scan

Closes #106. The Security Gate job installs no frontend dependencies, so every
run wrote a bare 'sh: 1: eslint: not found' into section 4 and the '|| true'
made it indistinguishable from a section that ran and found nothing. The
section stays informational — the Lint job gates ESLint properly — but now
follows the Hadolint section's convention and says when it did not run."
```

---

### Task 4: Tier 1 — unit and integration gate script

**Files:**
- Create: `scripts/ci/tier1-unit.sh`
- Test: `tests/build/test_ci_script_contract.py` (extend `TIER_SCRIPTS`)

**Interfaces:**
- Consumes: Task 1's library; Task 3's fixed `security_scan.sh`.
- Produces: `scripts/ci/tier1-unit.sh`; honours `CB_VERIFY_BACKEND=shards|off` (default `shards`).

**Why the backend suite is sharded rather than run under `-n auto`:** `apps/backend/tests/conftest.py` starts its TimescaleDB testcontainer in `pytest_configure`, which runs once per process. Under xdist that is one container per worker — twelve on this laptop. The suite already has a deterministic path-hash sharder (`tests/build/backend_shard.py`, REL-20) that CI uses; running those same four shards as four concurrent processes gives full coverage, four containers, and the identical partition CI reports against.

- [ ] **Step 1: Extend the contract test**

In `tests/build/test_ci_script_contract.py`, change:

```python
TIER_SCRIPTS = ["tier0-static.sh"]
```

to:

```python
TIER_SCRIPTS = ["tier0-static.sh", "tier1-unit.sh"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: FAIL — `tier1-unit.sh is missing`.

- [ ] **Step 3: Write the script**

```bash
#!/usr/bin/env bash
# Tier 1 — unit and integration gates. Everything a developer must pass before
# pushing (ADR 0005 §4). Budget: 4 minutes wall clock. That budget is a hard
# constraint: a gate slower than the developer's patience gets bypassed, and a
# bypassed gate is worse than none because branch protection still reports it
# satisfied.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$CB_REPO_ROOT"

EVIDENCE="$(cb::evidence_dir tier1)"
CB_VERIFY_BACKEND="${CB_VERIFY_BACKEND:-shards}"

cb::require_tool docker "the backend suite and the security gate both need it"
cb::require_tool npm
cb::require_file .venv/bin/pytest "run 'make install' to build the dev virtualenv"
cb::require_file apps/frontend/node_modules "run 'cd apps/frontend && npm ci' first"

cb::section "Frontend unit tests"
( cd apps/frontend && npm test ) 2>&1 | tee "$EVIDENCE/logs/frontend.log"

cb::section "Backend suite (mode: $CB_VERIFY_BACKEND)"
if [ "$CB_VERIFY_BACKEND" = "off" ]; then
    # Explicit, never silent: the operator asked for this, and the run has to
    # say so rather than reporting a pass that covered less than it looks like.
    cb::skipped "backend suite" "CB_VERIFY_BACKEND=off"
else
    # The four shards CI runs, run concurrently. Same sharder, same partition,
    # so "shard 3 failed" means the same set of tests here as in CI.
    pids=()
    for shard in 1 2 3 4; do
        (
            cd apps/backend
            SHARD="$shard" PYTHONPATH=src \
                "$CB_REPO_ROOT/.venv/bin/pytest" tests \
                -p no:cacheprovider \
                --junitxml="$EVIDENCE/junit/backend-$shard.xml" \
                > "$EVIDENCE/logs/backend-$shard.log" 2>&1
        ) &
        pids+=("$!")
    done
    failed=0
    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            failed=1
            printf '::error::backend shard %s failed — see %s\n' \
                "$((i + 1))" "$EVIDENCE/logs/backend-$((i + 1)).log" >&2
        fi
    done
    [ "$failed" -eq 0 ] || exit 1
fi

cb::section "Security gate"
./scripts/security_scan.sh --gate

cb::section "Tier 1 complete"
```

Then `chmod +x scripts/ci/tier1-unit.sh`.

- [ ] **Step 4: Run the contract tests**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Run the script end to end and record the wall clock**

Run: `time scripts/ci/tier1-unit.sh`
Expected: exit 0. **Write the measured duration down — Task 5 Step 4 needs it.**

If it exceeds the 4-minute budget, do not relax the budget. Re-run with `CB_VERIFY_BACKEND=off scripts/ci/tier1-unit.sh` and time that too; Task 5 Step 4 decides between them on the evidence.

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/tier1-unit.sh tests/build/test_ci_script_contract.py
git commit -m "feat(ci): tier 1 gate script — frontend, backend shards, security

ADR 0005 Phase 1. The backend suite runs CI's four deterministic shards as four
concurrent processes rather than under xdist's -n auto: conftest starts its
TimescaleDB container in pytest_configure, which is once per process, so -n auto
would start one container per worker. Same sharder as CI, so a failing shard
names the same set of tests in both places."
```

---

### Task 5: Make targets, and tune T1 to its budget

**Files:**
- Modify: `Makefile` (add targets after the existing `lint` target, around line 230)
- Modify: `docs/design/2026-08-27-verification-strategy-design.md` (record the measured duration in §12)

**Interfaces:**
- Consumes: `scripts/ci/tier0-static.sh`, `scripts/ci/tier1-unit.sh`.
- Produces: `make verify-fast`, `make verify`.

- [ ] **Step 1: Add the targets**

```makefile
# ADR 0005: the verification ladder. Each target is a thin caller of the script
# GitHub Actions also calls, so "it passed locally" means the same gate ran —
# not a local reimplementation of it.
verify-fast: ## Tier 0 only — static gates (~90s)
	scripts/ci/tier0-static.sh

verify: verify-fast ## Tier 0 + Tier 1 — the pre-push gate (budget: 4 min)
	scripts/ci/tier1-unit.sh
```

- [ ] **Step 2: Run both targets**

Run: `make verify-fast`
Expected: exit 0.

Run: `time make verify`
Expected: exit 0.

- [ ] **Step 3: Confirm make surfaces a failure**

Run: `CB_VERIFY_BACKEND=nonsense make verify; echo "exit=$?"`

This exercises the default branch (any value other than `off` runs the shards), so it should still pass. Then confirm real failure propagation by temporarily breaking a lint rule:

```bash
printf '\nimport os\n' >> apps/backend/src/app/main.py
make verify-fast; echo "exit=$?"   # expect non-zero: ruff F401 unused import
git checkout apps/backend/src/app/main.py
```

Expected: non-zero exit, and the failure is visibly attributed to the Ruff section.

- [ ] **Step 4: Decide T1's contents against the measurement**

Using the durations from Task 4 Step 5:

- **If `make verify` ≤ 4 min:** keep the default (`CB_VERIFY_BACKEND=shards`). No change.
- **If it exceeds 4 min:** change the `verify` target to `CB_VERIFY_BACKEND=off scripts/ci/tier1-unit.sh`, add a `verify-full` target that runs it with the shards on, and record in the design's §4 table that T1's backend component moved to T2 for budget reasons. The gate still covers lint, typecheck, repo policy, the release ledger, ESLint, frontend units and the full security gate — and it stays honest, because `cb::skipped` prints the omission on every run.

```makefile
# Only if the measurement demanded it:
verify-full: verify-fast ## Tier 0 + full Tier 1 including the backend suite
	CB_VERIFY_BACKEND=shards scripts/ci/tier1-unit.sh
```

- [ ] **Step 5: Record the measured number in the design**

In `docs/design/2026-08-27-verification-strategy-design.md` §12, replace the
`make verify` p95 duration row's `n/a` with the measured figure and the date, so
the budget is tracked against evidence rather than intention.

- [ ] **Step 6: Commit**

```bash
git add Makefile docs/design/2026-08-27-verification-strategy-design.md
git commit -m "feat(ci): make verify-fast and make verify

ADR 0005 Phase 1. Both are thin callers of the scripts GitHub Actions calls, so
a local pass and a CI pass are the same gate rather than two implementations of
one description. The measured wall clock is recorded in the design's success
criteria so the four-minute budget is tracked against evidence."
```

---

### Task 6: Wire the pre-push gate and enforce the rules that keep it honest

**Files:**
- Modify: `.husky/pre-push`
- Create: `tests/build/test_pytest_marker_registration.py`
- Test: `tests/build/test_ci_script_contract.py` (extend)

**Interfaces:**
- Consumes: `make verify` from Task 5.
- Produces: no new interface; two policy tests that fail when the rules regress.

- [ ] **Step 1: Write the failing marker-registration test**

```python
# tests/build/test_pytest_marker_registration.py
"""R5: every custom pytest mark must be registered in the config that governs it.

The repo-root pytest.ini carries `filterwarnings = error`, so an unregistered
mark is not a warning — it is a collection failure. On 2026-08-27 that took the
composed agent journey from twelve tests to zero, and it was invisible because
e2e.yml runs against main while the filterwarnings block lives on dev.

Registration is checked rather than the warning being suppressed, per that
file's own rule: fix ours instead.
"""

from __future__ import annotations

import configparser
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Marks provided by pytest itself or by a plugin the suites depend on.
_BUILTIN = {
    "parametrize", "skip", "skipif", "xfail", "usefixtures", "filterwarnings",
    "timeout",  # pytest-timeout
    "asyncio",  # pytest-asyncio
}

_MARK_RE = re.compile(r"@pytest\.mark\.([a-zA-Z_][a-zA-Z0-9_]*)")


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO_ROOT / p for p in out]


def _registered_in_root_ini() -> set[str]:
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    raw = parser.get("pytest", "markers", fallback="")
    return {line.split(":")[0].strip() for line in raw.splitlines() if line.strip()}


def _registered_in_backend() -> set[str]:
    data = tomllib.loads(
        (REPO_ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    entries = data["tool"]["pytest"]["ini_options"].get("markers", [])
    return {entry.split(":")[0].strip() for entry in entries}


def test_every_custom_mark_is_registered_by_its_governing_config():
    root_registered = _registered_in_root_ini()
    backend_registered = _registered_in_backend()

    unregistered: list[str] = []
    for path in _tracked_python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        # apps/backend runs from its own directory under its own config; every
        # other suite is collected under the repo-root pytest.ini.
        governing = (
            backend_registered
            if rel.startswith("apps/backend/")
            else root_registered
        )
        for mark in _MARK_RE.findall(path.read_text(encoding="utf-8")):
            if mark in _BUILTIN or mark in governing:
                continue
            unregistered.append(f"{rel}: @pytest.mark.{mark}")

    assert not unregistered, (
        "unregistered pytest marks — `filterwarnings = error` turns these into "
        "collection failures:\n  " + "\n  ".join(sorted(set(unregistered)))
    )


def test_e2e_mark_means_the_same_thing_in_both_configs():
    """One mark, one meaning, whichever config is in force."""
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    root_raw = parser.get("pytest", "markers")
    root_e2e = next(l.strip() for l in root_raw.splitlines() if l.strip().startswith("e2e:"))

    data = tomllib.loads(
        (REPO_ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    backend_e2e = next(
        e for e in data["tool"]["pytest"]["ini_options"]["markers"]
        if e.startswith("e2e:")
    )
    assert root_e2e == backend_e2e, (
        f"root pytest.ini says {root_e2e!r}, backend says {backend_e2e!r}"
    )
```

- [ ] **Step 2: Run it to verify it passes already**

Run: `.venv/bin/pytest tests/build/test_pytest_marker_registration.py -v`
Expected: PASS — commit `05350354` already registered `e2e`. This test is the regression lock, so confirm it genuinely bites:

```bash
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("pytest.ini"); s = p.read_text()
p.write_text(s.replace("    e2e: requires Docker; not run by default\n", ""))
PY
.venv/bin/pytest tests/build/test_pytest_marker_registration.py -v   # expect FAIL
git checkout pytest.ini
.venv/bin/pytest tests/build/test_pytest_marker_registration.py -v   # expect PASS
```

- [ ] **Step 3: Extend the CI contract test for the husky hook**

Append to `tests/build/test_ci_script_contract.py`:

```python
def test_pre_push_hook_runs_the_full_gate():
    """The hook existed and ran `make lint` — a fraction of the gate. ADR 0005
    makes the pre-push slot the T0+T1 gate."""
    hook = (REPO_ROOT / ".husky" / "pre-push").read_text(encoding="utf-8")
    assert "make verify" in hook, hook
```

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/bin/pytest tests/build/test_ci_script_contract.py::test_pre_push_hook_runs_the_full_gate -v`
Expected: FAIL — the hook still says `make lint`.

- [ ] **Step 5: Update the hook**

```bash
# .husky/pre-push
make verify
```

- [ ] **Step 6: Run the full repo-policy suite**

Run: `.venv/bin/pytest tests/build -q`
Expected: PASS — all pre-existing tests plus the new contract, security-scan and marker tests.

- [ ] **Step 7: Prove the hook actually gates**

```bash
git commit --allow-empty -m "chore: verify pre-push gate fires"
git push --dry-run origin dev
```

Expected: `make verify` runs to completion before the push is attempted. If the gate is slow enough to be annoying, that is the Task 5 Step 4 decision resurfacing — revisit it rather than adding `--no-verify` to your muscle memory.

- [ ] **Step 8: Commit**

```bash
git add .husky/pre-push tests/build/test_pytest_marker_registration.py tests/build/test_ci_script_contract.py
git commit -m "feat(ci): pre-push runs the full gate, and two rules that keep it honest

ADR 0005 Phase 1. .husky/pre-push ran 'make lint' — one gate of seven. It now
runs 'make verify'.

The marker test is the regression lock for the defect that started this: an
unregistered @pytest.mark.e2e under 'filterwarnings = error' took the composed
agent journey from twelve tests to zero, and it was invisible because e2e.yml
runs against main while the filterwarnings block lives on dev. It checks every
custom mark against whichever config governs its file, and that 'e2e' is worded
identically in both — one mark, one meaning."
```

---

## Self-Review

**Spec coverage.** Phase 1 in §11 is "Extract T0/T1 and wire the pre-push gate": Tasks 2, 4, 5, 6 cover it. P1 is enforced by a test (Task 2 Step 1). P2/R4 are Tasks 1 and 3. R5 is Task 6. The design's §12 measurement row is filled by Task 5 Step 5.

Deliberately **not** in Phase 1, and not gaps: R1–R3 (harness hardening) are Phase 4; T2 and T3 scripts are Phases 2–4; §9's SHA-pinning and §10's merge queue are Phase 5. `make test-backend` targets `tests/integration` while CI's backend job targets `apps/backend/tests` — a real parity discrepancy, but it belongs with the T2 extraction in Phase 4, so it is recorded here rather than fixed.

**Placeholders.** None: every step carries the command or the code. Task 5 Step 4's branch is a decision on a measured number with both outcomes fully specified, not deferred work.

**Type consistency.** `cb::require_tool`, `cb::require_file`, `cb::skipped`, `cb::section`, `cb::evidence_dir` and `$CB_REPO_ROOT` are defined in Task 1 and used with those exact names and argument orders in Tasks 2 and 4. `TIER_SCRIPTS` is introduced in Task 2 and extended in Task 4. `CB_VERIFY_BACKEND` is defined in Task 4 and consumed in Task 5.
