# Circuit Breaker

Self-hosted homelab visualization platform: interactive topology across hardware,
services, networks, and clusters. Users are homelabbers and self-hosters who value
simple, local, visual, zero-lock-in tooling.

**Current version: see `VERSION` (0.4.0 at time of writing).**
Repo: https://github.com/BlkLeg/circuitbreaker · Image: `ghcr.io/blkleg/circuitbreaker`

## Layout

```
apps/backend/src/app/   FastAPI + SQLAlchemy + Pydantic, Python 3.12
apps/frontend/src/      React + Vite + Tailwind, JavaScript/JSX (not TypeScript)
apps/agent/             Go agent
docker/                 mono image entrypoint, supervisord, nginx
tests/                  integration/, unit/, build/ (repo-policy suites)
specs/                  release control, owner map
```

Stack: PostgreSQL, Redis (cache + WS pub/sub), NATS (internal bus), nginx.

## Product principles

**Freeform first.** Any `name`/`model`/`vendor` the user types must save. Catalogs
and autocomplete exist to speed input up, never to block it.

**Simple first.** The core path is: add a device, draw lines. Telemetry, scans, and
integrations are opt-in on top of that.

**Backward compatible.** Self-hosters upgrade on their own schedule, and a
half-updated deployment must still work. Migrations use `ADD COLUMN IF NOT EXISTS`;
add fields alongside old ones rather than renaming or dropping.

**Air-gap is first-class.** `CB_AIRGAP=true` must block outbound calls. No feature
may assume internet access.

**No placeholders.** Ship complete code — no `TODO`, bare `pass`, or
`NotImplementedError` left behind. If something is genuinely unclear, ask.

## Conventions

- **Python**: snake_case, full type annotations (mypy runs with
  `disallow_untyped_defs`), docstrings on classes and public functions. Services hold
  logic; routes stay thin. Sessions via `Depends(get_db)`.
- **Frontend**: `.jsx` components (PascalCase), `.js` hooks (`useCamelCase`) and API
  modules. All HTTP goes through the axios client in `src/api/client.jsx` — no inline
  `fetch`. Always render loading and error states.
- **API**: snake_case JSON, errors as `{"detail": "..."}`, correct HTTP codes.
- **Secrets**: never hardcode credentials, tokens, signing material, JWT secrets, or
  vault keys — including in CI workflows, tests, examples, and fixtures. Generate
  ephemeral values at runtime or inject them through the platform's secret store.
- **Commits**: `feat:` / `fix:` / `chore:` / `docs:`.

## Before pushing

```bash
make lint      # ruff + mypy + eslint
make verify    # the pre-push gate (~3m20s)
```

Never lower the coverage gate to make a build green.

## Skills

Four skills carry the detail — consult them rather than reconstructing conventions:

- **cb-code-quality** — gates, naming, constants, error handling, tests
- **cb-security-hardening** — auth, headers, container hardening, vault rotation
- **cb-realtime-api** — NATS subjects, WebSocket/SSE streams, frontend↔backend contract
- **cb-build-test** — dev env, test DB, packaging, secrets and air-gap

## Two things that look like bugs but aren't

- The mono container **starts as root on purpose** so the entrypoint can fix volume
  ownership; supervisord then drops app processes to `breaker:1000`. Don't add a
  top-level `USER`.
- The mono runtime base is **Debian slim**, not Alpine. Only the frontend builder
  stage is Alpine.
