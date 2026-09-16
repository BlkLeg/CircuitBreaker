# 02 · Inventory transfer — validate, resolve, preview, apply

Status: canvas-backed implementation plan for the approved design. Visual baseline:
[Transfer v1 — Validate, Preview, Import](https://p.superdesign.dev/draft/c588cc25-16f9-4273-bbaf-6cb0585fc1ad)
(v1). Upgraded 2026-09-10 from the approved 2026-09-08 minimal contract; every decision in that
contract remains binding and is folded in below. Depends on plan 00 (theme and shared
primitives) and plan 07's entity picker and structured-error contracts. Backend boundaries are
specified in [backend-functions plan 06](../backend-functions/06-inventory-transfer.md);
this plan is its UI consumer. Paths under frontend/backend refer to their respective `src/` and
`src/app/` roots.

**Implementation status (2026-09-10, second pass):** the full flow shipped — backend
resolution vocabulary (match/rename/reassign), `GET /inventory-transfer/summary`, apply audit
events, and the complete Settings → System → Data Management workbench (summary tiles, import
stepper, decisions ledger and drawer, review, result, export & recovery cards), with service,
API-route, hook, lib, and panel tests. T12's live-browser theme/keyboard pass is the one open
item.

## Shipped ground truth (recheck before opening packages)

Commit `4729e8bd` (seven-workflow backend slice) and `1d6d2a79` landed most of the backend
package. Already shipped, with tests:

- `services/inventory_transfer/{format,export,plan,apply}.py`,
  `schemas/inventory_transfer.py`, `db/models/transfers.py`
  (`InventoryTransferPlan`, `InventoryTransferOperation`), `api/inventory_transfer.py`
- `GET /api/v1/inventory-transfer/export` → `PortableInventory`
  (`format: "circuitbreaker.inventory"`, `version: 1`, `manifest.included/excluded`), admin-gated;
  includes `hardware_connections` (the assessment defect) and declares exclusions
  (users, sessions, tokens, credentials, settings, audit_logs, operational_runs, telemetry,
  map_layouts, uploaded_files)
- `POST /preview` `{document, resolutions}` → `plan_id`, `plan_digest`, `expires_at`,
  `creates/matches/relationships` maps, `conflicts[]` (`entity_type`, `source_id`,
  `reason_code`, `message`, `candidates`), `can_apply`, `warnings`
- `POST /plans/{plan_id}/apply` with `plan_digest` + `Idempotency-Key` header → replay-safe
  actor-scoped result; `GET /operations/{operation_id}` returns the stored result
- Identity safety: foreign primary keys create new local rows (never overwrite), relationship
  IDs are remapped, inventory changes invalidate the preview digest, unknown fields are
  rejected before ORM work, legacy v2 exports are adapted by `normalize_legacy_v2`
- Tests: `tests/services/test_inventory_transfer.py` (round trips, collisions, replay,
  invalidation, actor scoping)

Not started at the first pass (2026-09-10 morning): every frontend piece (no client functions,
no panel; `SystemSection` still showed the mislabeled “Full Backup” button and no import), the
summary-tile data source, the canvas's rename/reassign decision kinds (the resolution schema
accepted `action: "match"` only), audit events, and route-level API tests. All closed in the
second pass the same day; see the work packages below.

## Outcome and location

Settings → System → Data Management becomes the **Inventory transfer** workbench. It keeps three
artifacts honestly distinct: portable inventory export, previewed inventory import (merge), and
full-state snapshot with offline restore. Existing integration points:

- Frontend: `pages/settings/SystemSection.jsx`, `pages/SettingsPage.jsx` (owns `handleExport`
  blob download and `?tab=`), `components/settings/BackupSettings.jsx` (snapshots, S3/AGE),
  `api/client.jsx` (`adminApi.export`, unused `adminApi.import`, `triggerSnapshot`,
  `listSnapshots`), `data/navigation.js` (settings tabs), shared `components/common/*`
  primitives (Panel, Tabs, Drawer, StatTile, Banner, EmptyState, Toast, ConfirmDialog,
  SkeletonTable)
