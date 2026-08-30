---
name: cb-code-quality
description: Circuit Breaker code conventions and the quality gates that actually block a push — ruff, mypy, eslint, the pytest coverage ratchet, and the make verify tiers. Use this whenever writing, reviewing, or refactoring backend Python (FastAPI/SQLAlchemy under apps/backend/src/app) or frontend JavaScript/JSX (apps/frontend/src), before committing or pushing anything, when a lint or type error needs fixing, or when asked about naming, constants, error handling, file structure, or test requirements in this repo.
---

# Circuit Breaker — Code Quality

## Run the real gates, not remembered ones

Every check below is wired into the Makefile. Prefer these over ad-hoc tool
invocations — they carry the flags, paths, and env the repo actually needs, and
they are the same commands CI runs.

```bash
make lint          # ruff check + mypy src/app + eslint          (fast)
make format        # ruff format + prettier
make verify        # Tier 0 static + Tier 1 unit — THE PRE-PUSH GATE (~3m20s)
make verify-full   # verify + the backend suite                  (~6m45s)
make test-backend  # integration tests; provisions the test DB first
make test-frontend # vitest
```

`make verify` is the gate to run before pushing. `make verify-fast` (~90s) is
the Tier 0 static subset when you only need a quick signal.

There is no flake8 and no `cognitive-complexity` plugin in this project. Do not
install them — **ruff** is the Python linter (`line-length = 100`,
`select = ["E", "F", "I", "UP", "ASYNC"]`) and it is also the formatter.

`.pre-commit-config.yaml` runs gitleaks, ruff, ruff-format, and `mypy --strict`
on commit. If a commit is rejected, read which hook failed before changing code —
a gitleaks rejection means a secret reached a staged file and the fix is to
remove the secret, never to bypass the hook.

## The frontend is JavaScript, not TypeScript

`apps/frontend/src` is 318 `.jsx` + 123 `.js` files and one stray `.ts`. There
is a `tsconfig.json`, but it is not what the code is written in.

Write `.jsx` for components and `.js` for hooks, API modules, and helpers, and
match the surrounding file. Do not add TypeScript annotations, `interface`
declarations, or `.ts`/`.tsx` files to existing directories — a lone typed file
in a JS tree is churn for the next reader, not an upgrade. Type intent goes in
JSDoc and PropTypes where the surrounding code already uses them.

## Backend types are enforced

`[tool.mypy]` sets `disallow_untyped_defs = true`, `check_untyped_defs = true`,
and `warn_return_any = true` against `src/app`. Every function you add needs
annotated parameters and a return type, or `make lint` fails:

```python
async def get_cached_telemetry(hardware_id: int) -> dict | None:
```

`ignore_missing_imports` is on and `import-untyped` is disabled, so third-party
libraries without stubs will not fight you. Your own code has no such excuse.

## Constants

```
Backend  : apps/backend/src/app/core/constants.py
Frontend : apps/frontend/src/lib/constants.js
```

Name any literal that carries meaning — a TTL, a threshold, a retry budget, a
port. The value is that a reader meets `TELEMETRY_CACHE_TTL_SECONDS` instead of
`300` and does not have to reconstruct intent from a number.

```python
await redis.setex(cache_key, TELEMETRY_CACHE_TTL_SECONDS, payload)   # not 300
```

Exempt: `0`, `1`, `""`, booleans, and format strings. A literal used exactly
once, immediately beside the thing that explains it, is often clearer inline —
use judgment rather than extracting on reflex.

## Error handling

Anything touching I/O — DB, Redis, NATS, HTTP, filesystem, SNMP/IPMI/Redfish —
needs a handler that names the exception it expects. The reason to catch
specifically is that a broad catch hides the failure you did not anticipate,
and this project runs unattended in other people's homelabs where a silently
swallowed error is indistinguishable from working software.

```python
try:
    raw = await get_redis().get(cache_key)
except redis.ConnectionError as exc:
    logger.warning("[telemetry_cache] Redis unavailable for hw:%s: %s", hardware_id, exc)
    return None
except json.JSONDecodeError as exc:
    logger.error("[telemetry_cache] corrupt cache for hw:%s: %s", hardware_id, exc)
    return None
```

Every handler either logs and returns a typed fallback, or re-raises. Never
`except Exception: pass`. Prefix log messages with `[module_name]` and use
`logger`, never `print()`.

Degradation is a first-class path here: Redis or NATS being down should leave
the app serving REST, not crashing. `CB_ALLOW_DEGRADED_DEPENDENCIES` exists for
exactly this and the integration suite runs with it on.

## Structure — targets for code you write

Aim for functions under ~40 lines, nesting at or below 3 levels, and modules
that hold one responsibility. Prefer splitting a long function into named
helpers over compressing it — `_is_active_hardware(r)` tells a reader what the
condition means in a way a stacked boolean never does.

**These are targets for new and modified code, not a mandate to refactor what
is already here.** 166 of 301 backend files exceed 150 lines; `db/models.py` is
2846 and `services/discovery_service.py` is 2805. Those sizes are a known
property of the codebase, not a defect list to burn down. When you touch a large
file, add your change in the local style and leave the rest alone unless
splitting it is the task you were actually given. Unrequested refactors of a
2800-line module are how a small fix becomes an unreviewable diff.

## Naming

```
Python functions : verb_noun()      poll_device(), write_telemetry()
Python classes   : PascalCase       TelemetryCollector, VaultService
Constants        : UPPER_SNAKE      MAX_RETRY_COUNT, CACHE_TTL_SECONDS
Booleans         : is_/has_/can_    is_active, has_telemetry, can_retry
JSX components   : PascalCase.jsx   TelemetryBadge, NodeCard
React hooks      : useCamelCase.js  useTelemetryStream, useDiscoveryStream
```

Avoid single letters outside loop counters, and avoid `cfg`/`mgr`/`proc`/`res`.
Comments explain *why*; the code should already say *what*.

## Tests and the coverage ratchet

```
apps/backend/tests/          unit + service tests   (pytest, asyncio_mode=auto)
tests/integration/           needs live PostgreSQL  (make test-backend)
tests/build/                 repo-policy/governance suites
apps/frontend/src/__tests__/ vitest, *.test.jsx
```

Backend coverage is gated at `--cov-fail-under=56`, deliberately ratcheted to
the suite's measured value. **Never lower it to make a red build green** — the
number moves up only after real coverage clears the new figure.

New endpoints, services, and hooks need at least a happy path and one error or
edge case. Root-suite pytest runs with `filterwarnings = error`: a new warning
fails the run, and the fix is the underlying defect, not an ignore entry. If an
ignore is genuinely unavoidable, it must name an owner and a removal condition —
`tests/build/test_skip_register.py` enforces that.

## Before you push

- [ ] `make lint` clean — ruff, mypy, eslint
- [ ] `make verify` passes (or `make verify-full` if you touched backend logic)
- [ ] New/changed functions carry full type annotations
- [ ] I/O paths catch specific exceptions and log with a `[module]` prefix
- [ ] Meaningful literals live in `constants.py` / `constants.js`
- [ ] New behavior has a test; coverage gate not lowered
- [ ] No `print()`, no commented-out code, no secrets in the diff
- [ ] Frontend additions are `.js`/`.jsx`, matching the file around them
