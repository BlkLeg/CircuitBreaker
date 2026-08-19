# Release Pipeline Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the release pipeline from publishing claims it cannot honor — build the container for both supported architectures, and make promotion to `latest` an explicit post-acceptance action instead of a side effect of tagging.

**Architecture:** Three changes to `.github/workflows/release.yml` plus two new pure-Python gate scripts. The gate scripts are unit-tested in `tests/build/`; the workflow changes are verified by running the same commands locally. Channel selection and version parity become code with tests, not YAML conditionals, so they are reviewable and cannot silently rot.

**Tech Stack:** GitHub Actions, `docker buildx`, QEMU, Python 3.12 + pytest, `nfpm`, `syft`, `cosign`.

**Spec:** `specs/1.0.0/07-documentation-repository-governance.md` (GOV-09, GOV-18, GOV-19, GOV-20), `specs/1.0.0/01-release-contract.md` (RC-02), `specs/1.0.0/05-artifact-acceptance-and-recovery.md` (ACC-17)

## Global Constraints

- Python `>=3.12,<4`. Tests run under `pytest` from the repo root; `tests/build/` is already on the path.
- The canonical version lives in the root `VERSION` file and nowhere else (GOV-09). Everything else derives from it.
- Container registry is `ghcr.io/blkleg/circuitbreaker`.
- Supported architectures per `docs/release/1.0.0-support-contract.md:58` are `amd64` and `arm64`.
- Build-tool identities must be immutable (GOV-18): no `latest`, no floating tags, no unpinned `go install`.
- A release job must never sign, attest, or promote an artifact that has not passed its gate.

---

### Task 1: Release-channel decision as tested code

Today `release.yml:100-106` pushes `:latest` in the same step as `:${VERSION}`, and `release.yml:207` creates the GitHub Release with no `--prerelease`. Tagging `v1.0.0-rc.3` therefore moves both "latest" pointers to a release candidate. Extracting the decision into a tested function is the prerequisite for gating it.

**Files:**
- Create: `scripts/release_channel.py`
- Test: `tests/build/test_release_channel.py`

**Interfaces:**
- Produces: `is_prerelease(version: str) -> bool`, `channel_tags(version: str) -> list[str]`, and a `__main__` block supporting `--version <v> --field {prerelease,tags}` for the workflow to call.

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_release_channel.py
import subprocess
import sys

import pytest

from scripts.release_channel import channel_tags, is_prerelease


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0", False),
        ("1.0.1", False),
        ("2.3.4", False),
        ("1.0.0-rc.1", True),
        ("1.0.0-rc.2", True),
        ("1.0.0-alpha.1", True),
        ("1.0.0-beta", True),
        ("1.0.0-dev", True),
        ("dev-abc1234", True),
    ],
)
def test_is_prerelease(version, expected):
    assert is_prerelease(version) is expected


def test_stable_version_gets_latest_tag():
    assert channel_tags("1.0.0") == ["1.0.0", "latest"]


def test_prerelease_never_gets_latest_tag():
    assert channel_tags("1.0.0-rc.2") == ["1.0.0-rc.2"]
    assert "latest" not in channel_tags("1.0.0-rc.2")


def test_rejects_empty_version():
    with pytest.raises(SystemExit):
        channel_tags("")


