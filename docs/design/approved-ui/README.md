# Approved UI implementation plans

Date: 2026-09-07  
Status: all eight designs approved by the user; implementation has not started under these plans.

## Decisions of record

1. Implement the seven operational workflows and the global navigator approved on the Superdesign canvas.
2. The navigator replaces **both** the top-right Routes dropdown **and** the existing command palette. Keep one overlay, one opening state, and one keyboard/search experience. Preserve the dock and its independent customization.
3. Every approved surface is theme-aware. Gruvbox was the presentation theme, not a mandatory production palette. Preserve composition, density, hierarchy, interactions, and semantic status distinctions across all supported themes.
4. This request authorizes plans, not application/backend changes. Canvas approval does not mean the mocked API contracts, sample records, or prototype-only controls already exist.
5. Complete the promised workflows using existing services and components. New helpers must have a concrete responsibility and caller; no speculative framework or generic workflow engine.

These decisions supersede earlier instructions to retain a separate Ctrl/Cmd+K palette, use a fixed Gruvbox palette, or leave metric alert rules unselected.

## Backend implementation companion

The [backend function and helper plans](../backend-functions/README.md) specify the current backend integration points, proposed directory/file ownership, callable contracts, transaction boundaries, migrations, and verification for these designs. Use them alongside the screen plans below. They deepen backend implementation detail without changing visual approval or authorizing live mutations.

## Plan index and approved references

