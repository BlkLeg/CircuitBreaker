# 01 · Unified navigation and command search

Status: approved, including the user's subsequent consolidation decision. Depends on plan 00.

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
- **Pins:** store stable destination IDs, independently of dock preferences. Initial scope: browser-local, deployment/user-namespaced storage with versioning, bounds, validation, and graceful fallback if storage is blocked. No cross-device synchronization backend solely for this feature.
- **Recents:** update after successful navigation from any entry point, not only navigator clicks. Keep a small bounded list (six initially), canonicalize IDs, and exclude auth flows, sensitive query strings, and failed navigation. Clear in-memory state on logout; isolate masquerade identity and re-filter persisted references on every read/activation.
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

Filter pages, settings children, actions, pins, recents, and entity results using current route/capability and resource visibility policies. Parent access does not imply access to every settings tab. Search result authorization must also be enforced server-side. Preserve the separation between navigation visibility and actual API/route authorization.

## Work packages

- [ ] **N1:** Add parity tests enumerating current routes, settings tabs, asset types, and Login/Profile actions. Include dock configuration snapshots and direct URLs.
- [ ] **N2:** Extend existing navigation metadata with stable IDs, descriptions, aliases, and children; share settings metadata and visibility without creating another registry.
- [ ] **N3:** Build themed browse/search/result/pin/recent UI and keyboard behavior against fixtures.
- [ ] **N4:** Connect entity search. Fix collection-only/legacy URLs through a canonical result adapter and supported entity deep links. Bound backend queries before materialization; do not fetch all matches then slice. Use existing authorization dependencies.
- [ ] **N5:** Wire Header and App to one navigator state and Ctrl/Cmd+K handler. Preserve existing palette actions and remove the redundant header search entry/Routes menu.
- [ ] **N6:** Add isolated personal shortcut persistence and successful-route tracking. Revalidate stored values, avoid arbitrary URL execution, and do not persist returned asset descriptions.
- [ ] **N7:** Remove CommandPalette and palette-only styles/tests only after migrated behavior passes. Remove prototype planned-workflow links and simulated route messages.

## Acceptance

- Both click and Ctrl/Cmd+K open the same overlay exactly once; no legacy palette remains.
- All visible destinations and valid settings children are reachable; aliases and permissions stay consistent with dock/router/settings.
- Searching for an asset opens that asset; slow/failed search does not block local page navigation or replace newer results.
- Existing Login/Profile actions work with correct modal/focus handoff.
- Pins and recents survive reload within their defined scope, never leak between users, and never modify dock state.
- Theme switching, mobile width, focus trapping/return, browser Back/Forward, direct settings links, route guards, and navigation responsiveness tests pass.
- API/contract tests cover bounded results, canonical Networks/IPAM activation, unauthorized results, deleted entities, and malformed destinations.
