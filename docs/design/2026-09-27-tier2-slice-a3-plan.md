# Tier 2 Slice A3 — `mono-smoke.yml`, the Tier's Third Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull the mono image smoke out of `dev-ci.yml`'s `build-docker` job into a reusable
`mono-smoke.yml`, make it Tier 2's third suite (`"mono"`), and give it one definition shared with a new
`make verify-composed-mono`, without ever weakening the rule that `:dev`/`:nightly` are pushed only for an
image that has already started, migrated, reached `/readyz` and stopped cleanly.

**Architecture:** `mono-smoke.yml` builds the image, smokes it through `scripts/ci/tier2-mono-smoke.sh`,
and, only when its `publish` input is true and the event is a push to `dev`, pushes the image **in the
same job**. That same-job push is the maintainer decision below.

`mono-smoke.yml` declares **no `permissions:` block**, so every job inherits the calling job's
`GITHUB_TOKEN` grant:
- `dev-ci.yml` grants `packages: write`, so it can publish.
- `tier2.yml`, `release.yml` and `release-dry-run.yml` grant read only, so their mono runs *cannot* push.
  The capability is decided by the caller's grant, not by an `if:`.

`tier2.yml` gains a `mono` job. `tier2_gate.py` learns the suite.

**Tech Stack:** GitHub Actions reusable workflows, bash (`scripts/ci/lib/common.sh`), Docker Compose,
Python stdlib (3.10 floor), pytest, GNU make.

**Spec:** [`docs/design/2026-09-27-tier2-composed-and-triage-design.md`](./2026-09-27-tier2-composed-and-triage-design.md),
slice A3 of §9, together with §3.1's `mono-smoke.yml` row and §7.4. The A2 plan
([`2026-09-27-tier2-slice-a2-plan.md`](./2026-09-27-tier2-slice-a2-plan.md)) shows the conventions:
per-suite scripts, `tests/build/test_tier2_wiring.py` and `tier2_gate.KNOWN_SUITES`.

**Prerequisites:** branch from `origin/dev` **after #195 merges**. #195 makes the permissions guard pass a
caller's grant down through a job that declares none. Without it, the guard would skip `mono-smoke.yml`
silently. #194 (clean stops) should also be in, because this suite asserts SIGTERM handling.

## Maintainer decisions

1. **2026-09-27: the push moves into the called workflow.** The built image never leaves the runner that
   smoke-tested it; there is no image-as-artifact transport. Push is **off by default** (`publish: false`),
   and only `dev-ci.yml` turns it on.
2. **Proposed in this plan, flagged for confirmation: the release path adds `"mono"`.**
   - Maintainer decision 1 of A2 excluded only the composed journey from the release. Design §10.2's
     "the release runs the whole tier" still stands for browser and mono.
   - Task 4 therefore sets release and dry-run `suites` to `["browser","mono"]`.
   - The cost is one extra amd64 image build on the release path.
   - To reverse, set it back to `["browser"]` in both files. `test_the_release_runs_browser_and_mono`
     pins the value either way.

## Global Constraints

