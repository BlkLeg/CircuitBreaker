# 01 · Unified navigation and command search

Status: approved, including the user's subsequent consolidation decision. Depends on plan 00.

Execution status: U1–U6 are implemented in the current working tree. The reconciled plan below now records the completed cutover and its validation evidence. The older 2026-09-08 scratch execution document is historical after Task 7.

## Outcome and replacement boundary

One header **Navigate** control and **Ctrl/Cmd+K** open the same responsive navigator. It replaces both Header's Routes dropdown and CommandPalette. Preserve the dock, its saved order, visibility, labels, and customization behavior. Keep unrelated header widgets and utilities.

The approved grouped/pinned/recent layout is the default browse state. The same input searches pages, settings, assets, and supported account actions. Do not preserve a second “Search your lab” overlay or redirect empty results to a removed palette. The canvas showed page-only search; the consolidation requirement below intentionally expands its data sources without requiring a separate layout.

## Existing files and proposed boundaries

Existing: `apps/frontend/src/App.jsx`, `components/Header.jsx`, `components/CommandPalette.jsx`, `data/navigation.js`, `data/routeGuards.js`, `components/settings/SettingsNav.jsx`, `pages/SettingsPage.jsx`, `api/client.jsx`, and backend `apps/backend/src/app/api/search.py`.

Proposed within frontend `src/`:

- `components/navigation/GlobalNavigator.jsx`: overlay composition, grouped browse/results, focus and activation.
- Small focused child components for result rows and personal shortcuts only when separation helps.
- `hooks/useNavigatorSearch.js`: immediate local matches plus cancellable/debounced remote entity search.
- `lib/navigationSearch.js`: pure matching, ranking, result normalization, and stable IDs.
- Shared settings destination metadata, extracted from the current settings tab definitions. A minimal personal-navigation storage helper, if existing user-preference helpers are unsuitable.

Avoid turning App or Header into a large new navigation controller.

## Interaction and data contract

- **Browse:** retain Acquire, Inventory, Observe, Govern, System. Counts derive from visible registered pages; do not hard-code 21 for every role or release.
- **Local search:** pages, aliases, nested settings, and eligible actions appear immediately. Prioritize exact/prefix destination matches; group Pages & Settings, Assets, and Actions clearly. Deduplicate identical canonical destinations.
- **Entity search:** reuse the authenticated search API; debounce approximately 200 ms, ignore out-of-order responses, cancel on close/query change where supported, and keep local results usable during remote loading/failure. Show an explicit asset-search failure and Retry rather than “no results.”
- **Activation:** route items use the existing router. Asset results open the actual selected asset where supported, not just an unfiltered collection. Define and test canonical entity identity/deep-link handling before promising it. Unknown, deleted, or inaccessible results fail safely.
- **Actions:** preserve the existing Login/Profile entry points where appropriate. Close the navigator before opening an auth/profile dialog and transfer focus intentionally. Actions must execute what their label promises; do not add destructive command execution.
- **Pins:** store stable page/settings destination IDs, independently of dock preferences. Remote asset hits and account actions are not pinnable. Initial scope: browser-local, deployment/user-namespaced storage with versioning, bounds, validation, and graceful fallback if storage is blocked. No cross-device synchronization backend solely for this feature.
- **Recents:** update only after the routed page has rendered, from any entry point—not only navigator clicks. Keep a small bounded list (six initially), canonicalize dynamic/detail routes to registered pages, and exclude auth flows, sensitive query strings, unknown routes, and failed navigation. Clear in-memory state on logout without deleting the returning user's namespaced persisted shortcuts; isolate masquerade identity and re-filter persisted references on every read/activation.
- **Keyboard:** Ctrl/Cmd+K is the primary shortcut, shown using platform conventions. Optional G G follows existing app shortcut policy and must not fire during typing, IME composition, or conflicting modal interactions. Focus search on open; arrows/Enter navigate results; Escape closes and restores the actual opener. Never have two active keyboard listeners toggling separate overlays.
- **Responsive/accessibility:** anchored desktop dialog, full-height mobile dialog, local scroll for long groups/results, visible focus, labelled groups, live result/status announcements, and no color-only selection. Page-only search remains usable offline.

