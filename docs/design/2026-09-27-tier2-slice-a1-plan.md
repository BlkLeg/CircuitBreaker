# Tier 2 Slice A1 — Extract the Composed Journey — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the composed agent journey into a reusable `composed-e2e.yml` that Tier 2 can call, and
replace QUAR-001's invisible `if: false` with a skip that names its register row.

**Architecture:** `composed-e2e.yml` becomes the single definition of the suite, taking a `ref` input
(so a nightly can test `dev` while the workflow file comes from `main`) and a `quarantined` input that
defaults to **true**. When quarantined, a second job runs `scripts/ci/quarantine_notice.py`, which reads
the register and fails if no row justifies the skip. `e2e.yml` keeps its own triggers and becomes a thin
caller. Nothing about when the suite runs changes in this slice.

**Tech Stack:** GitHub Actions reusable workflows (`workflow_call`), Python 3.12 stdlib, pytest.

**Spec:** [`docs/design/2026-09-27-tier2-composed-and-triage-design.md`](./2026-09-27-tier2-composed-and-triage-design.md)
— slice A1 of §9. Read §3.1, §4's granularity note and §7.4 before starting.

## Global Constraints

- **Python**: snake_case, full type annotations (mypy runs with `disallow_untyped_defs`), docstrings on
  every public function. Stdlib only in `scripts/ci/`.
- **New `scripts/ci/*.py` must be named in `make lint`'s ruff and mypy lines** (`Makefile:325-326`) or it
  is linted by nobody.
- **Workflows**: top-level `permissions:` no wider than `contents: read`; every `${{ }}` through `env:`
  and quoted; actions pinned by tag (`actions/checkout@v5`, `actions/upload-artifact@v7`);
  `# checkov:skip=CKV_GHA_7` with a reason on every `workflow_dispatch` input.
- **No `|| true` on a gate.** "Did not run" and "found nothing" must never be spelled the same way.
- **Commits**: `feat:` / `fix:` / `chore:` / `docs:`. End every commit message with
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and **no session link**.
- **Branch**: work on `docs/tier2-composed-triage-design` or a branch off `origin/dev`. Never push to
  `dev` or `main` directly.
