# Circuit Breaker

Self-hosted homelab visualization platform: interactive topology across hardware,
services, networks, and clusters. Users are homelabbers and self-hosters who value
simple, local, visual, zero-lock-in tooling.

**Current version: see `VERSION` (0.4.2 at time of writing).**
Repo: https://github.com/BlkLeg/circuitbreaker · Image: `ghcr.io/blkleg/circuitbreaker`

## Layout

```
apps/backend/src/app/   FastAPI + SQLAlchemy + Pydantic, Python 3.12
apps/frontend/src/      React + Vite + Tailwind, JavaScript/JSX (not TypeScript)
apps/agent/             Go agent
docker/                 mono image entrypoint, supervisord, nginx
tests/                  integration/, build/ (repo-policy suites), fixtures/
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
make verify    # the pre-push gate (~3m20s); runs with CB_VERIFY_BACKEND=off
```

If the change touches `apps/backend/src/app`, run `make verify-full` instead —
`make verify` skips the backend unit suite entirely.

Never lower the coverage gate to make a build green.

### What the gates do NOT cover

`make verify` and `make verify-full` run unit suites, lint, and the security
gate. **Neither runs a browser and neither runs the agent.** Two whole suites
sit outside them:

| Suite | Covers | How to run it |
|---|---|---|
| Browser E2E (Playwright) | the real frontend in a real browser | `cd apps/frontend && npx playwright test` |
| Composed Agent E2E | the agent against the mono image | `make e2e-local` |

A green `verify-full` therefore says nothing about a frontend dependency bump,
a Playwright change, an agent change, or anything about rendering, routing or
enrollment.

### Rules for claiming something is verified

These exist because each one has already been broken here, at cost.

1. **Name the suite that exercises the change, and run it.** Do not offer a
   gate's exit code as evidence for a change that gate does not execute. A
   frontend dependency bump needs the browser E2E; an agent or harness change
   needs `make e2e-local`. If the covering suite was not run, say so plainly
   rather than reporting the gate that was.
2. **Never dismiss a red check as stale, flaky, or pre-existing without
   proving it.** Proof is reproducing it, or running the same check on a clean
   tree at an older commit and showing it fails identically. "Those runs
   predate the fix" is a hypothesis, not a finding.

   A red required check has exactly two permitted outcomes: it is **fixed**, or
   it is **quarantined** with a row in
   `specs/1.0.0/release-control/quarantine-register.csv` naming an owner, a
   tracking item and an expiry no more than 90 days out. There is no third
   outcome. "Probably flaky" is not an outcome, and
   `tests/build/test_quarantine_register.py` fails the build on an expired row.
3. **Push only after the covering suite passes locally.** CI is for
   confirmation, not discovery. Pushing to find out costs ~40 minutes per
   round and burns someone else's time.
4. **Never dispatch CI against a ref you have not confirmed is on the remote.**
   Check the push actually landed — `git ls-remote` — before triggering a
   workflow, or the run tests code nobody can fetch.
5. **Dependencies that are pinned in two places move together.** The Playwright
   container tag and `@playwright/test` are the known pair;
   `tests/build/test_playwright_image_matches_package.py` enforces it. When a
   bump breaks a pairing like this, add the guard rather than only fixing the
   instance.
6. **A binary that answers `--version` has not been shown to run.** Version
   parity is an identity check. The only evidence that an artifact works is
   something importing or starting the application inside it — `circuit-breaker
   --selftest` at minimum, a boot and a `/readyz` probe where the suite allows.

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