- Everything in the A2 plan's Global Constraints still applies:
  - stdlib Python with a 3.10 floor;
  - tier scripts start `#!/usr/bin/env bash` and `set -euo pipefail`, source `common.sh`, have no
    `|| true`, and are executable and listed in `TIER_SCRIPTS`;
  - `persist-credentials: false`, actions pinned by tag, `env:` indirection for every `${{ }}` in `run:`;
  - checkov reports 0 failed;
  - the commit trailer is `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, with no session
    links.
- **The smoke's assertions move verbatim.** They move from `dev-ci.yml`'s `build-docker` steps into
  `scripts/ci/tier2-mono-smoke.sh`. Each existing step becomes a function carrying its full comment block:
  the comments there record why each assertion exists and must survive.
  - The one sanctioned change: `|| true` is banned in tier scripts. The two places that read
    `supervisorctl status` output use `if ! …; then :; fi` or an explicit `status=$?` capture instead, and
    keep the same semantics.
- **No new secrets.** The four smoke secrets stay ephemeral: minted per run, `::add-mask::`ed only when
  `GITHUB_ACTIONS=true`, written with `umask 077`, and shredded in an `EXIT` trap.
- **Only the push step may use the token for writing.** No other step in `mono-smoke.yml` references
  `GITHUB_TOKEN`.
- **Check names change.** `Build Docker (smoke test)` becomes `Build Docker (smoke test) / Mono image
  smoke`. It is not a required check (`tests/build/required_checks.py` does not list it). Verify that, and
  state it in the PR.

## Review Focus

1. **`publish: true` on a pull request must never push.** The push keeps
   `if: inputs.publish && github.event_name == 'push' && github.ref == 'refs/heads/dev'`. Inside a called
   workflow, `github` is the caller's context, so this still reads dev-ci's event. →
   `test_mono_push_is_gated_on_publish_and_a_push_to_dev`.
2. **A caller that grants only read access must be accepted by the permissions guard, not flagged.**
   `mono-smoke.yml` declares nothing, so it inherits. Its push must be impossible without a write grant,
   and the guard must neither skip it nor demand a grant the release path must not have. →
   `test_mono_smoke_inherits_its_callers_grant`, plus the guard running green with read-only tier2 and
   release callers.
3. **The provenance artifact dev-ci's `runtime-parity` job downloads must keep its name**
   (`dev-image-build-info-amd64`) and be produced in the same run. → the `provenance_artifact` input, and a
   wiring test tying dev-ci's `with:` to `runtime-parity`'s download name.
4. **`:nightly` must still wait for `artifact-smoke`.** `test_release_promote_contract.py::test_nightly_publish_waits_for_artifact_smoke`
   follows the step into `mono-smoke.yml`, and `build-docker` keeps `needs: [artifact-smoke]`.
5. **The smoke secrets must never outlive the script**, even when an assertion fails halfway. → an `EXIT`
   trap tears down compose and shreds `.env`, and a test asserts the trap exists and names `shred`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ci/tier2-mono-smoke.sh` | **Create.** `tier2-mono-smoke.sh IMAGE_TAG`: mints secrets, runs `compose up`, and asserts livez, readyz, the HTTP→TLS redirect, the SPA over TLS, every supervisord program, zero restarts and a clean SIGTERM stop. Writes diagnostics to `artifacts/diagnostics/`. An EXIT trap tears down. |
| `.github/workflows/mono-smoke.yml` | **Create.** `name: Mono image smoke (suite)`, `workflow_call` only. Inputs: `ref`, `publish` (bool, default false), `provenance_artifact` (string, default ""). One job: build → provenance → agent-binaries check → script → push → diagnostics. **No `permissions:`.** |
| `.github/workflows/dev-ci.yml` | **Modify.** `build-docker` becomes a caller (`needs: [artifact-smoke]`, `permissions: {contents: read, packages: write}`, `with: publish: true, provenance_artifact: dev-image-build-info-amd64`). |
| `.github/workflows/tier2.yml` | **Modify.** Adds a `mono` job (`contents: read`, `actions: read`) calling `mono-smoke.yml` with `ref`. `result.needs` gains `mono`. |
| `.github/workflows/release.yml`, `release-dry-run.yml` | **Modify.** `suites: '["browser","mono"]'` (decision 2). |
| `scripts/ci/tier2_gate.py` | **Modify.** `KNOWN_SUITES` and `DEFAULT_SUITES` gain `"mono"`. |
| `Makefile` | **Modify.** `verify-composed-mono` builds `circuitbreaker:local-smoke` and calls the script. `verify-composed` gains it. |
| `tests/build/test_reusable_workflow_permissions.py` | **Modify.** Adds an explicit, reasoned allowlist for called-only workflows that inherit (marker comment `# permissions: inherited-from-caller`). |
| `tests/build/test_tier2_wiring.py`, `test_tier2_gate.py`, `test_ci_script_contract.py`, `test_ci_evidence_retention.py`, `test_release_promote_contract.py` | **Modify.** They follow the move (details per task). |
| Design doc, `CLAUDE.md` Tier 2 row, cb-build-test skill | **Modify.** Record A3 and the inheritance decision. |

---

## Task 1: The smoke becomes one script

**Files:**
- Create `scripts/ci/tier2-mono-smoke.sh`.
- Modify `tests/build/test_ci_script_contract.py` (`TIER_SCRIPTS`).
- Create `tests/build/test_tier2_mono_smoke_script.py`.