- **This slice changes no schedule and no trigger.** `e2e.yml` keeps its tag push, its path-filtered
  `pull_request` and its `0 3 * * *` nightly. The cron moves to `tier2.yml` in slice A2, not here.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ci/quarantine_notice.py` | **Create.** Given a check name, print why it is quarantined from the register, or exit non-zero if the register does not justify it. One job: turn a register row into an honest skip marker. |
| `tests/build/test_quarantine_notice.py` | **Create.** Fixture CSVs in `tmp_path`, plus one test that binds the script to the real register. |
| `.github/workflows/composed-e2e.yml` | **Create.** The suite's single definition: `workflow_call` only, `ref` and `quarantined` inputs, two mutually exclusive jobs. |
| `.github/workflows/e2e.yml` | **Rewrite as a caller.** Keeps every trigger it has; the 8 steps move out. |
| `tests/build/test_ci_evidence_retention.py` | **Modify.** `ARTIFACT_SOURCE_WORKFLOWS` and `test_the_composed_journey_seed_is_fixed_too` both name `e2e.yml` and both break when its steps leave. |
| `Makefile` | **Modify.** Two lines: add the new script to ruff and mypy. |

---

## Task 1: The quarantine notice script

**Files:**
- Create: `scripts/ci/quarantine_notice.py`
- Create: `tests/build/test_quarantine_notice.py`
- Modify: `Makefile:325-326`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `python3 scripts/ci/quarantine_notice.py --check "<check name>"` → exit 0 having printed one
  `SKIPPED (...)` line per matching register row; exit 1 with an `::error::` line if no row matches or a
  matching row has expired. Task 2's `quarantine-notice` job calls exactly this.
- Public functions: `rows_for_check(register: Path, check: str) -> list[dict[str, str]]`,
  `format_notice(row: Mapping[str, str], today: date) -> str`,
  `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_quarantine_notice.py`:

```python
"""A quarantined check must be able to say which register row permits the skip.

QUAR-001 was expressed as `if: false` in e2e.yml, which removes the check run
entirely: the suite did not run and nothing said so. That is the defect class
`cb::skipped` exists to prevent. This script is what replaces it, so its
contract is that a skip WITHOUT a register row is an error rather than a pass —
otherwise the honest-looking marker becomes a new way to hide a dead gate.
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

from quarantine_notice import (  # noqa: E402
    REGISTER,
    format_notice,
    main,
    rows_for_check,
)

COLUMNS = [
    "quarantine_id",
    "check",
    "scope",
    "reason",
    "owner",
    "tracking",
    "opened",
    "expiry",
    "notes",
]

CHECK = "Composed Agent E2E / composed-journey"


def _register(tmp_path: Path, **overrides: str) -> Path:
    """A one-row register CSV, with any cell overridable."""
    row = {
        "quarantine_id": "QUAR-001",
        "check": CHECK,
        "scope": "test_alpha, test_beta",
        "reason": "The bootstrap never creates its profiles, so the tests time out.",
        "owner": "shawnji (qa)",
        "tracking": "https://github.com/BlkLeg/CircuitBreaker/issues/162",
        "opened": "2026-09-23",
        "expiry": "2026-12-21",
        "notes": "Job quarantined pending a fix.",
    }
    row.update(overrides)
    path = tmp_path / "quarantine-register.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_a_matching_row_is_found(tmp_path: Path) -> None:
    rows = rows_for_check(_register(tmp_path), CHECK)
    assert [row["quarantine_id"] for row in rows] == ["QUAR-001"]


def test_a_different_check_matches_nothing(tmp_path: Path) -> None:
    assert rows_for_check(_register(tmp_path), "Browser E2E / browser-e2e") == []


def test_the_check_is_matched_exactly_not_by_prefix(tmp_path: Path) -> None:
    """`Composed Agent E2E` is a prefix of the real check name, and a prefix
    match would report a quarantine that the register does not actually carry."""
    assert rows_for_check(_register(tmp_path), "Composed Agent E2E") == []


def test_the_notice_names_the_row_the_expiry_and_the_tracking_item(tmp_path: Path) -> None:
    rows = rows_for_check(_register(tmp_path), CHECK)
    notice = format_notice(rows[0], date(2026, 9, 27))
    assert notice.startswith("SKIPPED (QUAR-001")
    assert "2026-12-21" in notice
    assert "85 days" in notice
    assert "issues/162" in notice
    assert CHECK in notice


def test_a_matching_row_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--check", CHECK, "--register", str(_register(tmp_path)), "--today", "2026-09-27"])
    assert code == 0
    assert "SKIPPED (QUAR-001" in capsys.readouterr().out


def test_no_row_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The whole point: a skip nobody registered must fail, not pass quietly."""
    code = main(
        ["--check", "Browser E2E / browser-e2e", "--register", str(_register(tmp_path)),
         "--today", "2026-09-27"]
    )
    assert code == 1
    assert "::error::" in capsys.readouterr().err


def test_an_expired_row_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An expired quarantine is not a licence to skip. test_quarantine_register.py
    fails the build on the same condition; this fails the job that would
    otherwise have reported the skip as fine."""
    register = _register(tmp_path, expiry="2026-09-26")
    code = main(["--check", CHECK, "--register", str(register), "--today", "2026-09-27"])
    assert code == 1
    assert "expired" in capsys.readouterr().err


def test_the_real_register_still_covers_the_composed_journey() -> None:
    """Binds the script to reality: if QUAR-001 is retired without the workflow's
    `quarantined` input flipping to false, the job would fail on a missing row.
    This says so here, in a fast test, instead of on a nightly."""
    assert rows_for_check(REGISTER, CHECK), (
        f"{REGISTER} has no row for {CHECK!r}. If the quarantine is over, set "
        "`quarantined: false` in .github/workflows/e2e.yml's call to composed-e2e.yml "
        "in the same commit that removes the row."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/build/test_quarantine_notice.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'quarantine_notice'`

- [ ] **Step 3: Write the implementation**

Create `scripts/ci/quarantine_notice.py`:

```python
#!/usr/bin/env python3
"""Print the register row that permits a check to be skipped, or fail.

QUAR-001 disabled the composed agent journey with `if: false` in e2e.yml. That
removes the check run altogether: the suite did not run, and nothing in the
pipeline said so. `scripts/ci/lib/common.sh`'s `cb::skipped` exists because
"did not run" and "found nothing" must never be spelled the same way, and a
workflow-level `if: false` is the strongest form of that mistake — there is not
even a line of output to read.