## Settings and authorization correction

Current SettingsPage reads `?tab=`, not the canvas/palette's `?section=`. Generate destinations from SETTINGS_TABS and the same allowed-tab policy used by SettingsPage:

- General/defaults → `/settings?tab=general`
- Appearance/timezone/icons/branding → Appearance, with field-specific focus only where explicitly supported
- Categories/environments/locations → Resources
- Authentication/session controls → Security
- Docker → Integrations; inventory transfer/backup → System
- Device Roles, Connectivity, and Knowledge Base retain their actual tab IDs and restrictions

Do not invent an Experimental section from a stale command label. Verify any fine-grained keyword target against its real owner. Add a small, explicit legacy-link normalization map only for valid historical links.

SettingsPage itself owns direct-link normalization and URL synchronization: a browser-opened legacy `?section=` bookmark must be replaced with its canonical allowed `?tab=`, and Back/Forward query changes must update the rendered tab. Normalizing only navigator-triggered links is insufficient.

## Approved canvas translation invariants

The production overlay keeps the approved titlebar and visible Close control, All pages and Recent modes, pinned-pages strip, Everything plus five lifecycle category filters, current-page marker, wide three-column grouped browse layout, local result scrolling, and footer/status treatment. The desktop panel is anchored below the header at the right and grows to the approved wide workbench footprint; the narrow layout becomes a full-height dialog.

The canvas's Planned workflows mode, canvas links, simulated selection messages, sample controls, and hard-coded `HOMELAB / LOCAL` label are review scaffolding and are omitted. If the application has no real deployment label, do not fabricate one to fill the titlebar.

Entity selection is durable URL state. Keep `?entity=<id>` in the address bar while the detail panel is open, resolve direct links through the entity's read endpoint rather than the currently loaded list, remove the parameter when the panel closes, and synchronize Back/Forward. Network results target the Networks tab explicitly; same-path navigation cannot assume the target page remounts.

Filter pages, settings children, actions, pins, recents, and entity results using current route/capability and resource visibility policies. Parent access does not imply access to every settings tab. Search result authorization must also be enforced server-side. Preserve the separation between navigation visibility and actual API/route authorization.

## Work packages

- [x] **N1:** Add parity tests enumerating current routes, settings tabs, asset types, and Login/Profile actions. Include dock configuration snapshots and direct URLs.
- [x] **N2:** Extend existing navigation metadata with stable IDs, descriptions, aliases, and children; share settings metadata and visibility without creating another registry.
- [x] **N3:** Build themed browse/search/result/pin/recent UI and keyboard behavior against fixtures.
- [x] **N4:** Connect entity search. Fix collection-only/legacy URLs through a canonical result adapter and supported entity deep links. Bound backend queries before materialization; do not fetch all matches then slice. Use existing authorization dependencies.
- [x] **N5:** Wire Header and App to one navigator state and Ctrl/Cmd+K handler. Preserve existing palette actions and remove the redundant header search entry/Routes menu.
- [x] **N6:** Add isolated personal shortcut persistence and successful-route tracking. Revalidate stored values, avoid arbitrary URL execution, and do not persist returned asset descriptions.
- [x] **N7:** Remove CommandPalette and palette-only styles/tests only after migrated behavior passes. Remove prototype planned-workflow links and simulated route messages.

## Reconciled execution plan

This section is the executable continuation from `1fb9b472`. It replaces Tasks 8–10 in the 2026-09-08 scratch plan, whose logout, navigation-success, selected-entity, settings-URL, and visual-shell assumptions do not match the current application or the approved canvas.

### Verified starting point

The working tree was clean and the full frontend suite passed on 2026-09-09: 194 files and 1,610 tests.