**Interfaces:** Produces `scripts/ci/tier2-mono-smoke.sh IMAGE` (exit 2 on a missing or extra argument).
It uses ports `CB_SMOKE_PORT` (default 18080) and `CB_SMOKE_PORT_HTTPS` (default 18443) and the data dir
`${RUNNER_TEMP:-$CB_REPO_ROOT/.smoke-tmp}/cb-smoke-data`, and writes `artifacts/diagnostics/{compose-ps.txt,container.log,inspect.json,supervisor-status.txt,readyz.json}`.

- [ ] **Step 1: Write the failing tests** in `tests/build/test_tier2_mono_smoke_script.py`:

```python
"""The mono smoke has one definition: scripts/ci/tier2-mono-smoke.sh."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "tier2-mono-smoke.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_requires_exactly_one_image_argument():
    for argv in ([], ["a", "b"]):
        result = subprocess.run(["bash", str(SCRIPT), *argv], capture_output=True, text=True,
                                cwd=REPO_ROOT, env={"PATH": "/usr/bin:/bin"})
        assert result.returncode == 2, result.stderr
        assert "image" in result.stderr.lower()


def test_every_dev_ci_assertion_moved_into_the_script():
    """Each probe the build-docker job ran must still run, by its distinctive command."""
    text = _text()
    for needle in (
        "/api/v1/livez", "grep -q '\"alive\"'", "/api/v1/readyz",
        "http://127.0.0.1:${CB_SMOKE_PORT}/", "301",
        "https://127.0.0.1:${CB_SMOKE_PORT_HTTPS}/", '<div id="root"',
        "supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status",
        "for proc in postgres nats redis backend-api nginx",
        "{{.RestartCount}}", "stop -t 30",
    ):
        assert needle in text, f"tier2-mono-smoke.sh lost the assertion containing {needle!r}"


def test_the_secrets_never_outlive_the_script():
    text = _text()
    assert "trap" in text and "EXIT" in text, "no EXIT trap: a failed assertion would leave .env behind"
    assert "shred" in text
    assert "umask 077" in text
    assert "::add-mask::" in text
```

Add `"tier2-mono-smoke.sh"` to `TIER_SCRIPTS`, which makes strict bash, no `|| true` and the executable
bit apply to the new script.

- [ ] **Step 2: Run the tests and confirm they fail.**
  Run `.venv/bin/pytest tests/build/test_tier2_mono_smoke_script.py tests/build/test_ci_script_contract.py -q`.
  They fail because the script is missing.

- [ ] **Step 3: Write the script.**
  - Use the header and preamble pattern of `tier2-agent-journey.sh`: argument check first (exit 2), then
    `source lib/common.sh` and `cd "$CB_REPO_ROOT"`.
  - `cb::require_tool` for `docker`, `curl` and `python3`.
  - Then one function per former dev-ci step, in the same order, each keeping its original comment
    block **verbatim**:
    `mint_secrets`, `start_compose`, `wait_livez`, `wait_readyz`, `assert_http_redirect`,
    `assert_tls_spa`, `assert_supervisord_running`, `assert_no_restarts`, `assert_clean_stop`,
    `collect_diagnostics`.
  - Differences from the YAML:
    - The ports come from `CB_SMOKE_PORT`/`CB_SMOKE_PORT_HTTPS`, with the old values as defaults.
    - `CB_IMAGE` is `$1`.
    - `::add-mask::` is emitted only when `[[ ${GITHUB_ACTIONS:-} == true ]]`.
    - An `EXIT` trap runs `collect_diagnostics` and then teardown: `docker compose down -v --remove-orphans`,
      `shred -u .env`, and `rm -rf` of the data dir. Each teardown command is individually guarded with
      `if ! cmd; then echo "::warning::…"; fi`, because a failed teardown must not mask the real exit code
      and `|| true` is banned.
    - The trap preserves `$?`.
    - The two `supervisorctl … || true` uses become `if ! docker compose … > file 2>&1; then :; fi`.
      supervisorctl exits non-zero whenever a program isn't RUNNING, which is the case the assertion reads
      from the file.

