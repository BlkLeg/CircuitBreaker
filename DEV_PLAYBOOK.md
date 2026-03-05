# Circuit Breaker — Dev Playbook

Quick reference for every `make` command. Run `make help` at any time for a one-line summary of all targets.

---

## How versioning works

The single source of truth is the repo-root `VERSION` file.

```
0.1.5
```

Edit that file before cutting a release — every Make target, Docker tag, and build artifact derives its version from it automatically.

| VERSION value | RELEASE_TAG produced |
|---|---|
| `0.1.5` | `0.1.5-beta` |
| `0.1.5.1` | `0.1.5.1-beta` |
| `1.0.0` | `1.0.0` (no suffix once v1+) |

---

## Daily development

### `make dev`
**Use when:** Starting a fresh dev session.

Kills anything on ports 8000 / 5173, then starts the FastAPI backend (hot-reload) and the Vite frontend dev server side by side.

```
Backend  → http://localhost:8000
Frontend → http://localhost:5173
```

### `make stop`
**Use when:** You want to kill both dev servers without restarting.

Sends SIGKILL to whatever process is holding ports 8000 and 5173.

### `make backend`
**Use when:** You only changed backend code and want to restart just the API.

Kills port 8000 and relaunches uvicorn with `--reload`.

### `make frontend`
**Use when:** You only changed frontend code / config and want to restart Vite.

Kills port 5173 and relaunches `npm start`.

---

## Tests & linting

### `make test`
**Use when:** Quick sanity check before committing.

Runs backend pytest (quiet) + frontend Vitest in one shot.

### `make test-backend`
**Use when:** Debugging a specific backend failure — shows full verbose pytest output.

```bash
make test-backend
```

### `make test-frontend`
**Use when:** Debugging a frontend component test failure.

### `make test-all`
Alias for `test-backend` + `test-frontend` with full verbosity on both.

### `make test-coverage`
**Use when:** Checking coverage before a PR or release. Prints line-level missing coverage for backend and generates a frontend coverage report.

### `make lint`
**Use when:** Enforcing code style before a commit or PR. Runs `ruff` on the backend and `eslint` on the frontend.

### `make format`
**Use when:** Auto-fixing style issues. Runs `ruff format` on the backend and `prettier` on the frontend.

### `make ci`
Runs `lint` then `test` — matches what the CI pipeline checks on every push.

---

## Docker (local stack)

### `make compose-up`
**Use when:** Testing the full containerised stack locally on port 8080.

Rebuilds both the backend and frontend images from source and starts them detached. The database persists across restarts.

```
App → http://localhost:8080
```

### `make compose-down`
**Use when:** Stopping the stack without losing data.

Brings containers down but leaves volumes (database, uploads) intact.

### `make compose-clean`
**Use when:** You want to wipe all data but not restart yet.

Runs `docker compose down -v` — stops containers and removes every named volume. Database and uploads are gone.

> ⚠️ Destructive. Use intentionally.

### `make compose-fresh`
**Use when:** Simulating a first-run / OOBE on a clean install.

Wipes all volumes (`down -v`), then immediately rebuilds and starts the stack. The app will present the OOBE wizard on next browser load.

```bash
make compose-fresh
# Open http://localhost:8080 → OOBE wizard appears
```

---

## Release workflow

### 1. Bump the version

Edit `VERSION` in the repo root:

```
0.1.5.1
```

Commit it:

```bash
git add VERSION
git commit -m "Bump version to 0.1.5.1"
```

### 2. Run preflight checks

```bash
make preflight
```

Runs `test` → `frontend-build` → `docker-build` (native amd64 image tagged `circuit-breaker:beta`). All three must pass before publishing.

### 3. Publish a multi-arch image

```bash
make docker-publish
```

This automatically:
1. Registers QEMU binfmt handlers (`setup-buildx`) so ARM builds work on an amd64 host
2. Builds for `linux/amd64`, `linux/arm64`, and `linux/arm/v7` with `--no-cache`
3. Pushes two tags to GHCR:
   - `ghcr.io/blkleg/circuitbreaker:0.1.5.1-beta`
   - `ghcr.io/blkleg/circuitbreaker:latest`

