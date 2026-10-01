# Enterprise navigation dock — implementation plan

**Status:** Active — planned; no implementation task started.
**Date:** 2026-09-29.
**Design:** [approved dock design](../docs/design/2026-09-29-enterprise-dock-design-plan.md), navigation draft **version 4**.
**Scope:** replace the dock presentation and integrate its Map anchor, configured shortcuts, and All pages control. Frontend only. The canvas scene and page browser are excluded.

This is the executable companion to the design document. That document owns visual decisions; this plan owns task boundaries, concrete contracts, verification, and completion evidence. All tasks below remain unchecked.

## Implementation constraints

- Retain `MacOSDOCK.jsx` as the integration boundary initially; do not combine this change with a rename across the app.
- Keep `NAV_GROUPS`, `NAV_ITEMS_FLAT`, `navItem`, `navGroupOf`, `canSeeNavItem`, and `resolveDockPaths` authoritative. No copied production destination list or second permission model.
- Keep `dock_order` and legacy `dock_hidden_items` semantics in the resolver. The fixed Map anchor is a presentation rule layered over the resolved list.
- Persist through the existing settings API. These are application settings, not personal navigator pins. Add no storage field, migration, endpoint, or new permission.
- Preserve the nine current fresh-install defaults and all valid legacy shortcuts. The four-shortcut canvas example is a visual fixture only.
- Use local React SVGs and existing theme variables. No CDN scripts, remote illustrations, generated raster assets, new icon dependency, or prototype HTML in application code.
- Preserve concurrent map work, router transition behavior, and existing navigation timing instrumentation. Coordinate map-control clearance through the app shell's layout contract.

## Delivery order

| Task | Depends on | Reviewable result |
| --- | --- | --- |
| D1 · Layout contract | — | Tested, shared projection of saved shortcuts into desktop/mobile layouts. |
| D2 · Artwork | — | Complete illustrated family, including optional destinations and All pages. |
| D3 · Dock composition | D1, D2 | Real routed dock matching the approved desktop reference. |
| D4 · Navigator and reveal | D3 | One navigator, correct opener focus, keyboard-safe auto-hide. |
| D5 · Dock settings | D1, D3 | Accurate preview and membership/order editing with fixed Map. |
| D6 · Responsive integration | D3, D4 | Overflow, touch, themes, and content clearance on real pages. |
| D7 · Verification and docs | D4–D6 | Passing focused checks, screenshots, updated docs, and implementation evidence. |

D1 and D2 are independent preparation work. Complete the remaining dependencies before presenting the dock as production-ready. Keep each task's changes reviewable; there is no requirement to commit partially functioning application states.

## D1 · Define a shared dock layout projection

**Files:** add `apps/frontend/src/lib/dockLayout.js` and `src/__tests__/dock-layout.test.js`. Consume the existing registry without changing its persisted-list resolver.

- [ ] Implement `buildDockLayout(settings, user)` returning `{ map, shortcuts, desktopLeft, desktopRight, mobileShortcuts }`.
- [ ] Resolve membership with `resolveDockPaths`, safely look up each path, apply shared authorization, and exclude `/map` from the configurable shortcut sequence.
- [ ] Resolve the fixed Map entry from `navItem('/map')` and apply the same visibility gate. Render it once; never bypass the registry even for the anchor.
- [ ] Split authorized non-Map shortcuts at `Math.ceil(shortcuts.length / 2)` for desktop. Mobile uses `shortcuts.slice(0, 2)`. All pages is a button, not an invented registered route.
- [ ] Preserve registry IDs. Do not derive artwork identity from a transformed URL slug.
- [ ] Do not mutate settings, write settings, change defaults, or attach new ordering rules to navigator pins.

Required fixtures:

| Input | Expected projection |
| --- | --- |
| `['/hardware', '/services', '/map', '/monitors', '/discovery']` | Hardware/Services, Map, Monitors/Discovery; mobile Map, Hardware/Services, All pages. |
| `['/hardware', '/map', '/services', '/monitors']` | Hardware/Services, Map, Monitors; non-Map relative order retained. |
| `[]` | Fixed Map plus All pages; no configurable shortcuts. |
| Map omitted or repeated | Exactly one Map anchor; no Map in either shortcut group. |
| Unknown routes or prototype keys | Ignored without a crash. |
| Viewer with restricted stored paths | Restricted entries absent before splitting or mobile selection. |
| Legacy hidden-list only | Existing resolver membership preserved, with Map handled as a fixed anchor. |