This is the workflow-side equivalent. A quarantined job runs this instead of
the suite, and the skip is only reported when
specs/1.0.0/release-control/quarantine-register.csv actually carries a row for
that check. A missing row, or an expired one, is an error: without that, the
honest-looking marker would become a new way to hide a dead gate, which is the
defect it was written to remove.

Exit codes: 0 when every matching row is live, 1 when no row matches or a
matching row has expired, 2 on a malformed register.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"

# Read, never written: this script reports the register and never edits it.
# Naming the columns it reads means a renamed column fails here with the column
# name rather than with a KeyError three frames down.
READ_COLUMNS = ("quarantine_id", "check", "scope", "owner", "tracking", "expiry")


class RegisterError(Exception):
    """The register is missing, malformed, or has an unparseable date."""


def rows_for_check(register: Path, check: str) -> list[dict[str, str]]:
    """Every register row whose `check` equals `check` exactly.

    Exact equality, not a prefix or substring test: "Composed Agent E2E" is a
    prefix of "Composed Agent E2E / composed-journey", and a loose match would
    report a quarantine the register does not carry for the job being skipped.
    """
    if not register.is_file():
        raise RegisterError(f"{register} does not exist")
    with register.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in READ_COLUMNS if column not in (reader.fieldnames or ())]
        if missing:
            raise RegisterError(f"{register} is missing column(s): {', '.join(missing)}")
        return [row for row in reader if row["check"].strip() == check]


def format_notice(row: Mapping[str, str], today: date) -> str:
    """One `SKIPPED (...)` line, in `cb::skipped`'s shape, naming the row.

    The days-remaining figure is the part a reader acts on: it turns "this is
    quarantined" into "this stops being allowed on a date you can see".
    """
    expiry = _parse_date(row["expiry"], row["quarantine_id"])
    remaining = (expiry - today).days
    return (
        f"SKIPPED ({row['quarantine_id']}, expires {expiry.isoformat()}, "
        f"{remaining} days left): {row['check']}\n"
        f"  scope:    {row['scope']}\n"
        f"  owner:    {row['owner']}\n"
        f"  tracking: {row['tracking']}"
    )