- [ ] **Step 4: Run the tests again, then lint.**
  Re-run the tests from step 2 (now passing), then `bash -n scripts/ci/tier2-mono-smoke.sh` and
  `shellcheck scripts/ci/tier2-mono-smoke.sh` if shellcheck is installed; say so if it isn't.

- [ ] **Step 5: Commit.**
  `feat(ci): the mono smoke becomes scripts/ci/tier2-mono-smoke.sh`

---

## Task 2: `mono-smoke.yml`, with a permissions grant that is inherited, not requested

**Files:**
- Create `.github/workflows/mono-smoke.yml`.
- Modify `tests/build/test_reusable_workflow_permissions.py`.
- Modify `tests/build/test_tier2_wiring.py`.

**Interfaces:**
- Consumes the script from Task 1.
- Produces the `workflow_call` inputs:
  - `ref: string = ""`
  - `publish: boolean = false`
  - `provenance_artifact: string = ""`
- Produces the job id `mono-smoke`, named `Mono image smoke`.

- [ ] **Step 1: Write the failing tests.**

  Append to `test_tier2_wiring.py`:

```python
MONO_SCRIPT = "scripts/ci/tier2-mono-smoke.sh"


def test_mono_workflow_calls_the_script_and_inlines_nothing():
    runs = _run_blocks(_load("mono-smoke.yml"))
    assert any(MONO_SCRIPT in r for r in runs)
    inlined = [r for r in runs if "/api/v1/readyz" in r or "supervisorctl" in r]
    assert not inlined, f"mono-smoke.yml re-inlines smoke assertions: {inlined}"


def test_mono_smoke_inherits_its_callers_grant():
    """No permissions anywhere: dev-ci's packages: write reaches the push, and a
    read-only caller's run physically cannot push (maintainer decision, A3 plan)."""
    wf = _load("mono-smoke.yml")
    assert "permissions" not in wf
    assert all("permissions" not in job for job in wf["jobs"].values())
    assert "# permissions: inherited-from-caller" in (WORKFLOWS / "mono-smoke.yml").read_text()


def test_mono_push_is_gated_on_publish_and_a_push_to_dev():
    steps = _load("mono-smoke.yml")["jobs"]["mono-smoke"]["steps"]
    pushes = [s for s in steps if "docker push" in str(s.get("run", ""))]
    assert pushes, "no push step"
    for step in pushes:
        cond = str(step.get("if", ""))
        for part in ("inputs.publish", "github.event_name == 'push'", "github.ref == 'refs/heads/dev'"):
            assert part in cond, f"push step {step.get('name')!r} is missing {part!r}"


def test_only_the_push_steps_touch_the_token():
    for step in _load("mono-smoke.yml")["jobs"]["mono-smoke"]["steps"]:
        if "GITHUB_TOKEN" in str(step):
            assert "docker push" in str(step.get("run", "")), step.get("name")
```

  In `test_reusable_workflow_permissions.py`:
  - Add `INHERITS_MARKER = "# permissions: inherited-from-caller"`.
  - Change `test_every_workflow_declares_top_level_permissions` to exempt a workflow only when **all**
    of these hold:
    1. its only trigger is `workflow_call`;
    2. it carries the marker;
    3. no job in it declares `permissions`.
  - Add a synthetic test: a marked, called-only workflow with no permissions, called from a caller that
    grants `contents: read`, produces no violation, and its jobs are walked with the caller's bound. That
    relies on #195's recursion.
  - Add a second synthetic test: a marked workflow that *also* has `on: push` is not exempt.

- [ ] **Step 2: Run and confirm they fail.** They fail because `mono-smoke.yml` is missing.

