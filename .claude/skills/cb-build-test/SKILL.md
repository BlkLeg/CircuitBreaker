---
name: cb-build-test
description: How Circuit Breaker is built, tested, packaged, and kept secret-safe — the make dev/verify/test targets, the PostgreSQL integration test database and its fixtures, the mono Docker image and native deb/rpm/apk/AppImage packages, and the Fernet vault plus air-gap handling for credentials. Use this whenever running or writing tests, setting up or debugging the dev environment, working on Dockerfile.mono or the entrypoint/supervisord config, building or releasing packages, adding an integration that stores credentials, or touching anything involving CB_VAULT_KEY, CB_AIRGAP, or secret material.
---

# Circuit Breaker — Build, Test & Packaging

## Dev environment

```bash
make install     # bootstrap once
make dev         # deps + migrations + backend + frontend + monitor workers
make deps-up     # Postgres / Redis / NATS in Docker, nothing else
make migrate     # alembic
make reset-oobe  # rewind to the first-run wizard
```

`make dev` runs the app **natively** against Dockerized dependencies. The
Makefile calls this "ZERO DOCKER DRIFT" for `make backend` — the point is that
the thing you debug is the thing that ships. Reach for `make deps-native-up`
when you need prod parity, since it uses the same systemd units `install.sh`
installs on a user's box.

Note `make backend` has no reload; `make backend-watch` does. The comment marks
watch mode as post-fix only, because auto-reload masks import-time failures that
a real start would surface.

## Testing

```bash
make test-backend   # tests/integration — provisions the test DB first
make test-frontend  # vitest
make test           # both
make verify         # the pre-push gate
```

Test code lives in four places, and putting a test in the wrong one is how it
silently never runs:

```
apps/backend/tests/           unit + service tests, own pyproject config
tests/integration/            backend-scoped, needs live PostgreSQL
tests/unit/                   repo-root scoped
tests/build/                  repo-policy / governance suites
apps/frontend/src/__tests__/  vitest, *.test.jsx
```

`tests/build/` is a real enforcement suite — tracked-file policy, governance
files, CLI parity, restart probes, version parity. It once collected zero tests
because pytest's default `norecursedirs` contains "build"; `pytest.ini` at the
repo root exists specifically to override that. Read the comments in that file
before changing collection settings, because the failure mode is a suite that
looks green and enforces nothing.

### The integration database

`make test-db` runs `scripts/ensure_test_db.py` against `CB_TEST_DB_URL` and
**never drops the database**. Integration tests run with:

```
CB_ALLOW_DEGRADED_DEPENDENCIES=true    # Redis/NATS optional
CB_ALLOW_DIRECT_EGRESS=true
```

These tests hit real PostgreSQL on purpose. Don't mock the database in
`tests/integration/` — assert against real persisted state, because the bugs
worth catching there are constraint, migration, and transaction bugs that a mock
cannot express. Fixtures and factories are in `apps/backend/tests/conftest.py`
and `factories.py`.

When a test fails, decide explicitly whether the **test** is wrong (fixture
drifted from the schema) or the **code** is wrong (missing field, bad query),
and say which. Batch fixes by category instead of re-running the full suite
after each one — the backend suite is minutes, not seconds.

Coverage is gated at `--cov-fail-under=56`, ratcheted to measured reality.
Raise it only after coverage genuinely clears a higher number; never lower it
to turn a build green.

## Packaging

Two distribution paths, both real:

**Native packages** are the primary install route:
```bash
make build           # tarball + deb + rpm + apk + AppImage + .pkg.tar.zst
make build-release   # toolchain + build
make sign            # GPG-sign artifacts + SHA256SUMS (needs GPG_KEY_ID)
make sbom            # syft
```
Driven by `scripts/build_native_release.py` and `nfpm.yaml` (arch from `GOARCH`).

**The mono Docker image** packs Postgres, NATS, Redis, backend, workers, and
nginx into one container:
```bash
make docker-build    # Dockerfile.mono -> $(DOCKER_REGISTRY):$(cat VERSION)
```

Facts about `Dockerfile.mono` that are easy to get wrong:

- The runtime base is **`python:3.12-slim-bookworm`** — Debian, not Alpine.
  Only the frontend builder stage uses Alpine. Use `apt-get`, not `apk`.
- The container **intentionally starts as root** so the entrypoint can fix
  volume ownership and wire the embedded services; supervisord then drops
  application processes to `breaker:1000` (uid/gid 1000, no home, nologin).
  There is a `checkov:skip=CKV_DOCKER_3` on that line explaining it. Do not
  "fix" this by adding a top-level `USER breaker` — the bootstrap breaks.
- `VOLUME ["/data"]` is the only persistent path.
- `HEALTHCHECK` targets **`/livez`**, deliberately not `/health` or `/readyz`:
  a failing healthcheck restarts the container, and readiness failing during a
  slow dependency start must not become a restart loop.
- Multi-arch is amd64 + arm64, built as **separate per-platform jobs** joined
  with `buildx imagetools create` in `release.yml` — not one `--platform`
  invocation. The combined build was OOM-killed; the comment there records why.
  Preserve that split.

## Secrets, vault, and air-gap

Credentials for integrations are Fernet-encrypted at rest under `CB_VAULT_KEY`
via `services/vault_service.py`, with the API surface in `api/vault.py`. The key
auto-rotates on a daily APScheduler job that re-encrypts stored credentials and
hot-swaps the in-memory vault; `cb-security-hardening` covers the rotation
contract in detail.

Rules that keep this safe:

- Encrypt before the value reaches the database. Never log a credential, and
  never echo one back in an API response.
- Secrets come from env, never from the image or a default in compose.
  `CB_DB_PASSWORD`, `CB_VAULT_KEY`, `CB_JWT_SECRET`, and `NATS_AUTH_TOKEN` all
  use `${VAR:?...}` so a missing one fails the container at start rather than
  booting something insecure.
- `CB_AIRGAP=true` must block outbound network calls. Any new integration that
  reaches the internet needs to honor it, plus the CIDR allowlist in
  `core/network_acl.py`. Air-gapped homelabs are a first-class deployment here,
  not an edge case.
- Credential changes belong in the audit log.

`gitleaks` runs as a pre-commit hook. If it blocks a commit, remove the secret
and rotate it — the value is already in your working tree's history if you
staged it, so bypassing the hook is never the fix.

```bash
make security-check    # gate mode — fails on HIGH/CRIT
make security-report   # full report, non-blocking
```
