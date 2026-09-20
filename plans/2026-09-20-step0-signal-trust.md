# Step 0 — Signal Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every CI signal either trusted or explicitly quarantined with an enforced expiry, and make the scheduled-workflow ref hazard impossible to reintroduce silently.

**Architecture:** Three independent additions, none of which touch application code. A quarantine register modelled exactly on the existing `skip-register.csv` pattern, validated by a test that compares expiry dates against `date.today()`. A policy test that reads every workflow YAML and requires any `schedule:` trigger to either pin a ref or declare default-branch execution intentional. A doctrine change to ADR 0005 and CLAUDE.md that states the rule the other two enforce.

**Tech Stack:** Python 3.12, pytest, PyYAML (already a dev dependency via the workflow-reading tests), CSV, Markdown.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §4, §5, §7.

## Global Constraints

- Python 3.12. snake_case, full type annotations — mypy runs with `disallow_untyped_defs`. Docstrings on classes and public functions.
- **No placeholders.** No `TODO`, bare `pass`, or `NotImplementedError` in shipped code.
- Never hardcode credentials, tokens, signing material or vault keys — including in tests and fixtures.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- `tests/build/` is collected by the repo-root `pytest.ini`. That config sets `filterwarnings = error`, so any warning a new test raises fails the run.
- Root pytest `testpaths = tests`. Run repo-policy suites with `pytest tests/build -q`.
- Before pushing: `make lint`, then `make verify`. This plan touches no code under `apps/backend/src/app`, so `make verify` is the correct gate — not `make verify-full`.
- Never lower the coverage gate to make a build green.

## File Structure

| File | Responsibility |
|---|---|
| `specs/1.0.0/release-control/quarantine-register.csv` | One row per quarantined required check. Sibling of `skip-register.csv`; same governance model. |
| `tests/build/test_quarantine_register.py` | Enforces the register: expiry against today, owner in the owner map, tracking item present, ids unique and well-formed. |
| `tests/build/test_scheduled_workflows_pin_their_ref.py` | Policy test over `.github/workflows/*.yml`: a `schedule:` trigger pins a ref or declares intent. |
| `docs/adr/0005-verification-tiers-and-platform-support.md` | Gains the fourth repo-wide rule. |
| `CLAUDE.md` | Rule 2 gains the two-permitted-outcomes clause. |
| `scripts/ci/verify_plan_references.py` | Resolves a plan's named references against the tree before anyone implements it. |
| `tests/build/test_plan_references.py` | Runs that checker over every plan in `plans/`. |

---

### Task 1: The quarantine register and its enforcement

