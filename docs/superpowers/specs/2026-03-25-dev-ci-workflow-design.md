# Dev Branch CI Workflow — Design Spec

**Date:** 2026-03-25
**Status:** Approved
**File to create:** `.github/workflows/dev-ci.yml`

---

## Problem

`ci.yml` only targets `main` (push + PR). The `dev` branch has no CI at all — no lint, no tests, no build verification. Broken builds and lint regressions are only caught when merging to `main` or manually running `build.yml` via `workflow_dispatch`.

## Goal

A single, self-contained CI workflow that runs on every push to `dev` and verifies:
1. Code quality (lint + types)
2. Frontend tests
3. Security gate
4. Native package builds (amd64)
5. Docker image builds

No artifacts are published. No GHCR push. No GitHub Release.

---

## Trigger

```yaml
on:
  push:
    branches: [dev]
```

---

## Job Structure

All five jobs run **in parallel** — no inter-job dependencies. A failure in one does not block the others.

| Job | Runner | Purpose |
|---|---|---|
| `lint` | ubuntu-22.04 | ruff + mypy + eslint |
| `test` | ubuntu-22.04 | frontend unit tests |
| `security-gate` | ubuntu-22.04 | bandit + semgrep |
| `build-native` | ubuntu-22.04 | amd64 package build + artifact upload |
| `build-docker` | ubuntu-22.04 | docker build smoke test (no push) |

---

## Job Details

### `lint`
Mirrors `ci.yml` exactly:
- Setup python 3.12 + node 20
- `python3.12 -m venv .venv && pip install -e apps/backend/[dev]`
- `cd apps/frontend && npm ci`
- `ruff check src/app`
- `mypy src/app`
- `npm run lint`

### `test`
Mirrors `ci.yml` exactly:
- Setup node 20
- `cd apps/frontend && npm ci && npm test`

### `security-gate`
Mirrors `ci.yml` exactly:
- Setup python 3.12
- Install bandit + semgrep
- `./scripts/security_scan.sh --gate`
- Upload `security_scan_report.md` artifact (`if: always()`, 30-day retention)

### `build-native`
Mirrors `build.yml` single-arch (no matrix — amd64 only):
- Setup python 3.12 + node 20
- `bash scripts/install-build-deps.sh`
- `python3.12 -m venv .venv && pip install -e apps/backend/[dev]`
- `cd apps/frontend && npm ci && npm run build`
- `build_native_release.py --version dev-<short-sha> --clean`
- Upload `dist/native/` as artifact **`dev-packages-amd64`**, **3-day retention**

Version string: `dev-$(git rev-parse --short HEAD)` — same pattern as `build.yml` workflow_dispatch default.

### `build-docker`
New job — simple smoke build:
- `docker build -f Dockerfile.mono -t circuitbreaker:dev-<short-sha> .`
- No `docker login`, no `docker push`, no GHCR interaction
- Job passes if build exits 0

---

## What This Does NOT Do

- No GHCR push
- No GitHub Release
- No cosign signing
- No SBOM generation
- No GPG signing
- No arm64 build (dev speed over release parity)
- No job gating (lint failure does not block build jobs)

---

## File Location

`.github/workflows/dev-ci.yml` — standalone file, no changes to existing workflows.

---

## Success Criteria

- Every push to `dev` triggers all five jobs
- Native build artifact is downloadable from the Actions run for 3 days
- Docker build failure is surfaced immediately without blocking other job results
- No credentials or registry tokens required