- Backend: `api/inventory_transfer.py`, `services/inventory_transfer/*`,
  `api/admin.py` (legacy `export_backup`/`import_backup`, Clear Lab, recent-changes),
  `core/audit.py` (`log_audit`), `core/destructive_actions.py`, `services/backup/`
- Docs: `docs/backup-restore.md`

The “Full Backup” SettingField is removed once the panel’s export card replaces it; Clear Lab and
Factory Reset stay where they are with their existing safeguards, untouched by this plan. The
panel renders under the existing settings visibility policy (the System tab is admin-only in
practice) and every transfer endpoint enforces `require_role("admin")` regardless.

## Canvas translation invariants

Keep from the approved draft:

- Feature-local tabs: **Import inventory** / **Export & recovery**
- Four summary tiles above the tabs (contract below)
- Import stepper: ✓ Validate → Resolve → Review → Apply, with the honest
  “No changes have been applied” footer while unresolved
- File card: filename, detected format/version chip, summary chips
  (Entities, Relationships, New records, Require a decision)
- Import operation select defaulting to **Merge**, with the deliberately blocked
  **Replace…** choice opening the warning drawer and returning to merge
- Decisions table (incoming asset, issue/resolution, decision control) with an
  editable resolve drawer and an “N of M resolved” counter
- Review step: operation counts (new incl. renamed, explicitly matched, relationships,
  unrelated overwritten), remapping note, explicit confirmation checkbox enabling Apply
- Result state with actual counts, and the recovery callout linking to Export & recovery
- Export & recovery tab: two artifact cards (portable export vs full-state snapshot) and the
  offline-restore callout with `cb restore <archive>`

Omit as review scaffolding: “Use sample file” control, “FORMAT V2 · SAMPLE” chip, hard-coded
counts (248/392/48/67/…), header wall clock, “DESIGN PREVIEW · SAMPLE DATA” chip, canvas CDN
scripts and Gruvbox hex, “Apply sample import”/“Start another sample”/“No real data was
changed” wording — production applies for real and reports real counts.

Theme: Gruvbox was presentation only. Use plan 00 tokens for every color; status distinctions
must stay readable from labels/icons when the palette changes.

## Summary strip contract (four tiles)

| Tile | Honest definition |
| --- | --- |
| Inventory objects | Row counts summed over the seven portable asset kinds (hardware, compute_units, services, storage, networks, misc_items, external_nodes), “Across N asset types” names the kinds counted |
| Relationships | Row counts summed over the eleven declared relationship kinds, labeled “Hosting, dependencies & connections” |
| Latest full-state snapshot | Newest record from the existing snapshots endpoint (timestamp, size, local availability); empty state “No snapshot yet” with a create action |
| Recovery readiness | Derived only from snapshot existence/age — “Snapshot available” or “No snapshot yet”; keep the static note that restore verification is a separate, offline step. Never claim a verified restore |

Counts come from a new read-only `GET /inventory-transfer/summary` (admin) returning per-kind
asset and relationship counts plus the portable format version — small, bounded, fetched on
mount, no polling. The snapshot tiles compose from the existing `listSnapshots` endpoint.
Loading, permission, and error states use the shared patterns; never render partial numbers
with no explanation.

## Import step-flow contract (validate → resolve → review → apply)

1. **Validate.** File card accepts one JSON file; the client checks type and size against the
   backend's bounded limits before uploading, then sends the parsed document to
   `POST /preview` with no resolutions. Summary chips are computed from the response:
   Entities/Relationships from the document, New records from the `creates` map, Require a
   decision from `conflicts`. The format chip shows what the document actually declares
   (`circuitbreaker.inventory` v1, or legacy v2 accepted via the adapter). Invalid files
   produce safe errors, change nothing, and let the operator retry without losing chosen
   settings. A new file resets decisions.
