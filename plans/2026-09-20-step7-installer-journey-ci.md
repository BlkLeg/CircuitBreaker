# Step 7 — Installer Journey in CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute `install.sh` end to end in CI for the first time, make the manual fleet tier reachable from the pipeline, and cover tarball rollback.

**Architecture:** A job that installs from a staged bundle inside a systemd-capable container, boots, and probes `/readyz`. A `workflow_dispatch` entry point for `scripts/ci/fleet/dispatch.sh`. A tarball row in `matrix.yaml` so the fleet tier covers the format `install.sh` actually installs.

**Tech Stack:** GitHub Actions, podman or QEMU, systemd, Bash, `curl`.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §13, §14, §25.

**Depends on:** Steps 1–6. This job asserts the phase ledger reached its final phase, which requires Step 5's renderer.

**This is the largest and most flake-prone plan in the set.** It is sequenced last deliberately: Step 0's quarantine policy is already in place, so a flaky new suite cannot train everyone to ignore red.

## Global Constraints

- **No placeholders.**
- Never hardcode credentials, tokens, signing material or vault keys. Generate per-run values and register them with `::add-mask::` before use, exactly as `dev-ci.yml` does.
- **Air-gap is first-class.** The job installs from a **locally staged bundle** with `--local-bundle`, which is also how it avoids depending on a published release.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- **The container-versus-VM choice is made on a measured flake rate, not on preference.** Task 1 Step 6 is that measurement and it is not optional.
- This plan does not touch `apps/backend/src/app`, so `make verify` is the local gate — but the covering evidence for this plan is the job itself running green twenty times.

## Background an implementer needs

`install.sh` has never been executed in CI. `pages.yml` publishes it, `release.yml` attaches it, and `tests/build/*` greps its text. Nothing runs it.

The blocker is systemd: `install.sh` writes systemd units and calls `systemctl start`. A default GitHub runner container has no PID 1 that answers `systemctl`.

`scripts/ci/fleet/dispatch.sh` drives `tier3-artifact.sh` against QEMU guests defined in `scripts/ci/fleet/matrix.yaml`. It appears in no workflow; `make verify-fleet` runs it locally and its own Makefile comment says it "gates nothing and is not a release gate".

`matrix.yaml`'s header states the rule this plan must honour: "a row here is a published promise, not a convenience", and image digests must be the distributor-published ones.

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/installer-journey.yml` | Runs `install.sh` end to end, boots, probes `/readyz`. |
| `scripts/ci/installer-journey.sh` | The journey itself, so it is runnable locally and identical in both. |
| `.github/workflows/fleet.yml` | `workflow_dispatch` entry point for the fleet tier. |
| `scripts/ci/fleet/matrix.yaml` | Gains a tarball install row and a tarball upgrade row. |
| `docs/evidence/2026-09-20-installer-journey-flake-rate.md` | The twenty-run measurement behind the container/VM decision. |

---

### Task 1: The installer journey

**Files:**
- Create: `scripts/ci/installer-journey.sh`
- Create: `.github/workflows/installer-journey.yml`
- Create: `docs/evidence/2026-09-20-installer-journey-flake-rate.md`

**Interfaces:**
- Consumes: a bundle tarball path; `install.sh`'s `--local-bundle`, `--unattended`, `--no-tls` flags.
- Produces: exit 0 only when the service answered `/readyz` with 200 and the phase ledger reached its final phase.

- [ ] **Step 1: Write the journey script**

Create `scripts/ci/installer-journey.sh`:

```bash
#!/usr/bin/env bash
#
# Run install.sh end to end and prove the result works.
#
# Nothing has ever executed this installer. pages.yml publishes it, release.yml
# attaches it, and tests/build/ greps its text — so every defect in the most
# prominently documented install path has been found by users.
#
# One file, run identically in CI and locally, because a journey that only
# exists as workflow YAML cannot be reproduced when it fails.
#
# Usage: installer-journey.sh <bundle.tar.gz>
set -euo pipefail

BUNDLE="${1:?usage: installer-journey.sh <bundle.tar.gz>}"
PORT="${CB_JOURNEY_PORT:-8088}"
READY_BUDGET="${CB_JOURNEY_READY_BUDGET:-180}"
EVIDENCE="${CB_JOURNEY_EVIDENCE:-/tmp/installer-journey}"

mkdir -p "$EVIDENCE"

section() { printf '\n=== %s ===\n' "$1"; }