> **Requires:** `docker login ghcr.io` first.

**Example release sequence for `v0.1.5.1-beta`:**
```bash
echo "0.1.5.1" > VERSION
git add VERSION && git commit -m "Bump version to 0.1.5.1"
make preflight          # all checks green
docker login ghcr.io -u <your-github-username>
make docker-publish     # builds + pushes 0.1.5.1-beta and latest
git tag v0.1.5.1
git push origin dev --tags
```

### 4. Tag triggers the CI release workflow

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which:
- Re-runs tests
- Builds the multi-arch image via GitHub Actions (QEMU already set up in CI)
- Pushes to GHCR
- Creates a GitHub Release with auto-generated notes

---

## Multi-arch & ARM testing

### `make setup-buildx`
**Use when:** First time doing a multi-arch build on a new machine, or after a Docker Desktop reset.

Registers QEMU CPU emulation handlers and creates the `cb-multiarch` buildx builder. Called automatically by `docker-publish` and `docker-multiarch`, but you can run it standalone to verify the setup.

### `make docker-multiarch`
**Use when:** Publishing a new image without the `--no-cache` flag (faster incremental builds).

Same as `docker-publish` but skips `--no-cache`. Useful for testing image changes where layer caching is acceptable.

### `make test-pi-local`
**Use when:** Verifying the ARM64 image actually boots before tagging a release.

Pulls the published ARM64 image, runs it locally under QEMU emulation on port 8080, hits the `/health` endpoint, then stops the container.

```bash
make test-pi-local
```

---

## Native binary

### `make build-native`
**Use when:** Packaging a standalone executable for the current machine (no Docker required).

Uses PyInstaller to produce a single-file binary in `dist/`:

```
dist/circuit-breaker-0.1.5-linux-x86_64
```

### `make release-dry-run`
Builds the native binary and lists the `dist/` output without pushing anything. Good for checking that PyInstaller produces the expected artifact.

---

## Dependencies

### `make lock`
**Use when:** You've changed `pyproject.toml` or `poetry.lock` and need to regenerate `backend/requirements.txt`.

The Docker build uses `requirements.txt` (not Poetry) for deterministic, offline-capable installs. Always commit `requirements.txt` alongside any `poetry.lock` change.

```bash
# After: poetry add some-package
make lock
git add backend/requirements.txt poetry.lock
git commit -m "Add some-package dependency"
```

---

## Security scanning

### `make snyk-test`
**Use when:** Checking for known vulnerabilities before a release. Scans all projects (backend + frontend).

### `make snyk-monitor`
**Use when:** Registering the current state of the repo in Snyk for ongoing CVE alerts.

### `make snyk-auth`
**Use when:** First-time Snyk setup or after the local CLI token expires.

---

## Quick reference card

| Command | What it does | Destructive? |
|---|---|---|
| `make dev` | Start full dev stack (hot-reload) | No |
| `make stop` | Kill dev ports | No |
| `make backend` | Restart backend only | No |
| `make frontend` | Restart frontend only | No |
| `make test` | Run all tests | No |
| `make lint` | Check code style | No |
| `make format` | Auto-fix code style | No |
| `make ci` | lint + test | No |
| `make preflight` | test + frontend-build + docker-build | No |
| `make compose-up` | Start Docker stack (port 8080) | No |
| `make compose-down` | Stop Docker stack, keep data | No |
| `make compose-clean` | Stop + wipe all volumes | **Yes** |
| `make compose-fresh` | Wipe + rebuild + start (OOBE) | **Yes** |
| `make setup-buildx` | Register QEMU + buildx for ARM builds | No |
| `make docker-build` | Build local amd64 image (`:beta`) | No |
| `make docker-publish` | Build + push multi-arch to GHCR | No |
| `make docker-multiarch` | Same as above, with layer cache | No |
| `make test-pi-local` | Boot ARM64 image locally and health-check | No |
| `make build-native` | PyInstaller binary for current arch | No |
| `make release-dry-run` | Build native binary, list output only | No |
| `make lock` | Regenerate requirements.txt | No |
| `make snyk-test` | Vulnerability scan | No |
| `make snyk-monitor` | Register in Snyk for ongoing alerts | No |