def test_cli_emits_shell_consumable_fields():
    out = subprocess.run(
        [sys.executable, "scripts/release_channel.py", "--version", "1.0.0-rc.2", "--field", "prerelease"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "true"

    out = subprocess.run(
        [sys.executable, "scripts/release_channel.py", "--version", "1.0.0", "--field", "tags"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.split() == ["1.0.0", "latest"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_release_channel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.release_channel'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Decide which registry tags and GitHub Release flags a version is entitled to.

GOV-20: promotion of a stable channel is an explicit post-acceptance action. A
release candidate must never move `latest`, and must be marked prerelease on
GitHub so it does not become the "Latest release" a user lands on.
"""

from __future__ import annotations

import argparse
import re
import sys

# A stable version is exactly MAJOR.MINOR.PATCH with no pre-release suffix.
_STABLE_RE = re.compile(r"^\d+\.\d+\.\d+$")


def is_prerelease(version: str) -> bool:
    """True for anything that is not a bare MAJOR.MINOR.PATCH.

    Deliberately allowlist-shaped rather than blocklist-shaped: an unrecognised
    version string is treated as a prerelease, so a typo can never promote a
    stable channel.
    """
    return not _STABLE_RE.match(version.strip())


def channel_tags(version: str) -> list[str]:
    value = version.strip()
    if not value:
        raise SystemExit("release_channel: version must not be empty")
    if is_prerelease(value):
        return [value]
    return [value, "latest"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--field", required=True, choices=["prerelease", "tags"])
    args = parser.parse_args()

    if args.field == "prerelease":
        print("true" if is_prerelease(args.version) else "false")
    else:
        print(" ".join(channel_tags(args.version)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/build/test_release_channel.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/release_channel.py tests/build/test_release_channel.py
git commit -m "feat(release): decide registry channel and prerelease flag from the version string

GOV-20: a release candidate must not move :latest or become GitHub's
Latest release. Unrecognised version strings fail closed to prerelease."
```

---

### Task 2: Version parity gate

GOV-09 requires `VERSION` to be the sole hand-edited version, with everything else deriving from it. Today `apps/frontend/package.json` and the root `package.json` are synced by hand (both currently `1.0.0-rc.2`, correct by luck), and the git tag is trusted blindly by `release.yml:32`. Nothing detects disagreement.

**Files:**
- Create: `scripts/check_version_parity.py`
- Test: `tests/build/test_version_parity.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `collect_versions(root: Path) -> dict[str, str]` and `check_parity(root: Path, expected: str | None = None) -> list[str]` returning a list of human-readable mismatch strings (empty means parity holds).

- [ ] **Step 1: Write the failing test**

```python
# tests/build/test_version_parity.py
import json
from pathlib import Path

import pytest

from scripts.check_version_parity import check_parity, collect_versions


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "package.json").write_text(json.dumps({"name": "circuitbreaker", "version": "1.2.3", "private": True}))
    frontend = tmp_path / "apps" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"name": "frontend", "version": "1.2.3"}))
    return tmp_path


def test_collects_every_known_version_source(tree: Path):
    versions = collect_versions(tree)
    assert versions == {
        "VERSION": "1.2.3",
        "package.json": "1.2.3",
        "apps/frontend/package.json": "1.2.3",
    }


def test_parity_holds_when_all_agree(tree: Path):
    assert check_parity(tree) == []


def test_detects_frontend_drift(tree: Path):
    path = tree / "apps" / "frontend" / "package.json"
    path.write_text(json.dumps({"name": "frontend", "version": "1.2.2"}))
    problems = check_parity(tree)
    assert len(problems) == 1
    assert "apps/frontend/package.json" in problems[0]
    assert "1.2.2" in problems[0]


def test_detects_tag_drift(tree: Path):
    problems = check_parity(tree, expected="1.2.4")
    assert any("expected 1.2.4" in p for p in problems)


def test_expected_matching_version_is_clean(tree: Path):
    assert check_parity(tree, expected="1.2.3") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/build/test_version_parity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.check_version_parity'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""GOV-09: VERSION is the only hand-edited version. Prove everything agrees.

Run with --expected <v> in the release workflow to also prove the pushed git
tag matches, which `release.yml`'s version job otherwise trusts blindly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every file that carries a copy of the version, and how to read it.
_JSON_MANIFESTS = ("package.json", "apps/frontend/package.json")


def collect_versions(root: Path) -> dict[str, str]:
    versions = {"VERSION": (root / "VERSION").read_text().strip()}
    for rel in _JSON_MANIFESTS:
        path = root / rel
        if path.exists():
            versions[rel] = json.loads(path.read_text())["version"]
    return versions


def check_parity(root: Path, expected: str | None = None) -> list[str]:
    versions = collect_versions(root)
    canonical = versions["VERSION"]
    problems = [
        f"{source} is {value!r}, but VERSION is {canonical!r}"
        for source, value in versions.items()
        if source != "VERSION" and value != canonical
    ]
    if expected is not None and expected.strip() != canonical:
        problems.append(f"VERSION is {canonical!r}, but expected {expected.strip()}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", default=None, help="Version the caller (e.g. a git tag) expects")
    args = parser.parse_args()

    problems = check_parity(REPO_ROOT, expected=args.expected)
    if problems:
        print("version parity FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"version parity ok: {(REPO_ROOT / 'VERSION').read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes, then run the gate on the real tree**

Run: `python -m pytest tests/build/test_version_parity.py -v && python scripts/check_version_parity.py`
Expected: PASS (5 passed), then `version parity ok: 1.0.0-rc.2`

- [ ] **Step 5: Commit**

```bash
git add scripts/check_version_parity.py tests/build/test_version_parity.py
git commit -m "feat(release): add GOV-09 version parity gate

VERSION is canonical; package.json, the frontend manifest and the pushed
git tag must agree with it or the release fails."
```

---

### Task 3: Build the container for both supported architectures

`release.yml:100-106` runs a plain `docker build` on an amd64 runner, so `ghcr.io/blkleg/circuitbreaker` is amd64-only — while `docs/release/1.0.0-support-contract.md:40` sells arm64 for the Docker Compose install path. Native packages are already dual-arch via `build.yml:22-30`; only the image is not.

**Files:**
- Modify: `.github/workflows/release.yml:88-110`

**Interfaces:**
- Consumes: `scripts/release_channel.py` from Task 1 (`--field tags`).
- Produces: `steps.docker_push.outputs.digest` unchanged in meaning — still the immutable digest the Trivy scan and cosign steps consume, now pointing at a multi-arch manifest list.

- [ ] **Step 1: Verify the multi-arch build works locally before touching CI**

Run:
```bash
docker buildx create --name cb-multiarch --use --bootstrap || docker buildx use cb-multiarch
docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.mono -t cb-multiarch-smoke:local .
```
Expected: both platforms build. If arm64 fails, **stop and fix `Dockerfile.mono` first** — that failure is the real content of this task and means the support-contract row was never achievable. Record the failure and treat it as a blocking finding rather than working around it.

- [ ] **Step 2: Replace the build-and-push step**

Replace `.github/workflows/release.yml:95-110` (the `Build and push Docker image` step) with:

```yaml
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      # RC-02 claims amd64 AND arm64 for the container channel. A plain
      # `docker build` on an amd64 runner silently shipped amd64 only, so the
      # support contract promised an image that was never built. buildx with
      # an explicit --platform is what makes that row true.
      #
      # GOV-20: the tag list comes from scripts/release_channel.py, so a
      # release candidate cannot move :latest. See Task 1.
      - name: Build and push Docker image
        id: docker_push
        env:
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          IMAGE="ghcr.io/blkleg/circuitbreaker"
          TAG_ARGS=""
          for tag in $(python3 scripts/release_channel.py --version "${VERSION}" --field tags); do
            TAG_ARGS="${TAG_ARGS} -t ${IMAGE}:${tag}"
          done
          echo "Publishing tags:${TAG_ARGS}"
          docker buildx build \
            --platform linux/amd64,linux/arm64 \
            -f Dockerfile.mono \
            ${TAG_ARGS} \
            --provenance=true \
            --sbom=true \
            --push \
            .
          DIGEST=$(docker buildx imagetools inspect "${IMAGE}:${VERSION}" \
            --format '{{json .Manifest.Digest}}' | tr -d '"')
          echo "digest=${IMAGE}@${DIGEST}" >> "$GITHUB_OUTPUT"

      # Prove both architectures are actually in the published manifest list,
      # rather than trusting that --platform did what it was asked.
      - name: Assert published manifest covers both architectures
        env:
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          MANIFEST=$(docker buildx imagetools inspect "ghcr.io/blkleg/circuitbreaker:${VERSION}" --raw)
          for arch in amd64 arm64; do
            echo "${MANIFEST}" | grep -q "\"architecture\":\"${arch}\"" \
              || { echo "::error::published manifest is missing linux/${arch}"; exit 1; }
          done
          echo "manifest covers amd64 and arm64"
```

- [ ] **Step 3: Validate the workflow file parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('release.yml parses')"`
Expected: `release.yml parses`

- [ ] **Step 4: Clean up the local builder**

Run: `docker buildx rm cb-multiarch && docker rmi cb-multiarch-smoke:local 2>/dev/null || true`
Expected: builder removed; no error that stops the task.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "fix(release): build the container for amd64 and arm64

RC-02 claimed both architectures for the Docker Compose install path while
release.yml ran a plain docker build on an amd64 runner. Adds buildx+QEMU,
takes the tag list from release_channel.py so an RC cannot move :latest,
and asserts both architectures are present in the published manifest."
```

---

### Task 4: Gate publication on an installed-artifact smoke test

GOV-20 requires artifact installation gates to run *before* publication. Today nothing installs a built package on a clean host at any point in the pipeline; `release.yml` downloads the build artifacts and uploads them straight to a GitHub Release.

**Files:**
- Create: `.github/workflows/artifact-smoke.yml`
- Modify: `.github/workflows/release.yml:47` (the `release` job's `needs:`)

**Interfaces:**
- Consumes: the `packages-${{ matrix.arch }}` artifacts produced by `build.yml:74-80`.
- Produces: a job named `artifact-smoke` that the `release` job must depend on.

- [ ] **Step 1: Create the smoke workflow**

```yaml
# .github/workflows/artifact-smoke.yml
name: Artifact Smoke

# GOV-20 / ACC-17: a package is not publishable until it has been installed on
# a clean host from the exact built candidate — not from a source checkout.
on:
  workflow_call:
    inputs:
      version:
        required: true
        type: string

permissions:
  contents: read

jobs:
  deb-install:
    name: Install .deb (${{ matrix.arch }})
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

      - name: Install the candidate .deb on a clean host
        run: |
          DEB=$(find dist -name '*.deb' | head -1)
          [ -n "${DEB}" ] || { echo "::error::no .deb in packages-${{ matrix.arch }}"; exit 1; }
          echo "Installing ${DEB}"
          sudo apt-get update
          sudo apt-get install -y "./${DEB}" || sudo dpkg -i "${DEB}" || true
          sudo apt-get install -f -y

      - name: Assert the installed binary reports the candidate version
        env:
          VERSION: ${{ inputs.version }}
        run: |
          # The packaged binary must identify itself as the version being
          # released. A mismatch here means GOV-09 parity broke somewhere
          # between VERSION and the artifact a user actually receives.
          INSTALLED=$(/usr/lib/circuitbreaker/circuit-breaker --version 2>/dev/null \
            || /usr/bin/circuit-breaker --version 2>/dev/null)
          echo "installed reports: ${INSTALLED}"
          echo "${INSTALLED}" | grep -q "${VERSION}" \
            || { echo "::error::installed binary reports ${INSTALLED}, expected ${VERSION}"; exit 1; }

      - name: Assert uninstall leaves no service behind
        run: |
          sudo apt-get remove -y circuit-breaker || sudo dpkg -r circuit-breaker
          ! systemctl list-unit-files 2>/dev/null | grep -q '^circuitbreaker-backend' \
            || { echo "::error::uninstall left circuitbreaker-backend registered"; exit 1; }
          echo "uninstall clean"
```

- [ ] **Step 2: Verify the new workflow parses and the binary path assumption is real**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/artifact-smoke.yml')); print('artifact-smoke.yml parses')"
grep -n "bindir\|/usr/lib/circuitbreaker\|/usr/bin" nfpm.yaml | head -20
```
Expected: the workflow parses, and `nfpm.yaml` confirms the installed binary path. **If the path differs, correct the two `--version` invocations in Step 1 to match `nfpm.yaml` before continuing** — do not leave a guess in the gate.

- [ ] **Step 3: Wire the gate into the release workflow**

In `.github/workflows/release.yml`, add the smoke job after the `build` job and make `release` depend on it:

```yaml
  # ── Installed-artifact gate (GOV-20) ─────────────────────────────────────────
  artifact-smoke:
    name: Artifact Smoke
    needs: [version, build]
    uses: ./.github/workflows/artifact-smoke.yml
    with:
      version: ${{ needs.version.outputs.version }}

  # ── Create GitHub Release + push Docker ──────────────────────────────────────
  release:
    name: Publish Release
    needs: [version, build, artifact-smoke]
    runs-on: ubuntu-22.04
```

- [ ] **Step 4: Verify the dependency graph**

Run:
```bash
python3 - <<'PY'
import yaml
wf = yaml.safe_load(open('.github/workflows/release.yml'))
needs = wf['jobs']['release']['needs']
assert 'artifact-smoke' in needs, f"release must depend on artifact-smoke, got {needs}"
assert 'artifact-smoke' in wf['jobs'], "artifact-smoke job is missing"
print("release gated on artifact-smoke:", needs)
PY
```
Expected: `release gated on artifact-smoke: ['version', 'build', 'artifact-smoke']`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/artifact-smoke.yml .github/workflows/release.yml
git commit -m "feat(release): gate publication on an installed-artifact smoke test

GOV-20/ACC-17: nothing installed a built package on a clean host before
publication. Installs the exact candidate .deb on both architectures,
asserts the installed binary reports the release version, and asserts
uninstall deregisters the service."
```

---

### Task 5: Mark release candidates as prereleases

`release.yml:207-221` runs `gh release create` with no `--prerelease`, so `v1.0.0-rc.3` would become GitHub's "Latest release".

**Files:**
- Modify: `.github/workflows/release.yml:207-221`

**Interfaces:**
- Consumes: `scripts/release_channel.py --field prerelease` from Task 1.

- [ ] **Step 1: Update the release-creation step**

Replace the `Create GitHub Release` step's `run:` block with:

```yaml
      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          VERSION: ${{ needs.version.outputs.version }}
        run: |
          # setup.sh kept as backward-compat alias for install.sh
          cp install.sh setup.sh

          # GOV-20: an RC must not become GitHub's "Latest release". The flag
          # comes from the same tested function that decides registry tags, so
          # the two channels can never disagree about what "stable" means.
          PRERELEASE_FLAG=""
          if [ "$(python3 scripts/release_channel.py --version "${VERSION}" --field prerelease)" = "true" ]; then
            PRERELEASE_FLAG="--prerelease"
            echo "Publishing ${VERSION} as a prerelease"
          else
            echo "Publishing ${VERSION} as a stable release"
          fi

          gh release create "v${VERSION}" \
            --title "Circuit Breaker v${VERSION}" \
            --generate-notes \
            ${PRERELEASE_FLAG} \
            dist/release/* \
            install.sh \
            setup.sh \
            packaging/circuit-breaker-release-key.asc
```

- [ ] **Step 2: Add the parity gate to the version job**

In `.github/workflows/release.yml`, replace the `version` job's steps with:

```yaml
    steps:
      - uses: actions/checkout@v5

      - name: Derive version string
        id: ver
        run: |
          if [ "${{ github.event_name }}" = "push" ]; then
            # Strip leading 'v' from tag
            echo "version=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"
          else
            echo "version=${{ inputs.version }}" >> "$GITHUB_OUTPUT"
          fi

      # GOV-09: the tag is not authoritative. VERSION is. Fail before anything
      # is built if they disagree.
      - name: Assert version parity
        run: python3 scripts/check_version_parity.py --expected "${{ steps.ver.outputs.version }}"
```

Note: the `version` job previously had no `checkout` step — it is added above because the parity gate needs the tree.

- [ ] **Step 3: Verify the workflow parses and the version job checks out**

Run:
```bash
python3 - <<'PY'
import yaml
wf = yaml.safe_load(open('.github/workflows/release.yml'))
steps = wf['jobs']['version']['steps']
names = [s.get('name') or s.get('uses') for s in steps]
assert any('checkout' in str(n) for n in names), names
assert 'Assert version parity' in names, names
print("version job steps:", names)
PY
```
Expected: the list contains `actions/checkout@v5`, `Derive version string`, `Assert version parity`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "fix(release): mark release candidates as prereleases and gate on version parity

GOV-20: gh release create had no --prerelease, so tagging v1.0.0-rc.3 would
make an RC GitHub's Latest release. GOV-09: the git tag is no longer trusted
over the VERSION file."
```

---

### Task 6: Pin build-tool identities and wire the ledger validator into CI

GOV-18 requires immutable tool identities. Three floating references remain: `NFPM_VERSION=latest` (`scripts/install-build-deps.sh:7`), `go install ...govulncheck@latest` (`scripts/security_scan.sh:313`), and `ghcr.io/gitleaks/gitleaks:latest` (`scripts/security_scan.sh:122`). Separately, `scripts/validate_v1_release_control.py` passes but runs in no workflow, so the ledger can drift silently.

**Files:**
- Modify: `scripts/install-build-deps.sh:7`
- Modify: `scripts/security_scan.sh:313`, `scripts/security_scan.sh:122`
- Modify: `.github/workflows/ci.yml` (add a step to the `lint` job)

- [ ] **Step 1: Confirm the current floating references**

Run:
```bash
grep -n 'NFPM_VERSION="${NFPM_VERSION:-latest}"' scripts/install-build-deps.sh
grep -n 'govulncheck@latest' scripts/security_scan.sh
grep -n 'gitleaks:latest' scripts/security_scan.sh
```
Expected: one hit each — line 7, line 313, line 122.

- [ ] **Step 2: Pin them**

```bash
sed -i 's|NFPM_VERSION="${NFPM_VERSION:-latest}"|# GOV-18: pinned so an RC rebuild uses an immutable tool identity.\nNFPM_VERSION="${NFPM_VERSION:-v2.43.0}"|' scripts/install-build-deps.sh
sed -i 's|golang.org/x/vuln/cmd/govulncheck@latest|golang.org/x/vuln/cmd/govulncheck@v1.1.4|' scripts/security_scan.sh
sed -i 's|ghcr.io/gitleaks/gitleaks:latest|ghcr.io/gitleaks/gitleaks:v8.21.2|' scripts/security_scan.sh
```

Then verify each pinned version actually exists before trusting it:

```bash
curl -sfI https://github.com/goreleaser/nfpm/releases/tag/v2.43.0 >/dev/null && echo "nfpm v2.43.0 ok"
curl -sfI https://github.com/gitleaks/gitleaks/releases/tag/v8.21.2 >/dev/null && echo "gitleaks v8.21.2 ok"
curl -sfI https://github.com/golang/vuln/releases/tag/v1.1.4 >/dev/null && echo "govulncheck v1.1.4 ok"
```
Expected: three `ok` lines. **If any 404s, pick the current release tag from that project and use it instead** — the point is immutability, not these specific numbers.

- [ ] **Step 3: Add the ledger validator to CI**

Append this step to the `lint` job in `.github/workflows/ci.yml`, after the `Mypy` step:

```yaml
      # EXEC: the requirement ledger is the release's source of truth. It
      # validated clean by hand but ran in no workflow, so it could drift
      # silently between the specs and the CSV.
      - name: Validate 1.0.0 release-control ledger
        run: python3 scripts/validate_v1_release_control.py
```

- [ ] **Step 4: Verify everything still runs**

Run:
```bash
bash -n scripts/install-build-deps.sh && bash -n scripts/security_scan.sh && echo "shell syntax ok"
python3 scripts/validate_v1_release_control.py
python3 -c "import yaml; wf=yaml.safe_load(open('.github/workflows/ci.yml')); names=[s.get('name') or s.get('uses') for s in wf['jobs']['lint']['steps']]; assert 'Validate 1.0.0 release-control ledger' in names, names; print('ci lint steps:', names)"
grep -n 'latest' scripts/install-build-deps.sh scripts/security_scan.sh | grep -v '^\s*#' | grep -iv 'releases/latest' || echo "no floating tool tags remain"
```
Expected: shell syntax ok; `release-control validation ok: 145 ledger rows, 145 canonical IDs`; the CI step present; no floating tool tags.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-build-deps.sh scripts/security_scan.sh .github/workflows/ci.yml
git commit -m "chore(release): pin build tools and run the ledger validator in CI

GOV-18: nfpm, govulncheck and the gitleaks image were floating on latest, so
an RC could not be rebuilt from an immutable tool set. Also wires
validate_v1_release_control.py into the lint job so the requirement ledger
cannot drift from the specs unnoticed."
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| RC-02 (no untested row called supported) | 3 |
| GOV-09 (VERSION is canonical) | 2, 5 |
| GOV-18 (immutable tool identities) | 6 |
| GOV-19 (provenance/attestations) | 3 (`--provenance=true --sbom=true`) |
| GOV-20 (promotion is post-acceptance) | 1, 4, 5 |
| ACC-17 (clean-host install from published candidates) | 4 |

**Known gap left open deliberately:** GOV-19's SLSA `actions/attest-build-provenance` for the *native packages* is not added here — buildx provenance covers the container only. Native-package attestation is a one-step addition once the smoke gate in Task 4 proves the artifacts are trustworthy; it is recorded as remaining GOV-19 work rather than silently skipped.

**Type consistency:** `is_prerelease` / `channel_tags` (Task 1) are consumed by name in Tasks 3 and 5. `check_parity(root, expected=None)` (Task 2) is consumed in Task 5 via the `--expected` CLI flag. `steps.docker_push.outputs.digest` keeps the `IMAGE@sha256:...` shape the existing Trivy and cosign steps already consume.
