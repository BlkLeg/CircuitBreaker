# Step 3 — Tier 2 In Force and Per-Release Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ADR 0005's Tier 2 guarantee into force by building the boot-and-exercise job it names, make release readiness assertable by a script rather than felt, and stop any documentation page promising more than the tier table supports.

**Architecture:** Three pieces. A boot job that starts the installed service against containerised Postgres, Redis and NATS and polls `/readyz` — a subset of `tier3-artifact.sh`'s contract running on a GitHub-hosted runner. A `release_checklist.py` that asserts every readiness condition and exits non-zero on any unsatisfied row, run by `release.yml` before `publish`. A policy test that fails if a docs page claims a guarantee the ADR's *in force* column does not support.

**Tech Stack:** GitHub Actions service containers, Bash, `curl`, Python 3.12, pytest, PyYAML.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §15, §16, §17.

**Depends on:** Step 0 (the quarantine register schema), Step 1 (`--selftest`), Step 2 (the smoke and post-publish jobs the checklist asserts).

## Global Constraints

- Python 3.12. snake_case, full type annotations — mypy runs with `disallow_untyped_defs`. Docstrings on classes and public functions.
- **No placeholders.**
- Never hardcode credentials, tokens, signing material or vault keys. The service containers below need a database password, a JWT secret, a NATS token and a Fernet vault key: **generate them at runtime and register them with `::add-mask::` before they are written anywhere**, exactly as `dev-ci.yml` already does. Copy that idiom; do not invent one.
- **Backward compatible.** The checklist is additive; it blocks publication but changes no artifact.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan does not touch `apps/backend/src/app`, so `make verify` is the correct pre-push gate.
- **A tier moves into force by a commit that adds the named evidence, and that commit updates ADR 0005's last column in the same change.** Editing that column to claim more than the evidence supports is, in the ADR's own words, a defect.

## Background an implementer needs

`docs/adr/0005-verification-tiers-and-platform-support.md` states Tier 2 — "install and boot, deb/rpm arm64" — enters force when "the §8.2 L2 job extends `artifact-smoke.yml`'s `ubuntu-22.04-arm` run to the full boot-and-exercise contract", and records its current state as **not in force**: "That job still asserts only that the binary prints a version."

Step 1 added `--selftest` to that run. **That is not sufficient for Tier 2** and must not be presented as such — it proves the application imports, not that the service boots. Declaring it sufficient would redefine a published promise downward to match what was built, which is exactly what the ADR's *in force* column exists to prevent.

`scripts/ci/tier3-artifact.sh` already contains the boot-and-probe logic to imitate: `systemctl start circuit-breaker`, poll `/livez`, poll `/readyz` to HTTP 200 with a 180-second budget, assert the readiness payload. Read `t3::start_and_wait_ready` before writing Task 1.