**Files:**
- Create: `specs/1.0.0/release-control/quarantine-register.csv`
- Create: `tests/build/test_quarantine_register.py`
- Read for reference: `tests/build/test_skip_register.py`, `specs/1.0.0/release-control/skip-register.csv`, `specs/1.0.0/release-control/owner-map.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `specs/1.0.0/release-control/quarantine-register.csv` with header
  `quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes`.
  Task 3 references this path in CLAUDE.md. Step 3's release checklist
  (`scripts/release_checklist.py`) reads it via
  `load_quarantine_rows(path: Path) -> list[dict[str, str]]`, exported from
  `tests/build/test_quarantine_register.py`? **No** — see Step 3 Task 2, which
  defines its own reader in `scripts/release_checklist.py`. The CSV schema above
  is the contract between them; neither imports the other.

- [ ] **Step 1: Create the register with its header and no rows**

The register starts empty. That is the honest state: nothing is quarantined today, and an empty register is what the test must handle first.

```bash
cat > specs/1.0.0/release-control/quarantine-register.csv <<'EOF'
quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes
EOF
```

- [ ] **Step 2: Write the failing test**

Create `tests/build/test_quarantine_register.py`:

```python
"""A red required check is fixed, or quarantined with an owner and an expiry.

There is no third option. "Probably flaky" is not an outcome, and the six
incidents in docs/design/2026-09-20-install-experience-and-release-verification-design.md
§1.9 are what the third option costs: a nightly that characterised three-week-old
`main` for nine consecutive runs, an agent suite where eight of ten failures
traced to one harness bug, and a genuinely red Browser E2E written off as
"stale runs from before #137 landed".

Modelled on test_skip_register.py, deliberately, including the lesson its
docstring records: expiry is compared against `date.today()`, never against the
date the register was written. A register whose rows expire relative to their
own authoring date is green forever.

The expiry ceiling is the part that makes an expiry date mean anything. A
quarantine renewable to an arbitrary date is a permanent exemption with a date
column, so a row may not be opened for more than 90 days. Renewing it is a
commit that a reviewer sees.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"
OWNER_MAP = REPO_ROOT / "specs" / "1.0.0" / "release-control" / "owner-map.md"

EXPECTED_COLUMNS = [
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

ID_RE = re.compile(r"^QUAR-\d{3}$")
MAX_QUARANTINE_DAYS = 90
REQUIRED_NON_EMPTY = ("check", "scope", "reason", "owner", "tracking", "opened", "expiry")


def _rows() -> list[dict[str, str]]:
    """Every row in the register, as dicts keyed by column name."""
    with REGISTER.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _owners() -> set[str]:
    """Owner strings the owner map declares, e.g. 'shawnji (release)'."""
    text = OWNER_MAP.read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*(shawnji \([a-z]+\))\s*\|", text))


def test_register_exists_and_has_the_expected_columns() -> None:
    assert REGISTER.exists(), (
        f"{REGISTER.relative_to(REPO_ROOT)} is missing. The register is the only "
        "permitted alternative to fixing a red required check, so its absence "
        "means the policy has no mechanism."
    )
    with REGISTER.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == EXPECTED_COLUMNS, (
        f"quarantine-register.csv header is {header}, expected {EXPECTED_COLUMNS}. "
        "scripts/release_checklist.py reads these column names."
    )


def test_no_quarantine_is_past_its_expiry() -> None:
    """The one assertion that makes the expiry column load-bearing."""
    today = date.today()
    expired = [
        (row["quarantine_id"], row["check"], row["expiry"])
        for row in _rows()
        if date.fromisoformat(row["expiry"]) < today
    ]
    assert not expired, (
        "Quarantine entries are past their expiry: "
        + "; ".join(f"{qid} ({check}) expired {exp}" for qid, check, exp in expired)
        + ". Fix the check, or renew the row with a new expiry and a reason — "
        "renewal is a commit a reviewer sees, which is the point."
    )


def test_every_row_is_complete_and_well_formed() -> None:
    for row in _rows():
        qid = row["quarantine_id"]
        assert ID_RE.match(qid), f"quarantine_id {qid!r} is not QUAR-NNN"
        for column in REQUIRED_NON_EMPTY:
            assert row[column].strip(), (
                f"{qid} has an empty {column}. A row missing an owner, a reason "
                "or a tracking item is a placeholder, which is the state this "
                "register exists to reject."
            )
        opened = date.fromisoformat(row["opened"])
        expiry = date.fromisoformat(row["expiry"])
        assert expiry > opened, f"{qid} expires ({expiry}) on or before it opened ({opened})"
        assert (expiry - opened).days <= MAX_QUARANTINE_DAYS, (
            f"{qid} is quarantined for {(expiry - opened).days} days, over the "
            f"{MAX_QUARANTINE_DAYS}-day ceiling. A quarantine renewable to an "
            "arbitrary date is a permanent exemption with a date column."
        )


def test_quarantine_ids_are_unique() -> None:
    ids = [row["quarantine_id"] for row in _rows()]
    duplicates = sorted({qid for qid in ids if ids.count(qid) > 1})
    assert not duplicates, f"duplicate quarantine ids: {duplicates}"


def test_every_owner_is_named_in_the_owner_map() -> None:
    known = _owners()
    assert known, (
        "No owners parsed from owner-map.md — the parser and the map have "
        "diverged, and this test would pass vacuously."
    )
    for row in _rows():
        assert row["owner"] in known, (
            f"{row['quarantine_id']} names owner {row['owner']!r}, which is not in "
            f"owner-map.md. Known owners: {sorted(known)}"
        )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/build/test_quarantine_register.py -v`

Expected: `test_register_exists_and_has_the_expected_columns` FAILS if Step 1 was skipped. If Step 1 ran, all five tests PASS against the empty register — that is correct and expected, because an empty register genuinely satisfies every rule. To prove the test has teeth before trusting it, continue to Step 4.

- [ ] **Step 4: Prove the enforcement works by adding a deliberately expired row**

```bash
cat >> specs/1.0.0/release-control/quarantine-register.csv <<'EOF'
QUAR-999,Temporary Proof,tests/build/test_nothing.py,"Deliberately expired row proving the expiry assertion has teeth. Removed in the next step.",shawnji (release),RISK-010,2026-01-01,2026-01-02,Delete me.
EOF
pytest tests/build/test_quarantine_register.py::test_no_quarantine_is_past_its_expiry -v
```

Expected: FAIL, naming `QUAR-999` and the date `2026-01-02`.

- [ ] **Step 5: Remove the proof row and confirm green**

```bash
cd /home/shawnji/project/CircuitBreaker
grep -v '^QUAR-999,' specs/1.0.0/release-control/quarantine-register.csv > /tmp/qr.csv
mv /tmp/qr.csv specs/1.0.0/release-control/quarantine-register.csv
pytest tests/build/test_quarantine_register.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add specs/1.0.0/release-control/quarantine-register.csv tests/build/test_quarantine_register.py
git commit -m "feat: add the quarantine register and enforce its expiries

A red required check now has exactly two permitted outcomes: fixed, or
quarantined with an owner, a tracking item and an expiry no more than 90 days
out. Modelled on skip-register.csv, including its lesson that expiry is
compared against date.today() rather than the date the register was written.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The scheduled-workflow ref guard

**Files:**
- Create: `tests/build/test_scheduled_workflows_pin_their_ref.py`
- Read for reference: `.github/workflows/e2e.yml` (the workflow whose redirect never ran)

**Interfaces:**
- Consumes: nothing.
- Produces: the marker comment contract `# scheduled-ref: default-branch-intentional`, which any future workflow may use to declare default-branch execution deliberate.

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_scheduled_workflows_pin_their_ref.py`:

```python
"""A scheduled workflow runs the default branch's copy of itself.