| Commit                 | Completed responsibility                                              |
| ---------------------- | --------------------------------------------------------------------- |
| `75a8741c`             | Pure theme token derivation                                           |
| `068177d3`             | Apply/reset raised-surface, status, and contrasting-foreground tokens |
| `2cf2202c`             | Shared settings visibility and canonical `?tab=` destinations         |
| `faadd2bb`             | Local ranking and remote result normalization                         |
| `7d0fe879`             | Namespaced browser-local pins and recents primitives                  |
| `56933f25`             | Immediate local plus debounced/cancellable remote search              |
| `3ead2e59`, `1fb9b472` | Unmounted navigator skeleton, focus containment, and ARIA groups      |

At the verified starting point, runtime still used `CommandPalette`: App owned `paletteOpen`, Header rendered both Routes and the palette trigger, and `GlobalNavigator` was not mounted. The units below closed those gaps without replaying the completed foundation commits.

### U1 — Complete the existing registries and settings URLs

Files: `data/navigation.js`, `data/settingsDestinations.js`, `components/settings/SettingsNav.jsx`, `pages/SettingsPage.jsx`, `lib/navigationSearch.js`, and their existing tests.

- Add a unique stable ID, short operational description, and aliases to every existing `NAV_GROUPS` item. Keep route paths, route-derived guards, dock defaults, and saved dock paths unchanged.
- Build page search entries from that metadata. `description: null` and `keywords: []` are not the approved N2 result.
- Move `SETTINGS_TABS` ownership into `data/settingsDestinations.js`; `SettingsNav` imports it. The destination data layer must not depend on a rendered component for its registry.
- Export one settings keyword matcher and use it in both SettingsPage search and navigator search. Delete SettingsPage's duplicate keyword map.
- Resolve `tab` and valid historical `section` values through one pure, authorization-aware function.
- Synchronize SettingsPage with URL changes after mount. A direct valid `?section=` bookmark is replaced with canonical `?tab=`; Back/Forward changes the rendered tab; invalid or forbidden values fall back without briefly rendering forbidden content.

Required tests:

- Registry IDs are unique; every item has a description/aliases, a real App route, and unchanged guard/dock behavior.
- Description/alias searches such as `server`, `topology`, and `ssl` find the intended page.
- Direct legacy settings links normalize; `experimental` remains invalid; editor/viewer/admin results match the page's allowed tabs.
- Back/Forward between settings query URLs changes the active tab.

Run from `apps/frontend`:

```bash
npx vitest run src/__tests__/navigation-search.test.js \
  src/__tests__/settings-destinations.test.js \
  src/__tests__/settings-page.test.jsx
```

### U2 — Align the unmounted navigator with the approved shell

Files: `components/navigation/GlobalNavigator.jsx`, `components/navigation/NavigatorResultRow.jsx`, `styles/navigator.css`, and `__tests__/global-navigator.test.jsx`.

- Restore the approved top-right desktop workbench geometry: approximately 924×824px, capped to the viewport, with an intermediate fluid width and a full-height/full-width dialog at 640px and below. The present 640px single-column dialog is only a skeleton.
- Add the title/subtitle and visible Close control. Keep search focused on open and restore the actual opener on ordinary close.
- Add All pages and Recent modes. Do not add Planned workflows.
- In All pages, render the pinned strip, Everything plus the five lifecycle category filters, then the visible groups. Search always spans every allowed group regardless of the selected browse filter.
- Use the approved three-column grouped browse layout at wide sizes and a single column on narrow screens. Counts derive from visible registry items.
- Derive the current-page marker from the router, including canonical parent markers for `/agents/:id` and `/monitors/:id`; expose `aria-current="page"` and a non-color-only marker.
- Show the new page descriptions. Render pin controls only for page and settings entries—not remote assets or actions. Revalidate stored IDs against the current authorized index on open and activation.
- Keep the live result status and footer keyboard hints. Omit canvas links, simulated messages, sample controls, and unbacked environment labels.
- Replace the focus-return safety net with a real Tab/Shift+Tab loop across close, modes/filters, search, rows, pin buttons, and Retry. Preserve Escape, arrows/Enter, IME handling, modal handoff, reduced motion, and token-only colors.