- [ ] **Step 3: Write `mono-smoke.yml`.**

  The header comment explains three things:
  - why this workflow declares no permissions (quote maintainer decision 1 and the architecture
    paragraph above);
  - why the push is in the same job (the image never leaves the runner that tested it);
  - that a read-only caller's run cannot push.

  Put `# permissions: inherited-from-caller` on its own line directly above `jobs:`.

  Steps, in this order:
  1. Checkout with `ref: ${{ inputs.ref }}` and `persist-credentials: false`.
  2. Derive the version (`dev-$(git rev-parse --short HEAD)`), exactly as dev-ci did.
  3. `docker build -f Dockerfile.mono -t "circuitbreaker:${CB_VERSION}" .`
  4. Export the provenance, only `if: inputs.provenance_artifact != ''`, and upload it under
     `${{ inputs.provenance_artifact }}` with `retention-days: 3` and `if-no-files-found: error`.
  5. The agent-binaries check, verbatim.
  6. `scripts/ci/tier2-mono-smoke.sh "circuitbreaker:${CB_VERSION}"` with `env: CB_VERSION`.
  7. **Publish :nightly**, moved verbatim with its comment and extended as follows:
     - add `inputs.publish &&` to its `if:`;
     - the token comes through `env: GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`, and the actor through
       `env: ACTOR: ${{ github.actor }}`, with `docker login … --password-stdin <<<"$GH_TOKEN"`.
       Nothing is interpolated into `run:`.
  8. **Push the dev image**, moved verbatim the same way, with the same `if:` and `env:` changes.
  9. Upload diagnostics (`if: always()`, name `mono-smoke-diagnostics`, `retention-days: 14`).

  `timeout-minutes: 40`, `runs-on: ubuntu-22.04`. There are no dispatch inputs, so no checkov skip is
  needed.

  **The push steps must come after the smoke script and before nothing else destructive.** The script's
  EXIT trap has already torn the containers down by the time the push runs. The image is still in the
  runner's daemon, and that is what the push tags.

- [ ] **Step 4: Run the tests, the guards and checkov.**

```bash
.venv/bin/pytest tests/build/test_tier2_wiring.py tests/build/test_reusable_workflow_permissions.py \
  tests/build/test_scheduled_workflows_pin_their_ref.py tests/build/test_workflow_wiring_resolves.py -q
checkov -f .github/workflows/mono-smoke.yml --framework github_actions
```

  If checkov flags the missing top-level permissions (CKV2_GHA_1 or similar), add a
  `# checkov:skip=<ID>: permissions are inherited from the caller by design; see header` beside the
  marker. Verify the ID from checkov's own output; don't guess it.

- [ ] **Step 5: Commit.**
  `feat(ci): mono-smoke.yml builds, smokes and (only when a writer calls it) publishes`

---

## Task 3: `dev-ci.yml` becomes a caller

**Files:** Modify `.github/workflows/dev-ci.yml` (the `build-docker` job, currently lines ~665-1000),
`tests/build/test_release_promote_contract.py` and `tests/build/test_tier2_wiring.py`.

- [ ] **Step 1: Write the failing tests.**

  Append to `test_tier2_wiring.py`:

```python
def test_dev_ci_publishes_through_mono_smoke_and_keeps_the_parity_artifact():
    dev = _load("dev-ci.yml")["jobs"]
    job = dev["build-docker"]
    assert job["uses"] == "./.github/workflows/mono-smoke.yml"
    assert job["with"]["publish"] is True
    assert job["permissions"] == {"contents": "read", "packages": "write"}
    assert "artifact-smoke" in (job["needs"] if isinstance(job["needs"], list) else [job["needs"]])
    name = job["with"]["provenance_artifact"]
    downloads = [s for s in dev["runtime-parity"]["steps"]
                 if str(s.get("uses", "")).startswith("actions/download-artifact")]
    assert any(s.get("with", {}).get("name") == name for s in downloads), (
        f"runtime-parity no longer downloads {name!r}"
    )
```

  In `test_release_promote_contract.py`, update `test_nightly_publish_waits_for_artifact_smoke`:
  - keep asserting that `build-docker` needs `artifact-smoke`;
  - assert `build-docker.uses` is `./.github/workflows/mono-smoke.yml`;
  - assert `"Publish :nightly"` is a step name in `mono-smoke.yml`'s `mono-smoke` job, and that it comes
    after the step that runs `tier2-mono-smoke.sh`.

  Update the docstring to say the step moved in A3.

- [ ] **Step 2: Run and confirm they fail.**

- [ ] **Step 3: Replace the job.** Replace the whole `build-docker` job with:

```yaml
  # The mono image's build, compose smoke and publish live in mono-smoke.yml
  # (Tier 2 slice A3), shared with tier2.yml and the release. The push stays in
  # the same job as the smoke that started the image; this caller's
  # packages: write is what lets it happen, and only on a push to dev (the
  # step's own `if:`). Pull requests build and smoke the same way and never push.
  build-docker:
    name: Build Docker (smoke test)
    needs: [artifact-smoke]
    permissions:
      contents: read
      packages: write
    uses: ./.github/workflows/mono-smoke.yml
    with:
      publish: true
      provenance_artifact: dev-image-build-info-amd64
```

  `runtime-parity` keeps `needs: [build-native, build-docker]`, and its download name is unchanged.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/build -q` and `checkov -f .github/workflows/dev-ci.yml --framework github_actions`
  (no new failures).

- [ ] **Step 5: Commit.** `refactor(ci): dev-ci's build-docker calls mono-smoke.yml`. Use `refactor:` only
  if #195's commit-type decision allows it; otherwise use `feat(ci):`.

---

## Task 4: Tier 2 gains its third suite

**Files:** Modify `scripts/ci/tier2_gate.py`, `.github/workflows/tier2.yml`, `release.yml`,
`release-dry-run.yml`, `tests/build/test_tier2_gate.py` and `tests/build/test_tier2_wiring.py`.

- [ ] **Step 1: Update the failing tests.**
  - `test_tier2_gate.py`:
    - `parse_suites("")` must now return `["browser", "composed", "mono"]`;
    - add `test_mono_is_a_known_suite`;
    - update any fixture that builds `needs` so it includes `mono`.
  - `test_tier2_wiring.py`:
    - replace `test_the_release_does_not_gate_on_the_composed_journey` with
      `test_the_release_runs_browser_and_mono`, asserting `json.loads(suites) == ["browser", "mono"]` for
      both release files and that `"composed"` is absent;
    - the existing `test_every_suite_job_is_gated_on_its_own_name_and_the_sets_agree`,
      `test_result_job_needs_…` and `test_tier2_passes_the_planned_ref_to_every_suite` then fail until
      `tier2.yml` has the `mono` job.

- [ ] **Step 2: Run and confirm they fail.**

- [ ] **Step 3: Implement.**
  - `tier2_gate.py`: `KNOWN_SUITES = ("browser", "composed", "mono")` and
    `DEFAULT_SUITES = ("browser", "composed", "mono")`.
  - `tier2.yml`: add, after `composed`:

```yaml
  # No publish: this caller grants read-only, and mono-smoke.yml inherits the
  # caller's grant, so a Tier 2 run of the mono suite cannot push an image.
  mono:
    name: Mono image smoke
    needs: plan
    if: contains(fromJSON(needs.plan.outputs.suites), 'mono')
    permissions:
      contents: read
      actions: read
    uses: ./.github/workflows/mono-smoke.yml
    with:
      ref: ${{ needs.plan.outputs.ref }}
```

  - Add `mono` to `result.needs`.
  - `release.yml` and `release-dry-run.yml`: `suites: '["browser","mono"]'`, and update each `tier2` job's
    comment to cite decision 2 of this plan.

- [ ] **Step 4: Run** `.venv/bin/pytest tests/build -q`, then checkov on `tier2.yml`, `release.yml` and
  `release-dry-run.yml`.

- [ ] **Step 5: Commit.**
  `feat(ci): Tier 2 runs the mono smoke as its third suite; the release runs browser + mono`

---

## Task 5: `make verify-composed-mono`, the evidence registry, and docs

**Files:** Modify `Makefile`, `tests/build/test_tier2_wiring.py`, `tests/build/test_ci_evidence_retention.py`,
the design doc, `CLAUDE.md` and `.claude/skills/cb-build-test/SKILL.md`.

- [ ] **Step 1: Write the failing tests.** In `test_tier2_wiring.py`:
  - `verify-composed`'s prerequisites are exactly `{"verify-composed-browser", "verify-composed-agent", "verify-composed-mono"}`;
  - the `verify-composed-mono` recipe contains `docker build -f Dockerfile.mono` and `scripts/ci/tier2-mono-smoke.sh`.

  In `test_ci_evidence_retention.py`, add `mono-smoke.yml` to `ARTIFACT_SOURCE_WORKFLOWS` and
  `EVIDENCE_OWING_JOBS` (`{"mono-smoke.yml": ("mono-smoke",)}`), as design §7.4 requires. Run it and see
  whether it demands anything the new workflow lacks, such as retention days on diagnostics. Satisfy it in
  the workflow, not by weakening the test.