---

## Feature rollout — E2E development guide

### Branch strategy

```
main          ← stable, tagged releases only
  └── dev     ← integration branch, always deployable
        └── feat/<name>     ← new features
        └── fix/<name>      ← bug fixes
        └── hotfix/<name>   ← urgent patches to ship outside normal cadence
        └── maintenance/<name>  ← refactors, dependency bumps, CI work
```

**Rules:**
- Never commit directly to `main`.
- `dev` is the default merge target for all work.
- `main` only receives merges from `dev` when cutting a release.
- Hotfixes branch from `main` (or `dev` if the issue is dev-only), are fixed, then merged into **both** `dev` and `main`.

---

### Phase 1 — Start a feature

```bash
# Always branch from the latest dev
git checkout dev
git pull origin dev
git checkout -b feat/my-feature
```

Start the dev stack:

```bash
make dev
# Backend  → http://localhost:8000
# Frontend → http://localhost:5173
```

Restart individual services as you work:

```bash
make backend     # after Python changes
make frontend    # after frontend config changes (Vite usually hot-reloads without this)
```

---

### Phase 2 — During development

**Run tests frequently — don't wait until you're done:**

```bash
make test              # fast, run this constantly
make test-backend      # verbose pytest when debugging a specific failure
make test-frontend     # Vitest when debugging a component test
```

**Keep code clean as you go:**

```bash
make lint              # catch style issues early
make format            # auto-fix before committing
```

**If you added or changed a Python dependency:**

```bash
poetry add <package>           # adds to pyproject.toml + poetry.lock
make lock                      # regenerates backend/requirements.txt
git add backend/requirements.txt poetry.lock pyproject.toml
```

**Commit often with descriptive messages:**

```bash
git add .
git commit -m "feat(map): add node grouping by environment"
git commit -m "fix(auth): clear token on 401 during profile upload"
git commit -m "chore(deps): bump fastapi to 0.111"
```

---

### Phase 3 — Pre-merge checks

Before opening a PR or merging into `dev`, run the full local preflight:

```bash
make preflight
```

This runs `test` → `frontend-build` → `docker-build` (native amd64 image). All three must be green.

**Also verify the Docker stack end-to-end:**

```bash
make compose-fresh     # wipe + rebuild + start — triggers OOBE wizard
# Open http://localhost:8080, complete OOBE, smoke-test your changes
```

If your feature involves first-run behaviour, explicitly test with a clean database:

```bash
make compose-clean     # wipe only
make compose-up        # start fresh without rebuilding images
```

---

### Phase 4 — Push and open a PR

```bash
git push origin feat/my-feature
```

Open a PR targeting `dev` on GitHub.

**CI checks that run automatically on every PR and push to `dev`/`main`:**

| Check | Workflow | What it does |
|---|---|---|
| Backend tests | `dev-checks.yml` | `pytest -q` on Python 3.11 |
| Frontend build | `dev-checks.yml` | `npm ci && npm run build` |
| Docs build | `dev-checks.yml` | `zensical build` |
| Full preflight | `preflight.yml` | tests + frontend build + Docker smoke test |

All checks must pass before merging.

---

### Phase 5 — Merge into dev

```bash
# After PR is approved and CI is green:
git checkout dev
git pull origin dev
git merge --no-ff feat/my-feature
git push origin dev
```

The `--no-ff` flag keeps the feature visible as a unit in the log. Squash only if the branch history is noisy/WIP commits.

After merging, delete the branch:

```bash
git branch -d feat/my-feature
git push origin --delete feat/my-feature
```

---

### Phase 6 — Hotfix workflow

Use this when a bug needs to ship outside the normal feature cadence.