`dev-ci.yml` contains the secret-minting idiom to copy — `hexgen`, a Fernet key via `base64.urlsafe_b64encode(os.urandom(32))`, and `::add-mask::` registered before any value is used.

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/artifact-smoke.yml` | The arm64 leg gains boot-and-exercise: service containers, service start, `/readyz` poll. |
| `scripts/release_checklist.py` | Asserts every release-readiness row; exits non-zero on any unsatisfied one. |
| `tests/build/test_release_checklist.py` | The checklist fails on an unsatisfied row and passes on a satisfied one. |
| `tests/build/test_docs_match_tier_table.py` | No docs page promises more than ADR 0005's *in force* column. |
| `.github/workflows/release.yml` | Runs the checklist before `publish`. |
| `docs/adr/0005-verification-tiers-and-platform-support.md` | Tier 2's last column, updated by the commit that adds the evidence. |

---

### Task 1: The boot-and-exercise job

**Files:**
- Modify: `.github/workflows/artifact-smoke.yml`
- Read first: `scripts/ci/tier3-artifact.sh` (`t3::start_and_wait_ready`), `.github/workflows/dev-ci.yml` (the secret-minting step)

**Interfaces:**
- Consumes: the installed `.deb` from the existing `deb-install` job's steps.
- Produces: a job named `deb-boot` that proves install-and-boot on both architectures.

- [ ] **Step 1: Read the two references**

```bash
sed -n '298,360p' scripts/ci/tier3-artifact.sh
grep -n 'Mint ephemeral secrets' -A 20 .github/workflows/dev-ci.yml
grep -n 'BASE_URL\|8080\|listen' scripts/ci/tier3-artifact.sh | head
```

Record: the exact readiness URL and port the packaged service listens on, the poll budget, and the secret-minting block verbatim.

- [ ] **Step 2: Write the failing policy test**

Append to `tests/build/test_artifact_smoke_covers_every_published_format.py` (created in Step 2):

```python
def test_a_boot_job_exists_for_the_tier_two_promise() -> None:
    """ADR 0005 Tier 2 is "install and boot", and it enters force only when a
    job proves boot. --selftest proves the application imports, which is a real
    advance over --version and still not boot."""
    jobs = _jobs()
    assert "deb-boot" in jobs, (
        "artifact-smoke.yml has no boot job. ADR 0005 records Tier 2 as not in "
        "force because 'that job still asserts only that the binary prints a "
        "version'. A self-test does not discharge that promise."
    )
    rendered = yaml.safe_dump(jobs["deb-boot"])
    assert "readyz" in rendered, (
        "the boot job never polls /readyz, so it proves the unit started but "
        "not that the service became ready — which is the half that catches a "
        "failed migration, an unreachable broker or a bad config."
    )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/build/test_artifact_smoke_covers_every_published_format.py -v`

Expected: `test_a_boot_job_exists_for_the_tier_two_promise` FAILS.

- [ ] **Step 4: Add the `deb-boot` job**

Append to `.github/workflows/artifact-smoke.yml`'s `jobs:` map. Replace the port and readiness path with those recorded in Step 1 if they differ.

```yaml
  deb-boot:
    name: Boot the .deb (${{ matrix.arch }})
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-22.04
            arch: amd64
          - os: ubuntu-22.04-arm
            arch: arm64
    runs-on: ${{ matrix.os }}

    # ADR 0005's Tier 2 promise is "install and boot". Until this job existed
    # that row read "not in force" with the reason recorded in the ADR itself:
    # "That job still asserts only that the binary prints a version." A
    # self-test proves the application imports; it does not prove the service
    # starts, migrations apply, or the broker is reachable.
    #
    # A subset of scripts/ci/tier3-artifact.sh's contract, on a hosted runner:
    # start, wait for /livez, wait for /readyz. The dependencies are service
    # containers rather than the packaged units, because this gate is about the
    # application booting, not about the vendored Postgres layout — which the
    # fleet tier already covers.
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: circuitbreaker
          POSTGRES_DB: circuitbreaker
          POSTGRES_PASSWORD: ${{ env.CB_DB_PASSWORD }}
        options: >-
          --health-cmd "pg_isready -U circuitbreaker"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 12
        ports:
          - 5432:5432
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 12
        ports:
          - 6379:6379

    steps:
      # Ephemeral, per-run, never stored. ::add-mask:: is registered before any
      # value is written anywhere, so a later step dumping the environment is
      # redacted rather than leaked. Same idiom as dev-ci.yml's smoke run.
      - name: Mint ephemeral secrets for the boot run
        run: |
          set -euo pipefail
          hexgen() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }
          DB_PASSWORD="$(hexgen)"
          JWT_SECRET="$(hexgen)"
          NATS_TOKEN="$(hexgen)"
          VAULT_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
          for secret in "${DB_PASSWORD}" "${JWT_SECRET}" "${NATS_TOKEN}" "${VAULT_KEY}"; do
            echo "::add-mask::${secret}"
          done
          {
            echo "CB_DB_PASSWORD=${DB_PASSWORD}"
            echo "CB_JWT_SECRET=${JWT_SECRET}"
            echo "CB_NATS_TOKEN=${NATS_TOKEN}"
            echo "CB_VAULT_KEY=${VAULT_KEY}"
          } >> "$GITHUB_ENV"

      - name: Download candidate packages
        uses: actions/download-artifact@v5
        with:
          name: packages-${{ matrix.arch }}
          path: dist/
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - name: Install the candidate set
        run: |
          set -euo pipefail
          sudo apt-get update
          find "$PWD/dist" -name '*.deb' -print0 | xargs -0 sudo apt-get install -y

      - name: Point the service at the ephemeral dependencies
        run: |
          set -euo pipefail
          sudo install -d -m 0750 /etc/circuit-breaker
          sudo tee /etc/circuit-breaker/circuit-breaker.env >/dev/null <<EOF
          CB_DB_URL=postgresql://circuitbreaker:${CB_DB_PASSWORD}@127.0.0.1:5432/circuitbreaker
          CB_REDIS_URL=redis://127.0.0.1:6379/0
          CB_JWT_SECRET=${CB_JWT_SECRET}
          CB_VAULT_KEY=${CB_VAULT_KEY}
          EOF
          sudo chmod 0640 /etc/circuit-breaker/circuit-breaker.env

      - name: Start the service
        run: |
          set -euo pipefail
          sudo systemctl daemon-reload
          sudo systemctl start circuit-breaker

      - name: Wait for /livez
        run: |
          set -euo pipefail
          for _ in $(seq 1 60); do
            curl -fsS http://127.0.0.1:8080/livez >/dev/null 2>&1 && break
            sleep 2
          done
          curl -fsS http://127.0.0.1:8080/livez

      # The half that catches a failed migration, an unreachable dependency or
      # a bad config — all of which leave the unit "active" and the service
      # useless.
      - name: Wait for /readyz
        run: |
          set -euo pipefail
          for _ in $(seq 1 90); do
            code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz)"
            [ "${code}" = "200" ] && break
            sleep 2
          done
          code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/readyz)"
          if [ "${code}" != "200" ]; then
            echo "::error::service never became ready (last /readyz was ${code})"
            curl -s http://127.0.0.1:8080/readyz || true
            sudo journalctl -u circuit-breaker --no-pager -n 100
            exit 1
          fi
          curl -fsS http://127.0.0.1:8080/readyz

      - name: Collect diagnostics on failure
        if: failure()
        run: |
          sudo systemctl status circuit-breaker --no-pager -l || true
          sudo journalctl -u circuit-breaker --no-pager -n 200 || true
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/build/test_artifact_smoke_covers_every_published_format.py -v`

Expected: all pass.

- [ ] **Step 6: Validate the workflow parses**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/artifact-smoke.yml').read_text())
print(sorted(d['jobs']))
assert {'deb-install','tarball-smoke','deb-boot'} <= set(d['jobs'])
print('OK')
"
```