`.github/workflows/e2e.yml` redirects its scheduled run to `dev` with
`ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}`, because `main`
trails the integration branch. That redirect never executed for nine-plus
consecutive nightlies up to 2026-09-19: a `schedule` event loads the workflow
file from the **default branch**, and `main`'s copy still had a bare
`actions/checkout@v5`. Every red nightly characterised three-week-old `main`
rather than the code the fixes went into.

The failure is silent. Nothing in the run log says "this is the default
branch's copy" — the tell is the checkout line, which nobody reads, and a
run manifest that records `GITHUB_SHA` rather than the checked-out ref.

So the guard is static and mechanical: a workflow that can be triggered by
`schedule` either pins a ref on every checkout, or says in one comment that
default-branch execution is what it wants. Both are legitimate. Silence is not,
because silence is indistinguishable from the bug.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
MARKER = "# scheduled-ref: default-branch-intentional"


def _scheduled_workflows() -> list[Path]:
    """Workflow files carrying a `schedule:` trigger."""
    found: list[Path] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        # yaml parses the bare `on:` key as the boolean True, which is a YAML 1.1
        # quirk and exactly why this is read from the parsed document rather than
        # grepped: `on:` and `"on":` must behave identically.
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        triggers = document.get("on", document.get(True))
        if isinstance(triggers, dict) and "schedule" in triggers:
            found.append(path)
    return found