**Exit:** projection tests pass; existing resolver tests still pass unchanged. Update rendered membership expectations only when the later component begins using the new projection.

## D2 · Build the complete local artwork family

**Files:** add `src/components/navigation/DockArtwork.jsx` and `src/__tests__/dock-artwork.test.jsx`.

- [ ] Implement `<DockArtwork itemId={id} />` with PropTypes. Use the design document's six reference symbols and a consistent `0 0 120 110` coordinate system.
- [ ] Supply illustrations for every `NAV_ITEMS_FLAT` ID and the reserved `all-pages` control. Keep the artwork map private to this presentation component; it contains no paths, labels, guards, or default membership.
- [ ] Use React `useId` for every SVG definition/reference pair. Prefix derived definition names consistently; rendering several instances of the same symbol must not collide.
- [ ] Use semantic variables and opacity for materials. Preserve the Map connected-block mark and shallow illustrated depth. Keep non-Map accents subordinate to Map.
- [ ] Export a small supported-ID list or predicate only for the completeness assertion. Test it against the actual navigation registry.
- [ ] Test two instances of an icon for distinct IDs and valid local gradient references; test decorative accessibility semantics.
- [ ] Inspect the six reference icons at production size, 2× density, and in light/dark themes. Inspect optional icons together to catch inconsistent perspective and weight.

**Exit:** all registered destinations are covered; no stock-icon fallback, remote dependency, or duplicated gradient IDs. Optional artwork follows the approved family's style; do not introduce another design direction.

## D3 · Replace the rendered dock and old styling

**Files:** `src/components/MacOSDOCK.jsx`, add `src/styles/dock.css`, remove superseded dock selectors from `src/styles/main.css`, update `src/__tests__/dock-membership.test.jsx` and `nav-surface-parity.test.jsx`.

- [ ] Consume `buildDockLayout` and preserve `pendingCount` / `wsStatus` props.
- [ ] Render one navigation landmark named **Primary navigation**, desktop shortcut groups, the fixed Map anchor, and All pages. The DOM order must match visual and tab order.
- [ ] Use real `NavLink` destinations. Reuse the existing current-route matching rule, including distinct Logs/Audit Log/Parked Messages entries. Ensure React Router's `aria-current` matches the same rule rather than independently marking a parent current.
- [ ] Render permanent translated labels, decorative `DockArtwork`, a current-page underline, and the raised Map tile. Map's persistent visual treatment must not imply `aria-current` while another destination is current.
- [ ] Implement the approved dimensions and component-scoped material variables in `dock.css`. Preserve `.macos-dock-root`, `.macos-dock-shelf`, and `.macos-dock-link` integration selectors initially so existing browser journeys remain usable.
- [ ] Replace the existing Framer Motion tap magnification with CSS hover/press treatment; remove the unused motion import. Limit hover lift to 4px; disable movement for reduced motion.
- [ ] Preserve Discovery counts, `99+` cap, and connecting/disconnected states. Use semantic tokens and translated accessible descriptions instead of hard-coded colors or unexplained dots.
- [ ] Replace tooltip-based parity-test extraction with route-link labels/accessibility queries. Exclude the All pages button from route parity comparisons.
- [ ] Update rendered membership tests for one fixed Map plus authorized shortcuts. Keep resolver tests' empty-array and legacy behavior assertions; the resolver still represents persisted membership.

**Exit:** a real desktop dock matches version 4; current route and permissions are correct; no duplicate Map link or old magnification remains.

## D4 · Connect All pages and implement safe reveal/focus behavior

**Files:** `src/App.jsx`, `src/components/MacOSDOCK.jsx`; add `src/__tests__/dock-interaction.test.jsx`, extend `src/__tests__/navigator-wiring.test.jsx`. Change `GlobalNavigator.jsx` only if existing opener restoration demonstrably needs a narrow fix.