Required tests cover both modes, category filtering, search across categories, current-page semantics, descriptions, pinnable kinds, focus-loop boundaries, responsive classes, and absence of every prototype-only element.

Run:

```bash
npx vitest run src/__tests__/global-navigator.test.jsx \
  src/__tests__/navigation-search.test.js \
  src/__tests__/navigator-prefs.test.js
```

### U3 — Make entity selection durable before exposing asset search

Files: create `hooks/useEntityDeepLink.js`; modify `lib/navigationSearch.js`, the Hardware/Compute/Services/Storage/External Nodes pages, `pages/IPAMPage.jsx`, `components/ipam/NetworksTab.jsx`, and focused tests. Misc remains collection-only because it has no read-only detail panel; never open its edit form from search.

The hook accepts a stable per-entity loader and selection/error callbacks, and returns row-open and panel-close handlers:

- A row click immediately selects the loaded row and pushes `entity=<id>` while preserving other query parameters.
- A direct load or Back/Forward change resolves the entity through the type's existing `get(id)` API, independent of current filters and future pagination.
- Keep the entity parameter while the detail panel is open. Close clears the selection and removes only `entity` with `replace`.
- Back closes and Forward reopens. Validate positive integers before requesting. Missing, deleted, inaccessible, or malformed targets settle on the collection, remove the bad parameter, and show one sanitized message.
- Guard late responses so rapid entity changes cannot open an older target.
- Replace each page's direct row/detail state callbacks with the hook handlers while preserving edit/form state and detail props.
- Hardware entity activation selects the Hardware inventory tab even when the mounted page was showing Clusters.
- Network results use `/ipam?tab=networks&entity=<id>`. Make IPAM tabs URL-aware so same-path activation from IP Addresses, VLANs, or Sites opens Networks; leaving Networks closes/removes a network selection.

Required tests cover direct load/reload outside the current list, row-open and close URL changes, Back/Forward, stale requests, safe 404/403/malformed handling, same-path Hardware/IPAM tab changes, canonical Network URLs, and Misc's honest collection fallback.

Run:

```bash
npx vitest run src/__tests__/entity-deep-link.test.jsx \
  src/__tests__/navigation-search.test.js \
  src/__tests__/hardware-page.test.jsx \
  src/__tests__/external-nodes-page.test.jsx
```

### U4 — Cut over App and Header; record only rendered routes

Files: `App.jsx`, `components/Header.jsx`, `hooks/useNavigationTiming.js`, `styles/navigator.css`, new `__tests__/navigator-wiring.test.jsx`, plus the existing navigation timing/header/surface parity tests.

- Replace `paletteOpen` with `navigatorOpen`; mount one GlobalNavigator and pass one `onOpenNavigator` callback to Header.
- Remove Header's Routes dropdown and wide palette trigger. Put one compact Navigate trigger in their place; keep brand, widgets, Recent Changes, theme controls, user avatar, and dock untouched.
- Keep one Ctrl/Cmd+K listener in App. Ignore repeat/composition. Header and keyboard operate the same state and dialog.
- Centralize activation in App: routes use React Router; actions close first and then call the existing auth/profile modal functions.
- Extend `NavigationMountSignal` with an optional callback carrying the location captured by the newly mounted route. Record a recent only from that success callback—not from an effect above the Suspense route tree.
- Resolve a mounted pathname to an authorized registered destination before recording. Canonicalize dynamic details to their parent; never record redirects, auth lifecycle paths, query strings, unknown routes, or a route that did not mount.
- Do not call `clearNavigatorPrefs` on logout. Remove that dead helper/test unless a real explicit-reset caller is introduced. AppInner/navigator unmount clears in-memory state; the returning user's namespaced persisted shortcuts survive.

Required tests:

- Exactly one Navigate control; no Routes/palette control.
- Header click and Ctrl/Cmd+K open exactly one dialog; a second shortcut closes it.
- Modal handoff order is close then open.
- An unmounted location is not recent; a successfully mounted route is.
- Dock/navigator/registry parity remains true for viewer/editor/admin.
- Logout/unmount clears visible component state without deleting persisted state; user and masquerade namespaces remain isolated.
- Existing navigation-timing wedge semantics are unchanged.

Run:

```bash
npx vitest run src/__tests__/navigator-wiring.test.jsx \
  src/__tests__/navigation-timing.test.jsx \
  src/__tests__/header-nav-menu.test.jsx \
  src/__tests__/nav-surface-parity.test.jsx \
  src/__tests__/navigator-prefs.test.js
```

### U5 — Remove CommandPalette after parity passes

Delete `components/CommandPalette.jsx` and `__tests__/command-palette-nav.test.jsx`; remove the contiguous Command Palette CSS block from `styles/main.css`; update the stale consumer comment in `data/navigation.js`; extend `UpdateThemeTokens.test.jsx`; add `navigator-parity.test.jsx`.

Before deletion, tests must prove every authorized top-level page and settings tab is reachable, Login/Profile action parity remains, asset search opens durable entity URLs, both open mechanisms exercise the mounted navigator, and the dock is unchanged.

After deletion, scan production source for `CommandPalette`, `paletteOpen`, `onOpenPalette`, `palette-overlay`, `.command-palette`, and `.palette-*`. `ThemePalette` is unrelated and stays.

Run:

```bash
npx vitest run src/__tests__/navigator-parity.test.jsx \
  src/__tests__/UpdateThemeTokens.test.jsx
npm test
npm run lint
npm run format:check
```

### U6 — Browser, accessibility, and release evidence

Create `e2e/global-navigator.spec.ts`; extend the shared accessibility coverage if it does not open dialogs; update `docs/getting-started.md` and `docs/settings.md`.

Playwright must verify:

- One overlay from the header and shortcut on desktop and mobile.
- Wide top-right desktop composition and full-height mobile layout with local scrolling and 40px pin / 48px route targets.
- Focus entry, containment, return, and Profile handoff.
- Local page search during a failed remote search plus a working Retry.
- A Hardware result opens the real `/hardware?entity=<id>` detail; reload preserves it; Back closes; Forward reopens.
- A Network result switches an already-mounted IPAM page from a different tab and opens the target.
- Canonical and legacy Settings URLs render and follow Back/Forward.
- Viewer/editor/admin filtering holds for browse, search, pins, and recents.
- Gruvbox dark/light, one contrasting native preset, and one custom palette update while the overlay is open; axe passes for open desktop/mobile dialogs.
- No prototype links, external assets, console errors, or ErrorBoundary output.

Run from `apps/frontend`:

```bash
npx playwright test e2e/global-navigator.spec.ts --project=chromium --project=mobile-chrome
npx playwright test e2e/global-navigator.spec.ts --project=firefox --project=webkit
```

Then run from the repository root:

```bash
make lint
make verify
git diff --stat d3ea69aa...HEAD -- apps/backend/src/app
```

The backend diff for this slice should be empty. If implementation changes backend application files, run `make verify-full` and the relevant API/service tests rather than reporting `make verify` as backend coverage.

Use one reviewable commit per unit: registry/settings contract; approved shell alignment; durable entity selection; App/Header cutover; palette removal; browser evidence. Do not mix plans 02–08 into these commits.

## Acceptance

- Both click and Ctrl/Cmd+K open the same overlay exactly once; no legacy palette remains.
- All visible destinations and valid settings children are reachable; aliases and permissions stay consistent with dock/router/settings.
- Searching for an asset opens that asset; slow/failed search does not block local page navigation or replace newer results.
- Existing Login/Profile actions work with correct modal/focus handoff.
- Pins and recents survive reload within their defined scope, never leak between users, and never modify dock state.
- Theme switching, mobile width, focus trapping/return, browser Back/Forward, direct settings links, route guards, and navigation responsiveness tests pass.
- API/contract tests cover bounded results, canonical Networks/IPAM activation, unauthorized results, deleted entities, and malformed destinations.
