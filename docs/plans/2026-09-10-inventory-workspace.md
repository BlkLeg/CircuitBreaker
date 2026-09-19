# Inventory Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the approved Hardware inventory vertical slice — server-paged lists, page vs all-matching selection, async entity picker, and structured IP-conflict correction — then migrate sibling inventory pages without breaking complete-dataset callers.

**Architecture:** Reuse the already-landed backend contracts (`PageRequest`/`PageResult`, `GET /hardware/page`, `GET /inventory/options`, bulk tag/document loaders). Teach EntityTable and HardwarePage to drive those contracts instead of client-side slicing of unbounded `GET /hardware`. Keep map/export/relationship consumers on explicit full-list APIs. Extend axios error normalization so 409 `ip_conflict` responses surface field errors and an inspectable conflicting asset without `[object Object]` or lost form state.

**Tech Stack:** FastAPI + SQLAlchemy (existing), React/JSX + Vitest + Playwright, shared `EntityTable` / panels, axios client in `apps/frontend/src/api/client.jsx`.

**Sources of truth:**
- UI: [docs/design/approved-ui/07-inventory-workspace.md](../design/approved-ui/07-inventory-workspace.md)
- Backend: [docs/design/backend-functions/01-inventory-and-search.md](../design/backend-functions/01-inventory-and-search.md)
- Visual baseline: [Inventory v1](https://p.superdesign.dev/draft/71281813-1ede-42bd-bc7d-d2da53c66d34) / `.superdesign/tmp/06-inventory-workspace-saved.html`
- Delivery stage: Stage C in [docs/design/approved-ui/README.md](../design/approved-ui/README.md)

**Why this slice now:** Navigator (01), Access Tokens (09), and Inventory Transfer (02 except live-browser T12) are done. Stage C is the next delivery stage and unblocks Docker parent pickers, alert target selection, and honest inventory UX. Theme plan 00 remains open; this slice consumes existing theme tokens only — no page-local hex, no Gruvbox hard-coding.

**Already shipped (do not rebuild):**
- `apps/backend/src/app/schemas/inventory.py` — `PageRequest`, `PageResult`, `EntityRef`, `EntityOption*`
- `apps/backend/src/app/services/inventory_queries.py` — `list_entity_options`, entity specs
- `apps/backend/src/app/services/entity_tags.py` — `get_tags_for_many`, `get_documents_for_many`
- `apps/backend/src/app/services/hardware_service.py` — `list_hardware_page` with bulk enrichment
- `apps/backend/src/app/api/hardware.py` — `GET /hardware/page`
- `apps/backend/src/app/api/inventory.py` — `GET /inventory/options`
- Service/API tests: `test_hardware_page.py`, `test_inventory_queries.py`, `test_entity_tags_bulk.py`, `test_inventory_query_api.py`
- Hardware create already raises `ConflictError(..., error_code="ip_conflict", fields=..., context=...)`

**Honest gaps vs the canvas:**
- ~~`EntityTable` paginates client-side over a full `data` array; Hardware still calls `hardwareApi.list`.~~ **Done for Hardware** — server paging + `hardwareApi.page`.
- ~~Selection is page-of-loaded-rows only; there is no “select all matching” scope object.~~ **Done** — selection helpers + toolbar.
- ~~`buildUserMessage` / `extractFieldErrors` ignore 409 structured `fields`/`context`; `_safe_context` currently strips `entity_name`.~~ **Done**.
- Sibling `/page` endpoints and frontend migrations are done (W7).
- Canvas summary strip (online / needs attention / awaiting observation) remains out of scope.

**Status (2026-09-10):** Tasks 1–8, W7, and W8 complete. Query-count budgets are recorded in
`docs/design/approved-ui/07-inventory-workspace.md`; loadgen ROUTES include inventory pages.

---

## Task 1: Lock consumer inventory and compatibility rules

**Files:**
- Create: `docs/design/approved-ui/07-inventory-workspace-audit.md` (short working notes; delete or fold into 07 when the slice ships)
- Read: every `hardwareApi.list` / sibling `.list(` caller under `apps/frontend/src`
- Read: `apps/backend/src/app/api/hardware.py`, `apps/backend/src/app/services/hardware_service.py`

**Steps:**
1. Enumerate callers into three buckets: **page UI**, **picker/options**, **complete dataset** (map, export, network membership UIs, cluster member lists, transfer resolve drawer today).
2. Record the compatibility rule: `GET /hardware` remains unbounded for complete-dataset callers; Hardware page switches to `GET /hardware/page`; pickers switch to `GET /inventory/options`.
3. Define the selection model once: `{ mode: 'ids' | 'all_matching', ids: number[], filter: {q,role,tag,sort,direction}, total_matching: number, exclusions: number[] }`. Page checkbox fills `ids` for visible page IDs only; “Select all matching” sets `mode: 'all_matching'` with the current filter snapshot and clears exclusions.
4. Note that no new destructive bulk API is introduced in this slice unless an existing Hardware bulk action already exists — selection UI must still distinguish scopes so later bulk work cannot silently enlarge.

**Verification:**
- Audit doc lists every `hardwareApi.list` call site with its bucket.
- `make` / editor search shows no uncategorized caller.

---

## Task 2: Authorize safe IP-conflict labels in the API

**Files:**
- Modify: `apps/backend/src/app/core/errors.py` (`_CONFLICT_ITEM_KEYS` / `_safe_context`)
- Modify: `apps/backend/tests/` covering AppError/ip_conflict serialization (extend existing error or hardware create tests)
- Read: `apps/backend/src/app/services/ip_reservation.py` (`ConflictResult.to_dict`)

**Steps:**
1. Write a failing test: creating/updating hardware with a colliding IP returns HTTP 409 with `error_code=ip_conflict`, `fields.ip_address`, and `context.conflicts[]` that includes `entity_type`, `entity_id`, and a sanitized `entity_name` (or `label`) for an authorized conflict the caller can already see via normal inventory reads.
2. Allowlist `entity_name` (max length, string-only) in `_safe_context` for `ip_conflict` only. Do not leak unauthorized private fields, ports beyond the existing keys, or raw ORM dumps.
3. Confirm names of entities the requester cannot access are either omitted or replaced with a generic “existing asset” label using the same authorization rules as list/get — if no row-level ACL exists today, document that names follow the same visibility as `GET /hardware/{id}` and do not invent a new ACL layer.
4. Keep 422 validation-array behavior unchanged.

**Verification:**
```bash
cd apps/backend && python -m pytest tests/ -k "ip_conflict or ConflictError or hardware" -q
```

---

## Task 3: Frontend error normalizer for structured conflicts

**Files:**
- Modify: `apps/frontend/src/api/client.jsx` (`buildUserMessage`, interceptor, optionally `extractFieldErrors`)
- Create: `apps/frontend/src/__tests__/api-conflict-normalization.test.js` (or extend the nearest client error test)
- Modify (later consumers): Hardware form handlers only after this lands

**Steps:**
1. Write failing tests for axios error shaping:
   - 409 with `{ detail, error_code: 'ip_conflict', fields, context }` → `err.message` is the string detail, `err.fieldErrors` from `fields`, `err.errorCode`, `err.conflictContext` from sanitized context.
   - Object-valued legacy detail never becomes `"[object Object]"`.
   - 422 array field errors still populate `fieldErrors` as today.
2. Implement the minimal interceptor changes. Do not expand into a generic error-framework rewrite.
3. Export a tiny pure helper if tests need it without mounting axios (e.g. `normalizeApiErrorPayload`).

**Verification:**
```bash
cd apps/frontend && npm test -- --run api-conflict-normalization
```

---

## Task 4: Client API + pure list/selection helpers

**Files:**
- Modify: `apps/frontend/src/api/client.jsx` — add `hardwareApi.page` and `inventoryApi.options` (or a small `api/inventory.js` if that matches nearby modules)
- Create: `apps/frontend/src/lib/inventoryList.js` — page param builders, selection reducers, range labels (`1–25 of 248`)
- Create: `apps/frontend/src/__tests__/inventory-list-lib.test.js`

**Steps:**
1. Tests first for:
   - Building `{ limit, offset, sort, direction, q, role, tag }` from UI state.
   - Toggling page IDs without clearing unrelated selected IDs on other pages.
   - Entering `all_matching` clears per-id mode semantics for bulk display count.
   - Changing `q`/`role`/`tag`/`sort` clears or reconfirms selection (choose clear + explicit toast/banner; document in helper).
   - `pageLabel(offset, limit, total)` edge cases (empty, last partial page).
2. Add API methods that hit `/hardware/page` and `/inventory/options` with params arrays for `types`/`selected` as the backend expects.
3. Do not change `hardwareApi.list` behavior.

**Verification:**
```bash
cd apps/frontend && npm test -- --run inventory-list-lib
```

---

## Task 5: Server-driven pagination controls on EntityTable (additive)

**Files:**
- Modify: `apps/frontend/src/components/EntityTable.jsx`
- Modify: `apps/frontend/src/__tests__/` EntityTable tests (create/extend)
- Read: existing client-side pageSize UI so complete-dataset callers keep working

**Steps:**
1. Add an optional controlled mode: when `serverPaging` (or `total` + `offset` + `onPageChange`) is provided, render footer from server `total/limit/offset` and do **not** slice `data`.
2. Keep default behavior (client slice) for pages that still pass full arrays — Storage/Services/etc. until Task 9.
3. Selection “select page” must operate on the currently displayed rows only; expose a slot or callback for “Select all N matching” rather than baking inventory filters into EntityTable.
4. Theme tokens only; no new hex colors for selection chrome.

**Verification:**
```bash
cd apps/frontend && npm test -- --run EntityTable
```

---

## Task 6: Async `EntityPicker` against `/inventory/options`

**Files:**
- Create: `apps/frontend/src/components/common/EntityPicker.jsx` (Drawer or modal using existing Drawer)
- Create: `apps/frontend/src/__tests__/entity-picker.test.jsx`
- Optional hook: `apps/frontend/src/hooks/useEntityOptions.js`

**Steps:**
1. Fixture-test: typing queries `inventoryApi.options` with debounce (~200 ms), cancels/stales out-of-order responses, shows loading/empty/error, retains selected labels via `selected=type:id`.
2. Action parameter defaults to the caller’s purpose (`view` / `relate` / `docker_parent`); Hardware parent association uses the action the backend already allows.
3. Unavailable selected refs render the server’s `unavailable_reason` instead of a blank control.
4. Replace at least one Hardware association control (parent/host or “Find asset”) in Task 7; transfer’s resolve drawer can migrate in a follow-up once this component exists — do not block Hardware on rewriting transfer.

**Verification:**
```bash
cd apps/frontend && npm test -- --run entity-picker
```

---

## Task 7: Hardware page vertical slice

**Files:**
- Modify: `apps/frontend/src/pages/HardwarePage.jsx`
- Modify: `apps/frontend/src/__tests__/hardware-page.test.jsx`
- Modify: `apps/frontend/src/styles/` only if needed (token-only feature CSS)
- Read: `useEntityDeepLink` — preserve entity deep-link behavior

**Steps:**
1. Switch list fetch from `hardwareApi.list` to `hardwareApi.page` with limit/offset/sort/filters. Debounce search; reset offset on filter/sort change; ignore stale responses.
2. Wire EntityTable server paging + selection bar: page select, “Select all matching” using `total` from the page response, Clear, visible count/scope label matching the canvas language.
3. Loading / empty / error states replace the table content (existing EmptyState/Banner patterns). Preserve selection and form drafts across recoverable fetch failures.
4. Detail/edit path: on IP conflict save failure, show field error + conflict alert with “Inspect {name} →” that opens the conflicting asset via deep link or detail fetch — form values retained, Save stays disabled until the address changes.
5. Add Hardware entry for EntityPicker where the canvas shows parent/find-asset (only if Hardware already has a parent/association field; do not invent new relationship types).
6. Leave Clusters tab behavior intact unless it shares the same list hook; do not silently page cluster membership lists that must stay complete.
7. Update tests that mock `hardwareApi.list` to mock `page` with `{ items, total, limit, offset, sort, direction }`.

**Verification:**
```bash
cd apps/frontend && npm test -- --run hardware-page
```

---

## Task 8: Structured conflict UI shared helper

**Files:**
- Create: `apps/frontend/src/components/common/IpConflictAlert.jsx` (or fold into form field pattern if smaller)
- Create: `apps/frontend/src/__tests__/ip-conflict-alert.test.jsx`
- Modify: Hardware create/edit forms to use it (from Task 7)

**Steps:**
1. Component accepts normalized conflict context + `onInspect(ref)`.
2. Never render raw objects; always string labels.
3. Reuse Banner/alert patterns and semantic status tokens.

**Verification:**
```bash
cd apps/frontend && npm test -- --run ip-conflict-alert
```

---

## Task 9: Sibling page migrations (batched)

**Files:**
- Modify one vertical at a time: `ComputeUnitsPage.jsx`, `ServicesPage.jsx`, `StoragePage.jsx`, `ExternalNodesPage.jsx`, IPAM/Other as applicable
- Backend: add `GET /{resource}/page` only when that service has bulk serialization ready — copy the hardware pattern from `list_hardware_page`
- Tests: matching page tests per resource

**Steps:**
1. For each sibling: backend page endpoint + service method with bulk tags/docs (and conflict flags where they already exist) → frontend page fetch → preserve domain columns/actions.
2. Complete-dataset secondary fetches (e.g. Storage page loading all hardware for a dropdown) must move to `inventoryApi.options` or keep an intentional full list — never point them at `/page` and assume one page is enough.
3. Stop after each resource when its unit tests pass; do not big-bang all pages in one commit if the diff is large.

**Verification:**
```bash
cd apps/backend && python -m pytest tests/services/test_hardware_page.py tests/api/test_inventory_query_api.py -q
cd apps/frontend && npm test -- --run "compute-units-page|services-page|storage-page|external-nodes"
```

---

## Task 10: Query-count and regression harness

**Files:**
- Extend or add: backend tests that assert tag/document query counts stay O(1) per page (already partially covered by `test_entity_tags_bulk.py` / hardware page tests)
- Record measured before/after in the plan completion notes or `docs/design/approved-ui/07-inventory-workspace.md`

**Steps:**
1. Use the existing load harness / SQLAlchemy query counting pattern already used in inventory tests.
2. Record figures for Hardware page size 25 and 100. Do not claim infinite scale; do not add virtualization unless measurements require it.
3. Confirm map/export still receive full datasets in their existing tests.

**Verification:**
```bash
cd apps/backend && python -m pytest tests/services/test_hardware_page.py tests/services/test_entity_tags_bulk.py -q
# plus the repo load harness target if documented in cb-build-test
```

---

## Task 11: Browser / a11y acceptance for Hardware

**Files:**
- Create or extend: `apps/frontend/e2e/` Playwright coverage for Hardware paging, selection scope label, conflict inspect, and deep link
- Manual checklist against plan 00 theme presets on the Hardware surface

**Steps:**
1. Automated: page 2 retains independent selection; filter change clears all-matching; conflict inspect navigates without wiping unrelated fields.
2. Manual: dark/light/custom theme, keyboard through table → detail → picker drawer (focus trap/return), reduced motion, narrow-screen local table scroll.
3. Mark W1–W8 checkboxes in `07-inventory-workspace.md` as packages complete; leave honest unchecked items visible.

**Verification:**
```bash
cd apps/frontend && npx playwright test e2e/ --grep hardware
cd /home/shawnji/project/CircuitBreaker && make verify-full
```

---

## Task 12: Close related loose ends (same PR series, not blockers for Task 7)

**Files:**
- Optional: migrate `ResolveDecisionDrawer` hardware fetch to EntityPicker
- Optional: Inventory Transfer plan 02 **T12** live-browser pass (theme/keyboard on the transfer workbench) can ride alongside Hardware browser checks
- Update: `docs/design/approved-ui/07-inventory-workspace.md` work-package boxes; brief user-docs touch only if list behavior changes operator expectations

**Steps:**
1. Do not block Hardware GA on transfer T12 or every sibling migration.
2. Update the approved-ui README Stage C exit condition when Hardware + contracts + at least one sibling batch and measurements are done.

---

## Out of scope

- Observation/health summary strip metrics that are not already defined by honest telemetry
- New bulk-destructive APIs or a generic selection persistence table
- Virtualization / infinite scroll
- Replacing map data loading with paged APIs
- Completing theme plan 00 F5 (impact graphs / alert charts) or metric alert rules
- Canvas sample scenario dropdowns and prototype chrome

---

## Suggested commit sequence

1. `test+fix:` IP conflict context allowlist + frontend error normalization  
2. `feat:` inventory list helpers + `hardwareApi.page` / `inventoryApi.options`  
3. `feat:` EntityTable server paging + EntityPicker  
4. `feat:` Hardware page vertical slice + conflict alert  
5. `feat:` sibling page N migrations (one commit per resource if large)  
6. `test+docs:` query counts, E2E, plan checkbox updates  

---

## Self-review

- Spec coverage: W1→Task 1, W2/W3→Tasks 2/10 + existing backend, W4→Tasks 5–7, W5→Tasks 2–3/8, W6→Task 7, W7→Task 9, W8→Task 10.
- No speculative workflow engine; reuses existing services and EntityTable.
- Compatibility: unbounded `GET /hardware` retained for complete-dataset callers.
- TDD ordered: failing tests before implementation in Tasks 2–8.