Expected: three job names, then `OK`.

- [ ] **Step 7: Commit — but do NOT update ADR 0005 yet**

```bash
git add .github/workflows/artifact-smoke.yml tests/build/test_artifact_smoke_covers_every_published_format.py
git commit -m "feat: boot the installed package in the release gate

ADR 0005 records Tier 2 as not in force because the arm64 job asserts only
that the binary prints a version. --selftest proved the application imports;
this proves the service starts and becomes ready. Postgres and Redis are
service containers with per-run generated secrets, masked before use.

ADR 0005's tier table is unchanged until this job has passed against a real
candidate — the ADR requires evidence before the claim, not alongside it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: After the job passes against a real candidate, update the ADR**

**This step is deliberately not executable today.** It runs after the first release candidate whose `deb-boot` job is green. At that point, and only then, change ADR 0005's Tier 2 row last column from

```
**Not in force.** That job still asserts only that the binary prints a version.
```

to a sentence naming the candidate and the run, and commit it with the evidence link. The ADR is explicit: "A tier moves into force by a commit that adds the named evidence, at which point this table's last column is updated in the same change. Editing the last column to claim more than the evidence supports is a defect."

---

### Task 2: The release checklist

**Files:**
- Create: `scripts/release_checklist.py`
- Create: `tests/build/test_release_checklist.py`
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `specs/1.0.0/release-control/quarantine-register.csv` (Step 0 Task 1 schema).
- Produces:
  - `evaluate(version: str, repo_root: Path) -> list[ChecklistRow]`
  - `ChecklistRow` — frozen dataclass with `name: str`, `satisfied: bool`, `detail: str`.
  - CLI: `python3 scripts/release_checklist.py --version X.Y.Z`, exit 0 when every row is satisfied, exit 1 otherwise.

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_release_checklist.py`:

```python
"""Release readiness is asserted, not felt.

specs/1.0.0/release-control/ is strong governance scoped to one future
milestone. v0.4.2 shipped with no equivalent: the gap between the rigour of
that directory and how 0.4.2 actually shipped is the disjointedness this whole
design exists to close.

The checklist is generated rather than hand-written on purpose. A hand-written
checklist is a signal, and a signal that can be waved through is the failure
mode documented in §1.9 of the design.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release_checklist.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_checklist_passes_on_the_current_tree() -> None:
    from release_checklist import evaluate

    rows = evaluate(version=(REPO_ROOT / "VERSION").read_text().strip(), repo_root=REPO_ROOT)
    unsatisfied = [row for row in rows if not row.satisfied]
    assert not unsatisfied, "unsatisfied rows: " + "; ".join(
        f"{row.name}: {row.detail}" for row in unsatisfied
    )


def test_checklist_reports_every_expected_row() -> None:
    from release_checklist import evaluate

    rows = evaluate(version=(REPO_ROOT / "VERSION").read_text().strip(), repo_root=REPO_ROOT)
    names = {row.name for row in rows}
    assert names == {
        "changelog_entry",
        "quarantine_register_current",
        "tier_table_matches_evidence",
        "version_parity",
    }, f"unexpected checklist rows: {sorted(names)}"


def test_an_expired_quarantine_fails_the_checklist(tmp_path: Path) -> None:
    """The row that connects Step 0's register to the release gate."""
    from release_checklist import evaluate

    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("9.9.9\n")
    (fake_root / "CHANGELOG.md").write_text("## 9.9.9\n\n- entry\n")
    yesterday = date.today() - timedelta(days=1)
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
        f"QUAR-001,Some Check,tests/x.py,reason,shawnji (release),RISK-010,"
        f"{yesterday - timedelta(days=10)},{yesterday},note\n"
    )
    rows = {row.name: row for row in evaluate(version="9.9.9", repo_root=fake_root)}
    assert not rows["quarantine_register_current"].satisfied
    assert "QUAR-001" in rows["quarantine_register_current"].detail


def test_cli_exits_non_zero_when_a_row_is_unsatisfied(tmp_path: Path) -> None:
    fake_root = tmp_path / "repo"
    (fake_root / "specs" / "1.0.0" / "release-control").mkdir(parents=True)
    (fake_root / "VERSION").write_text("9.9.9\n")
    (fake_root / "CHANGELOG.md").write_text("nothing relevant\n")
    (fake_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv").write_text(
        "quarantine_id,check,scope,reason,owner,tracking,opened,expiry,notes\n"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "9.9.9", "--repo-root", str(fake_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "changelog_entry" in completed.stdout + completed.stderr
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_release_checklist.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'release_checklist'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/release_checklist.py`:

```python
#!/usr/bin/env python3
"""Assert every release-readiness condition for a candidate.

specs/1.0.0/release-control/ governs one future milestone. Nothing governed
v0.4.2, and v0.4.2 shipped a binary with no application in it through a fully
green pipeline. This is the per-release equivalent: generated rather than
hand-written, because a hand-written checklist is one more signal that can be
waved through.

Run by release.yml before publish. Exits non-zero if any row is unsatisfied,
and names the row.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ChecklistRow:
    """One readiness condition and whether the tree satisfies it.

    Attributes:
        name: Stable identifier, used by tests and by the CI summary.
        satisfied: True when the condition holds.
        detail: Human-readable evidence or the reason it does not hold.
    """

    name: str
    satisfied: bool
    detail: str


def _changelog_entry(version: str, repo_root: Path) -> ChecklistRow:
    """The release must be described somewhere a user can read."""
    changelog = repo_root / "CHANGELOG.md"
    if not changelog.exists():
        return ChecklistRow("changelog_entry", False, "CHANGELOG.md is missing")
    text = changelog.read_text(encoding="utf-8")
    if version in text:
        return ChecklistRow("changelog_entry", True, f"CHANGELOG.md mentions {version}")
    return ChecklistRow(
        "changelog_entry",
        False,
        f"CHANGELOG.md has no entry for {version}",
    )


def _quarantine_register_current(repo_root: Path) -> ChecklistRow:
    """No quarantined check may be past its expiry at release time."""
    register = repo_root / "specs" / "1.0.0" / "release-control" / "quarantine-register.csv"
    if not register.exists():
        return ChecklistRow(
            "quarantine_register_current", False, f"{register} is missing"
        )
    today = date.today()
    with register.open(encoding="utf-8", newline="") as handle:
        expired = [
            f"{row['quarantine_id']} ({row['check']}) expired {row['expiry']}"
            for row in csv.DictReader(handle)
            if date.fromisoformat(row["expiry"]) < today
        ]
    if expired:
        return ChecklistRow(
            "quarantine_register_current",
            False,
            "expired quarantine entries: " + "; ".join(expired),
        )
    return ChecklistRow("quarantine_register_current", True, "no expired entries")


def _tier_table_matches_evidence(repo_root: Path) -> ChecklistRow:
    """ADR 0005's in-force column must not claim more than exists.

    Checked structurally rather than semantically: the table must still carry an
    explicit state for every tier. A row whose state cell has been emptied is
    the shape of a claim made by deletion.
    """
    adr = repo_root / "docs" / "adr" / "0005-verification-tiers-and-platform-support.md"
    if not adr.exists():
        return ChecklistRow("tier_table_matches_evidence", False, f"{adr} is missing")
    text = adr.read_text(encoding="utf-8")
    states = re.findall(r"^\|\s*([123])\s*\|.*\|\s*(\*\*.+?\*\*.*?)\s*\|\s*$", text, re.M)
    if len(states) != 3:
        return ChecklistRow(
            "tier_table_matches_evidence",
            False,
            f"expected 3 tier rows with an explicit state, found {len(states)}",
        )
    return ChecklistRow(
        "tier_table_matches_evidence",
        True,
        "; ".join(f"tier {tier}: {state[:40]}" for tier, state in states),
    )


def _version_parity(version: str, repo_root: Path) -> ChecklistRow:
    """Delegates to the existing parity gate rather than reimplementing it."""
    script = repo_root / "scripts" / "check_version_parity.py"
    if not script.exists():
        return ChecklistRow("version_parity", False, f"{script} is missing")
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    if completed.returncode != 0:
        return ChecklistRow(
            "version_parity",
            False,
            (completed.stdout + completed.stderr).strip()[:400],
        )
    return ChecklistRow("version_parity", True, f"parity green for {version}")


def evaluate(version: str, repo_root: Path) -> list[ChecklistRow]:
    """Every readiness row for this candidate, in a stable order."""
    return [
        _changelog_entry(version, repo_root),
        _quarantine_register_current(repo_root),
        _tier_table_matches_evidence(repo_root),
        _version_parity(version, repo_root),
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the checklist and return 0 only when every row is satisfied."""
    parser = argparse.ArgumentParser(description="Assert release readiness.")
    parser.add_argument("--version", required=True, help="Candidate version, e.g. 0.4.3")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to evaluate.",
    )
    args = parser.parse_args(argv)

    rows = evaluate(version=args.version, repo_root=Path(args.repo_root))
    width = max(len(row.name) for row in rows)
    for row in rows:
        mark = "PASS" if row.satisfied else "FAIL"
        print(f"[{mark}] {row.name.ljust(width)}  {row.detail}")

    unsatisfied = [row.name for row in rows if not row.satisfied]
    if unsatisfied:
        print(f"\nRelease blocked: {', '.join(unsatisfied)}", file=sys.stderr)
        return 1
    print("\nRelease checklist satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/build/test_release_checklist.py -v`

