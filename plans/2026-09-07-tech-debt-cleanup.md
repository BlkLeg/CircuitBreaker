# Circuit Breaker — Technical Debt Cleanup Plan

**Date:** 2026-09-07
**Status:** Active
**Scope:** current tree at `VERSION` **0.4.2** (README already matches; `CLAUDE.md` still says 0.4.0)
**Constraint:** no new product features. Goal is scalability, maintainability, and contributor cleanliness.
**Method:** layout inventory, LOC ranking, test-runner wiring, doc/plan status, and contributor-file review. No production code was changed in the planning pass.

A plan is a record of intent at its date; it is not evidence that the work shipped. The requirement ledger (`specs/1.0.0/release-control/requirement-ledger.csv`) remains the status source for 1.0.0 requirements.

---

## Executive summary

Circuit Breaker is a working modular monolith with unusually strong gates for a homelab project (`make verify`, coverage ratchets, gitleaks, release-control ledger). The debt is not “nobody tested this.” The debt is **concentration and archaeology**: a few god-files absorb most change, and a second repository of finished plans, audits, and orphaned tests sits in front of the code.

Rough working-tree size (source only, excluding `node_modules`, caches, and generated coverage):

| Area | Files | Lines of code |
|---|---|---|
| Backend Python (`apps/backend/src`) | 317 | ~90k |
| Backend tests (`apps/backend/tests`) | 311 | ~75k |
| Frontend JS/JSX (excl. tests) | 341 | ~87k |
| Frontend Vitest (`src/__tests__`) | 158 | ~25k |
| Agent Go (excl. tests) | 52 | ~16k |
| Root policy/integration tests (`tests/`) | 105 py | ~22k |
| Markdown in `docs/` + `specs/` + `plans/` | ~232 | living + historical mixed |

**Highest-leverage problems, in order:**

1. **God-files as merge and review bottlenecks.** Eight backend modules and four frontend pages exceed 1,500 lines. `db/models.py` (3,030 lines, 86 classes) is imported across the app. `main.py` (2,518) holds a ~1,100-line `lifespan`. `MapPage.jsx` is 3,031 lines.
2. **A dead frontend test tree.** `tests/unit/*.jsx` is not collected by Vitest (which only runs under `apps/frontend`) and is not collected by pytest (JSX). Imports still point at a pre-monorepo `../pages/` layout. `describe.skip('SettingsPage Redesign')` is sitting in a suite that never runs.
3. **Contributor onboarding is buried under finished 1.0 work.** ~28 plans, 67 slice specs, dated design docs, root working notes, and overlapping architecture write-ups all look equally “current.” A new contributor cannot tell `docs/overview.md` from `ARCHITECTURE_ASSESSMENT.md` from `PRODUCTION_READINESS_ROUTE.md`.
4. **Version and language drift in contributor docs.** `CONTRIBUTING.md` and root `package.json` lint-staged still mention `.ts`/`.tsx`. The UI is JavaScript. `SECURITY.md` talks about a 1.0.x support line while `VERSION` is 0.4.2.

This plan does **not** propose extracting microservices, rewriting the frontend in TypeScript, or flattening `specs/1.0.0` (the requirement ledger is a live control, not clutter). It proposes pruning archaeology, then splitting the files that actually hurt, then aligning tests and docs, then making the repo readable to a stranger in under 30 minutes.

---

## Current repository layout

```
apps/backend/     FastAPI + SQLAlchemy + Pydantic (Python 3.12)
  src/app/{api,services,db,core,workers,schemas,integrations,middleware,jobs}
  tests/          unit + service + API tests (pytest)
  migrations/     124 Alembic revisions
apps/frontend/    React + Vite + Tailwind (JSX/JS, not TypeScript)
  src/{pages,components,hooks,api,lib,context,utils,__tests__}
apps/agent/       Go cb-agent (cmd/, internal/, e2e/)
docker/           mono image, nginx, entrypoint, supervisord
tests/            integration/, build/ (repo-policy), unit/ (mostly dead JSX)
docs/             user + ops docs (MkDocs) + design/ + evidence/
specs/            1.0.0 release-control ledger + dated design specs
plans/            indexed implementation plans (mostly Complete)
scripts/          CI tiers, install helpers, version parity
packaging/        nfpm, native bundle, rollback
.github/          CI workflows, CODEOWNERS, PR + bug templates
SECURITY_REPORTS/ + SECURITY_PATCHES/  indexed historical audits
```

**Runtime stack:** PostgreSQL, Redis, NATS, nginx. Mono container or native systemd via `install.sh` / `cb`.

**Contributor-facing files already present:** `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE` (MIT), `SECURITY.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`. Missing: `CHANGELOG`, feature-request template, a short architecture-for-contributors doc, `AGENTS.md` (optional).