fail() {
  printf '::error::%s\n' "$1" >&2
  section "Diagnostics"
  tail -n 200 /var/lib/circuitbreaker/logs/install.log 2>/dev/null || true
  systemctl status 'circuitbreaker-*' --no-pager -l 2>/dev/null || true
  journalctl -u 'circuitbreaker-*' --no-pager -n 200 2>/dev/null || true
  exit 1
}

section "Install from the staged bundle"
# --local-bundle, so the journey does not depend on a published release and
# makes no outbound request for the artifact under test. --unattended, because
# there is no operator. --no-tls, because a self-signed certificate adds a
# failure mode this job is not trying to characterise.
#
# Output is captured rather than streamed so the phase ledger can be asserted
# below; it is echoed back on both paths so a failure is still readable.
set +e
bash install.sh --local-bundle "$BUNDLE" --unattended --no-tls \
  > "$EVIDENCE/install-stdout.log" 2>&1
INSTALL_RC=$?
set -e
cat "$EVIDENCE/install-stdout.log"
[ "$INSTALL_RC" -eq 0 ] || fail "install.sh exited $INSTALL_RC"

section "Assert the installer reported every phase"
# --unattended selects the renderer's plain mode, which prints one timestamped
# line per phase transition. The final phase is the one that proves the run
# reached the end rather than exiting early with status 0 from a subshell.
for phase in \
  "Pre-flight checks" \
  "Downloading bundle" \
  "Installing files" \
  "System dependencies" \
  "Preparing database" \
  "Services and networking" \
  "Starting Circuit Breaker"; do
  grep -qF "$phase" "$EVIDENCE/install-stdout.log" \
    || fail "installer never reported the phase: $phase"
done

section "Wait for /livez"
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:${PORT}/livez" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "http://127.0.0.1:${PORT}/livez" > "$EVIDENCE/livez.json" \
  || fail "service never answered /livez"

section "Wait for /readyz"
deadline=$(( SECONDS + READY_BUDGET ))
code=000
while [ "$SECONDS" -lt "$deadline" ]; do
  code="$(curl -s -o "$EVIDENCE/readyz.json" -w '%{http_code}' \
    "http://127.0.0.1:${PORT}/readyz" || echo 000)"
  [ "$code" = "200" ] && break
  sleep 2
done
[ "$code" = "200" ] || fail "service never became ready (last /readyz was $code)"
cat "$EVIDENCE/readyz.json"

section "Assert the installed binary contains its application"
/opt/circuitbreaker/bin/circuit-breaker --selftest \
  || fail "the installed binary failed its self-test"

section "Journey complete"
```

- [ ] **Step 2: Make it executable and syntax-check it**

```bash
chmod +x scripts/ci/installer-journey.sh
bash -n scripts/ci/installer-journey.sh && echo "syntax OK"
shellcheck scripts/ci/installer-journey.sh || true
```

- [ ] **Step 3: Write the workflow, container route first**

Create `.github/workflows/installer-journey.yml`:

```yaml
name: Installer Journey

# The first time install.sh has ever been executed by CI. Until now pages.yml
# published it, release.yml attached it, and tests/build/ grepped its text —
# so every defect in the most prominently documented install path was found by
# users.
#
# scheduled-ref: not applicable — this workflow has no schedule trigger.
on:
  pull_request:
    paths:
      - 'install.sh'
      - 'uninstall.sh'
      - 'deploy/**'
      - 'scripts/build_native_release.py'
      - 'scripts/ci/installer-journey.sh'
      - '.github/workflows/installer-journey.yml'
  workflow_dispatch:
    inputs:
      runs:
        description: 'Consecutive runs, for measuring the flake rate'
        required: false
        default: '1'

permissions:
  contents: read