```bash
git checkout main
git pull origin main
git checkout -b hotfix/broken-thing

# … fix the bug …

make test              # must pass
make preflight         # must pass

# Merge into BOTH main and dev
git checkout main
git merge --no-ff hotfix/broken-thing

git checkout dev
git merge --no-ff hotfix/broken-thing

git push origin main dev
git branch -d hotfix/broken-thing
git push origin --delete hotfix/broken-thing
```

> Hotfixes that only affect dev-branch code can skip the `main` merge, but always merge into `dev` last.

---

### Phase 7 — Cut a release

**1. Bump the version**

Edit `VERSION` in the repo root. Follow the pattern:

```
# patch release
0.1.5  →  0.1.5.1

# minor release
0.1.5  →  0.2.0

# hotfix on a shipped minor
0.1.5  →  0.1.5.1
```

Examples of tags this produces:

| VERSION | Docker tag | Git tag |
|---|---|---|
| `0.1.5` | `0.1.5-beta` | `v0.1.5` |
| `0.1.5.1` | `0.1.5.1-beta` | `v0.1.5.1` |
| `0.2.0` | `0.2.0-beta` | `v0.2.0` |
| `1.0.0` | `1.0.0` | `v1.0.0` |

**2. Run the documentation checklist** (see below)

**3. Preflight**

```bash
make preflight
```

**4. Merge dev into main**

```bash
git checkout main
git pull origin main
git merge --no-ff dev
git push origin main
```

**5. Publish the image manually (optional — CI does this on tag push)**

```bash
docker login ghcr.io -u <your-github-username>
make docker-publish
# Pushes: ghcr.io/blkleg/circuitbreaker:0.1.5.1-beta
#         ghcr.io/blkleg/circuitbreaker:latest
```

**6. Tag and push — this triggers the CI release workflow**

```bash
git tag v0.1.5.1
git push origin main --tags
```

Pushing the tag fires `.github/workflows/release.yml` which:
- Runs tests
- Builds the multi-arch image (`linux/amd64`, `linux/arm64`, `linux/arm/v7`)
- Pushes to GHCR
- Creates a GitHub Release with auto-generated notes

**7. Verify the ARM image boots**

```bash
make test-pi-local
```

---

### Documentation checklist

Complete this before every merge to `main` or public release:

- [ ] `VERSION` file updated
- [ ] `CHANGELOG` or GitHub Release notes drafted (what changed, what's fixed)
- [ ] Any new API endpoints documented (route, method, request/response shape)
- [ ] New environment variables added to `docker/docker-compose.yml` comments and README
- [ ] New `make` targets added to `DEV_PLAYBOOK.md` quick reference table
- [ ] `backend/requirements.txt` regenerated (`make lock`) if dependencies changed
- [ ] Frontend `.env` / `VITE_*` variables documented if new ones were added
- [ ] Breaking changes flagged in the PR description and release notes
- [ ] OOBE flow manually tested on a clean database (`make compose-fresh`)
- [ ] ARM64 boot verified (`make test-pi-local`) before tagging

---

### Full E2E example — shipping `v0.1.5.1-beta`

```bash
# 1. Branch off dev
git checkout dev && git pull origin dev
git checkout -b feat/audit-log-improvements

# 2. Develop + test continuously
make dev
make test              # run after every meaningful change

# 3. Preflight before PR
make format
make lint
make preflight

# 4. Push and merge via PR
git push origin feat/audit-log-improvements
# Open PR → dev, get review, CI green → merge

# 5. Bump version on dev
echo "0.1.5.1" > VERSION
git add VERSION
git commit -m "Bump version to 0.1.5.1"
git push origin dev

# 6. Final integration test
make compose-fresh
# Verify OOBE + new features at http://localhost:8080

# 7. Merge dev → main
git checkout main && git pull origin main
git merge --no-ff dev
git push origin main

# 8. Tag — triggers CI release workflow
git tag v0.1.5.1
git push origin main --tags

# 9. Verify ARM image
make test-pi-local

# 10. Done — GitHub Release created automatically by CI
```
