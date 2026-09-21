# Step 6 — Upgrade, Uninstall and the Diagnostic Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the progress renderer to the other two flows a human watches start to finish, and give an operator one redacted file to hand over when something goes wrong.

**Architecture:** `uninstall.sh` and `run_upgrade` source the same `deploy/lib/ui.sh` and declare their own phase tables — the library needs no change beyond supporting a second weight table. `cb diag bundle` collects the existing diagnostic sources into one tarball, reusing `cb_env_redacted` and the CLI's existing redaction rather than writing new masking.

**Tech Stack:** Bash 5.x, pytest, `tar`.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §25, §26.

**Depends on:** Step 5 (`deploy/lib/ui.sh` must exist), Step 1 (`--selftest`, which the bundle captures).

## Global Constraints

- **No placeholders.**
- **Backward compatible.** `uninstall.sh` and the upgrade path keep every existing flag and behaviour.
- **Secrets never leave the host in the clear.** The diagnostic bundle is the highest-risk artifact in this whole design: it exists to be pasted into a public issue. Reuse `cb_env_redacted` and the CLI's existing redaction helpers; write no new masking regex without a test that proves it.
- **Air-gap is first-class.** `cb diag bundle` makes no outbound call and never uploads anything. It writes a file and prints its path.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan does not touch `apps/backend/src/app`, so `make verify` is the gate. It does not execute `uninstall.sh` against a real install; see "What this plan does NOT cover".
- `uninstall.sh` runs under **`set -e`** (not `set -euo pipefail`) — check before relying on pipefail semantics.

## Background an implementer needs

`uninstall.sh` is 476 lines. `run_upgrade` lives in `deploy/setup.sh` and is reached from `install.sh::main` when `UPGRADE_MODE=true`. Its pre-upgrade backup dominates elapsed time, which is why it gets a phase of its own.

`tests/build/test_uninstall_tty_preflight.py` and `test_uninstall_volume_prompt.py` already assert behaviour about `uninstall.sh`'s terminal handling and its prompts. Read both before touching that file — the prompt behaviour is a contract, and a progress bar must not eat a question.

`tests/build/test_pre_upgrade_backup.py` extracts `run_upgrade`'s backup block by regex, anchored on `cb_step "Creating pre-upgrade backup"`. **Changing that line breaks the test**, which is the test working: it exists because `|| true` once turned a failed backup into a success.

## File Structure

| File | Responsibility |
|---|---|
| `deploy/lib/ui.sh` | Gains `cb_ui_use_weights`, so a flow can install its own phase table. |
| `uninstall.sh` | Four phases; sources the library. |
| `deploy/setup.sh` | `run_upgrade` gains five phases. |
| `deploy/cli/cb` | `cb diag bundle`. |
| `tests/build/test_installer_phase_model.py` | Extended to cover all three weight tables. |
| `tests/build/test_diag_bundle_redaction.py` | No secret pattern survives into the bundle. |

---

### Task 1: Let a flow install its own phase table

**Files:**
- Modify: `deploy/lib/ui.sh`
- Modify: `tests/build/test_installer_phase_model.py`

**Interfaces:**
- Produces: `cb_ui_use_weights <name>` — swaps `CB_PHASE_WEIGHTS` for the named table. Tables are `CB_PHASE_WEIGHTS_INSTALL`, `CB_PHASE_WEIGHTS_UPGRADE`, `CB_PHASE_WEIGHTS_UNINSTALL`.

- [ ] **Step 1: Write the failing test**

Extend `tests/build/test_installer_phase_model.py`. Replace `_declared_weights()` with a version that takes a table name, and parametrise every existing assertion across all three tables:

```python
import pytest

TABLES = {
    "CB_PHASE_WEIGHTS_INSTALL": REPO_ROOT / "install.sh",
    "CB_PHASE_WEIGHTS_UPGRADE": REPO_ROOT / "deploy" / "setup.sh",
    "CB_PHASE_WEIGHTS_UNINSTALL": REPO_ROOT / "uninstall.sh",
}


def _declared_weights(table: str) -> dict[str, int]:
    text = UI.read_text(encoding="utf-8")
    block = re.search(rf"declare -gA {table}=\((.*?)\)", text, re.DOTALL)
    assert block, f"{table} not found in deploy/lib/ui.sh"
    return {key: int(value) for key, value in re.findall(r"\[(\w+)\]=(\d+)", block.group(1))}


@pytest.mark.parametrize("table", sorted(TABLES))
def test_weights_sum_to_one_hundred(table: str) -> None:
    weights = _declared_weights(table)
    total = sum(weights.values())
    assert total == 100, f"{table} sums to {total}, not 100: {weights}"


@pytest.mark.parametrize("table,script", sorted(TABLES.items()))
def test_every_runtime_phase_is_declared(table: str, script: Path) -> None:
    declared = set(_declared_weights(table))
    used = set(re.findall(r"cb_phase_(?:begin|end)\s+([a-z_]+)", script.read_text(encoding="utf-8")))
    assert used, f"no cb_phase_begin/end calls found in {script.name}"
    undeclared = used - declared
    assert not undeclared, (
        f"{script.name} opens phases {sorted(undeclared)} that {table} does not "
        "declare, so they contribute no weight and the bar jumps."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_installer_phase_model.py -v`

Expected: FAIL — the three named tables do not exist.

- [ ] **Step 3: Add the tables and the switch to `deploy/lib/ui.sh`**

Replace the single `CB_PHASE_WEIGHTS` declaration with three named tables plus the switch. Keep `CB_PHASE_WEIGHTS` as the live table the renderer reads, so nothing else in the library changes.

```sh
# One table per flow. A phase is a unit of elapsed time a user can feel, so the
# three flows weight differently: an uninstall is dominated by stopping services
# and removing a data directory, an upgrade by its pre-upgrade backup.
declare -gA CB_PHASE_WEIGHTS_INSTALL=(
  [preflight]=2 [bundle]=12 [files]=6 [deps]=45 [database]=15 [services]=12 [start]=8
)
declare -gA CB_PHASE_WEIGHTS_UPGRADE=(
  [preflight]=5 [backup]=40 [bundle]=20 [apply]=20 [start]=15
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
```

`local -n` needs bash 4.3+. `install.sh`'s `cb_replace_all` already uses it, so the floor is established.

- [ ] **Step 4: Call it from each flow**

In `install.sh::main`, immediately after `cb_ui_init`:

```sh
  if [[ "${UPGRADE_MODE}" == "true" ]]; then
    cb_ui_use_weights CB_PHASE_WEIGHTS_UPGRADE
  else
    cb_ui_use_weights CB_PHASE_WEIGHTS_INSTALL
  fi
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/build/test_installer_phase_model.py -v`

Expected: the install table passes; upgrade and uninstall still fail on `test_every_runtime_phase_is_declared` because those scripts have no phase calls yet. That is correct — Tasks 2 and 3 fix it.

- [ ] **Step 6: Commit**

```bash
git add deploy/lib/ui.sh install.sh tests/build/test_installer_phase_model.py
git commit -m "feat: let each installer flow declare its own phase weights

An uninstall is dominated by stopping services and removing a data directory,
an upgrade by its pre-upgrade backup. One table each, one switch, and the
renderer still reads a single live table.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Phases for `uninstall.sh`

**Files:**
- Modify: `uninstall.sh`

- [ ] **Step 1: Read the existing contracts first**

```bash
pytest tests/build -k uninstall -v
grep -n 'read \|prompt\|confirm\|-t 0\|tty' uninstall.sh | head -20
```

`test_uninstall_tty_preflight.py` and `test_uninstall_volume_prompt.py` assert how this script behaves around a terminal and a prompt. **A live progress region must never be drawn while a prompt is waiting** — that is exactly the "prompt goes somewhere nobody sees" failure the installer's own header comment documents.

- [ ] **Step 2: Source the library and initialise**

Near the top of `uninstall.sh`, after its colour codes:

```sh
# Same renderer as the installer. The bundle's copy is authoritative; a
# standalone uninstall.sh downloaded on its own falls back to plain output,
# which the library selects on its own when the library is absent.
if [[ -r /opt/circuitbreaker/deploy/lib/ui.sh ]]; then
  # shellcheck source=deploy/lib/ui.sh
  source /opt/circuitbreaker/deploy/lib/ui.sh
  cb_ui_init
  cb_ui_use_weights CB_PHASE_WEIGHTS_UNINSTALL