**Gitignored but locally noisy:** `artifacts/`, `apps/frontend/coverage/`, `.coverage`, `.claude/` (thousands of files on a typical agent workstation). These should stay untracked; they should not become part of anyone’s mental model of “the repo.”

### What is already in good shape

- Discovery is **already partially modularized** (18 `discovery_*.py` services). The leftover problem is `discovery_service.py` itself (2,786 lines).
- Agent backend is **already split** into enrollment, registry, link, telemetry, install, endpoints.
- `plans/README.md` is an honest status index (Complete / Active / Superseded). Keep the index; stop treating the plans as current instructions.
- `tenants.py` is **not dead code** — it is a deliberate 410 stub for the single-tenant 1.0 contract. Do not delete it.
- Comments in core Python are mostly *why* comments, not `# TODO` litter. Blind comment-stripping would destroy load-bearing policy notes (`pytest.ini`, Alembic guards, air-gap). Target **commented-out code and root working notes**, not the GOV-style explanations. There are **zero** `TODO`/`FIXME`/`HACK` markers in apps source.

---

## Highest-priority debt (ranked)

| Rank | Area | Evidence | Why it matters |
|---|---|---|---|
| P0 | Orphan `tests/unit/*.jsx` | 30+ JSX files; Vitest include is `apps/frontend`; pytest ignores JSX; `SettingsPage.test.jsx` imports `../pages/SettingsPage` | False sense of coverage; skipped tests that never fail |
| P0 | `apps/backend/src/app/db/models.py` | 3,030 LOC, 86 classes, imported everywhere | Every domain change collides here |
| P0 | `apps/backend/src/app/main.py` | 2,518 LOC; `lifespan()` ~lines 527–1623 | Startup, health, static serving, and ~25 jobs in one file |
| P0 | `apps/frontend/src/pages/MapPage.jsx` | 3,031 LOC | Topology is the product’s face and the nav-wedge hotspot |
| P1 | Discovery + agent API/service cores | `discovery_service.py` 2,786; `api/agents.py` 2,179; `agent_registry.py` 1,972; `api/discovery.py` 1,465 | Fat routes violate “routes stay thin” |
| P1 | Mega pages | `OOBEWizardPage.jsx` 2,215; `SettingsPage.jsx` 1,886; `AdminUsersPage.jsx` 1,535; `LogsPage.jsx` 1,453 | Unreviewable UI diffs |
| P1 | Case-collision `components/Map/` vs `map/` | `Map/Sidebar.jsx` (1,120) vs `map/` (23 files) | Breaks on case-insensitive checkouts (macOS) |
| P1 | Root archaeology | `dev_notes_7-18.md`, `DocsPage.md`, `agent_findings.md`, `known_bugs-v1.0.0-rc.1.md` (all items FIXED), `TESTING/*_REPORT.md`, `security_scan_report.md` | Looks like open work |
| P1 | Dead forks | `apps/backend/db_rewrite_proposal/` (1,670-line models fork); `LiveComponents.jsx` (no importers) | Dead code that looks like a second schema / live UI |
| P2 | Dual architecture narratives | `ARCHITECTURE_ASSESSMENT.md` (40k), `PRODUCTION_READINESS_ROUTE.md` (65k), `docs/overview.md`, `CLAUDE.md` | Contributors pick the wrong source of truth |
| P2 | Contributor doc drift | `CONTRIBUTING.md` Git Flow + `.ts`/`.tsx`; lint-staged same; no feature template; no CHANGELOG; `make test-backend` ≠ backend unit suite | First-hour friction |
| P2 | Copy-paste helpers | `_sync_tags` / `_to_dict` ×7 services; `CAPABILITY_LABELS` ×3; dual discovery API clients | Drift, not just LOC |
| P2 | Oversized tests that *do* run | `test_discovery.py` 2,992; `test_agents_api.py` 2,612; `agent-detail-page.test.jsx` 1,745 | Slow reviews; hard to localize failures |
| P3 | Installer triplication | `install.sh` 1,291; `cb-proxmox-deploy.sh` 1,406; `deploy/setup.sh` 1,953 (plus ignored `dist/`/`build/` copies) | High change cost; not Phase 1 |

---

## Phase 1: Quick wins and pruning

**Goal:** Remove things that are unused, misleading, or finished — without changing runtime behavior.
**Success:** a new clone’s top level looks like a product repo, not a lab notebook. `make verify` still green.

### 1.1 Delete or quarantine dead tests

