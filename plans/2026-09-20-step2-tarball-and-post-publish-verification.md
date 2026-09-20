# Step 2 — Tarball Smoke and Post-Publication Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the flagship `curl … install.sh | bash` path its first automated coverage, and verify published artifacts from the URLs users actually fetch.

**Architecture:** Two new CI jobs and one documentation correction. A `tarball-smoke` job in `artifact-smoke.yml` that unpacks the release tarball, self-tests the binary inside it, and asserts the bundle layout `install.sh` depends on. A `post-publish` job in `release.yml` that downloads from the real GitHub Release URLs, verifies against the published `SHA256SUMS`, self-tests, and confirms `install.sh`'s own release discovery resolves the new version.

**Tech Stack:** GitHub Actions, Bash, `jq`, `curl`, `sha256sum`, Python 3.12 for the workflow-shape tests.

**Spec:** `docs/design/2026-09-20-install-experience-and-release-verification-design.md` §11, §12, §18.

**Depends on:** Step 1 (`--selftest` must exist in the shipped binary).

## Global Constraints

- **No placeholders.** No `TODO` or unimplemented steps in workflows or scripts.
- Never hardcode credentials, tokens, signing material or vault keys — including in CI workflows. Use `${{ secrets.GITHUB_TOKEN }}` and nothing invented.
- **Air-gap is first-class.** Nothing added here runs during an install; these are release-time jobs only. `install.sh` gains no new outbound call.
- Commits: `feat:` / `fix:` / `chore:` / `docs:`.
- This plan does not touch `apps/backend/src/app`, so `make verify` is the correct pre-push gate.
- `tests/build/` is collected by the repo-root `pytest.ini` with `filterwarnings = error`.

## Background an implementer needs

`build.yml` runs `scripts/build_native_release.py` and uploads everything in `dist/native/` as one artifact named `packages-${arch}`. That artifact contains the tarball **and** the deb/rpm. `artifact-smoke.yml` downloads it and today tests only the `.deb`.

The tarball is named `circuit-breaker_<version>_linux_<arch>.tar.gz` (see `archive_name()` in `scripts/build_native_release.py`) and unpacks to a bundle directory containing `bin/circuit-breaker` — confirm the exact internal layout with `tar -tzf` in Task 1 Step 1 rather than assuming it.