fi
```

**Guard every call.** Because the library may be absent, wrap each phase call:

```sh
_cb_phase() { declare -f "$1" >/dev/null 2>&1 && "$@"; return 0; }
```

and call `_cb_phase cb_phase_begin stop "Stopping services"`. This keeps a standalone uninstall working with no renderer at all.

- [ ] **Step 3: Tear the live region down before every prompt**

Find each prompt in `uninstall.sh` and precede it with:

```sh
  _cb_phase cb_ui_teardown
```

This is not optional. A question drawn under a redrawing bar is a hung uninstall.

- [ ] **Step 4: Declare the four phases**

Wrap the script's existing work:

**`uninstall.sh` is Docker-only.** It requires `docker` (line 69), targets the
container `circuit-breaker` and the volume `circuit-breaker-data`, and contains no
`systemctl` calls at all — `docs/installation/uninstalling.md:83` states this
outright. The native uninstaller is a different program
(`deploy/cli/cb:1889` execs `/usr/local/bin/uninstall-circuit-breaker`) and is NOT
in scope here. Phase the script for what it does:

- `preflight` — "Pre-flight checks": docker availability, container detection, confirmation prompt
- `stop` — "Stopping the container": `docker stop`
- `remove` — "Removing the container": `docker rm` of the container and its `-prev` sibling
- `cleanup` — "Removing data": `docker volume rm`, behind the existing prompt

- [ ] **Step 5: Verify**

```bash
bash -n uninstall.sh && echo "syntax OK"
pytest tests/build -k uninstall -v
pytest tests/build/test_installer_phase_model.py -v
```

Expected: syntax clean, the uninstall suites pass **unedited**, and the uninstall table's phase assertions now pass.

- [ ] **Step 6: Commit**

```bash
git add uninstall.sh
git commit -m "feat: give uninstall.sh the same four-phase progress display

Every prompt tears the live region down first: a question drawn under a
redrawing bar is a hung uninstall, which is the failure the installer's own
header comment already documents for debconf.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Phases for `run_upgrade`

**Files:**
- Modify: `deploy/setup.sh` — `run_upgrade`

- [ ] **Step 1: Read the backup contract**

```bash
sed -n '/^run_upgrade()/,/^}/p' deploy/setup.sh | head -60
pytest tests/build/test_pre_upgrade_backup.py -v
```

`test_pre_upgrade_backup.py` extracts the backup block by regex anchored on `cb_step "Creating pre-upgrade backup"`. **Do not change that line.** It exists because `|| true` once turned a failed backup into a reported success.

- [ ] **Step 2: Declare the five phases**

Wrap `run_upgrade`'s existing work, leaving the anchored `cb_step` line exactly as it is:

- `preflight` — "Pre-flight checks"
- `backup` — "Creating pre-upgrade backup" (weight 40; it dominates)
- `bundle` — "Installing new version"
- `apply` — "Applying configuration and migrations"
- `start` — "Restarting Circuit Breaker"

- [ ] **Step 3: Verify**

```bash
bash -n deploy/setup.sh && echo "syntax OK"
pytest tests/build/test_pre_upgrade_backup.py -v
pytest tests/build/test_installer_phase_model.py -v
```

Expected: all pass, `test_pre_upgrade_backup.py` **unedited**.

- [ ] **Step 4: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat: give the upgrade path five phases

The pre-upgrade backup gets a phase and 40% of the weight because it dominates
elapsed time. Its cb_step anchor line is untouched — test_pre_upgrade_backup.py
extracts the block by that string, and it exists because a || true once turned a
failed backup into a reported success.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `cb diag bundle`