Expected: 4 passed. If `test_checklist_passes_on_the_current_tree` fails, read the named row — it is telling you the tree is genuinely not release-ready, which is the script working.

- [ ] **Step 5: Run it by hand**

```bash
python3 scripts/release_checklist.py --version "$(cat VERSION)"; echo "exit=$?"
```

Expected: four `[PASS]` lines and `exit=0`, or a named failing row.

- [ ] **Step 6: Wire it into `release.yml` before publish**

In `.github/workflows/release.yml`, in the `publish` job, immediately after the `actions/checkout@v5` step:

```yaml
      # specs/1.0.0/release-control/ governs a future milestone. Nothing
      # governed v0.4.2. This is the per-release equivalent, and it runs before
      # anything is attached to a Release.
      - name: Assert release readiness
        env:
          VERSION: ${{ needs.version.outputs.version }}
        run: python3 scripts/release_checklist.py --version "${VERSION}"
```

- [ ] **Step 7: Validate and commit**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/release.yml').read_text())
names = [s.get('name') for s in d['jobs']['publish']['steps']]
assert any('release readiness' in str(n) for n in names), names
print('OK')
"
make lint
git add scripts/release_checklist.py tests/build/test_release_checklist.py .github/workflows/release.yml
git commit -m "feat: assert release readiness before publishing

Generated rather than hand-written: a hand-written checklist is one more signal
that can be waved through. Asserts a CHANGELOG entry, no expired quarantine,
an explicit state for every ADR 0005 tier, and version parity. Runs in the
publish job before anything is attached to a Release.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Documentation may not promise more than the tier table supports

**Files:**
- Create: `tests/build/test_docs_match_tier_table.py`
- Modify: `docs/installation/quick-install.md`

- [ ] **Step 1: Write the failing test**

Create `tests/build/test_docs_match_tier_table.py`:

```python
"""No page may promise a guarantee ADR 0005 records as not in force.

quick-install.md leads with

    curl -fsSL .../install.sh | bash

which installs the tarball — which ADR 0005 places at Tier 3, "guaranteed to
build only". The two statements were individually honest and jointly
indefensible: the most prominently documented way to install Circuit Breaker
carried the weakest guarantee attached.

The ADR already requires that docs/release/1.0.0-support-contract.md publish no
tier language while any row reads *not in force*. This extends that rule to
every page, mechanically, so the contradiction cannot reappear by someone
editing a different file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "docs" / "adr" / "0005-verification-tiers-and-platform-support.md"
QUICK_INSTALL = REPO_ROOT / "docs" / "installation" / "quick-install.md"

# Phrases that assert a working install rather than describing how to attempt one.
OVERPROMISE = re.compile(
    r"\b(guaranteed to (install|boot|work)|fully (tested|verified) on|"
    r"production[- ]ready on every)\b",
    re.IGNORECASE,
)


def _tier_states() -> dict[str, str]:
    text = ADR.read_text(encoding="utf-8")
    return {
        tier: state
        for tier, state in re.findall(
            r"^\|\s*([123])\s*\|.*\|\s*(\*\*.+?\*\*.*?)\s*\|\s*$", text, re.M
        )
    }


def test_the_adr_still_states_every_tier() -> None:
    states = _tier_states()
    assert set(states) == {"1", "2", "3"}, (
        f"ADR 0005's in-force table no longer states all three tiers: {sorted(states)}. "
        "Every assertion below reads that table, so they would pass vacuously."
    )


def test_quick_install_does_not_overpromise() -> None:
    text = QUICK_INSTALL.read_text(encoding="utf-8")
    hits = OVERPROMISE.findall(text)
    assert not hits, (
        f"quick-install.md asserts {hits}, which ADR 0005's in-force column does "
        "not support. The tarball this page leads with is Tier 3 — guaranteed to "
        "build only — until the tarball smoke, boot and installer-journey jobs "
        "are green against a candidate."
    )


def test_quick_install_states_what_is_actually_verified() -> None:
    """Silence about the guarantee is how the contradiction survived."""
    text = QUICK_INSTALL.read_text(encoding="utf-8").lower()
    assert "verification tiers" in text or "adr 0005" in text, (
        "quick-install.md does not point at the tier table at all. A reader "
        "cannot discover what is guaranteed about the path this page recommends."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_docs_match_tier_table.py -v`

Expected: `test_quick_install_states_what_is_actually_verified` FAILS.

- [ ] **Step 3: Add the accurate note to `docs/installation/quick-install.md`**

Immediately after the first `curl … | bash` block, insert:

```markdown
> **What is verified about this path.** Every release builds this tarball, and
> the release gate unpacks it, checks the bundle layout, and asserts the binary
> can load the application it serves. Installing and booting from it is verified
> by the installer-journey job; see
> [ADR 0005 — Verification tiers and platform support](../adr/0005-verification-tiers-and-platform-support.md)
> for exactly which guarantees are in force today. Packages (`.deb`, `.rpm`)
> carry the strongest guarantees.
```

**Accuracy requirement:** this note describes Steps 2 and 3 of this plan. Do not add the sentence about the installer-journey job until Step 7's plan has landed — until then, write the note without that clause. A documentation page claiming a gate that does not exist is the same defect in the opposite direction.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/build/test_docs_match_tier_table.py -v`

Expected: 3 passed.

- [ ] **Step 5: Run the docs build**

Run: `mkdocs build --strict 2>&1 | tail -20`

Expected: clean. A relative link that does not resolve fails `--strict`, and the note above adds one.

- [ ] **Step 6: Commit**

```bash
git add tests/build/test_docs_match_tier_table.py docs/installation/quick-install.md
git commit -m "docs: quick-install states what is actually guaranteed

The page leads with curl|bash, which installs the tarball — ADR 0005's Tier 3,
guaranteed to build only. Both statements were honest; together they promised
the most prominent install path with the weakest guarantee. Adds the note and a
policy test so the contradiction cannot reappear from a different file.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `pytest tests/build -q` passes.
- [ ] `make lint` and `make verify` pass.
- [ ] `python3 scripts/release_checklist.py --version "$(cat VERSION)"` exits 0.
- [ ] `mkdocs build --strict` is clean.
- [ ] `artifact-smoke.yml` parses and contains `deb-install`, `tarball-smoke`, `deb-boot`.
- [ ] `release.yml`'s `publish` job runs the checklist before attaching anything.
- [ ] **ADR 0005's Tier 2 row is unchanged.** It is updated only by the later commit that records a green `deb-boot` run against a real candidate (Task 1 Step 8).

## What this plan does NOT cover

`deb-boot` has not executed. Nothing here starts a packaged service locally; the job is verified by YAML parsing and policy tests only, and its first real run is on the next release candidate. Task 1 Step 8 — the ADR update — is explicitly deferred to that run, and moving it earlier would be the exact defect ADR 0005 names: claiming more than the evidence supports.