- [ ] Add dock props `onOpenNavigator` and `navigatorOpen`. Pass the app shell's existing callback/state; do not mount another overlay or add another Ctrl/Cmd+K listener.
- [ ] At All pages activation, focus the button before opening so the existing navigator captures the actual opener. Track whether that session originated from the dock locally; header/shortcut openings must not claim dock ownership.
- [ ] Keep the dock visible during its navigator session and through the close/focus-restoration transition. Use restored focus to clear or sustain the hold; do not race a hide timer against the overlay's cleanup.
- [ ] Preserve 100px bottom-edge trigger, 450ms hide delay, and 12px hit buffer initially. Include the raised tile in pointer hit bounds, not only the shelf rectangle.
- [ ] Consolidate visibility conditions: mobile, pointer inside the dock, focus inside the dock, or dock-owned navigator session. Cancel pending hide on any hold; clear listeners/timers on unmount.
- [ ] Ensure a keyboard user can recover the hidden dock. Provide a small visible, accessible **Show navigation** reveal handle while collapsed. Activating it reveals the dock and focuses Map; route links in the collapsed subtree must be inert until revealed. The handle has a 44px hit target and theme-aware focus state.
- [ ] Do not put invisible route links into the tab sequence. Do not make the entire dock permanently unreachable by applying `inert` without an external reveal control.
- [ ] In unit tests, exercise reveal/hide with fake timers, pointer entry over the raised tile, focus entry/exit, navigator hold/dismissal, and unmount cleanup.
- [ ] In app wiring tests, use the real dock: open from All pages, assert one Navigate dialog, verify search focus, dismiss with Escape, and verify focus returns to All pages. Repeat header and shortcut opening to catch ownership leaks.

**Exit:** all entry points use one navigator; mouse and keyboard can recover the dock; auto-hide never strands focus or hides the navigator opener during restoration.

## D5 · Align settings with the fixed anchor

**Files:** `src/components/settings/DockSettings.jsx`, `src/__tests__/dock-settings.test.jsx`.

- [ ] Separate the configurable shortcut editor from a desktop composition preview produced by `buildDockLayout`.
- [ ] Show Map as fixed, with no checkbox or move controls. Explain that shortcut order is split around Map and that the mobile dock uses the first two available shortcuts.
- [ ] Remove Map from the visible editable sequence without rewriting saved settings on mount. Preserve hidden/unauthorized stored entries when editing visible ones.
- [ ] Keep safe lookup/deduplication and visible-neighbor move logic. When moving a shortcut, swap its stored positions with the adjacent authorized non-Map shortcut; do not accidentally move Map or a hidden entry.
- [ ] Save through `settingsApi.update({ dock_order: order })` and reload the existing settings context. Preserve Map entries already stored; do not automatically insert/delete them merely to normalize the new appearance.
- [ ] Verify selecting, removing, reordering, legacy first-save, empty shortcut sequence, and failed save. On failure retain edits; on successful reload the actual dock and preview agree.
- [ ] Replace old tests that expect movable/removable Map with explicit fixed-anchor assertions. Keep legacy and permission-preservation coverage.

**Exit:** settings accurately explain and preview the rendered dock while retaining the existing storage contract.

## D6 · Finish overflow, responsiveness, and content clearance

**Files:** `src/components/MacOSDOCK.jsx`, `src/styles/dock.css`, relevant shared-shell spacing in `src/styles/main.css`; add `apps/frontend/e2e/dock.spec.ts` using existing `e2e/fixtures/api.ts`.

- [ ] Constrain shelf width to viewport minus gutters. Keep Map and All pages non-shrinking; use bounded, independently scrollable desktop wings with `min-width: 0`.
- [ ] Show directional scroll affordances only when a wing overflows. Label their side/direction, use 44px targets, and disable controls at the corresponding end.
- [ ] Recalculate scroll availability on container resize and membership changes; use `ResizeObserver` and clean it up. Handle pointer/wheel/touch scrolling and reduced-motion programmatic scrolling.
- [ ] On focus or active-route changes, reveal the shortcut within its wing without scrolling the document or changing route state.
- [ ] On widths below the existing 768px mobile breakpoint, render Map, the first two authorized shortcuts, and All pages in a single row. Never write this mobile projection back into settings.
- [ ] Support fewer than two shortcuts, long translated labels, enlarged text, and custom font size. Allow height growth; maintain full accessible names if visible names need truncation.
- [ ] Expose a shell-level dock clearance variable derived from shelf height, Map protrusion, bottom gap, and safe area. Reserve enough scroll-content padding for the last page action to remain reachable.
- [ ] Inspect `/map`'s controls, attribution, and bottom overlays with the dock revealed. Coordinate shared clearance with the current map layout rather than hard-coding offsets into node rendering or rewriting map controls.
- [ ] Provide a solid-surface fallback for unavailable blur/color mixing and a visible outline in forced-colors mode. Validate meaningful label/focus/selection contrast across representative theme presets and a custom palette.