**Files:**
- Modify: `deploy/cli/cb`
- Create: `tests/build/test_diag_bundle_redaction.py`

**Interfaces:**
- Produces: `cb diag bundle [--output <path>]`, writing a `.tar.gz` and printing its path.

**This is the highest-risk artifact in the design.** It exists to be pasted into a public issue.

- [ ] **Step 1: Write the failing redaction test**

```python
"""Nothing secret may survive into a bundle meant for a public issue.

`cb diag bundle` exists so an operator can hand over one file. That makes it the
highest-risk artifact in the installer design: everything it collects —
/etc/circuitbreaker/.env, journal output, the install log — has held a JWT
secret, a vault key or a database password at some point.

The redaction is not new here. cb_env_redacted already masks secrets and
credentials embedded in connection URLs, and the CLI has its own helpers. This
suite asserts the bundle actually uses them, against planted values, because a
redaction that is called on three of four inputs looks identical to one that
works.
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CB = REPO_ROOT / "deploy" / "cli" / "cb"

# Planted values. Distinctive enough that a hit is unambiguous, and generated
# shapes rather than realistic-looking credentials.
PLANTED = {
    "CB_JWT_SECRET": "PLANTEDJWTSECRETdeadbeefdeadbeefdeadbeef",
    "CB_VAULT_KEY": "PLANTEDVAULTKEYdeadbeefdeadbeefdeadbeefAA=",
    "CB_DB_PASSWORD": "PLANTEDDBPASSWORDdeadbeef",
}


def _fake_install(root: Path) -> Path:
    etc = root / "etc" / "circuitbreaker"
    etc.mkdir(parents=True)
    env = "\n".join(f"{key}={value}" for key, value in PLANTED.items())
    env += (
        f"\nCB_DB_URL=postgresql://breaker:{PLANTED['CB_DB_PASSWORD']}"
        "@127.0.0.1:6432/circuitbreaker\n"
    )
    (etc / ".env").write_text(env)
    logs = root / "var" / "lib" / "circuitbreaker" / "logs"
    logs.mkdir(parents=True)
    (logs / "install.log").write_text(
        f"starting with CB_JWT_SECRET={PLANTED['CB_JWT_SECRET']}\n"
    )
    return root


def test_no_planted_secret_appears_in_the_bundle(tmp_path: Path) -> None:
    root = _fake_install(tmp_path / "root")
    output = tmp_path / "bundle.tar.gz"
    completed = subprocess.run(
        ["bash", str(CB), "diag", "bundle", "--output", str(output)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CB_ROOT_PREFIX": str(root)},
        check=False,
    )
    assert output.exists(), (
        "cb diag bundle produced no file:\n" + completed.stdout + completed.stderr
    )

    leaked: list[str] = []
    with tarfile.open(output) as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            extracted = handle.extractfile(member)
            assert extracted is not None
            content = extracted.read().decode("utf-8", errors="replace")
            for name, value in PLANTED.items():
                if value in content:
                    leaked.append(f"{name} in {member.name}")
    assert not leaked, (
        "the diagnostic bundle contains unredacted secrets: "
        + "; ".join(leaked)
        + ". This file is meant to be pasted into a public issue."
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/build/test_diag_bundle_redaction.py -v`

Expected: FAIL — `cb diag bundle` does not exist.

- [ ] **Step 3: Read the CLI's existing shape**

```bash
grep -n 'doctor\|^cmd_\|case "\$1"\|usage' deploy/cli/cb | head -40
grep -n 'CB_ROOT_PREFIX\|redact' deploy/cli/cb | head
```

Follow the existing subcommand idiom exactly. If `CB_ROOT_PREFIX` does not exist, add it as a documented test seam defaulting to empty — the redaction test needs to point the CLI at a fixture tree, and a seam that only tests use is honest as long as it is documented as such.

- [ ] **Step 4: Implement `cb diag bundle`**

Collect into a temporary directory, then tar it:

| File in bundle | Source |
|---|---|
| `install.log` | `${CB_DATA_DIR}/logs/install.log`, tail 500 |
| `doctor.json` | `cb doctor --json` |
| `selftest.txt` | `circuit-breaker --selftest` output and exit code |
| `units.txt` | `systemctl status` for each `circuitbreaker-*` unit |
| `journal.txt` | `journalctl -u 'circuitbreaker-*' -n 500 --no-pager` |
| `identity.json` | the install identity record |
| `env.redacted` | `cb_env_redacted` output |
| `manifest.txt` | version, OS, arch, date, and the bundle's own file list |

**Do NOT reuse `_redact_evidence` verbatim.** Read `deploy/cli/cb:72` first. It
truncates to 500 characters (`print(text[:500])`, and `${text:0:500}` in the
fallback) because it is built for short doctor evidence tails — piping a 500-line
log through it yields the first 500 *characters*. Worse, its fallback when
`python3` is absent redacts **nothing**; it only truncates, which on a file meant
for a public issue is a secret leak.

Implement `_redact_stream` instead: the same four substitution patterns plus the
same env-value replacement, reading stdin and writing stdout, **with no
truncation**. It must **fail closed** — if `python3` is unavailable, `cb diag
bundle` refuses to produce a bundle and says why. A missing interpreter must never
downgrade to shipping logs in the clear.

Include this comment above the function:

```sh
# Everything here is written to be pasted into a public issue, so every source
# goes through the redaction that source already has — cb_env_redacted for the
# env file, the CLI's own masking for doctor output — and nothing is added
# without a matching assertion in tests/build/test_diag_bundle_redaction.py.
#
# Never uploads. The air-gap contract forbids an outbound call, and an operator
# handing over a file should be the one who decides where it goes.
```

Redact `install.log` and `journal.txt` through `_redact_stream` — those are the
two that carry planted values in the test, and both are far longer than 500
characters.

- [ ] **Step 5: Add it to `cb_fail`'s hints**

In `install.sh::cb_fail`, after the `Re-run with full output` line:

```sh
  echo -e "  ${BOLD}Collect everything for an issue:${RESET}  cb diag bundle"
```

- [ ] **Step 6: Run the tests**

```bash
pytest tests/build/test_diag_bundle_redaction.py -v
pytest tests/build -k cli -v
bash deploy/cli/cb diag bundle --output /tmp/cb-diag.tar.gz && tar -tzf /tmp/cb-diag.tar.gz
```

Expected: the redaction test passes, the CLI contract suites pass, and the bundle lists the eight files above.

- [ ] **Step 7: Commit**

```bash
git add deploy/cli/cb tests/build/test_diag_bundle_redaction.py install.sh
git commit -m "feat: add cb diag bundle

One redacted file an operator can hand over. Every source goes through the
redaction it already had, and a test plants secrets in the env file, the DB URL
and the install log and fails if any survives — because a redaction called on
three of four inputs looks identical to one that works.

Never uploads: the air-gap contract forbids it, and where the file goes is the
operator's decision.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `pytest tests/build -q`, `make lint`, `make verify` pass.
- [ ] `bash -n` clean for `install.sh`, `uninstall.sh`, `deploy/setup.sh`, `deploy/lib/ui.sh`.
- [ ] All three weight tables sum to 100 and cover every phase their script opens.
- [ ] `test_uninstall_tty_preflight.py`, `test_uninstall_volume_prompt.py` and `test_pre_upgrade_backup.py` pass **unedited**.
- [ ] `cb diag bundle` produces a tarball containing all eight files and no planted secret.
- [ ] Every prompt in `uninstall.sh` is preceded by a live-region teardown.

## What this plan does NOT cover

Nothing here runs `uninstall.sh` against a real installation, and nothing runs an upgrade. Both are verified by syntax checks and policy tests only. The upgrade-and-rollback contract is exercised by `scripts/ci/tier3-artifact.sh` for deb and rpm — **not for the tarball**, which Step 7 adds. Before merging, run the uninstall by hand on a throwaway VM with a real install on it and say in the PR which distro it was.
