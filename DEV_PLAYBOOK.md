# Circuit Breaker — Dev Playbook

Quick reference for every `make` command. Run `make help` for a one-line summary. One-person team, mono-only Docker stack.

---

## When to use what

| Goal | Command |
|------|--------|
| **Local dev** (backend + frontend on host) | `make dev` |
| **Run app in Docker** (builds mono image if needed, starts stack) | `make compose-up` |
| **Clean Docker run** (wipe data, rebuild, start — e.g. test OOBE) | `make compose-fresh` |
| **Rebuild mono image only** (no start) | `make compose-build` then `make compose-up` |
| **Before commit / PR** | `make ci` or `make test`; optionally `make lint` / `make format` |
| **Before release** | Bump `VERSION` → `make preflight` → `make docker-mono-release TAG=x.y.z` (then push tag for CI) |
| **Native binary** (current machine) | `make build-native` (or `make build-native-docker` for glibc build) |

---

## Versioning

The single source of truth is the repo-root `VERSION` file. Edit it before cutting a release.

| VERSION | RELEASE_TAG |
|---------|-------------|
| `0.1.5` | `0.1.5-beta` |
| `1.0.0` | `1.0.0` (no suffix once v1+) |

---

## Daily development

### `make dev`
**Use when:** Starting a fresh dev session.

Kills anything on ports 8000 / 5173, then starts the FastAPI backend (hot-reload) and the Vite frontend dev server.

- Backend → http://localhost:8000  
- Frontend → http://localhost:5173  

### `make stop`
**Use when:** Kill both dev servers without restarting.

### `make backend`
**Use when:** Restart only the API (e.g. after Python changes). Kills port 8000 and relaunches uvicorn with `--reload`.

### `make frontend`
**Use when:** Restart only the frontend. Kills port 5173 and relaunches `npm start`.

---

## Tests & linting

| Command | Use when |
|---------|----------|
| `make test` | Quick sanity check before committing. Backend pytest + frontend Vitest. |
| `make test-backend` | Debugging a backend test — verbose pytest. |
| `make test-frontend` | Debugging a frontend component test. |
| `make test-all` | Full backend + frontend tests with verbosity. |
| `make test-coverage` | Coverage before PR/release. |
| `make lint` | Enforce code style. Ruff + ESLint. |
| `make format` | Auto-fix style. Ruff format + Prettier. |
| `make ci` | Lint + test. Matches CI on push. |

---

## Docker (mono only)

One container: Postgres + NATS + backend + workers + nginx. Compose builds the mono image from `Dockerfile.mono` when you run `compose-up` or `compose-fresh` with `--build`.

**Required env:** `CB_DB_PASSWORD`, `CB_VAULT_KEY` (e.g. in `.env` at repo root).

| Command | What it does |
|---------|----------------|
| `make compose-up` | Build mono image if needed, start stack. Data persists. |
| `make compose-down` | Stop stack. Data kept. |
| `make compose-clean` | Stop and remove all volumes. **Destructive.** |
| `make compose-fresh` | Wipe volumes, build, start. Use to test OOBE / first run. |
| `make compose-build` | Build mono image only (no up). Use to force rebuild. |
| `make dev-stop-install` | Stop container from `install-mono.sh` if running (avoids port/name conflicts). |

TLS: put certs in `/data/tls` (see README / install-mono.sh). No Caddy; nginx serves HTTP and optional HTTPS.

If a mono boot fails before migrations complete, a plain rebuild can keep reusing the same broken
`./circuitbreaker-data/pgdata`. For migration-path changes, validate with a clean data dir:

```bash
docker stop circuitbreaker || true
rm -rf ./circuitbreaker-data/pgdata
make compose-build
make compose-up
```

Use `make compose-fresh` when you want the same clean-start behavior and are okay wiping the
compose-managed data for the mono stack.

---

## Release workflow

1. Edit `VERSION` in repo root.
2. Run **`make preflight`** (test + frontend-build + mono image build).
3. Run **`make docker-mono-release TAG=x.y.z`** (build, E2E test, push multi-arch to GHCR). Requires `docker login ghcr.io`.
4. Tag and push so CI runs: `git tag vx.y.z && git push origin --tags`.

Optional: **`make test-mono-e2e`** to run E2E against the mono container locally.

---

## Dependencies

### `make lock`
**Use when:** You changed `pyproject.toml` or `poetry.lock`.

Regenerates `apps/backend/requirements.txt`. Commit it alongside `poetry.lock`.

```bash
poetry add <package>
make lock
git add apps/backend/requirements.txt poetry.lock pyproject.toml
```

---

## Quick reference

| Command | Purpose | Destructive? |
|---------|---------|--------------|
| `make dev` | Start dev stack (host) | No |
| `make stop` | Kill dev ports | No |
| `make backend` | Restart backend only | No |
| `make frontend` | Restart frontend only | No |
| `make test` | Run all tests | No |
| `make lint` | Check style | No |
| `make format` | Fix style | No |
| `make ci` | lint + test | No |
| `make preflight` | test + frontend-build + mono build | No |
| `make compose-build` | Build mono image only | No |
| `make compose-up` | Build (if needed) + start | No |
| `make compose-down` | Stop stack, keep data | No |
| `make compose-clean` | Stop + wipe volumes | **Yes** |
| `make compose-fresh` | Wipe + build + start | **Yes** |
| `make dev-stop-install` | Stop install-mono container | No |
| `make docker-mono-release TAG=x.y.z` | Build, E2E, push mono | No |
| `make test-mono-e2e` | E2E test mono container | No |
| `make build-native` | PyInstaller binary | No |
| `make build-native-docker` | Native build in Docker (glibc) | No |
| `make lock` | Regenerate requirements.txt | No |

---

## Security (optional)

- **`make snyk-test`** — vulnerability scan.
- **`make security-scan`** — full scan (Bandit, Semgrep, etc.).

---

## Branch strategy (short)

- `main` — stable, tagged releases only.
- `dev` — integration branch. PR into `dev`; merge `dev` → `main` when releasing.
- Feature branches: `feat/<name>`, `fix/<name>`, etc. from `dev`.