Browser cases: 1440 × 900 approved-scale composition; 1912 × 983 large desktop; 820px tablet width; 390 × 844 mobile; 320px narrow width; enlarged text; all authorized destinations selected; no configurable shortcuts; light/dark/custom themes; reduced motion.

**Exit:** no viewport overflow, clipped focus, unreachable favorite, obstructed map control, or blocked final page action. Mobile follows saved order rather than the old hard-coded subset.

## D7 · Verification, documentation, and completion evidence

**Files:** `apps/frontend/e2e/navigation.spec.ts`, new `dock.spec.ts`, affected Vitest suites, `docs/settings.md`, this plan, and the design document's status/evidence section.

- [ ] Update navigation E2E comments that still describe magnifying icons. Keep actual dock `NavLink` clicks and the throttled map-navigation wedge test; do not replace them with `pushState` as a shortcut.
- [ ] Test Map → favorite → Map, a distinct log subroute, hidden-dock keyboard reveal, overflow favorite activation, navigator dismissal/focus return, mobile selection, and live theme changes.
- [ ] Check no new document load occurs during dock navigation and that real route content mounts. Retain error-boundary/console checks from existing fixtures.
- [ ] Capture revealed-dock screenshots against actual application pages. Compare the dock portion with version 4; the approved canvas heading/topology scene is not part of the comparison.
- [ ] Add/update relevant visual baselines only through the repository's documented Playwright container process in `docs/testing-visual-baselines.md`. Do not regenerate unrelated map baselines to accommodate dock defects.
- [ ] Document the fixed Map anchor, configured shortcut order, mobile selection, desktop reveal, overflow, and All pages in `docs/settings.md`.
- [ ] Remove obsolete dock-only CSS, imports, tooltip assumptions, and old motion after callers and tests have migrated. Leave unrelated page styles and theme logic intact.
- [ ] Record commands, results, reviewed screenshots, changed behavior, and any remaining issue here. Mark tasks complete only when their exit conditions pass.

### Commands during implementation

Run from `apps/frontend` unless noted otherwise. These are planned checks, not checks performed by this documentation change.

```bash
npm run test -- src/__tests__/dock-layout.test.js src/__tests__/dock-artwork.test.jsx src/__tests__/dock-membership.test.jsx src/__tests__/dock-interaction.test.jsx src/__tests__/dock-settings.test.jsx
npm run test -- src/__tests__/nav-surface-parity.test.jsx src/__tests__/navigator-wiring.test.jsx src/__tests__/global-navigator.test.jsx src/__tests__/nav-coverage.test.js src/__tests__/navigation-timing.test.jsx src/__tests__/navigation-longtask-consistency.test.jsx
npm run lint
npm run build
npm run e2e -- e2e/dock.spec.ts e2e/navigation.spec.ts --project=chromium
npm run e2e -- e2e/dock.spec.ts --project=firefox --project=webkit --project=mobile-chrome
```

Playwright uses the production build/preview configuration. If it reuses a preview server, confirm that server serves the current build before trusting results. `npm run build` invokes the repository's version-sync step; check the diff for incidental manifest changes.

Before pushing an implementation, run the repository-required `make lint` and `make verify` from the root in addition to the browser checks. Backend behavior is outside this change; do not claim backend coverage from those gates. Broaden testing only when changed callers or failures justify it.

## Completion ledger

| Task | Status | Evidence |
| --- | --- | --- |
| D1 | Pending | — |
| D2 | Pending | — |
| D3 | Pending | — |
| D4 | Pending | — |
| D5 | Pending | — |
| D6 | Pending | — |
| D7 | Pending | — |

No application implementation or production verification has been performed as part of writing this plan. Existing standalone prototype evidence remains recorded in the design document.