jobs:
  journey:
    name: Install from a staged bundle (${{ matrix.distro }})
    strategy:
      fail-fast: false
      matrix:
        distro: [ubuntu2204, debian12]
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - uses: actions/setup-node@v5
        with:
          node-version: '20'

      - name: Install build dependencies
        run: bash scripts/install-build-deps.sh

      - name: Build the candidate bundle
        run: |
          set -euo pipefail
          python3 -m venv .venv
          .venv/bin/pip install -r apps/backend/requirements.txt
          .venv/bin/pip install pyinstaller
          cd apps/frontend && npm ci && npm run build && cd -
          .venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
          ls -lh dist/native/

      # systemd as PID 1, which install.sh needs and a default runner container
      # does not have. podman rather than docker because it runs systemd inside
      # a container without the privileged/cgroup contortions docker needs.
      #
      # The alternative is a nested VM, which is slower and heavier. The choice
      # is recorded in docs/evidence/2026-09-20-installer-journey-flake-rate.md
      # and was made on a measured flake rate over twenty runs, not on
      # preference.
      - name: Start a systemd container
        env:
          DISTRO: ${{ matrix.distro }}
        run: |
          set -euo pipefail
          case "${DISTRO}" in
            ubuntu2204) IMAGE=docker.io/library/ubuntu:22.04 ;;
            debian12)   IMAGE=docker.io/library/debian:12 ;;
            *) echo "::error::unknown distro ${DISTRO}"; exit 1 ;;
          esac
          sudo podman run -d --name cb-journey \
            --systemd=always \
            --cgroupns=host \
            -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
            -v "$PWD:/workspace:ro" \
            -p 8088:8088 \
            "${IMAGE}" /sbin/init
          # The container needs the tools install.sh bootstraps with; installing
          # them here rather than letting the installer do it keeps the journey
          # about install.sh rather than about apt reachability.
          sudo podman exec cb-journey bash -c \
            'apt-get update && apt-get install -y systemd curl jq openssl ca-certificates'

      - name: Run the installer journey
        run: |
          set -euo pipefail
          BUNDLE="$(ls dist/native/circuit-breaker_*_linux_amd64.tar.gz | head -1)"
          sudo podman exec cb-journey bash -c "
            set -euo pipefail
            mkdir -p /candidate
            cp '/workspace/${BUNDLE}' /candidate/
            cp /workspace/install.sh /candidate/
            cd /candidate
            bash /workspace/scripts/ci/installer-journey.sh \
              \"/candidate/\$(basename '${BUNDLE}')\"
          "

      - name: Collect evidence
        if: always()
        run: |
          sudo podman exec cb-journey bash -c \
            'tar -czf /tmp/journey-evidence.tar.gz /tmp/installer-journey 2>/dev/null' || true
          sudo podman cp cb-journey:/tmp/journey-evidence.tar.gz . || true

      - name: Upload evidence
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: installer-journey-${{ matrix.distro }}
          path: journey-evidence.tar.gz
          if-no-files-found: warn

      - name: Tear down
        if: always()
        run: sudo podman rm -f cb-journey || true
```

- [ ] **Step 4: Validate the workflow parses**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/installer-journey.yml').read_text())
print(sorted(d['jobs']))
print('triggers:', sorted(d.get('on', d.get(True))))
print('OK')
"
pytest tests/build/test_scheduled_workflows_pin_their_ref.py -v
```