- [ ] **Step 2: Implement.**

```make
verify-composed-mono: ## Tier 2 — build the mono image and run the compose smoke CI runs
	docker build -f Dockerfile.mono -t circuitbreaker:local-smoke .
	scripts/ci/tier2-mono-smoke.sh circuitbreaker:local-smoke
```

  Add it to `verify-composed`'s prerequisites, to `.PHONY`, and to the T2 comment block.
  Docs:
  - Design doc: set the status to "A1–A3 implemented". Add an A3 implementation note: the inherited
    permissions and why; decision 2; the check-name change.
  - `CLAUDE.md`'s Tier 2 row: "the next two rows together" becomes "browser E2E, the composed journey and
    the mono smoke".
  - The cb-build-test skill: add `verify-composed-mono`.

- [ ] **Step 3: Run** `.venv/bin/pytest tests/build -q` and `make lint`, then commit:
  `feat(make): verify-composed-mono, and the mono smoke joins the evidence registry`

---

## Task 6: Prove it before the pull request

`make verify` runs none of this. The covering evidence, all of it on real runners:

- [ ] **Step 1: Local gates.** `make lint && make verify`. Nothing is under `apps/backend/src/app`, so
  `verify-full` is not owed.

  `make verify-composed-mono` cannot run on the headless box (rootless podman, no compose provider). Say
  so in the PR, not "passed".

- [ ] **Step 2: Push and confirm the remote** (`git ls-remote`, rule 4).

- [ ] **Step 3: Open the PR into `dev`.** Its CI is the first real proof:
  - `dev-ci.yml` on `pull_request` runs `Build Docker (smoke test) / Mono image smoke`. Expected: every
    assertion passes and **both push steps are skipped** (the event is a PR). Read the job's step list
    from the API.
  - `tier2.yml`'s own PR trigger does not fire unless `tier2.yml` or `tier2_gate.py` changed. Both change
    here, so it runs with the default suites, which now include `mono`. Expected: `Tier 2 / Mono image
    smoke` passes, and its push steps are skipped. Also expected, and the load-bearing check:
    **the workflow loads**, which proves the inherited-permission design against GitHub's own validator.

- [ ] **Step 4: Release dry run on the branch.** Run
  `gh workflow run release-dry-run.yml --ref <branch>`. Expected:
  - `Tier 2 / Mono image smoke` succeeds;
  - `tier2: success`;
  - the push steps are skipped. They must be, because the dry run is read-only.

- [ ] **Step 5: After merge (not part of the PR).**
  - The `dev` push run of `dev-ci.yml` must show both push steps **executed**.
  - `ghcr.io/blkleg/circuitbreaker:dev` must now point at the merge commit's `dev-<sha>` tag. Check with
    `gh api /users/blkleg/packages/container/circuitbreaker/versions --jq '.[0].metadata.container.tags'`
    or `docker manifest inspect`.
  - This is the only proof that the inherited `packages: write` actually reaches the push.

---

## Self-Review

**Spec coverage** (§9 A3 row, §3.1 mono row, §7.4):
- `mono-smoke.yml`: Task 2.
- The push decision (maintainer decision 1): Task 2, with the inherited grant.
- The release becoming "all-three minus composed": Task 4, decision 2, flagged.
- `packages: write` staying only where the push is: Tasks 2 and 3.
- The §7.4 evidence registry entry: Task 5.
- The scheduled-ref guard: satisfied because the checkout pins `inputs.ref`, and the Task 2 test run
  includes that guard.

**Placeholder scan:** the checkov skip ID in Task 2 step 4 is deliberately taken from checkov's own
output, because guessing a rule ID is worse. No TBDs.

**Type consistency:**
- `publish`, `provenance_artifact` and `ref` agree across Tasks 2–4.
- The `mono-smoke` job id agrees across Tasks 2 and 3 and the tests.
- `KNOWN_SUITES` / `DEFAULT_SUITES` agree between Task 4 and the tier2 wiring tests.
- Adding `mono` to the suites and to `tier2.yml` are one commit, so `test_every_suite_job_is_gated_on_its_own_name_and_the_sets_agree`
  is never half-true between tasks.

**Review Focus:** all five lines map to named tests, in Tasks 1–3 and 5.