2. **Resolve.** One row per returned conflict, kind-driven UI (vocabulary below), an editable
   drawer per decision, and the “N of M resolved” counter. Every saved decision re-previews so
   the digest always matches the current decision set. “Review changes” stays disabled until
   `can_apply` is true. Keep the canvas’s honesty footer: no changes have been applied.
3. **Review.** Counts from the latest preview: new (including renamed), explicitly matched,
   relationships to create/match, and “unrelated assets overwritten: 0” — structurally true for
   merge because identity never falls back to primary-key equality. Keep the remapping note
   (incoming IDs are remapped; relationships arrive with their assets). The confirmation
   checkbox enables Apply; Apply sends the plan digest plus a client-generated
   `Idempotency-Key`, so a retry or double-click cannot duplicate work.
4. **Result.** Report the operation’s actual created/matched/relationship counts and warnings.
   Failure means rolled back and nothing changed, with safe diagnostics and a retry that keeps
   the file and decisions. A stale preview (inventory changed underneath) surfaces the distinct
   re-review outcome rather than a generic error. Only two stages exist (validation, apply) —
   no invented percentage progress.

The mode select ships with **Merge** as the only working operation. “Replace…” stays visible,
opens the canvas’s warning drawer (safety snapshot + offline restore requirements), and returns
to merge — replacement is a future contract, not a hidden destructive option.

## Resolution vocabulary and its honest limits

The canvas demonstrated three decision kinds. Map them to the backend's reason codes:

| Canvas decision | Preview evidence | Resolution action |
| --- | --- | --- |
| Keep both · rename incoming | `unique_identity_conflict` (+candidates) | `rename` — create under an operator-supplied new unique value (UI proposes `<value>-imported`, editable) |
| Match the existing asset | `unique_identity_conflict` (+candidates) | `match` — explicit adoption of the chosen local record |
| Assign to an existing parent | `missing_reference` on an entity/relation reference | `reassign` — bind the incoming row's reference to an existing local target chosen through the local-record picker |

Honest limits to render, not hide: identity conflicts can only arise for kinds with a declared
unique field (today `services.slug`, `tags.name`, `hardware_clusters.name`) — a same-name
hardware row is not reported as a conflict and the UI must not claim it was checked. Reference
fields eligible for reassignment are the declared internal refs and relation refs. Conflicts
the operator cannot resolve in-UI (`unsupported_reference_type`, `match_not_found`) state plainly
that the source inventory must be revised or the preview refreshed.

## Backend work required for the full canvas flow

Small, contract-shaped extensions — not a second subsystem:

1. **Resolution vocabulary:** extend `TransferResolution` with bounded `rename` (new unique
   value) and `reassign` (reference field + existing target id) actions; teach `build_import_plan`
   and `apply_import` their semantics; keep duplicate-resolution and unknown-field rejection.
2. **Summary endpoint:** `GET /inventory-transfer/summary` per the tile contract.
3. **Audit events:** apply emits `log_audit` (actor, action `inventory_import_applied`,
   operation id, plan digest, created/matched/relationship counts — never file contents).
4. **Stale-preview outcome:** apply rejects a changed digest with a distinct error the UI can
   render as “re-review”, not a generic 500.
5. **Legacy disposition:** the unused `adminApi.import` client function is removed with the
   panel landing; the legacy `POST /admin/import` endpoint stays documented as compatibility
   surface with unchanged wipe guards, and `docs/backup-restore.md` says the portable API is
   the only UI import path.

## UI boundaries and work packages

Keep `SystemSection` thin. Concentrate the flow in
`components/settings/InventoryTransferPanel.jsx` with focused children under
`components/settings/transfer/` (summary tiles, file card, stepper, decisions table, resolve
drawer, review panel, result, export/recovery cards) and a feature-local
`hooks/useInventoryTransfer.js` owning step state, the document, decisions, and preview
results. New API functions live in `api/client.jsx` as `inventoryTransferApi`
(`export`, `preview`, `apply`, `result`, `summary`). Feature CSS is token-only. No generic
workflow engine, no second backup subsystem.