`release.yml`'s `publish` job generates `SHA256SUMS`, attaches assets, and creates the GitHub Release. `install.sh` discovers releases through `https://api.github.com/repos/BlkLeg/CircuitBreaker/releases`.

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/artifact-smoke.yml` | Gains a `tarball-smoke` job beside `deb-install`. |
| `.github/workflows/release.yml` | Gains a `post-publish` job that runs after `publish`. |
| `tests/build/test_artifact_smoke_covers_every_published_format.py` | Asserts the smoke workflow tests the tarball as well as the deb, so a future format cannot be added silently untested. |
| `CLAUDE.md` | "What the gates do NOT cover" gains two rows. |

---

### Task 1: The tarball smoke job

**Files:**
- Modify: `.github/workflows/artifact-smoke.yml`
- Create: `tests/build/test_artifact_smoke_covers_every_published_format.py`

**Interfaces:**
- Consumes: `--selftest` (Step 1 Task 4); the `packages-${arch}` artifact produced by `build.yml`.
- Produces: a job named `tarball-smoke` in `artifact-smoke.yml`.

- [ ] **Step 1: Discover the real bundle layout**

Do not guess the paths asserted below. Build or download a tarball and read it:

```bash
ls dist/native/*.tar.gz 2>/dev/null || .venv/bin/python scripts/build_native_release.py --version "$(cat VERSION)"
tar -tzf dist/native/circuit-breaker_*_linux_amd64.tar.gz | head -30
```

Record the top-level directory name and the exact paths to the binary, `deploy/setup.sh`, `share/VERSION` and `manifest.json`. The job below uses them.

- [ ] **Step 2: Write the failing policy test**

Create `tests/build/test_artifact_smoke_covers_every_published_format.py`:

```python
"""The release smoke gate must test what users actually download.

`docs/installation/quick-install.md` leads with

    curl -fsSL .../install.sh | bash

which installs the **tarball**. Until this suite existed, artifact-smoke.yml
tested only the .deb, scripts/ci/fleet/matrix.yaml declared four rows all of
which were deb or rpm, and nothing anywhere executed install.sh. The most
prominently documented way to install Circuit Breaker had no automated coverage
at any tier.

This is a policy test, not a functional one: it asserts the gate exists and
names the format, so a future format cannot be added to the build and published
without someone deciding, in a commit, whether it is smoke-tested.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / ".github" / "workflows" / "artifact-smoke.yml"


def _jobs() -> dict[str, dict]:
    document = yaml.safe_load(SMOKE.read_text(encoding="utf-8"))
    return document["jobs"]


def test_the_deb_is_smoke_tested() -> None:
    assert "deb-install" in _jobs(), "artifact-smoke.yml lost its deb job"


def test_the_tarball_is_smoke_tested() -> None:
    jobs = _jobs()
    assert "tarball-smoke" in jobs, (
        "artifact-smoke.yml has no tarball job. The tarball is what "
        "`curl ... install.sh | bash` installs — the path quick-install.md "
        "leads with — and it is published in every release."
    )


def test_every_smoke_job_executes_the_application() -> None:
    """A gate may not pass by not asking (ADR 0005).

    Two things count as executing the application: `--selftest`, which imports
    the ASGI target and every worker module, and a `/readyz` probe, which is
    strictly stronger because it also proves migrations applied and the
    dependencies resolved. A job doing neither is asserting identity only, and
    every identity check in this workflow passed on v0.4.2.
    """
    for name, job in _jobs().items():
        rendered = yaml.safe_dump(job)
        executes = "--selftest" in rendered or "readyz" in rendered
        assert executes, (
            f"job {name!r} installs or unpacks an artifact but never executes "
            "the application inside it — no --selftest and no /readyz probe. "
            "Every assertion short of that is an identity check, and identity "
            "checks all passed on v0.4.2."
        )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/build/test_artifact_smoke_covers_every_published_format.py -v`

Expected: `test_the_tarball_is_smoke_tested` FAILS. `test_every_smoke_job_executes_the_application` passes only if Step 1 of the previous plan landed.

- [ ] **Step 4: Add the `tarball-smoke` job**

Append to the `jobs:` map in `.github/workflows/artifact-smoke.yml`. Replace the four asserted paths with the ones recorded in Step 1 if they differ.

```yaml
  tarball-smoke:
    name: Smoke the tarball (${{ matrix.arch }})
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-22.04
            arch: amd64
          - os: ubuntu-22.04-arm
            arch: arm64
    runs-on: ${{ matrix.os }}
    steps:
      - name: Download candidate packages
        uses: actions/download-artifact@v5
        with:
          name: packages-${{ matrix.arch }}
          path: dist/
          github-token: ${{ secrets.GITHUB_TOKEN }}

      # The tarball is what `curl ... install.sh | bash` installs. It is the
      # path quick-install.md leads with, and until this job existed it was
      # verified by nothing at any tier: artifact-smoke tested only the .deb,
      # and matrix.yaml's four rows are all deb or rpm.
      - name: Unpack the candidate tarball
        env:
          VERSION: ${{ inputs.version }}
        run: |
          set -euo pipefail
          TARBALL="dist/circuit-breaker_${VERSION}_linux_${{ matrix.arch }}.tar.gz"
          [ -f "${TARBALL}" ] || {
            echo "::error::no tarball at ${TARBALL}"
            find dist -name '*.tar.gz' -print
            exit 1
          }
          mkdir -p unpacked
          tar -xzf "${TARBALL}" -C unpacked
          echo "BUNDLE=$(find unpacked -maxdepth 1 -mindepth 1 -type d | head -1)" >> "$GITHUB_ENV"

      # install.sh reads exactly these paths out of the bundle. A layout change
      # that breaks them breaks every curl|bash install, and does so after
      # publication, because nothing else looks.
      - name: Assert the bundle layout install.sh depends on
        run: |
          set -euo pipefail
          for path in \
            bin/circuit-breaker \
            deploy/setup.sh \
            share/VERSION \
            manifest.json; do
            [ -e "${BUNDLE}/${path}" ] || {
              echo "::error::bundle is missing ${path}; install.sh reads it"
              exit 1
            }
          done
          echo "bundle layout OK"

      - name: Assert the shipped VERSION matches the candidate
        env:
          VERSION: ${{ inputs.version }}
        run: |
          set -euo pipefail
          SHIPPED="$(cat "${BUNDLE}/share/VERSION")"
          [ "${SHIPPED}" = "${VERSION}" ] \
            || { echo "::error::bundle VERSION is '${SHIPPED}', expected '${VERSION}'"; exit 1; }

      # The assertion v0.4.2 needed. Every check above is satisfied by a bundle
      # whose binary contains no application.
      - name: Assert the bundled binary can load the application it serves
        run: |
          set -euo pipefail
          "${BUNDLE}/bin/circuit-breaker" --selftest
```

- [ ] **Step 5: Wire it into the release gate**

`release.yml` calls `artifact-smoke.yml` via `uses:` and already blocks `image-merge` and `publish` on `needs: [.., artifact-smoke, ..]`. A reusable workflow fails if **any** job in it fails, so the new job is blocking with no change to `release.yml`. Confirm rather than assume:

```bash
grep -n 'artifact-smoke' .github/workflows/release.yml
```

Expected: `artifact-smoke` appears in the `needs:` of both `image-merge` and `publish`. If it does not, add it.

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/build/test_artifact_smoke_covers_every_published_format.py -v`

Expected: 3 passed.

- [ ] **Step 7: Validate the workflow parses**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/artifact-smoke.yml').read_text())
print(sorted(d['jobs']))
assert 'tarball-smoke' in d['jobs']
print('OK')
"
```

Expected: both job names print, then `OK`.

- [ ] **Step 8: Commit**

```bash
git add .github/workflows/artifact-smoke.yml tests/build/test_artifact_smoke_covers_every_published_format.py
git commit -m "feat: smoke the release tarball

The tarball is what curl|bash installs and what quick-install.md leads with,
and it had no automated coverage at any tier — artifact-smoke tested only the
deb and matrix.yaml's four rows are all deb or rpm. Unpacks it, asserts the
bundle layout install.sh reads, and executes the application inside it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Post-publication verification

**Files:**
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: the published GitHub Release and its `SHA256SUMS` asset.
- Produces: a `post-publish` job gated on `needs: [version, publish]`.

**Why this is the highest-leverage job in the plan.** It is the only check that exercises the real distribution path: asset naming, checksum publication, API propagation, and `install.sh`'s own discovery logic. Had it existed, v0.4.2 would have been caught minutes after publication even with every other change here absent.

- [ ] **Step 1: Read how publish names and attaches assets**

```bash
sed -n '306,420p' .github/workflows/release.yml
grep -n 'SHA256SUMS\|gh release create\|gh release upload' .github/workflows/release.yml
```

Record the exact asset names and the release tag format (`v${VERSION}` or `${VERSION}`). The job below uses them.

- [ ] **Step 2: Add the job**

Append to `.github/workflows/release.yml`'s `jobs:` map. Adjust the tag format to match what Step 1 found.

```yaml
  post-publish:
    name: Verify the published release
    needs: [version, publish]
    runs-on: ubuntu-22.04
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v5

      # Everything upstream verifies a candidate. This verifies the RELEASE:
      # the assets as named and attached, the checksums as published, the API
      # as it answers install.sh, fetched over the network a user would use.
      #
      # It is the only check that exercises asset naming, checksum publication,
      # API propagation and install.sh's own discovery logic. Had it existed,
      # v0.4.2 would have been caught minutes after publication rather than by
      # the people who installed it.
      - name: Download the published tarball and checksums
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          mkdir -p published && cd published
          gh release download "v${VERSION}" \
            --repo "${GITHUB_REPOSITORY}" \
            --pattern "circuit-breaker_${VERSION}_linux_amd64.tar.gz" \
            --pattern "SHA256SUMS"
          ls -lh

      - name: Verify the published tarball against the published checksums
        env:
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          cd published
          grep " circuit-breaker_${VERSION}_linux_amd64.tar.gz\$" SHA256SUMS > expected.sha256 || {
            echo "::error::SHA256SUMS publishes no entry for the amd64 tarball"
            cat SHA256SUMS
            exit 1
          }
          sha256sum -c expected.sha256

      - name: Assert the published binary can load the application it serves
        env:
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          cd published
          mkdir -p unpacked
          tar -xzf "circuit-breaker_${VERSION}_linux_amd64.tar.gz" -C unpacked
          BUNDLE="$(find unpacked -maxdepth 1 -mindepth 1 -type d | head -1)"
          "${BUNDLE}/bin/circuit-breaker" --selftest

      # install.sh resolves a release through the GitHub API. A release that is
      # published but not yet discoverable, or discoverable under an unexpected
      # asset name, is an install that fails for everyone while every build gate
      # stays green.
      - name: Assert install.sh can discover and resolve this release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          set -euo pipefail
          RESOLVED="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/v${VERSION}" \
            --jq '.tag_name')"
          [ "${RESOLVED}" = "v${VERSION}" ] \
            || { echo "::error::API resolved '${RESOLVED}', expected 'v${VERSION}'"; exit 1; }

          ASSET="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/v${VERSION}" \
            --jq ".assets[] | select(.name == \"circuit-breaker_${VERSION}_linux_amd64.tar.gz\") | .name")"
          [ -n "${ASSET}" ] \
            || { echo "::error::the amd64 tarball asset install.sh downloads is not attached to the release"; exit 1; }
          echo "release discoverable and asset present: ${ASSET}"
```

- [ ] **Step 3: Validate the workflow parses and the job is gated correctly**

```bash
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('.github/workflows/release.yml').read_text())
job = d['jobs']['post-publish']
print('needs:', job['needs'])
assert 'publish' in job['needs'], 'post-publish must run after publish'
print('OK')
"
```

Expected: `needs: ['version', 'publish']` then `OK`.

- [ ] **Step 4: Confirm no secret is introduced**

```bash
scripts/secret_exposure_guard.sh || true
grep -nE 'secrets\.' .github/workflows/release.yml | grep -i 'post-publish' -A2 || true
```

The job uses only `secrets.GITHUB_TOKEN`, which is the workflow-scoped token, and declares `permissions: contents: read`. It introduces no new secret. Confirm the security gate agrees:

Run: `scripts/security_scan.sh --gate`

Expected: pass. If the report looks duplicated or out of order, that is the known concurrent-run race — re-run it standalone before investigating.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat: verify the release after it is published

Everything upstream verifies a candidate. This verifies the release: assets as
named and attached, checksums as published, the API as it answers install.sh,
and the application inside the tarball a user would actually download.

The only check that exercises the real distribution path.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Correct CLAUDE.md's coverage table

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the two rows**

In `CLAUDE.md`, under "### What the gates do NOT cover", extend the table:

```markdown
| Suite | Covers | How to run it |
|---|---|---|
| Browser E2E (Playwright) | the real frontend in a real browser | `cd apps/frontend && npx playwright test` |
| Composed Agent E2E | the agent against the mono image | `make e2e-local` |
| Installer journey | `install.sh` end to end on a real host | `bash install.sh --local-bundle <tarball> --unattended --no-tls` |
| Artifact self-test | that the packaged binary contains the application | `circuit-breaker --selftest` |
```

- [ ] **Step 2: Extend the sentence above the table**

Replace:

```
A green `verify-full` therefore says nothing about a frontend dependency bump,
a Playwright change, an agent change, or anything about rendering, routing or
enrollment.
```

with:

```
A green `verify-full` therefore says nothing about a frontend dependency bump,
a Playwright change, an agent change, a packaging change, or anything about
rendering, routing, enrollment or whether the built binary contains the
application at all. v0.4.2 shipped an empty binary through a fully green
pipeline.
```

- [ ] **Step 3: Verify the governance suites still pass**

Run: `pytest tests/build -q`

Expected: pass. Several suites read `CLAUDE.md` for governance policy; if one fails it is asserting document structure and must be read rather than worked around.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: name the installer and the self-test in the coverage table

verify-full runs no browser, no agent, no installer, and never asks whether the
built binary contains the application. Two of those were already recorded; the
other two are what v0.4.2 went through.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Definition of done

- [ ] `pytest tests/build -q` passes.
- [ ] `make lint` and `make verify` pass.
- [ ] Both workflow files parse under `yaml.safe_load`.
- [ ] `tarball-smoke` exists for amd64 and arm64 and executes `--selftest`.
- [ ] `post-publish` is gated on `needs: [version, publish]`.
- [ ] `scripts/security_scan.sh --gate` passes.
- [ ] CLAUDE.md's coverage table has four rows.

## What this plan does NOT cover

Neither new job has executed. They are verified here by YAML parsing, job-graph assertions and policy tests only. `tarball-smoke` first runs on the next release candidate; `post-publish` first runs on the next actual publication. **Do not report either as verified until a real run is green** — quoting `make verify` for a workflow it does not execute is precisely the failure CLAUDE.md rule 1 exists to prevent.