def _checkout_steps(document: dict) -> list[dict]:
    """Every actions/checkout step in the document, across all jobs."""
    steps: list[dict] = []
    for job in (document.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout"):
                steps.append(step)
    return steps


def test_at_least_one_scheduled_workflow_exists() -> None:
    """Guards against the guard passing vacuously if the parser breaks."""
    assert _scheduled_workflows(), (
        "No workflow with a `schedule:` trigger was found. Either the repo has "
        "none — in which case delete this suite — or the parser above no longer "
        "recognises the trigger, in which case this whole file is passing for "
        "the wrong reason."
    )


def test_scheduled_workflows_pin_a_ref_or_declare_intent() -> None:
    offenders: list[str] = []
    for path in _scheduled_workflows():
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        document = yaml.safe_load(text)
        steps = _checkout_steps(document)
        unpinned = [step for step in steps if "ref" not in (step.get("with") or {})]
        if unpinned:
            offenders.append(f"{path.name} ({len(unpinned)} of {len(steps)} checkouts unpinned)")
    assert not offenders, (
        "These workflows can be triggered by `schedule` but check out without an "
        f"explicit ref: {offenders}. A scheduled run loads this file from the "
        "DEFAULT branch, so an unpinned checkout tests the default branch "
        "whatever the newest copy of this file says. That silently characterised "
        "three-week-old `main` for nine consecutive nightlies.\n\n"
        "Fix by either pinning the ref:\n"
        "    - uses: actions/checkout@v5\n"
        "      with:\n"
        "        ref: ${{ github.event_name == 'schedule' && 'dev' || '' }}\n"
        f"or, if default-branch execution is deliberate, adding this comment:\n"
        f"    {MARKER}"
    )
```

- [ ] **Step 2: Run the test to verify it passes or fails honestly**

Run: `pytest tests/build/test_scheduled_workflows_pin_their_ref.py -v`

Expected: `test_at_least_one_scheduled_workflow_exists` PASSES (`e2e.yml` has a schedule). `test_scheduled_workflows_pin_a_ref_or_declare_intent` PASSES if `e2e.yml`'s redirect is present on this branch, FAILS naming any workflow that is unpinned. **Do not "fix" a failure by adding the marker comment** — the marker declares intent, and intent here is that the nightly tests `dev`. Pin the ref instead.

- [ ] **Step 3: Prove the guard has teeth**

Temporarily remove the `ref:` line from `e2e.yml`'s checkout step, run the test, and confirm it fails naming `e2e.yml`. Restore the line.

```bash
pytest tests/build/test_scheduled_workflows_pin_their_ref.py::test_scheduled_workflows_pin_a_ref_or_declare_intent -v
git diff --stat .github/workflows/e2e.yml   # must be empty after restoring
```

Expected: FAIL while the line is removed; `git diff` empty afterwards.

- [ ] **Step 4: Confirm PyYAML is available to the root suite**

Run: `python3 -c "import yaml; print(yaml.__version__)"`

Expected: a version string. If it raises `ModuleNotFoundError`, add `pyyaml` to `apps/backend/requirements-dev.txt` and regenerate per that file's header before continuing — do not vendor a hand-rolled YAML parser.

- [ ] **Step 5: Commit**

```bash
git add tests/build/test_scheduled_workflows_pin_their_ref.py
git commit -m "feat: guard against scheduled workflows testing the default branch

A schedule event loads workflow YAML from the default branch, so e2e.yml's
redirect to dev never ran and nine-plus consecutive nightlies characterised
three-week-old main. A scheduled workflow must now pin a ref on every checkout
or declare default-branch execution intentional in a comment.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The doctrine

Two documentation changes that state the rule the previous two tasks enforce. Folded into one task because neither is independently reviewable.

**Files:**
- Modify: `docs/adr/0005-verification-tiers-and-platform-support.md` — the "Three further rules apply repo-wide" paragraph
- Modify: `CLAUDE.md` — "Rules for claiming something is verified", rule 2

- [ ] **Step 1: Add the fourth repo-wide rule to ADR 0005**

Find this text in `docs/adr/0005-verification-tiers-and-platform-support.md`:

```
Three further rules apply repo-wide: a gate may not pass by not running; test
configuration that changes semantics must be branch-invariant; and evidence collection is
part of the gate, not an optional trailing step.
```

Replace it with:

```
Four further rules apply repo-wide: a gate may not pass by not running; a gate may not
pass by not asking; test configuration that changes semantics must be branch-invariant;
and evidence collection is part of the gate, not an optional trailing step.

**A gate may not pass by not asking.** A gate must execute the property it claims to
verify. Version parity is an identity check and is evidence of identity only — never
evidence that an artifact functions. v0.4.2 shipped a binary containing no application
and passed every blocking gate, because the only execution any gate performed was
`--version`, which `start.py` resolves from an embedded file and exits on before the
application is imported. The rule above ("not running") would not have caught it: that
gate ran.
```

- [ ] **Step 2: Give CLAUDE.md's rule 2 the two permitted outcomes**

Find rule 2 under "Rules for claiming something is verified":

```
2. **Never dismiss a red check as stale, flaky, or pre-existing without
   proving it.** Proof is reproducing it, or running the same check on a clean
   tree at an older commit and showing it fails identically. "Those runs
   predate the fix" is a hypothesis, not a finding.
```

Replace with:

```
2. **Never dismiss a red check as stale, flaky, or pre-existing without
   proving it.** Proof is reproducing it, or running the same check on a clean
   tree at an older commit and showing it fails identically. "Those runs
   predate the fix" is a hypothesis, not a finding.

   A red required check has exactly two permitted outcomes: it is **fixed**, or
   it is **quarantined** with a row in
   `specs/1.0.0/release-control/quarantine-register.csv` naming an owner, a
   tracking item and an expiry no more than 90 days out. There is no third
   outcome. "Probably flaky" is not an outcome, and
   `tests/build/test_quarantine_register.py` fails the build on an expired row.
```

- [ ] **Step 3: Add the sixth verification rule to CLAUDE.md**

Append to the same numbered list, after rule 5:

```
6. **A binary that answers `--version` has not been shown to run.** Version
   parity is an identity check. The only evidence that an artifact works is
   something importing or starting the application inside it — `circuit-breaker
   --selftest` at minimum, a boot and a `/readyz` probe where the suite allows.
```

- [ ] **Step 4: Verify the referenced paths exist**

```bash
test -f specs/1.0.0/release-control/quarantine-register.csv && echo "register OK"
test -f tests/build/test_quarantine_register.py && echo "test OK"
```

Expected: both lines print. CLAUDE.md must not name a path that does not exist; rule 6 names `--selftest`, which Step 1 of the next plan creates — that forward reference is deliberate and is why Task 3 is committed last in this plan and the `--selftest` plan runs immediately after.

- [ ] **Step 5: Run the full repo-policy suite**

Run: `pytest tests/build -q`

Expected: all pass. Several suites in `tests/build/` read CLAUDE.md and the ADRs for governance policy (`test_governance_files.py` and neighbours); if one fails, it is asserting something about document structure and must be read, not worked around.

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0005-verification-tiers-and-platform-support.md CLAUDE.md
git commit -m "docs: a gate may not pass by not asking

ADR 0005 already forbids a gate passing by not running. v0.4.2's gate ran; it
just never asked whether the binary contained an application. Adds the fourth
repo-wide rule, gives CLAUDE.md's rule 2 the two permitted outcomes for a red
check, and adds rule 6: --version is an identity check, never evidence that an
artifact functions.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The reference-verification pass

**Status: implemented 2026-09-20** (`scripts/ci/verify_plan_references.py`,
`tests/build/test_plan_references.py`). Recorded here because the plan set is the
record, and a task done outside its plan is how a plan stops describing the tree.

**Why it exists.** Five defects were found in the steps 2-7 plans, all one shape:
a thing in an existing system was *named* without being *read*. A job id inferred
from a display name (`publish`; the id is `release`) reached a commit and would
have failed every future Release workflow. A CLI flag was invented for a parser
that never declared it. Health routes were placed at the root when they are
mounted under `/api/v1`. Reviewing the prose caught none of them.

**What it checks:** `Modify:`/`Read:` paths exist; `Create:` paths do not already
exist (reported, not fatal — it means the task landed); `needs:` entries in
embedded workflow snippets name a job the real workflow declares; `--flag`s passed
to repo Python scripts exist in that script's argparse unless the plan adds them.

**What it cannot check, and must never be trusted for:** a reference that resolves
to the *wrong* thing. A real URL with a wrong prefix, a real unit file that is the
wrong one of two, an incomplete dependency set. Two of the five defects were
exactly that. Reading the code is still the only thing that catches them.

- [x] **Step 1: Write the checker** — `scripts/ci/verify_plan_references.py`.
- [x] **Step 2: Run it against the plan set, and fix what it finds.** Its first
  run reported 20 items, of which **three classes were bugs in the checker
  itself**: symbol names cited beside their file (`build_parser`, `cb_fail`) read
  as missing paths; cross-plan forward dependencies (step 6 modifies the `ui.sh`
  step 5 creates) read as missing; and already-landed `Create:` paths treated as
  failures rather than information. Fixed all three.
- [x] **Step 3: Write `tests/build/test_plan_references.py`** — parametrised over
  every plan, plus a regression test pinning the `needs: [version, publish]`
  defect and one pinning the symbol-vs-path false positive.
- [x] **Step 4: Prove it has teeth** — a deliberately bad `Modify:` path fails the
  suite naming the file; restored, green.
- [x] **Step 5: Confirm it is warning-clean.** `pytest.ini` sets
  `filterwarnings = error`, so a `SyntaxWarning` in the checker would fail the
  whole root suite. Verified with `python -W error`.

**Run it before dispatching any implementer:**

```bash
.venv/bin/python scripts/ci/verify_plan_references.py plans/2026-09-20-step*.md
```

---

## Definition of done

- [ ] `pytest tests/build -q` passes.
- [ ] `make lint` passes.
- [ ] `make verify` passes.
- [ ] Deliberately expiring a quarantine row fails the build (proved in Task 1 Step 4).
- [ ] Deliberately unpinning `e2e.yml`'s checkout fails the build (proved in Task 2 Step 3).
- [ ] ADR 0005 states four repo-wide rules; CLAUDE.md states six verification rules.
