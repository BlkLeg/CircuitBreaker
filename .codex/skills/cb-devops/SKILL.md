---
name: cb-devops
description: DevOps, build, Docker, and release workflows for Circuit Breaker. Use when working on Makefile targets, Docker builds (Dockerfile / docker/backend.Dockerfile / docker/frontend.Dockerfile), Docker Compose stacks (docker/docker-compose.yml / docker-compose.prebuilt.yml), multi-arch image publishing to GHCR, PyInstaller native binary builds, VERSION-file-driven versioning, poetry/pip dependency management, nginx config (docker/nginx.conf), install/uninstall scripts, or CI/CD preflight checks.
---

# Circuit Breaker — DevOps Skill

## Versioning

Single source of truth: **`/VERSION`** file (raw semver, e.g. `0.1.4`).

Everything else derives from it automatically:
- `backend/pyproject.toml` reads it via `hatchling` dynamic version (`path = "../VERSION"`).
- `frontend/package.json` syncs via `npm run syncversion` (run automatically as part of `npm run build`).
- Docker image tags: `0.x.y` → `0.x.y-beta`; `1.x.y+` → `1.x.y` (see `RELEASE_TAG` in Makefile).
- PyInstaller binary name includes `$VERSION-$OS_ARCH`.

**To cut a release**: edit `/VERSION`, then rebuild.

## Makefile quick-reference

Run `make help` to see all targets with descriptions.

| Target | What it does |
|--------|-------------|
| `make dev` | Kill dev ports, start backend (`uvicorn --reload :8000`) + frontend (`vite :5173`) |
| `make backend` | Restart backend only |
| `make frontend` | Restart frontend only |
| `make stop` | Kill processes on ports 8000 and 5173 |
| `make test` | Backend pytest (quiet) |
| `make test-backend` | Backend pytest (verbose, `--asyncio-mode=auto`) |
| `make test-frontend` | Frontend Vitest |
| `make test-all` | Both |
| `make test-coverage` | Coverage reports for both |
| `make lock` | Regenerate `backend/requirements.txt` from `poetry.lock` via `scripts/gen_requirements.py` |
| `make docker-build` | Build `circuit-breaker:beta` image with BuildKit |
| `make compose-up` | Rebuild + start `docker/docker-compose.yml` stack (port 8080) |
| `make compose-down` | Stop and remove compose stack |
| `make preflight` | test + frontend-build + docker-build (pre-commit gate) |
| `make build-native` | PyInstaller single binary for current OS/ARCH |
| `make docker-publish` | Multi-arch buildx push to GHCR (`linux/amd64,linux/arm64`) |
| `make docs` | Serve docs locally (Zensical, port 8001) |
| `make docs-build` | Build static docs site |

## Virtual environment

The repo uses `.venv/` at the repo root (not inside `backend/`).  
Activate with `source .venv/bin/activate` or use `.venv/bin/<command>` directly (as Makefile does).

```bash
python -m venv .venv
.venv/bin/pip install -e backend/[dev]
```

## Docker layout

```
docker/
├── backend.Dockerfile   # Python backend image (multi-stage: build → slim)
├── frontend.Dockerfile  # Node build → nginx serve
├── nginx.conf           # Serves /frontend/dist, proxies /api to backend:8000
├── docker-compose.yml   # Dev/self-host stack (builds from source)
├── docker-compose.prebuilt.yml  # Pulls pre-built GHCR image
└── entrypoint.sh        # Backend container entrypoint (runs migrations then uvicorn)
```

### Single-container vs. Compose

| Mode | How | Port |
|------|-----|------|
| One-liner install | `install.sh` pulls GHCR image, single container | `CB_PORT` (default 8080) |
| Compose (source) | `make compose-up` | 8080 |
| Compose (prebuilt) | `docker compose -f docker/docker-compose.prebuilt.yml up` | 8080 |
| Local dev | `make dev` | backend :8000, frontend :5173 |

### Key environment variables

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `sqlite:///./data/app.db` | Override for compose volume path |
| `UPLOADS_DIR` | `data/uploads` | Set `/app/data/uploads` in Docker |
| `STATIC_DIR` | `../frontend/dist` | Set `/app/frontend/dist` in single-image builds |
| `CB_VAULT_KEY` | (ephemeral) | Fernet key for telemetry credential encryption |
| `DEBUG` | `false` | |
| `APP_VERSION` | from `/VERSION` | Set as Docker build arg |
| `CB_PORT` | `8080` | Install script variable |
| `CB_IMAGE` | `ghcr.io/blkleg/circuitbreaker:latest` | Install script variable |
| `CB_CONTAINER` | `circuit-breaker` | Install script variable |
| `CB_VOLUME` | `circuit-breaker-data` | Install script variable |

### ARP scan capabilities

For discovery ARP phase, the backend container needs:

```yaml
cap_add:
  - NET_RAW
  - NET_ADMIN
network_mode: "host"
```

Without these, ARP is skipped; nmap TCP/ICMP still works.

## Dependency management

- **Lock file**: `backend/poetry.lock` (Poetry) is the source of truth.
- **requirements.txt**: generated from `poetry.lock` via `make lock` (runs `scripts/gen_requirements.py`).
- **Docker builds** use `requirements.txt` for `pip install` (not Poetry).
- **Dev installs** use `pip install -e backend/[dev]` against the venv.

After adding a new Python dependency:
1. Add to `backend/pyproject.toml` `[project.dependencies]`.
2. Run `cd backend && poetry lock --no-update` to update `poetry.lock`.
3. Run `make lock` to regenerate `requirements.txt`.
4. Commit both `poetry.lock` and `requirements.txt`.

## Multi-arch publishing

```bash
# Requires: docker buildx with QEMU, docker login ghcr.io
make docker-publish
# Builds linux/amd64 + linux/arm64, tags as <version>-beta and latest, pushes to GHCR
```

Image repo is derived from `git config remote.origin.url` → lowercased → prefixed with `ghcr.io/`.

## Native binary (PyInstaller)

```bash
make build-native
# Outputs: dist/circuit-breaker-<version>-<os>-<arch>
```

The `.spec` file at repo root (`circuit-breaker-v0.1.0-dev-linux-x86_64.spec`) documents the PyInstaller configuration used for the current release.

## Docs

- Framework: **Zensical** (MkDocs-compatible, see `mkdocs.yml`)
- Source: `docs/` directory
- Built output: `site/`
- `make docs` → serves on :8001
- `make docs-build` → builds `site/`