- [x] **T1 (shipped, extended):** round-trip fixtures covering declared entity/relationship kinds
  (incl. `hardware_connections`) and foreign-PK collisions. Extended for the rename/reassign
  actions and legacy v2 documents.
- [x] **T2:** Build the approved step flow (validate → resolve → review → result) with
  size/type checks, loading/validation failures, editable conflict decisions, preview,
  confirmation, and result states. Preserve choices when returning to prior steps and across
  recoverable failures.
- [x] **T3 (shipped):** server-side bounded parsing/schema validation and preview under the
  same rules as apply; frontend validation stays advisory.
- [x] **T4 (shipped):** source-ID remapping, referential validation, digest recheck,
  transaction/rollback, `Idempotency-Key` duplicate protection. Add audit events (backend item 3).
- [x] **T5:** Honest export surface: portable export card with the manifest's included/excluded
  lists rendered verbatim, filename `circuit-breaker-inventory-<date>.json`, full-state
  snapshot card, offline-restore callout with `cb restore <archive>`, and links to
  `docs/backup-restore.md`. Remove the mislabeled “Full Backup” field.
- [x] **T6:** Wire `inventoryTransferApi` end to end; refresh affected inventory/map query
  state after success; show recoverable failures without dropping the chosen file.
- [x] **T7:** Update portability/backup documentation and migration notes; record the legacy
  `/admin/import` compatibility decision.
- [x] **T8 (backend):** Resolution vocabulary extension (rename, reassign) with tests.
- [x] **T9 (backend):** `GET /inventory-transfer/summary` and the four tiles wired to it.
- [x] **T10:** `SystemSection` integration: panel replaces the Full Backup block, Clear Lab
  untouched; settings deep link `?tab=system` plus a section anchor registered in the
  navigation metadata so the navigator can target Data Management.
- [x] **T11:** Route-level API tests: admin gate on all five endpoints, idempotency-key
  behavior, stale-digest outcome, and the domain-validation error mapping (400, per
  `core/errors.py`; 422 stays pydantic's).
- [ ] **T12:** Browser verification per plans 00/07: theme presets (dark/light/custom) and
  contrast, keyboard focus through stepper → drawer → confirm (focus trap and return,
  Escape preserves the edited decision), reduced motion, narrow-screen stacking with locally
  scrolling tables. Needs a live instance and a real browser; the component and hook tests
  cover the structure, not the rendered pixels.

## Acceptance and tests

- Supported export/import round trips preserve declared fields and relationships, including
  hardware connections; imported IDs never overwrite unrelated local records silently.
- The three decision kinds work end to end: rename creates a distinct row with remapped
  relationships; reassign binds a missing reference to an existing target; match updates the
  chosen existing record explicitly.
- Invalid JSON/schema, unsupported versions, oversized files, missing references, ambiguous
  identity, and unauthorized requests change nothing.
- A preview becomes invalid if relevant inventory changes; the user gets a re-review path, and
  apply never replans silently.
- Retrying or double-clicking Apply does not duplicate entities (idempotency); a forced
  mid-apply failure rolls back with nothing changed.
- The summary tiles match real counts and degrade honestly when no snapshot exists.
- Portable inventory export is never labeled full backup; online import is never represented
  as restore; Clear Lab and Factory Reset keep accurate confirmations and safeguards; cancel
  before application makes no changes.
- End-to-end tests use disposable inventory only. Existing suites stay green
  (`tests/services/test_inventory_transfer.py`, settings page tests, backup/restore suites);
  `make verify-full` covers the backend changes — the shorter `make verify` gate does not.

## Out of scope

- Replace/wipe as a portable import mode (offline restore covers whole-instance recovery)
- An online full-database restore endpoint
- Exporting users, sessions, tokens, credentials, secrets, settings, operational history,
  telemetry, map layouts, or uploaded files
- Expanding identity rules beyond the declared unique fields (e.g. same-name hardware
  matching) — that is a format-semantics decision, not a UI fix
- Background async import workers or streaming progress
- Canvas sample-file controls, sample data, wall clocks, or prototype-only chrome