| Action | Path | Notes |
|---|---|---|
| Inventory unique assertions | `tests/unit/*.jsx` vs `apps/frontend/src/__tests__/` | Keep only behavior **not** already covered under `__tests__/` |
| Delete skipped redesign suite | `tests/unit/SettingsPage.test.jsx` (`describe.skip`) | Live coverage is `src/__tests__/settings-page.test.jsx` |
| Delete or move the one live Python file | `tests/unit/test_proxmox_cpu_calculation.py` | It tests inline arithmetic, not `proxmox_telemetry.py`. Either bind it to the real helper or drop it |
| Remove `tests/unit/` JSX leftovers | remaining `*.test.jsx` / `mocks/` | Paths like `../pages/SettingsPage` and `../components/...` are pre-monorepo |
| Empty smoke package | `apps/backend/tests/smoke/` | `__init__.py` only — fill it or remove it |

**Do not** delete `tests/build/` or `tests/integration/`. Those are live.

**Verify:** `cd apps/frontend && npm test`; `pytest tests/build -q`; `make test-backend` if any Python moved.

### 1.2 Prune root and one-off working notes

| Keep (product) | Relocate to `docs/evidence/` or delete |
|---|---|
| `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `LICENSE`, `CLAUDE.md` | `dev_notes_7-18.md` (stale install bugs, old 0.3.1 version) |
| | `DocsPage.md` (in-app seed copy; `main.py` already seeds docs — confirm it is not the seed source before delete) |
| | `TESTING/DISCOVERY_TEST_ASYNC_REPORT.md`, `TESTING/FORGOT_PASSWORD_TEST_REPORT.md` |
| | Root `security_scan_report.md` (already gitignored as generated) |
| | `.github/instructions/ISSUE_TEMPLATE/bug_report.md` (draft dump of CODE_OF_CONDUCT; live template is `.github/ISSUE_TEMPLATE/bug_report.yml`) |
| | `apps/backend/db_rewrite_proposal/` (parallel schema fork; only cited as history in `docs/1.0.0-incomplete-features.md`) |
| | `apps/frontend/src/components/discovery/LiveComponents.jsx` (244 lines; `LiveScanOverview` has no importers) |

**Archive, don’t delete (they have forensic value):**

- `known_bugs-v1.0.0-rc.1.md` — every item is FIXED; move under `docs/evidence/`
- `agent_findings.md` — spool-durability postmortem; move under `docs/evidence/` or `apps/agent/`
- `ARCHITECTURE_ASSESSMENT.md` and `PRODUCTION_READINESS_ROUTE.md` — dated 2026-08-30 snapshots; move to `docs/evidence/2026-08-30-*` and link from one living architecture page in Phase 3

### 1.3 Mark historical docs as historical (no mass delete yet)

Do **not** bulk-delete `plans/` or `specs/1.0.0/`. GOV-13 indexes them; `tests/build/test_record_indexes.py` fails if a plan vanishes without an index update.

Instead, in Phase 1:

- Add a one-line banner at the top of `docs/design/*.md` plans that are complete: “Historical. See `plans/README.md`.”
- Point `README.md` Documentation at **user** docs only (`docs/overview.md`, install, agent). Keep `specs/` and `plans/` off the landing page.
- Leave `SECURITY_REPORTS/` as-is except to fix the README contradiction (“Active” vs “all 51 findings fixed”). Historical scanner dumps from March 2026 stay as history.
- Fix `docs/evidence/2026-09-01-nav-wedge-baseline.md` header: it still says the H1 remediation **is not shipped**. `known_bugs-v1.0.0-rc.1.md` marks it FIXED on 2026-09-06. Keep the measured numbers; correct the headline.

**Do not archive as “done” — these are living (unimplemented) designs:**

- `specs/2026-09-06-site-scoping-design.md`
- `specs/2026-09-05-agent-console-redesign-design.md`
- `specs/2026-08-23-posture-engine-design.md` (2.0 deferred)
- `specs/1.0.0/slices/ui-1` … `ui-5` (197 unchecked boxes)

The requirement ledger is the status source: **145 rows, 12 passed, 76 not_started**. Slice files are work packages, not a second backlog. Cleanup must not silently cancel product specs.

### 1.4 Fix cheap contributor-doc lies

- `CLAUDE.md`: version `0.4.0` → read `VERSION` (0.4.2).
- Root `package.json` `lint-staged`: drop `*.{ts,tsx,py}` as the lint glob; match actual files (`*.{js,jsx,py}`).
- `apps/frontend/package.json` `lint-staged`: same — `*.{ts,tsx,...}` implies TypeScript is first-class.
- `CONTRIBUTING.md`: husky does **not** lint `.ts`/`.tsx` as the primary language; say `.js`/`.jsx` + Python. Replace “Git Flow-inspired” with the real rule: branch from `dev`, PR to `dev`.
- State the three test layers explicitly: `make test` (integration + Vitest), `make verify` (pre-push, backend suite **off**), `make verify-full` (includes `apps/backend/tests`). `make test-backend` runs **only** `tests/integration/` (~30 files), not the 311-file backend suite.
- Decide whether `apps/frontend/src/api/types.d.ts` is used. If nothing imports it, delete it in Phase 1 (the skill already calls it a stray `.ts` file). If JSDoc is wanted, keep types in JSDoc on the JS modules.

### 1.5 Comment and import hygiene (mechanical, gated)

- Run `ruff check --select F401,F841` (already in `make lint`) — do not add a new linter.
- Search for commented-out function bodies and `# noqa` that no longer apply. **Do not** strip the long *why* comments in `pytest.ini`, `conftest.py`, or discovery eligibility; those are the spec.
- Extraneous comments are **not** the main debt. Spend hours here only after 1.1–1.4.

### 1.6 Local artifact hygiene (docs only)

Confirm `.gitignore` continues to cover `artifacts/`, `coverage/`, `.coverage`. Add a one-liner to `CONTRIBUTING.md`: do not commit `make verify` output. No need to delete local caches.

**Phase 1 exit criteria**

- [ ] `tests/unit/` contains no orphaned JSX
- [ ] Root `*.md` is only product/contributor policy (plus `CLAUDE.md`)
- [ ] `db_rewrite_proposal/` and unused `LiveComponents.jsx` are gone
- [ ] Lint-staged globs match JS/JSX/Python
- [ ] `make lint` and `make verify` pass
- [ ] No behavior change; no schema change

---

## Phase 2: Structural refactoring

**Goal:** shrink the files people must hold in their head. Preserve public APIs, JSON contracts, and migrations (`ADD COLUMN IF NOT EXISTS` / no drops).
**Rule:** one vertical slice per PR. Do not split `models.py` and `MapPage.jsx` in the same diff.

Suggested order (highest conflict surface first):

### 2.1 Extract FastAPI lifespan from `main.py`

**Today:** `lifespan` starts ~line 527 and runs until ~1623 (migrations, scheduler, ~25 jobs, worker topology). Health probes and static-file helpers share the same module.

**Target modules** (new, under `apps/backend/src/app/`):

| Module | Responsibility |
|---|---|
| `startup/schema.py` | Alembic, `_assert_required_schema`, Timescale, RLS warnings |
| `startup/scheduler.py` | APScheduler registration, discovery crons |
| `api/health.py` | `livez` / `readyz` / `startupz` / `health` |
| `api/static_spa.py` | frontend dir resolution, favicon, cache middleware |

`main.py` should become: create app, include routers, attach lifespan. Target: **&lt; 400 lines**.

Tests: move health tests with the routes; add a smoke test that the app still exports the same OpenAPI paths.

### 2.2 Split `db/models.py` by bounded context

**Do not** rename tables or columns. Split into a package:

```
app/db/models/
  __init__.py          # re-export Base and every public class (compat)
  hardware.py
  discovery.py
  agents.py
  monitors.py
  auth.py
  audit.py
  settings.py
  ...
```

`from app.db.models import Hardware` must keep working. 124 migrations stay untouched. This is the single highest-ROI backend split: 86 models in one file is why every feature PR touches the same 3k-line blob.

### 2.3 Finish the discovery split

`discovery_*.py` already exists. `discovery_service.py` (2,786) is the remainder: job create/dispatch, nmap orchestration, import path.

Split by call site, not by “helpers vs rest”:

- job lifecycle → `discovery_jobs.py` (or keep `discovery_result_service.py` as the owner)
- scan execution → `discovery_scan.py`
- leave `discovery_service.py` as a façade if importers are wide

Keep `api/discovery.py` thin: HTTP in, service call out. Same pattern for `api/agents.py` (2,179) → handlers already have `agent_registry`, `agent_enrollment`, `agent_install`; the route file should stop duplicating them.

### 2.4 Deduplicate copy-paste (after the models package exists)

- **Shared entity helpers:** `_sync_tags` / `get_tags_for` / `_to_dict` are copy-pasted across `hardware_service`, `services_service`, `storage_service`, `networks_service`, `compute_units_service`, `misc_service`, and `external_nodes_service`. Extract one module.
- **`CAPABILITY_LABELS`:** defined in `fleetFilters.js`, `FleetRow.jsx`, and `AgentCapabilitiesPanel.jsx`. Keep one export.
- **`agentDisplayName`:** `lib/agentLabel.js` vs `monitors/RunFromSelect.jsx` disagree (hostname vs `Agent ${id}`). Unify on `agentLabel.js`.
- **Discovery HTTP client:** `api/client.jsx` (~690) still exports `discoveryApi` alongside `api/discovery.js`. Finish the split so there is one surface.
- **`Toggle`:** `components/common/Toggle.jsx` vs a local `Toggle` in `DiscoverySettingsPage.jsx`.
- **`IconPickerModal.jsx`:** move the ~900-line `LIBRARY_ICONS` catalog out of the component.

### 2.5 Frontend page decomposition (behavior-preserving)

| File | Split into |
|---|---|
| `MapPage.jsx` (3,031) | canvas shell, selection/keyboard, monitor actions, scan-import wiring, layout persistence — hooks already exist; move event handlers out |
| `OOBEWizardPage.jsx` (2,215) | one component per step |
| `SettingsPage.jsx` (1,886) | already has `pages/settings/DiscoverySettingsPage.jsx`; continue that pattern (Auth, Backup, About, Diagnostics) |
| `IconPickerModal.jsx` (1,392) | data vs UI |
| `components/Map/Sidebar.jsx` | **rename/merge into `components/map/`** to kill the case collision |

Target: no page over **800 lines** except Map canvas if measurement shows split would hurt the nav-wedge work; even then extract hooks first.

**Verify UI in the browser** after each page split: map pan/select/save, OOBE first-run, settings save, icon picker. Screenshot ≠ verification.

#### Outcome (2026-09-07)

| Page | Before | After | Note |
|---|---|---|---|
| `SettingsPage.jsx` | 1,886 | 556 | one component per tab under `pages/settings/` |
| `OOBEWizardPage.jsx` | 2,215 | 291 | seven steps, a context, and `useOOBEWizard` |
| `MapPage.jsx` | 3,025 | 3,025 | **not split — see below** |

**`MapPage` was measured and left whole**, which this section's own hedge allows. The
measurement: the two JSX blocks worth extracting need 29 and 34 values from the page
(header/toolbar, modal cluster), and of the three handler groups only quick-create is
genuinely separable — nine dependencies against nineteen for the label drag and
thirty-six for the uplink editor. Every available cut trades one long file for a
thirty-prop component or a large state restructure, and it would be done against six
Vitest tests that all render an *empty* graph.

So the precondition came first: `e2e/map-interaction.spec.ts` renders a populated graph
in Chromium, mounts the lazy Sigma canvas against a real build, and runs axe over it —
the first coverage the map has had with nodes on it. A real split needs more of that,
and needs the page state consolidated into a `useMapState` hook (the way `useOOBEWizard`
now holds the wizard's) before components can take props instead of thirty of them.

Verification for the two pages that were split is `e2e/settings-tabs.spec.ts` and
`e2e/oobe-first-run.spec.ts`. Both were checked to fail when a single value is withheld
from a split component, so they gate rather than decorate.


### 2.6 Agent `cmd/cb-agent/main.go` (1,844) and `internal/link/link.go` (1,478)

Extract flag/config wiring from `main.go`; keep `link.go` protocol-critical and CODEOWNERS-protected. Smaller PRs; run `apps/agent/e2e`.

### 2.7 What *not* to do in Phase 2

- Do not migrate the frontend to TypeScript.
- Do not extract discovery or the agent link-plane into separate deployables (`ARCHITECTURE_ASSESSMENT.md` already argued against this without a measured trigger).
- Do not rewrite installers (`install.sh` / `setup.sh`) until product cleanup is done; they are high-risk and already tested in `tests/build/`.
- Do not “DRY” WS `_extract_client_ip` copies without a regression test — that path is security-sensitive and may already have been unified; confirm before touching.

**Phase 2 exit criteria** — all met, 2026-09-07

- [x] `models.py` is a package with a compatibility re-export — 21 modules by bounded
      context; `from app.db.models import Hardware` unchanged for its 292 importers.
      Verified by diffing the compiled `CREATE TABLE` for all 88 tables, every index,
      and the relationship graph of all 87 mapped classes against HEAD: identical.
- [x] `main.py` &lt; ~400 lines — **358**, from 2,512.
- [x] `Map/` vs `map/` collision gone — `Map/Sidebar.jsx` merged into `map/`.
- [x] Map, Settings, OOBE under a documented line budget — Settings 1,886 → 556,
      OOBE 2,215 → 291. Map stays at 3,025 under this section's own hedge; the
      measurement and what a real split needs first are recorded in §2.5.
- [x] Shared entity-tag helpers and a single `CAPABILITY_LABELS` / `agentDisplayName` —
      `services/entity_tags` (296 duplicated lines removed), `lib/agentCapabilities`,
      and `RunFromSelect` now uses `lib/agentLabel` instead of its own divergent copy.
- [x] `make verify-full` green; coverage ratchet **not** lowered — exit 0 including the
      security gate (zero HIGH/CRIT). `--cov-fail-under=56` and the Vitest thresholds
      (38/31/30/40) are untouched; measured backend coverage is 66.98%.

Also completed beyond the criteria: §2.1's lifespan and router extraction
(`app/startup/*`, `api/routing`, `api/health`, `api/static_spa`), §2.3's discovery
split (`discovery_admission`, `discovery_dispatch`), §2.4's `discoveryApi` and
`LIBRARY_ICONS` consolidation, and §2.6's agent `main.go` split (1,844 → 138).

Browser verification for §2.5 is three new Playwright specs — `settings-tabs`,
`oobe-first-run`, `map-interaction` — taking the Chromium suite from 20 tests to 33.

### Map rework (2026-09-07, follow-on)

`map-reowrk.md` proposed a `features/map` module with a canonical map document,
domain hooks, and a renderer boundary. Its analysis was verified line by line
against the tree and was accurate: 3,025 lines, 50 `useState`, 26 effects, 39
callbacks, 70 imports all matched, as did every risk it named.

**Correctness came first**, because a behavior change buried inside a 3,000-line
structural move cannot be reviewed. Six defects shipped as separate commits:

| Defect | Effect before the fix |
|---|---|
| `ENTITY_API_DELETE` bracket-indexed on a `Map` | Deleting a node from the map failed for **every** type since 2026-03-17 (`5aae0a10`) |
| Tag and hardware-role filters in two effects | Whichever ran last won; either filter could unhide what the other excluded |
| No request-generation guard in `fetchData` | A slow earlier topology response could overwrite a newer one |
| Cloud View in `fetchData`'s deps | Toggling both transformed nodes in place *and* re-issued the fetch |
| `SigmaMap` never sent `map_id` | Sigma rendered an unscoped graph, inconsistent with React Flow |
| `SigmaMap` sent singular include tokens | `service`/`network` never matched `api/graph.py`, so Sigma silently dropped every service and network |

The last one is not in `map-reowrk.md` — it surfaced while fixing the `map_id`
scoping. `buildIncludeCSV` is now the single definition both renderers use.

**Structurally, only the precondition was taken.** `useMapEditorUi` owns the
sixteen transient editor fields that were sixteen `useState` calls, so cancelling
is one action instead of the hand-maintained sixteen-setter list the Escape
handler had become. `MapStatusBanners` then demonstrated the extraction pattern
on the two blocks that are genuinely separable (four and three values).

**What was deliberately not done, and why.** The header/toolbar and modal cluster
still need 29 and 34 values from the page — the same measurement that left
`MapPage` whole in §2.5. Consolidating transient UI does not by itself reduce
those; the document, filter, and persistence hooks in `map-reowrk.md` §"Safe
Extraction Order" steps 3–5 are what would. Also outstanding: the versioned
layout codec (`schemaVersion` still appears nowhere), the command router, the
renderer boundary, and the `features/map` relocation.

`MapPage.jsx` is **3,015** lines, against 3,025 before. That is not the point of
this pass and is not presented as progress: state ownership moved, and the
26 dependency-array entries eslint required once the setters were no longer
provably-stable `useState` returns cost most of what the extraction saved. The
line count falls when steps 3–5 land, not before.

Verification is `make verify` green (security gate zero HIGH/CRIT, coverage
ratchet untouched at 56 / 38-31-30-40), the frontend suite at 174 files and
1,426 tests, and the Chromium map spec at 4 tests — two of them new Escape
tests against a populated graph. The dialog one was mutation-checked: stubbing
`cancelActiveTool` to a no-op turns it red and leaves the other three green.

---

## Phase 3: Test and documentation alignment

**Goal:** every test that remains is collected by a named command; every doc a contributor opens is either living or clearly dated.

### 3.1 Tests to prune or relocate

| Item | Disposition |
|---|---|
| `tests/unit/*.jsx` | Phase 1 delete/migrate |
| `tests/integration/test_phase3_realtime.py` `@pytest.mark.skip` (“unreachable port; slow”) | Fix or delete; skipped integration tests are a gate that does not gate |
| `tests/integration/test_teams.py` skipif | Confirm teams/tenancy is 410; keep as a 410 contract test if that is the product rule |
| `apps/backend/tests/test_auth_e2e.py` skips for missing columns | Schema is current; skips that say “column not present” are stale — make them fail closed or drop |
| `apps/agent/e2e` `@pytest.mark.xfail` | Comment says the bugs are fixed; delete the marker after an XPASS |
| Duplicate Settings coverage | Keep `__tests__/settings-page.test.jsx`; drop the orphan |
| `TESTING/verify-nmap-raw-in-container.sh` | Move under `scripts/` or `tests/build/` if still used; otherwise delete |
| Playwright visual baselines | `apps/frontend/e2e/visual.spec.ts-snapshots/` (18 PNGs, filesystem date Aug 28) — re-snap if agent-console / nav UI has moved |

**Oversized but live tests** (split, don’t delete): `apps/backend/tests/test_discovery.py` (2,992), `api/test_agents_api.py` (2,612), `api/test_ws_agents_link.py` (2,176), `frontend/__tests__/agent-detail-page.test.jsx` (1,745). Split by endpoint or scenario so a failure names the behavior.

**Do not** lower `--cov-fail-under=56` or Vitest thresholds (stmts 38 / branches 31 / funcs 30 / lines 40) to make a split look green. If a split drops measured coverage, the missing tests moved with the code — add them back.

**Document the three layers** in CONTRIBUTING (also Phase 4):

| Command | What actually runs |
|---|---|
| `make test` | `tests/integration/` + frontend Vitest |
| `make test-backend` | **only** `tests/integration/` (~30 files) |
| `make verify` | Tier 0 + Tier 1 with `CB_VERIFY_BACKEND=off` |
| `make verify-full` | includes the ~311-file `apps/backend/tests` suite (CI shards this) |

### 3.2 Documentation alignment

Create **one** living contributor architecture page (suggested: `docs/architecture.md` or expand `docs/overview.md` with a “For developers” section) that states:

- Process topology (API, workers, agent, nginx, Postgres, Redis, NATS)
- “Routes thin, services hold logic” as a **target**, with the remaining fat files listed
- Pointers: `CLAUDE.md` for conventions, `specs/1.0.0/release-control/` for the ledger, `plans/README.md` for historical implementation

Then:

| Doc | Action |
|---|---|
| `docs/overview.md` | User-facing; keep. Discovery is still labeled Beta — confirm against product intent |
| `docs/roadmap.md` | Keep short; do not compete with 1.0 slice specs |
| `docs/1.0.0-incomplete-features.md` | Banner: register closed 2026-08-25; not a work list |
| `docs/design/2026-08-27` … `2026-09-05` | Historical; link from plans index. Re-reconcile phase-4 checkboxes vs shipped TLS pin / signing docs |
| `docs/design/2026-08-14-agents-page-redesign-design.md` | Likely superseded by `specs/2026-09-05-agent-console-redesign-*` — mark superseded after confirm |
| `specs/1.0.0/slices/` (67 files) | Keep as release evidence; **do not** list them in CONTRIBUTING |
| `specs/2026-09-06-site-scoping-design.md` etc. | Living — see §1.3. Confirm with maintainers before moving |
| `.superdesign/` | Design-tool scratch; gitignore or `docs/design/internal/` — not contributor onboarding |
| `mkdocs.yml` nav | User docs only; hide `design/`, `evidence/`, incomplete-feature register |

Version strings: `VERSION`, frontend `package.json`, README notice, `CLAUDE.md`, and SECURITY support table must tell the same story (0.4.2 line vs future 1.0.x).

**Phase 3 exit criteria**

- [ ] `make test` / `make verify-full` collect only intentional suites
- [ ] MkDocs nav has no “open work” that is actually closed
- [ ] One architecture page is the pointer; dated assessments are under `docs/evidence/`
- [ ] CONTRIBUTING names the three test layers

---

## Phase 4: Contributor readiness

**Goal:** a competent engineer who has never seen this repo can ship a small, safe PR on day one.

### 4.1 What is missing today

| Gap | Fix |
|---|---|
| No changelog | Add `CHANGELOG.md` (Keep a Changelog) starting at 0.4.2; generate from release notes going forward |
| No feature-request template | `.github/ISSUE_TEMPLATE/feature_request.yml` — and a config `contact_links` already funnels security away from public issues |
| CONTRIBUTING is incomplete | Real setup: Go + `govulncheck` (pre-push fails closed), nmap, `make install` **and** root `npm install` for husky, `make dev`, `make verify` as the pre-push gate |
| Language confusion | Explicit: **frontend is JavaScript/JSX**. Do not add `.ts`/`.tsx` under `src/` |
| No “where to look” map | 15-minute tour: `apps/backend/src/app/api/` → `services/` → `db/models`; `apps/frontend/src/pages` + `api/client.jsx`; `apps/agent/cmd/cb-agent` |
| PR template vs Makefile | Template says `cd apps/backend && pytest` and `npm test`; canonical is `make lint` + `make verify`. Align the template |
| Good first issues | Label `good first issue` on Phase 1 items (orphaned tests, comment/doc banners, lint-staged glob) **after** maintainers land the policy PRs |
| Dual CODEOWNERS reality | Almost everything is `@blkleg`. For OSS, document that as “single maintainer for 1.0 control paths,” not as a team that does not exist |
| No `AGENTS.md` | Optional; `CLAUDE.md` already plays this role. Prefer updating `CLAUDE.md` over adding a third conventions file |

### 4.2 Recommended onboarding path (write this into CONTRIBUTING)

1. Read `README.md` (what the product is) and `docs/overview.md` (what users do).
2. Read `CLAUDE.md` (how this repo works) and the new architecture page.
3. Run `make install && make dev`. Open the UI; complete OOBE against local Postgres.
4. Run `make lint` then `make verify` before the first push (install Go + govulncheck first).
5. Do **not** start in `specs/1.0.0/slices/` unless the change is a release-requirement. For a bugfix, the code and a regression test are enough.
6. Never lower coverage gates. Never commit `.env`, `artifacts/`, or scan reports.

### 4.3 Standards to publish (short)

Copy from `CLAUDE.md` / cb-code-quality into CONTRIBUTING so GitHub visitors see them without opening agent skill files:

- Python: typed defs, thin routes, `Depends(get_db)`, specific exception handling, `[module]` log prefix
- Frontend: axios via `src/api/client.jsx` only; loading and error states required
- Secrets: never in tests, fixtures, or workflows
- Commits: `feat:` / `fix:` / `chore:` / `docs:`
- Backward compatible migrations only

### 4.4 What “ready for contributors” does *not* require

- A TypeScript migration
- Public 1.0.0 (README already says RC / trusted LAN)
- Deleting the requirement ledger
- Multi-maintainer CODEOWNERS

**Phase 4 exit criteria**

- [ ] CONTRIBUTING + PR template match `Makefile` gates and JS/JSX
- [ ] Feature template + CHANGELOG exist
- [ ] A new contributor can follow CONTRIBUTING without opening `plans/`
- [ ] `good first issue` list is real Phase-1 leftovers, not stale rc.1 bugs

---

## Suggested sequencing and PR shape

| Sprint | Phase | Example PRs (small, reviewable) |
|---|---|---|
| 1 | 1 | Delete orphan `tests/unit` JSX; fix lint-staged globs |
| 1 | 1 | Relocate root working notes; version string pass; delete `db_rewrite_proposal/` and `LiveComponents.jsx` |
| 2 | 2 | Extract `api/health.py` + startup schema from `main.py` |
| 2–3 | 2 | `db/models/` package with re-exports (mechanized, tests first) |
| 3 | 2 | Merge `Map/Sidebar.jsx` into `map/`; start MapPage hook extraction; unify `CAPABILITY_LABELS` |
| 4 | 3 | Split `test_discovery.py`; kill stale skips |
| 4 | 3 | MkDocs nav + living architecture page |
| 5 | 4 | CONTRIBUTING / PR template / CHANGELOG / feature template |

Each PR: tests first where behavior moves, `make lint`, `make verify` (or `verify-full` if backend logic moved), coverage gate unchanged.

---

## Bottom line — impact of the cleanup

**Without this work,** Circuit Breaker stays a high-quality private codebase that looks chaotic from the outside. The next contributor (or the next you, in six months) will:

- Edit `models.py` / `MapPage.jsx` / `main.py` and produce unreviewable diffs
- Trust `tests/unit` or `known_bugs-*.md` as if they were live
- Follow CONTRIBUTING’s TypeScript/Git Flow story and fight the real JS + `dev`-branch workflow
- Spend the first day in `specs/` and `plans/` instead of `apps/`

**With Phases 1–4 completed, the impact is operational, not cosmetic:**

1. **Review latency drops.** Splitting the 1,500–3,000 line files cuts merge conflicts on the hottest paths (schema, map, discovery, agents) and makes security-sensitive review possible again.
2. **CI and local test time become honest.** Removing a suite that never ran does not speed Vitest much; it *does* stop skipped tests and duplicate Settings/OOBE files from rotting. Splitting the 2–3k line test modules makes failures localizable, which is what actually saves time.
3. **Onboarding time falls from days of archaeology to about 30 minutes.** That is the difference between “we are open source” and “strangers can land a fix.” The gates you already have (`make verify`, gitleaks, ledger) are an advantage — they only help if people can find them.
4. **You do not take on rewrite risk.** This plan keeps the modular monolith, the Go agent, Alembic history, and the 1.0 control plane. It removes *finished work from the foreground* and *oversized files from the critical path*. That is the highest maintainability return available without pausing the product.

**What cleanup will not do:** it will not finish 1.0 security evidence, fix installer edge cases, or make `deb`/`rpm` upgrade rows pass. Those are product/release tracks (`PRODUCTION_READINESS_ROUTE.md`). Mixing them into this cleanup would recreate the archaeology problem.

**Net:** Phase 1 is cheap and immediately changes how the repo *feels*. Phases 2–3 are where maintainability is actually won. Phase 4 is what makes that investment usable by people who do not already live in this tree.
