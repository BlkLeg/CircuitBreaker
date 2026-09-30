# Enterprise navigation dock — design and implementation plan

**Status:** visual design approved 2026-09-29; implementation pending. This change writes the plan only.
**Approval:** “Much better. This is good. Just the dock portion of course. Write up the design plan for it.”
**Baseline inspected:** `a8bc1b52`, app version `0.4.5`, with concurrent map changes in the working tree.
**Approved reference:** [navigation draft](https://p.superdesign.dev/draft/763528ae-7b07-4471-8c7e-d85941439824), **version 4**, on the [navigation canvas](https://superdesign.dev/teams/4281dc54-7c08-491e-9c06-483e758fa325/projects/02148c7f-c84d-4250-bab6-85efce83f378).
**Execution companion:** [enterprise dock implementation plan](../../plans/2026-09-29-enterprise-dock-implementation.md), tasks D1–D7; implementation has not started.

## 1. Outcome and scope

Replace the MacOS-style dock's stock line icons and magnification with a crafted, modern enterprise navigation surface. Map is the visual anchor; the user's configured shortcuts remain easy to identify by their permanent labels. A final **All pages** control opens the existing unified navigator.

Approval covers the dock: its shelf, icon family, prominent Map tile, labels, selected states, and restrained interaction treatment. The canvas heading, introductory copy, sample topology, background scene, theme-preview button, footer, and simulated page browser are presentation scaffolding. Do not implement them. Keep the real app header, map workspace, page content, and navigator design.

This plan supersedes earlier requirements to preserve the dock's **visual appearance**, including the dock exception in [navigation IA](../../specs/2026-08-24-navigation-ia-rework-design.md) and the appearance-preservation language in [unified navigator plan 01](approved-ui/01-unified-navigator.md). Their route registry, permission boundaries, single-navigator contract, and existing persistence ownership remain applicable.

## 2. Approved visual direction

The dock should feel engineered and deliberate. Its identity comes from consistent geometry and subtle materials, rather than decorative glow or oversized animation.

| Element | Treatment |
| --- | --- |
| Shelf | Floating, horizontally centered, rounded surface with a quiet tonal gradient, thin edge, subtle top highlight, and restrained shadow. |
| Map | Raised rounded-square tile integrated into the shelf; connected infrastructure blocks on a topology plane. The tile is larger than ordinary shortcuts. |
| Shortcut icons | Custom vector illustrations with consistent perspective, proportions, edge treatment, and shallow depth. |
| Labels | Always visible below the artwork, in the existing system font. Readable page names, with no uppercase transformation. |
| All pages | Four-module illustration after a subtle divider at the trailing edge; visible label and button semantics. |
| Current page | Clear label treatment and a short accent underline. Map's permanent emphasis is separate from selection. |
| Hover | Small upward lift and a subtle surface response. No rotation, bounce, orbital motion, or magnification. |

Use version 4 as the visual reference, not the earlier globe design. The Map mark has three connected blocks and a structured topology plane; no sphere, orbit, circular halo, or glow. The satellite-dish Discovery illustration from version 3 is also superseded.

### Reference dimensions

These describe the approved desktop composition and are starting values for production CSS, rather than fixed viewport assumptions.

| Measurement | Desktop reference |
| --- | --- |
| Shelf corner radius | 24px |
| Shelf padding | 10px vertically, 20px horizontally |
| Ordinary shortcut | Approximately 100px wide, 108px high |
| Ordinary artwork box | Approximately 75 × 73px; the actual drawn symbol is smaller |
| Map allocation | Approximately 120px wide, with 8px side margins |
| Raised Map tile | Approximately 98 × 100px, 22px corner radius, raised 22px above the ordinary row |
| Map artwork box | Approximately 100 × 94px |
| Label | 11px; medium weight; Map label slightly stronger |
| Active underline | 2px high; approximately 15px wide, 20px for Map |
| Hover lift | At most 4px, approximately 200ms |
| Viewport clearance | Retain 24px desktop bottom clearance; mobile includes the safe-area inset |

The approved example reads **Hardware · Services · Map · Monitors · Discovery · All pages**. These four shortcuts illustrate composition; they are not a replacement default list or a new inventory taxonomy.

## 3. Icon system

Implement the illustrations as local React SVG components. Preserve crisp edges at the actual rendered size and at 2× pixel density. SVG artwork must remain legible without motion or shadow.

| Destination | Approved symbol |
| --- | --- |
| Map | Three infrastructure blocks joined by a branching connection, on a subtle topology plane. |
| Hardware | Machined enclosure with two inset device bays and small accent details. |
| Services | Three shallow stacked modules with an accent detail on the top plane. |
| Monitors | Bounded monitoring screen with a concise rising trace. |
| Discovery | Scanning panel with corner registration marks and a single horizontal scan line. |
| All pages | Four evenly spaced modules, with one small accent detail. |

Extend this same family to **every configurable dock destination**, using the shared registry as the completeness check. Existing destinations include Agents, Compute, Storage, External Nodes, IPAM, Other Assets, Intel, Privacy, Users, Access Tokens, Certificates, Notifications, Logs, Audit Log, Parked Messages, Settings, and Docs. Use symbols appropriate to those destinations with the same geometry and material discipline. Do not ship a polished default set with unrelated Lucide fallbacks for optional shortcuts.

Keep `navigation.js`'s existing icons for the header, navigator, and settings picker. The illustrated set is a dock-specific presentation keyed by stable navigation IDs; it is not a second route registry. A coverage assertion should catch a registered destination missing dock artwork.

SVG requirements:

- Use a consistent viewBox, optical alignment, perspective, highlight direction, and detail density.
- Resolve fills, outlines, and accents from semantic theme variables. Prefer opacity and restrained color mixing over literal palette values.
- Generate collision-free SVG gradient IDs with React `useId`; multiple dock/icon instances must render correctly.
- Mark decorative SVGs `aria-hidden`; the enclosing link or button supplies the accessible name.
- Ship local SVG source. No CDN scripts, remote assets, icon-font requests, raster dependency, or canvas HTML in production.

## 4. Membership, order, and Map placement

The following translates the visual anchor into production behavior without introducing a new settings model.

1. Continue resolving stored membership through `resolveDockPaths(settings)`, including its legacy fallback, deduplication, and untrusted-path handling. Continue filtering through `navItem`, `navGroupOf`, and `canSeeNavItem`.
2. Treat Map as a fixed navigation anchor rendered once. Remove `/map` from the configurable shortcut sequence **for rendering only**. Do not rewrite saved settings on load.
3. Preserve the relative order of the remaining configured shortcuts. On desktop, split that sequence after `ceil(count / 2)`, placing the fixed Map anchor between the two groups. All pages follows the second group. This makes the placement predictable as membership changes.
4. An existing empty `dock_order` yields **Map + All pages**. Existing settings can no longer hide Map in this design. This is an intentional behavior change accompanying the approved permanent anchor, not a storage migration.
5. Update DockSettings to describe Map as fixed and show the resulting left-to-right preview. Map has no checkbox or reorder controls; move controls apply to configurable shortcuts. Retain existing save/error behavior and preserve unrelated stored entries.
6. The existing dock settings belong to application settings. Do not claim these are per-user favorites or connect them to the navigator's separately stored pins/recents. No new persistence, backend endpoint, schema migration, or role change is required.

This preserves existing shortcut membership and relative ordering while making Map's presentation deliberate. Do not replace the nine fresh-install defaults or legacy membership with the four-item canvas example.

## 5. Responsive layout and overflow

Keep Map and All pages reachable at every supported width. Match the real app's breakpoints and usable width rather than relying on the canvas's fixed viewport.

- **Desktop:** fixed Map anchor between two shortcut groups. Groups may shrink their allocations moderately; labels and usable hit targets remain. When configured shortcuts exceed available width, use independently scrollable shortcut groups around the fixed controls. Provide visible overflow affordances and scroll a focused/current shortcut into view. Do not silently delete configured destinations or let the shelf exceed the viewport.
- **Tablet:** smaller artwork and spacing; retain the raised Map treatment and permanent labels. Use the same bounded overflow behavior.
- **Mobile:** Map moves to the leading position, followed by the first two authorized configurable shortcuts in saved order, then All pages. Additional destinations remain reachable through the existing navigator. This replaces the current hard-coded Map/Hardware/Settings subset; it does not change the saved order.
- **Large text and localization:** allow the dock height and label allocation to grow. Do not clip the only visible page name. Provide an accessible full name if a narrow layout requires truncation.
- **Content clearance:** account for the entire raised tile and label height. Keep bottom map controls, attribution, scrollable page actions, and mobile safe areas clear of the dock. Coordinate placement with concurrent map work without redesigning map controls.

## 6. Interaction and accessibility

### Navigation and active state

Use normal React Router links for real page activation. Preserve the existing matching behavior: a parent may claim an unregistered detail route, but `/logs` must not also become current when `/logs/audit` or `/logs/parked` is the destination. Apply `aria-current="page"` to the actual current destination.

Map's tile remains emphasized while another page is current, but its active underline appears only on the Map route. A selected favorite receives its own underline and label treatment. Do not show two current-page indicators simply because Map is visually prominent.

The All pages button calls the app shell's existing `handleOpenNavigator`. Reuse its open state, search, permissions, keyboard behavior, and activation. Preserve Ctrl/Cmd+K as the same navigator entry point. The prototype's miniature browser is not a new production overlay.

### Visibility

Retain the existing desktop edge-reveal/auto-hide policy for this dock redesign. The always-visible canvas is a presentation state, not approval for a new visibility setting. Preserve the existing 100px trigger zone and 450ms hide delay initially, adjusting hit geometry for the raised tile.

Correct keyboard handling as part of integration: keep the dock visible while it contains focus, while the pointer is inside the complete dock bounds, or while its All pages opener owns the navigator session. Reveal it on focus entry. Hidden links must not be invisibly actionable or receive pointer events. On navigator dismissal, restore focus to All pages and keep it visible. Mobile remains visible.

### Input and motion

- Use a native navigation landmark named **Primary navigation**, native links, and a native button for All pages.
- Provide visible focus rings around the complete controls. Keep a logical tab sequence matching visual order.
- Maintain at least 44 × 44px touch targets, including overflow controls.
- Translate labels and accessible status descriptions through the existing i18n system.
- Apply only a short hover lift and subtle pressed response. Honor `prefers-reduced-motion` by removing movement.
- Retain Discovery's real pending-review count and connection state when Discovery is present. Use semantic status tokens, expose a textual accessible description, and avoid obscuring the illustration or label. Cap the visible count at `99+` as today. Add no decorative telemetry badges.

## 7. Theme contract

Use the existing runtime theme pipeline for the shelf, raised tile, icon materials, labels, focus, and status indicators. The amber appearance is the active Gruvbox reference, not a mandatory brand palette.

Relevant existing tokens include `--color-bg`, `--color-surface`, `--color-surface-alt`, `--color-border`, `--color-text`, `--color-text-muted`, `--color-primary`, `--color-primary-hover`, `--color-primary-fg`, `--color-info`, and semantic status colors. Component-scoped material variables may derive from them; add no independently selected dock palette.

Verify the icons against light, dark, preset, custom, and automatic theme changes. Labels need at least 4.5:1 contrast; meaningful focus/selection boundaries need 3:1 against adjacent surfaces. Color is supplementary to the underline, shape, and text. Keep a bounded surface and recognizable geometry when shadows, blur, or gradients are unavailable.

## 8. Implementation boundaries and sequence

| File or area | Responsibility |
| --- | --- |
| `apps/frontend/src/components/MacOSDOCK.jsx` | Dock composition, fixed Map anchor, route state, responsive projection, reveal/focus behavior, and navigator opener prop. Keep the existing component boundary initially. |
| `apps/frontend/src/components/navigation/DockArtwork.jsx` (proposed) | Complete local illustrated SVG family keyed by registry ID; unique gradient IDs and theme-aware materials. |
| `apps/frontend/src/styles/dock.css` (proposed) | Scoped shelf/icon/label/responsive/motion styles. Remove the superseded dock selectors from `styles/main.css` after integration. |
| `apps/frontend/src/data/navigation.js` | Continue owning destinations, visibility, and persisted membership resolution. Add only a focused pure layout helper if needed by both dock and settings preview. |
| `apps/frontend/src/components/settings/DockSettings.jsx` | Fixed Map explanation, shortcut membership/reorder UI, and accurate composition preview. Existing persistence path. |
| `apps/frontend/src/App.jsx` | Pass the existing navigator opener and relevant open-state information to the dock. Preserve the single overlay. |
| Existing dock/navigation tests and `apps/frontend/e2e/navigation.spec.ts` | Membership compatibility, current route, focus, overflow, theme, and real navigation coverage. |
| `docs/settings.md` | Explain the fixed Map anchor, configurable shortcut order, mobile projection, and All pages access. |

Implementation sequence:

1. Capture the approved version-4 dock as a visual reference; inventory all registered destinations and complete the illustrated SVG family.
2. Add the scoped styles and dock composition against existing routes/settings. Verify icon materials and proportions in both light and dark themes.
3. Implement the shared layout projection, update DockSettings, and preserve legacy settings behavior apart from the explicit fixed Map rule.
4. Wire All pages into the existing navigator. Finish focus-aware reveal, route indicators, badges, and responsive overflow/content clearance.
5. Run the focused automated and browser checks below, update user-facing settings documentation, and remove the superseded dock styling/motion.

Preserve concurrent map changes. No header redesign, navigator redesign, new graph engine, new preference store, or backend work is part of this implementation.

## 9. Acceptance and verification

### Visual acceptance

- [ ] The shelf, raised Map tile, and six reference illustrations match approved version 4 at desktop scale.
- [ ] Every optional dock destination has an illustration from the same family; no mixed stock-icon fallback remains.
- [ ] Map uses the connected-block topology mark. No globe, orbit, halo, heavy glow, or rotation returns.
- [ ] Labels remain visible and legible; current-page selection is distinguishable from Map's permanent emphasis.
- [ ] Light/dark/custom themes, enlarged text, long labels, and reduced motion retain usable composition.
- [ ] A dense configured dock fits the viewport; keyboard and pointer users can reach overflow shortcuts.
- [ ] The raised tile and dock do not block real map controls or bottom-of-page actions.

### Behavior and compatibility

- [ ] Real route links navigate without page reloads; Map remains one click away from other pages.
- [ ] All pages, header Navigate, and Ctrl/Cmd+K open one existing navigator instance.
- [ ] Navigator dismissal returns focus to the dock opener and keeps it visible.
- [ ] Saved and legacy shortcut membership, deduplication, permission filtering, and relative order are preserved.
- [ ] Fixed Map appears exactly once for orders containing, omitting, or repeating `/map`, including an empty order.
- [ ] Unknown/prototype-key stored paths cannot crash the dock.
- [ ] Viewer/editor/admin visibility matches the registered guards; no unauthorized shortcuts leak through overflow or mobile projection.
- [ ] Parent/detail matching and separate Logs/Audit Log/Parked Messages selection remain correct.
- [ ] Discovery counts and connection states remain truthful and accessible.
- [ ] Desktop reveal/hide works with pointer and keyboard; mobile navigation uses the defined saved-shortcut projection.
- [ ] Settings save failures preserve edits and report failure; loading settings does not rewrite persisted data.

Extend `dock-membership.test.jsx`, `dock-settings.test.jsx`, navigator wiring tests, and the existing navigation E2E suite around these changed contracts. Add tests for the pure layout projection and SVG destination coverage, rather than tests that merely duplicate CSS.

Run focused Vitest tests, the navigation Playwright suite, and the applicable frontend lint/build checks during implementation. Use browser screenshots at desktop, tablet, and mobile widths to assess geometry and theme behavior. Record the actual commands and results in this document when implementation lands; do not treat the standalone prototype checks as production validation.

## 10. Current evidence and delivery status

The version-4 standalone prototype was checked in Chromium at 1440 × 900 and 390 × 844. Checks exercised page selection, page filtering, Escape dismissal, light-theme switching, reduced motion, and mobile horizontal overflow; screenshots were visually inspected. The draft was refetched after import to confirm the refined Map artwork and shelf finish were saved.

Those checks establish the design reference and prototype behavior only. The application still renders the existing `MacOSDOCK.jsx`. Production implementation, complete optional-destination artwork, real navigator integration, and the acceptance checks above remain pending. This plan does not authorize deploying or publishing application changes.