def _parse_date(value: str, quarantine_id: str) -> date:
    """An ISO date from a register cell, or a RegisterError naming the row."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RegisterError(f"{quarantine_id} has an unparseable expiry {value!r}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Report the quarantine for one check, or fail if the register does not."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        required=True,
        help="the check name exactly as the register's `check` column spells it",
    )
    parser.add_argument("--register", default=str(REGISTER))
    parser.add_argument(
        "--today",
        default=date.today().isoformat(),
        help="ISO date the expiry is measured against; defaults to today",
    )
    args = parser.parse_args(argv)

    try:
        today = date.fromisoformat(args.today)
        rows = rows_for_check(Path(args.register), args.check)
    except RegisterError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    except ValueError:
        print(f"::error::--today is not an ISO date: {args.today!r}", file=sys.stderr)
        return 2

    if not rows:
        print(
            f"::error::no quarantine row for {args.check!r} in {args.register} — a check "
            "may not be skipped without one. Fix the check, or add a row with an owner, "
            "a tracking item and an expiry no more than 90 days out.",
            file=sys.stderr,
        )
        return 1

    expired = []
    for row in rows:
        try:
            notice = format_notice(row, today)
        except RegisterError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        print(notice)
        if _parse_date(row["expiry"], row["quarantine_id"]) < today:
            expired.append(row["quarantine_id"])

    if expired:
        print(
            f"::error::quarantine row(s) expired: {', '.join(expired)} — the skip is no "
            "longer permitted. Fix the check, or renew the row deliberately.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/build/test_quarantine_notice.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 5: Add the script to the lint gate**

In `Makefile`, append `scripts/ci/quarantine_notice.py` to both the ruff line and the mypy line that
already name `scripts/ci/ledger_watch.py` (lines 325 and 326). Both lines must list it — ruff alone
leaves it untyped, mypy alone leaves it unlinted.

- [ ] **Step 6: Verify lint and types pass on the new file**

Run: `.venv/bin/ruff check scripts/ci/quarantine_notice.py && .venv/bin/mypy scripts/ci/quarantine_notice.py`
Expected: `All checks passed!` and `Success: no issues found in 1 source file`

- [ ] **Step 7: Prove the script works against the real register**

Run: `python3 scripts/ci/quarantine_notice.py --check "Composed Agent E2E / composed-journey"; echo "exit=$?"`
Expected: a `SKIPPED (QUAR-001, expires 2026-12-21, N days left)` block naming issue 162, then `exit=0`.

Run: `python3 scripts/ci/quarantine_notice.py --check "Nothing / nowhere"; echo "exit=$?"`
Expected: an `::error::no quarantine row` line on stderr, then `exit=1`.

- [ ] **Step 8: Commit**

```bash
git add scripts/ci/quarantine_notice.py tests/build/test_quarantine_notice.py Makefile
git commit -m "$(cat <<'EOF'
feat(ci): report a quarantined check from its register row

QUAR-001 disabled the composed agent journey with `if: false`, which removes
the check run entirely — the suite did not run and nothing said so, which is
the defect cb::skipped exists to prevent in its strongest form.

This is what a quarantined job runs instead of the suite. It prints the
register row that permits the skip, and exits non-zero when no row matches or
a matching row has expired, so the honest-looking marker cannot become a new
way to hide a dead gate. Exact match on the check name: "Composed Agent E2E"
is a prefix of the real name and a loose match would report a quarantine the
register does not carry.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: The reusable composed-e2e.yml

**Files:**
- Create: `.github/workflows/composed-e2e.yml`

**Interfaces:**
- Consumes: `scripts/ci/quarantine_notice.py --check <name>` from Task 1.
- Produces: a `workflow_call` workflow with inputs `ref` (string, default `""`) and `quarantined`
  (boolean, default `true`), and two mutually exclusive jobs, `composed-journey` and
  `quarantine-notice`. Task 3's `e2e.yml` and slice A2's `tier2.yml` both call it with those two inputs
  and no others.

- [ ] **Step 1: Create the workflow**

The eight steps are moved **verbatim** from `e2e.yml:57-142`, with one change: the checkout `ref`
expression becomes `${{ inputs.ref }}`. Do not rewrite the step comments — they record defects.

```yaml
name: Composed Agent E2E (suite)

# The composed agent journey, defined once. It lived inline in e2e.yml; Tier 2
# needs a second caller (docs/design/2026-09-27-tier2-composed-and-triage-design.md,
# slice A1), and a 75-minute suite is not a thing to copy.
#
# Two inputs, and both exist because a called workflow cannot read the caller's
# situation for itself:
#
#   ref — `schedule` fires only from the default branch's copy of a workflow
#     file, and `main` trails the integration branch, so a nightly that checked
#     out its own ref would test frozen code. e2e.yml redirected the scheduled
#     run to `dev` with an inline expression; inside a called workflow
#     `github.event_name` is the CALLER's event, so that expression cannot live
#     here. The caller decides and passes a ref.
#
#   quarantined — defaults to TRUE, which is deliberate. QUAR-001 is a property
#     of this suite, not of any caller, so the safe value has to be the default:
#     a new caller that forgets the input inherits the quarantine rather than
#     running a suite that is known red. Flipping the default to false is the
#     one-line change that ends the quarantine, and
#     tests/build/test_quarantine_notice.py fails if the register row goes away
#     while the default still says true.
#
# The aggregate that branch protection could require stays in the CALLING
# workflow, as it does in browser-e2e.yml: a called workflow's jobs report as
# `<caller job> / <called job>`, so an aggregate here would be renamed by every
# caller and stop being the stable name it exists to be.

on:
  workflow_call:
    inputs:
      ref:
        description: "Ref to check out. Empty means the ref that triggered the caller."
        required: false
        type: string
        default: ""
      quarantined:
        description: "When true, skip the suite and report the register row instead."
        required: false
        type: boolean
        default: true

permissions:
  contents: read

jobs:
  # ── The suite ───────────────────────────────────────────────────────────────
  composed-journey:
    name: Composed agent journey
    if: ${{ !inputs.quarantined }}
    runs-on: ubuntu-22.04
    timeout-minutes: 75
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ inputs.ref }}

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      # httpx (all HTTP), websockets (presence and discovery streams) and
      # cryptography (Ed25519 signing in the tampered-binary test) are all
      # imported by the suite. A missing one fails deep into a test that has
      # already built containers, so it reads as a product defect.
      - name: Install test deps
        run: |
          python -m pip install --upgrade pip
          pip install pytest pytest-timeout httpx websockets cryptography

      # `.env` is untracked but every compose call interpolates its
      # ${VAR:?...} guards, so without it even `config` exits 1. conftest.py
      # does the same for a local pytest; doing it here too covers this job's
      # non-pytest steps and fails on a step that names itself. `config` is
      # the smoke check that the materialised file satisfies every guard.
      - name: Materialise the e2e env file
        run: |
          cd apps/agent/e2e
          python ensure_env.py
          docker compose -f docker-compose.yml config >/dev/null

      # REL-20: seed and PYTHONHASHSEED are constants, not derived from the
      # run id, so a green run can be used to characterise a red one. Both are
      # recorded below, making a change to them visible.
      - name: Record the run manifest
        env:
          CB_E2E_SEED: "20260826"
        run: |
          mkdir -p diagnostics
          {
            echo "commit=${GITHUB_SHA}"
            echo "workflow=${GITHUB_WORKFLOW}"
            echo "job=composed-journey"
            echo "runner=${RUNNER_OS}/${RUNNER_ARCH}"
            echo "python=$(python -V 2>&1)"
            echo "PYTHONHASHSEED=0"
            echo "CB_E2E_SEED=${CB_E2E_SEED}"
            echo "docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unavailable)"
            echo "compose=$(docker compose version 2>&1)"
          } | tee diagnostics/run-manifest.txt

      - name: Run the composed journey
        shell: bash
        env:
          CB_E2E_SEED: "20260826"
          PYTHONHASHSEED: "0"
          # Each test tears its own stack down in a `finally`, so a later
          # workflow step has nothing left to collect. `_dump_compose_logs`
          # writes here from inside `_down()`, while containers still exist.
          CB_E2E_DIAGNOSTICS_DIR: ${{ github.workspace }}/diagnostics
        run: |
          cd apps/agent/e2e
          python -m pytest test_agent_e2e.py -v \
            --junitxml=junit-agent-e2e.xml \
            --timeout=3600 \
            2>&1 | tee "${GITHUB_WORKSPACE}/diagnostics/composed-journey.log"

      # Backstop only, for a run killed before any `_down()`. The logs that
      # explain a failure come from CB_E2E_DIAGNOSTICS_DIR above.
      - name: Collect surviving container diagnostics
        if: always()
        run: |
          mkdir -p diagnostics
          docker ps -a > diagnostics/containers.txt 2>&1 || true
          docker version > diagnostics/docker-version.txt 2>&1 || true
          for c in $(docker ps -aq); do
            docker logs "$c" > "diagnostics/surviving-${c}.log" 2>&1 || true
            docker inspect "$c" > "diagnostics/surviving-${c}.json" 2>&1 || true
          done

      - name: Upload diagnostics
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: composed-agent-e2e
          path: |
            apps/agent/e2e/junit-agent-e2e.xml
            diagnostics/
          retention-days: 30

  # ── The quarantine, said out loud ───────────────────────────────────────────
  # This job is why the `if: false` could be removed. It is cheap (a checkout
  # and one Python call), and it fails when the register stops justifying the
  # skip, so the quarantine cannot outlive its row unnoticed.
  quarantine-notice:
    name: Composed agent journey — quarantined
    if: ${{ inputs.quarantined }}
    runs-on: ubuntu-22.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v5
        with:
          persist-credentials: false

      - name: Report the register row that permits the skip
        run: |
          python3 scripts/ci/quarantine_notice.py \
            --check "Composed Agent E2E / composed-journey" \
            | tee -a "${GITHUB_STEP_SUMMARY}"
```

- [ ] **Step 2: Verify the file parses and the job graph resolves**

Run: `.venv/bin/python -m pytest tests/build/test_workflow_wiring_resolves.py tests/build/test_workflow_job_graph.py tests/build/test_workflow_run_blocks.py -q`
Expected: PASS. (These parse every workflow in the directory, so a new file is covered automatically.)

- [ ] **Step 3: Run checkov on the new workflow**

Run: `checkov -f .github/workflows/composed-e2e.yml --framework github_actions --compact`
Expected: no FAILED checks. If `CKV_GHA_7` fires, it is wrong here — this workflow has no
`workflow_dispatch` inputs — so investigate rather than adding a skip.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/composed-e2e.yml
git commit -m "$(cat <<'EOF'
feat(ci): define the composed agent journey once, as a reusable workflow

Tier 2 needs a second caller for a 75-minute suite, and copying it is how the
Playwright container tag came to be pinned in two places. The eight steps move
verbatim; only the checkout ref changes, because a called workflow reads the
CALLER's github context and so cannot decide for itself that a nightly should
test dev rather than its own ref.

`quarantined` defaults to true on purpose. QUAR-001 belongs to the suite, not
to a caller, so a caller that forgets the input must inherit the quarantine
rather than run something known red. The quarantine-notice job replaces the
`if: false` that removed the check run altogether.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: e2e.yml becomes a caller, and the guards follow the steps

**Files:**
- Modify: `.github/workflows/e2e.yml` (whole file)
- Modify: `tests/build/test_ci_evidence_retention.py:62` and `:115-128`

**Interfaces:**
- Consumes: `composed-e2e.yml`'s `ref` and `quarantined` inputs from Task 2.
- Produces: nothing later tasks depend on. Slice A2 adds `tier2.yml` as a second, independent caller.

**Why the test edits are in this task and not their own:** `test_the_composed_journey_seed_is_fixed_too`
does `_load("e2e.yml")` and asserts a **step** env sets `CB_E2E_SEED`. A thin caller has no steps, so
that test fails the moment `e2e.yml` changes. `ARTIFACT_SOURCE_WORKFLOWS` has the same shape — it names
`e2e.yml` as the home of the composed journey's diagnostics. Both are registries of where things live,
and a rename that does not update them leaves a green test watching nothing.

- [ ] **Step 1: Write the failing test first — point the registries at the new home**

In `tests/build/test_ci_evidence_retention.py`, change line 62 and the docstring above it:

```python
# Where the artifact classes below are allowed to live. composed-e2e.yml carries
# the composed journey's diagnostics (it held them inline as e2e.yml until slice
# A1 moved the suite out); browser-e2e.yml carries Playwright's traces,
# screenshots and video, which is why scanning ci.yml alone stopped being
# enough once the suite moved out of it.
ARTIFACT_SOURCE_WORKFLOWS = ("ci.yml", "composed-e2e.yml", "browser-e2e.yml")
```

And in `test_the_composed_journey_seed_is_fixed_too`, replace both `e2e.yml` mentions:

```python
def test_the_composed_journey_seed_is_fixed_too():
    """The seed lives with the suite, which is composed-e2e.yml since slice A1.
    e2e.yml is a thin caller with no steps of its own, so asserting against it
    would pass vacuously — `seeds` would simply be empty, and the `assert seeds`
    below is what catches that."""
    workflow = _load("composed-e2e.yml")
    seeds = [
        str(value)
        for job in workflow["jobs"].values()
        for step in job.get("steps") or []
        for key, value in (step.get("env") or {}).items()
        if key == "CB_E2E_SEED"
    ]
    assert seeds, "composed-e2e.yml sets no CB_E2E_SEED"
    assert all("${{" not in seed for seed in seeds), (
        f"composed-e2e.yml derives CB_E2E_SEED per run: {seeds}"
    )
```

- [ ] **Step 2: Run the suite to confirm it passes against Task 2's file and would have caught the move**

Run: `.venv/bin/python -m pytest tests/build/test_ci_evidence_retention.py -q`
Expected: PASS — `composed-e2e.yml` from Task 2 already carries the seed and the uploads.

Then confirm the guard is not vacuous by checking the pre-change form would now fail:
Run: `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import yaml; w=yaml.safe_load(open('.github/workflows/e2e.yml')); print([s for j in w['jobs'].values() for s in (j.get('steps') or [])])"`
Expected (after Step 3): `[]` — an empty step list, which is exactly what `assert seeds` catches.

- [ ] **Step 3: Rewrite e2e.yml as a thin caller**

Every trigger is unchanged except that `workflow_call` is dropped and the path filter gains the new
file. The `schedule` stays here; slice A2 moves it to `tier2.yml`.

```yaml
name: Composed Agent E2E

# AGT-01: the composed journey runs per RC (tag push) and nightly. It is
# deliberately NOT a release gate — the agent has open development, and gating
# would hold every artifact of an otherwise-green release.
#
# The suite itself now lives in composed-e2e.yml (slice A1 of
# docs/design/2026-09-27-tier2-composed-and-triage-design.md). This file is the
# day-to-day trigger surface for it; `tier2.yml` becomes the second caller in
# slice A2 and takes over the nightly then.
#
# `workflow_call` is gone from this file on purpose: the reason it existed —
# "so re-gating is one job in release.yml when that changes" — is now served by
# calling composed-e2e.yml directly, and a thin caller that can itself be
# called only adds a level of check-name nesting for nothing.
on:
  push:
    tags:
      - "v*"
  # Path-filtered, and not a release gate — see the note above, which still
  # holds. What changes is when a defect in the agent or in this harness is
  # first seen: before this, the earliest signal for an agent change was the
  # nightly (against `dev`) or the tag itself, so v0.4.3's two failures were
  # found by the release. A pull request that touches the agent, its E2E
  # harness or the image it runs against now gets the same 40-minute journey
  # while the change is still a proposal.
  #
  # The filter is what keeps this proportionate: a frontend or docs pull
  # request does not pay for it.
  pull_request:
    paths:
      - 'apps/agent/**'
      - 'apps/backend/src/app/api/ws_agents.py'
      - 'apps/backend/src/app/services/agent_*.py'
      - 'Dockerfile.mono'
      - 'docker/supervisord.mono.conf'
      - '.github/workflows/e2e.yml'
      - '.github/workflows/composed-e2e.yml'
  schedule:
    - cron: "0 3 * * *"
  # checkov:skip=CKV_GHA_7: the input selects nothing about what is built — it
  # only decides whether the operator wants to pay 75 minutes to watch QUAR-001
  # fail on purpose. The default is the safe value.
  workflow_dispatch:
    inputs:
      quarantined:
        description: "Leave true to report QUAR-001 and skip. Set false to actually run the suite."
        required: false
        type: boolean
        default: true

permissions:
  contents: read

jobs:
  composed:
    # Only a deliberate dispatch can lift the quarantine. For a tag push, a
    # pull request or the nightly, `inputs` is null, so the first clause is
    # true and the suite stays skipped — written as `!=` plus `or` rather than
    # `&&` plus `or` because `false && x || true` evaluates to true and would
    # silently ignore an operator who asked for the real run.
    uses: ./.github/workflows/composed-e2e.yml
    with:
      quarantined: ${{ github.event_name != 'workflow_dispatch' || inputs.quarantined }}
      # `schedule` fires only from the default branch's copy of this file, and
      # `main` trails the integration branch, so a nightly on its own ref would
      # test frozen code. Every other trigger tests the ref that fired it.
      ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}
```

- [ ] **Step 4: Run every workflow guard plus the evidence registry**

Run: `.venv/bin/python -m pytest tests/build/test_ci_evidence_retention.py tests/build/test_workflow_wiring_resolves.py tests/build/test_workflow_job_graph.py tests/build/test_workflow_run_blocks.py tests/build/test_scheduled_workflows_pin_their_ref.py tests/build/test_discord_notify.py -q`
Expected: PASS. `test_discord_notify.py` matters here: `notify.yml` watches the name
`Composed Agent E2E`, and this file keeps that exact `name:`, so the pager is unaffected.

- [ ] **Step 5: Run checkov on the rewritten caller**

Run: `checkov -f .github/workflows/e2e.yml --framework github_actions --compact`
Expected: no FAILED checks; `CKV_GHA_7` is skipped with the reason written above the trigger.

- [ ] **Step 6: Run the whole repo-policy suite**

Run: `.venv/bin/python -m pytest tests/build -q`
Expected: PASS. This is the suite that actually covers a workflow change in this repo, so it is the one
to report.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/e2e.yml tests/build/test_ci_evidence_retention.py
git commit -m "$(cat <<'EOF'
refactor(ci): make e2e.yml a caller and end QUAR-001's silent skip

The suite moved to composed-e2e.yml, so this file is now only the trigger
surface for it: same tag push, same path-filtered pull request, same nightly.
`workflow_call` is dropped — callers use composed-e2e.yml directly, and a thin
caller that can be called only nests check names further.

QUAR-001 is still in force and now says so: the quarantine-notice job prints
the register row, its expiry and its tracking item, and fails if the register
stops justifying the skip. `if: false` reported nothing at all.

test_ci_evidence_retention.py follows the move. It is a registry of where
evidence lives, and both entries named e2e.yml: ARTIFACT_SOURCE_WORKFLOWS, and
a seed test that reads step env. A thin caller has no steps, so leaving them
pointed here would have left a green test watching nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Prove it in CI before opening the pull request

CLAUDE.md rule 3: push only after the covering suite passes locally, and rule 1: name the suite that
exercises the change. `make verify` runs no workflow at all, so the covering evidence for this slice is
the repo-policy suite plus a real dispatch. Rule 4: confirm the push landed before dispatching anything.

**Files:** none — this task produces evidence, not code.

- [ ] **Step 1: Run the pre-push gate**

Run: `make verify`
Expected: PASS. Note in the PR body that this gate does **not** execute any workflow, and say which
suite does.

- [ ] **Step 2: Push the branch and confirm the remote has it**

```bash
git push -u origin HEAD
git ls-remote --heads origin "$(git rev-parse --abbrev-ref HEAD)"
```
Expected: one line whose SHA equals `git rev-parse HEAD`. Do not dispatch anything until it does.

- [ ] **Step 3: Dispatch the quarantined path and read the output**

```bash
gh workflow run "Composed Agent E2E" --ref "$(git rev-parse --abbrev-ref HEAD)"
sleep 20 && gh run list --workflow "Composed Agent E2E" --limit 1
```
Expected: the run completes in under two minutes. `Composed agent journey — quarantined` succeeds;
`Composed agent journey` is reported **skipped** rather than absent. Confirm the step summary carries
the `SKIPPED (QUAR-001, expires 2026-12-21, N days left)` block.

Per the memory note on `gh pr checks`, read the check runs from the commit's API rather than trusting a
summary view:
```bash
gh api "repos/BlkLeg/CircuitBreaker/commits/$(git rev-parse HEAD)/check-runs" \
  --jq '.check_runs[] | "\(.name): \(.conclusion)"'
```

- [ ] **Step 4: Prove the un-quarantined path still reaches the suite**

```bash
gh workflow run "Composed Agent E2E" --ref "$(git rev-parse --abbrev-ref HEAD)" -f quarantined=false
```
Expected: `Composed agent journey` runs, and **fails** in the three discovery-bootstrap tests QUAR-001
names. That failure is the pass condition for this step: it proves the input works and that the
extraction did not change what the suite does. Budget 75 minutes. Do not quarantine anything new on the
strength of it and do not treat the red run as a regression — compare the failing test ids against
QUAR-001's `scope` column and say so in the PR body.

- [ ] **Step 5: Open the pull request**

Base `dev`. The body must state plainly: which suites were run and passed (`tests/build`, `make verify`),
that neither executes a workflow, that the covering evidence is the two dispatches in Steps 3 and 4,
and that the red suite in Step 4 matches QUAR-001's scope exactly. End the description with the
attribution line and no session link.

---

## Self-Review

**Spec coverage.** A1's four deliverables in §9 map to tasks: `composed-e2e.yml` → Task 2; `e2e.yml`
becomes a caller → Task 3; QUAR-001 becomes a visible `SKIPPED` backed by the register → Tasks 1–3;
the `test_ci_evidence_retention.py` registry follows the move → Task 3. §3.1's `ref` input is Task 2.
§7.4's list of guards that must pass is Task 3 Step 4 and Step 6. Not in this slice, and correctly so:
`tier2.yml`, `make verify-composed`, the drift guard, mono smoke, and everything in Phase B.

**Deviation from the spec, deliberate.** §9's A1 row says `e2e.yml` "drops its nightly". This plan keeps
the cron here and moves it in A2. Two reasons: the cron and `tier2.yml` cannot both hold `0 3 * * *`, so
moving it with the file that takes it over is one change rather than two; and keeping it exercises the
new `ref` input immediately, which is the input A2 depends on. The nightly is quarantined either way, so
no coverage changes. The spec's A1 row is amended to match.

**Type consistency.** `rows_for_check(register: Path, check: str) -> list[dict[str, str]]`,
`format_notice(row: Mapping[str, str], today: date) -> str` and `main(argv) -> int` are used with those
exact signatures in the test (Task 1 Step 1), the implementation (Step 3) and the workflow call (Task 2).
`REGISTER` is imported by the test and defined in the script. The workflow inputs `ref` and `quarantined`
are spelled identically in Task 2's definition and Task 3's call.

**No placeholders.** Every step carries the content to run or paste. The only figure left open is "N days
left", which is computed at run time by design.