Expected: `journey` listed, triggers `['pull_request', 'workflow_dispatch']`, and the Step 0 ref guard passes (this workflow has no `schedule`, so it is out of that rule's scope).

- [ ] **Step 5: Run it locally before pushing**

CLAUDE.md rule 3: push only after the covering suite passes locally. CI is for confirmation, not discovery.

```bash
.venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
BUNDLE="$(ls dist/native/circuit-breaker_*_linux_amd64.tar.gz | head -1)"
sudo podman run -d --name cb-journey-local --systemd=always --cgroupns=host \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$PWD:/workspace:ro" -p 8088:8088 \
  docker.io/library/ubuntu:22.04 /sbin/init
sudo podman exec cb-journey-local bash -c \
  'apt-get update && apt-get install -y systemd curl jq openssl ca-certificates'
sudo podman exec cb-journey-local bash -c \
  "mkdir -p /candidate && cp '/workspace/${BUNDLE}' /candidate/ && cp /workspace/install.sh /candidate/ && cd /candidate && bash /workspace/scripts/ci/installer-journey.sh /candidate/\$(basename '${BUNDLE}')"
sudo podman rm -f cb-journey-local
```

Expected: `Journey complete`. **Expect this to fail the first several times** — this is the first execution of `install.sh` in a container, ever. Each failure is a real finding about the installer or the harness. Fix them, and record each one in the PR description; that list is the most valuable output of this plan.

- [ ] **Step 6: Measure the flake rate — twenty consecutive runs**

The container-versus-VM decision is made here and nowhere else.

```bash
pass=0; fail=0
for i in $(seq 1 20); do
  if bash scripts/ci/installer-journey.sh "$BUNDLE" >/tmp/run-$i.log 2>&1; then
    pass=$((pass+1))
  else
    fail=$((fail+1)); echo "run $i failed"
  fi
done
echo "pass=$pass fail=$fail"
```

Record the result in `docs/evidence/2026-09-20-installer-journey-flake-rate.md` with the failures' causes.

**Decision rule, fixed here before the measurement:** if the container route passes 20 of 20, adopt it. If it fails once for an environmental reason, investigate and re-measure. If it fails twice or more for reasons that are not the installer's fault, switch to a nested VM and re-measure. If the VM route also fails, **do not merge a flaky required check** — take the recorded fallback in Task 3 and say so.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/installer-journey.sh .github/workflows/installer-journey.yml docs/evidence/2026-09-20-installer-journey-flake-rate.md
git commit -m "feat: run install.sh end to end in CI

The first time this installer has ever been executed by CI. Installs from a
staged bundle inside a systemd container, asserts every phase was reported,
waits for /livez and /readyz, and self-tests the installed binary.

One script, run identically locally and in CI, because a journey that exists
only as workflow YAML cannot be reproduced when it fails. Flake rate measured
over twenty runs and recorded.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Make the fleet tier reachable from CI

**Files:**
- Create: `.github/workflows/fleet.yml`

**Scope note.** This makes tier 3 *requestable*, not blocking. Making it a blocking gate needs a hosted fleet, which is out of scope and is stated as such in the design's §14.

- [ ] **Step 1: Read what dispatch.sh needs**

```bash
sed -n '1,60p' scripts/ci/fleet/dispatch.sh
grep -n 'runner:' scripts/ci/fleet/matrix.yaml
```

Every row's `runner` is `local/qemu`, so this workflow targets a self-hosted runner. Confirm one is registered before writing the `runs-on`; if none is, the workflow is still correct and simply queues, which is honest.

- [ ] **Step 2: Write the workflow**

```yaml
name: Fleet (Tier 3)

# Tier 3 boots a real VM per row and takes minutes. It gates nothing — ADR 0005
# is explicit that wiring it to a gate is separate work needing a hosted fleet.
#
# What this changes is that it stops being invisible. Before, tier3-artifact.sh
# was reachable only from scripts/ci/fleet/dispatch.sh, run by hand, and the
# newest evidence under artifacts/diagnostics/ was from v0.4.0. A release
# candidate can now request the run and the evidence lands as an artifact.
on:
  workflow_dispatch:
    inputs:
      row:
        description: 'matrix.yaml row id (e.g. debian-deb-amd64)'
        required: true
      candidate:
        description: 'Path or URL to the candidate package'
        required: true
      previous:
        description: 'N-1 package, required for a mode: upgrade row'
        required: false

permissions:
  contents: read

jobs:
  fleet:
    name: Tier 3 — ${{ inputs.row }}
    runs-on: [self-hosted, qemu]
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v5

      - name: Dispatch the row
        run: |
          set -euo pipefail
          bash scripts/ci/fleet/dispatch.sh \
            "${{ inputs.row }}" \
            "${{ inputs.candidate }}" \
            ${{ inputs.previous && format('"{0}"', inputs.previous) || '' }}

      - name: Upload row evidence
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: tier3-${{ inputs.row }}
          path: artifacts/diagnostics/tier3-${{ inputs.row }}
          if-no-files-found: warn
```

- [ ] **Step 3: Validate and commit**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/fleet.yml').read_text())
assert 'workflow_dispatch' in d.get('on', d.get(True))
print('OK')
"
git add .github/workflows/fleet.yml
git commit -m "feat: make the fleet tier requestable from the pipeline

tier3-artifact.sh boots the service, polls /livez and /readyz, exercises
backup and restore and the documented rollback — and was reachable only from a
script run by hand, with the newest evidence dating to v0.4.0. It still gates
nothing; it is no longer invisible.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Tarball rows in the fleet matrix

**Files:**
- Modify: `scripts/ci/fleet/matrix.yaml`
- Modify: `scripts/ci/tier3-artifact.sh`
- Modify: `tests/build/test_fleet_matrix.py`, `tests/build/test_fleet_multi_distro.py` (confirm names with `ls tests/build | grep fleet`)

**This is the recorded fallback** named in the design's §13: if the journey job cannot be made non-flaky, the tarball's coverage lives here instead, at Tier 3, and that is a decision written down rather than a silent omission.

- [ ] **Step 1: Read the matrix rules**

```bash
sed -n '1,48p' scripts/ci/fleet/matrix.yaml
pytest tests/build -k fleet -v
```

The header states: "a row here is a published promise, not a convenience", and `tier` must match what the row actually backs. A tarball row is **tier 3 today** — it becomes tier 2 only when ADR 0005's table is updated by the commit carrying the evidence.

- [ ] **Step 2: Teach `tier3-artifact.sh` to install a tarball**

The script currently branches on the artifact it is handed (`.deb` / `.rpm`). Add a `.tar.gz` branch that unpacks the bundle and runs `bash install.sh --local-bundle <tarball> --unattended --no-tls`, then rejoins the existing `t3::start_and_wait_ready` path. The unit name differs between layouts — the packaged path uses `circuit-breaker`, the installer path uses `circuitbreaker-backend` and friends — so resolve it from the install identity record rather than hardcoding.

- [ ] **Step 3: Add the rows**

Append to `scripts/ci/fleet/matrix.yaml`. The image URL and digest below are
copied from the existing `debian-deb-amd64` row — the same immutable dated path
and the same **distributor-published** SHA512, per that file's written refusal of
locally computed digests. Re-read the row before pasting in case it has moved on:

```yaml
# The format `curl ... install.sh | bash` actually installs. Tier 3 today: the
# row's existence does not move ADR 0005's table, which is updated only by the
# commit that records a passing run.
- id: debian-tarball-amd64
  distro: debian-12
  format: tarball
  arch: amd64
  runner: local/qemu
  tier: 3
  mode: install
  ssh_user: debian
  cloud_init: debian.user-data
  image_url: "https://cloud.debian.org/images/cloud/bookworm/20260821-2577/debian-12-genericcloud-amd64-20260821-2577.qcow2"
  image_sha512: "c602f42a374c097bafcbc77c2d034fb06cb8a831d791bcbaa5d043f029874b0c32d41cb72ba8b6d50ccfd64c9b4b0dc9ade5b6e4065712f3eb152338e532721f"

- id: debian-tarball-amd64-upgrade
  distro: debian-12
  format: tarball
  arch: amd64
  runner: local/qemu
  tier: 3
  mode: upgrade
  ssh_user: debian
  cloud_init: debian.user-data
  image_url: "https://cloud.debian.org/images/cloud/bookworm/20260821-2577/debian-12-genericcloud-amd64-20260821-2577.qcow2"
  image_sha512: "c602f42a374c097bafcbc77c2d034fb06cb8a831d791bcbaa5d043f029874b0c32d41cb72ba8b6d50ccfd64c9b4b0dc9ade5b6e4065712f3eb152338e532721f"
```

- [ ] **Step 4: Run the fleet policy suites**

Run: `pytest tests/build -k fleet -v`

Expected: pass. If a suite asserts an exact row count or an exact set of formats, update it in the same commit — that is a contract, and adding a row legitimately changes it.

- [ ] **Step 5: Run the row locally**

```bash
make verify-fleet CB_ROW=debian-tarball-amd64 \
  CB_CANDIDATE="$(ls dist/native/circuit-breaker_*_linux_amd64.tar.gz | head -1)"
```

Expected: the row completes and evidence lands in `artifacts/diagnostics/tier3-debian-tarball-amd64/`. This downloads a ~556 MB image on first run and takes minutes.

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/fleet/matrix.yaml scripts/ci/tier3-artifact.sh tests/build/
git commit -m "feat: cover the tarball in the fleet matrix, install and rollback

matrix.yaml's four rows were all deb or rpm, so the format curl|bash actually
installs was covered by nothing at any tier. Adds an install row and an upgrade
row, which is also where tarball rollback gets exercised for the first time.

Tier 3, because a row's existence does not move ADR 0005's table — only the
commit carrying a passing run does.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `scripts/ci/installer-journey.sh` passes locally against a freshly built bundle.
- [ ] Twenty consecutive local runs measured and recorded, with the container/VM decision stated.
- [ ] `installer-journey.yml` and `fleet.yml` parse; the Step 0 ref guard passes.
- [ ] `pytest tests/build -q`, `make lint`, `make verify` pass.
- [ ] `make verify-fleet CB_ROW=debian-tarball-amd64` completes and leaves evidence.
- [ ] Every installer defect found during Task 1 Step 5 is listed in the PR description.

## What this plan does NOT cover

The journey runs on amd64 and on two Debian-family distros. Fedora, RHEL, Rocky, AlmaLinux and Arch — all of which `install.sh` claims to support in its own error messages — are not exercised, and neither is arm64. The design's §27 coverage matrix records these as open gaps; do not let this plan's green check imply otherwise.

The `--docker` compose path is explicitly out of scope for the whole design and remains uncovered.

**Do not push before Task 1 Step 5 passes locally.** This job builds a full bundle and boots a container; discovering its failures through CI costs roughly forty minutes per round, which is the specific waste CLAUDE.md rule 3 exists to prevent.
