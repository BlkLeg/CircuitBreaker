# Dev Branch CI Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `.github/workflows/dev-ci.yml` — a full CI workflow that runs on every push to `dev`, covering lint, tests, security, native package build (amd64), and Docker image build, without publishing anything.

**Architecture:** Single self-contained workflow file. Five jobs run in parallel with no inter-job dependencies. Mirrors the jobs from `ci.yml` (lint/test/security) and `build.yml` (native build) but scoped to amd64 only and with a new Docker smoke-build job. No changes to any existing workflow file.

**Tech Stack:** GitHub Actions, ubuntu-22.04 runners, Python 3.12, Node 20, Docker (pre-installed on ubuntu-22.04 runners).

---

### Task 1: Create `dev-ci.yml`

**Files:**
- Create: `.github/workflows/dev-ci.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/dev-ci.yml` with the following content:

```yaml
name: Dev CI

on:
  push:
    branches: [dev]

jobs:
  # ── Lint ─────────────────────────────────────────────────────────────────────
  lint:
    name: Lint
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v5
        with:
          node-version: "20"

      - name: Install Python deps
        run: |
          python3.12 -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install -e "apps/backend/[dev]"

      - name: Install frontend deps
        run: cd apps/frontend && npm ci

      - name: Ruff check
        run: cd apps/backend && ../../.venv/bin/ruff check src/app

      - name: Mypy
        run: cd apps/backend && PYTHONPATH=src ../../.venv/bin/mypy src/app

      - name: ESLint
        run: cd apps/frontend && npm run lint

  # ── Tests ─────────────────────────────────────────────────────────────────────
  test:
    name: Test
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-node@v5
        with:
          node-version: "20"

      - name: Install frontend deps
        run: cd apps/frontend && npm ci

      - name: Frontend tests
        run: cd apps/frontend && npm test

  # ── Security Gate ─────────────────────────────────────────────────────────────
  security-gate:
    name: Security Gate
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install scan tools
        run: |
          python3.12 -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install bandit semgrep

      - name: Run security gate (fails on HIGH/CRIT)
        run: ./scripts/security_scan.sh --gate

      - name: Upload scan report
        uses: actions/upload-artifact@v5
        if: always()
        with:
          name: security-scan-report
          path: security_scan_report.md
          retention-days: 30

  # ── Native Build (amd64 only) ─────────────────────────────────────────────────
  build-native:
    name: Build Native (amd64)
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v5
        with:
          node-version: "20"

      - name: Derive version
        id: ver
        run: echo "version=dev-$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"

      - name: Install build deps
        run: bash scripts/install-build-deps.sh

      - name: Install Python deps
        run: |
          python3.12 -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install -e "apps/backend/[dev]"

      - name: Build frontend
        run: cd apps/frontend && npm ci && npm run build

      - name: Build packages
        run: |
          .venv/bin/python scripts/build_native_release.py \
            --version "${{ steps.ver.outputs.version }}" \
            --clean

      - name: List artifacts
        run: ls -lh dist/native/

      - name: Upload artifacts
        uses: actions/upload-artifact@v5
        with:
          name: dev-packages-amd64
          path: dist/native/
          if-no-files-found: error
          retention-days: 3

  # ── Docker Smoke Build ────────────────────────────────────────────────────────
  build-docker:
    name: Build Docker (smoke test)
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v5

      - name: Derive version
        id: ver
        run: echo "version=dev-$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"

      - name: Build Docker image
        run: |
          docker build -f Dockerfile.mono \
            -t "circuitbreaker:${{ steps.ver.outputs.version }}" \
            .
```

- [ ] **Step 2: Validate YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/dev-ci.yml'))" && echo "YAML valid"
```

Expected output: `YAML valid`

If it errors, fix the syntax before continuing.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/dev-ci.yml docs/superpowers/specs/2026-03-25-dev-ci-workflow-design.md docs/superpowers/plans/2026-03-25-dev-ci-workflow.md
git commit -m "ci: add dev branch CI workflow (lint, test, security, build)"
```

- [ ] **Step 4: Push and verify**

```bash
git push origin dev
```

Then go to the repo's **Actions** tab on GitHub. You should see "Dev CI" appear and all five jobs start in parallel:
- `Lint`
- `Test`
- `Security Gate`
- `Build Native (amd64)`
- `Build Docker (smoke test)`

Once `Build Native (amd64)` passes, confirm the `dev-packages-amd64` artifact is downloadable from the workflow run summary (3-day retention).