[Open the shared canvas](https://superdesign.dev/teams/4281dc54-7c08-491e-9c06-483e758fa325/projects/8b984ff8-fa32-4386-98b6-0de7bd58135b).

| Plan | Approved design | Initial home |
| --- | --- | --- |
| [00 · Theme and shared foundations](00-theme-and-shared-foundations.md) | Cross-cutting requirement | Existing theme pipeline and shared UI |
| [01 · Unified navigator](01-unified-navigator.md) | [Navigation v2](https://p.superdesign.dev/draft/535d202a-525f-4ec3-8382-796bb049c50c) | Global header; replaces Routes and command palette |
| [02 · Inventory transfer](02-inventory-transfer.md) | [Transfer v1](https://p.superdesign.dev/draft/c588cc25-16f9-4273-bbaf-6cb0585fc1ad) | Settings → System → Data Management |
| [03 · Docker discovery](03-docker-discovery.md) | [Docker v1](https://p.superdesign.dev/draft/aa80802b-d119-41c0-9c89-90794d8ee3a6) | Discovery, linked from Settings → Integrations |
| [04 · Vulnerability assessment](04-vulnerability-assessment.md) | [Assessment v1](https://p.superdesign.dev/draft/ceded7b7-7c26-4648-abb6-795f4357dba7) | Existing vulnerability detail panel; Intel entry point |
| [05 · Notification delivery](05-notification-delivery.md) | [Notifications v1](https://p.superdesign.dev/draft/7273cc9b-04ae-4e3d-96bf-f7de8a6be6b7) | Existing Notifications and settings entry points |
| [06 · Dependency impact](06-dependency-impact.md) | [Impact v1](https://p.superdesign.dev/draft/a2fae8fa-8586-4299-b24b-849c6b70501b) | Map / selected asset; existing impact panel |
| [07 · Inventory workspace](07-inventory-workspace.md) | [Inventory v1](https://p.superdesign.dev/draft/71281813-1ede-42bd-bc7d-d2da53c66d34) | Existing inventory entity pages |
| [08 · Metric alert rules](08-metric-alert-rules.md) | [Rules v1](https://p.superdesign.dev/draft/0d6b88b6-c407-45fa-a542-09fff90e0a7e) | Monitors → Alert rules |

The seven v1 workflow references and navigation v2 are the approved visual baselines. Apply the subsequent navigator/theme decisions above when translating them into production. The navigator's “Planned workflows” tab, simulated navigation messages, sample-data controls, and external canvas links are review scaffolding; do not ship them.

## Ground truth and changes since the assessment

The [functional assessment](../2026-09-07-functional-gaps-and-ui-plan.md) supplies defect evidence and intent, not an immutable inventory of missing code. Recheck each listed defect against the implementation branch before changing it. Preserve concurrent map work and reuse its final public hooks/components.

Targeted planning inspection confirmed:

- Header and command palette both consume the shared navigation registry; App currently mounts the palette and owns its shortcut.
- SettingsPage now reads `?tab=` and uses `SETTINGS_TABS`. The palette and canvas example still contain `?section=` links. Reconcile those during the navigator migration; do not copy them as working deep links.
- Non-admin settings visibility is narrower than the parent route gate: the current SettingsPage exposes only Integrations to non-admin users admitted to Settings. Nested search results must match that policy.
- Search currently returns entity results with collection-level `action_url` values, including the old Networks destination. Preserve search capability while fixing canonical and entity-specific activation.
- The theme pipeline updates core colors, but `--color-surface-raised` is a fixed value in panels.css and status tokens are not updated by applyTheme. Variable usage alone is therefore insufficient proof of theme support.

All file paths in the individual plans are repository-relative. New module names and response fields are proposed implementation boundaries; they are not claims about existing endpoints.

## Delivery sequence

| Stage | Work | Exit condition |
| --- | --- | --- |
| A | Theme/shared foundation; reconcile current route and settings metadata | Tested theme resolution and reusable primitives; no duplicated settings authorization |
| B | Unified navigator and command-palette migration | One reachable overlay; routes, assets, settings, and account actions work; dock unchanged |
| C | Inventory pagination, selectors, and structured errors | Reusable list/selection/picker contract; hardware vertical slice complete |
| D | Notification delivery and Docker reconciliation | Truthful delivery outcomes; authoritative source reconciliation; usable operational UIs |
| E | Vulnerability assessment and dependency impact | Honest assessment state; explainable directed impact paths |
| F | Inventory transfer | Validated, previewed, safe import/export using corrected inventory/relationship contracts |
| G | Metric alert rules | Durable evaluation and recovery transitions through verified notification delivery |
| H | Integrated hardening and release documentation | End-to-end, role, theme, migration, performance, and regression evidence |

This is dependency order, not a demand for unrelated work to wait. Notification correctness can land early; impact work waits only for the relevant map integration boundary. Metric rules depend on notification correctness and selector/telemetry contracts.

Within each slice: (1) confirm behavior and write contract fixtures/tests; (2) build the approved UI against test fixtures; (3) implement the existing-service/backend changes; (4) wire real data and test end to end; (5) remove fixtures from production paths and release the completed slice. A mocked UI may be reviewed in tests, but must not be presented as a functioning production capability.

## Common implementation constraints

- Use existing React/JSX conventions, PropTypes, local Lucide icons, shared panels/forms/tabs/dialogs, and the authenticated axios client. Do not paste standalone canvas HTML, CDN dependencies, inline scripts, or uploaded prototype asset URLs into production.
- Use the existing local logo and branding settings. Theme changes must not recolor a supplied logo destructively.
- Keep frontend visibility and backend authorization separate. Reuse existing gates; never widen permissions to make a screenshot work.
- Every operation needs defined loading, empty, stale/partial where relevant, success, permission, validation, and recoverable failure behavior. Retain entered values after failed saves.
- Use existing event streams or bounded fetches as appropriate. “Reactive” does not justify per-component polling loops, unnecessary sockets, or optimistic success for destructive/network operations.
- Reuse request IDs and sanitized error handling. Do not expose secrets, raw response bodies, filesystem paths, or unauthorized entity names in failure messages.
- Preserve valid bookmarks and existing callers. Add compatibility adapters/deprecation tests for changed API shapes instead of silently truncating lists or changing import semantics.
- Document each new storage field, migration, retention policy, and rollback behavior before applying it. Do not introduce a new persistence layer for cosmetic state.
- Remove superseded UI and duplicate code only after parity tests pass. No unrelated map rewrite, new graph engine, replacement backup system, or provider expansion.

## Release gates

- [ ] All eight approved surfaces are implemented against real contracts, not sample data.
- [ ] All built-in presets resolve required tokens in their supported modes; representative light/dark/custom/auto-switch browser checks pass across every new surface.
- [ ] Keyboard, focus return/trapping, reduced motion, readable contrast, small-screen scrolling, and enlarged text are verified in a real browser.
- [ ] Existing viewer/editor/admin and applicable capability restrictions are covered in frontend and API tests.
- [ ] Relevant unit, contract, integration, and Playwright tests pass; existing navigation responsiveness and map-state regressions remain covered.
- [ ] Run the repository verification ladder. `make verify` explicitly omits backend tests; use `make verify-full` and relevant integration/E2E suites for changed backend behavior. Do not report the shorter gate as complete backend coverage.
- [ ] Record measured query counts and performance results using the existing load harness; do not claim unmeasured scale.
- [ ] Upgrade/migration and rollback paths are tested on disposable data. Import tests must never mutate the user's inventory.
- [ ] Update user docs, release notes, and support boundaries. Metric rules are now selected scope, but advanced alert policies remain deferred.
- [ ] Record completion evidence per plan; leave unchecked work visible.

Approval is recorded; no new UI approval round is required for faithful implementation. Escalate materially different behavior, broadened product scope, or destructive migration choices rather than treating design approval as blanket authority.
