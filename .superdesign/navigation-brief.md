# Global page navigator — design proposal

Status: approved, with a subsequent user decision to replace BOTH the top-right Routes dropdown and CommandPalette. Preserve the dock. The authoritative implementation plan is [Unified navigator](../docs/design/approved-ui/01-unified-navigator.md); this brief also records the original canvas concept. No application/backend implementation is performed by this document update.

## Direction

A contained navigator opens from a compact **Navigate** button in the existing header or Ctrl/Cmd+K. It combines page browsing with existing asset search and account actions. Preserve the approved SOC hierarchy, official logo, readable labels, and immediate local feedback, but resolve every surface/status/accent through the active theme. Gruvbox is the reference appearance only. Keep the current page visible behind the panel. On narrow screens, the same navigator becomes a full-height dialog rather than introducing permanent navigation furniture.

The reference context is the Inventory Workspace canvas draft. Its page content and seven-button dock are preserved. This is a shared-shell concept, not a second redesign of that page or of the map.

## Information architecture

Retain the current five groups from `apps/frontend/src/data/navigation.js`:

| Group | Existing destinations |
| --- | --- |
| Acquire | Discovery, Agents |
| Inventory | Hardware, Compute, Services, Storage, External Nodes, IPAM, Other Assets |
| Observe | Map, Monitors, Intel, Privacy |
| Govern | Users, Access Tokens, Certificates, Notifications, Logs, Audit Log |
| System | Settings, Docs |

The administrator view contains 21 top-level destinations. Do not populate the page browser with redirects, authentication lifecycle routes, every individual asset, or deferred tenant pages.

## Interaction contract

- **All pages:** grouped overview, short descriptions, category filters, and a visible current-page indicator. Category filters do not reorder the source registry.
- **Search:** local, immediate matching on page names, descriptions, aliases, eligible actions, and settings sections, combined with debounced authenticated asset search. Search spans all groups even after selecting a category. No network round trip is needed for page discovery; remote asset loading/failure must not block local results. Preserve Login/Profile actions and actual entity activation when retiring CommandPalette.
- **Pinned pages:** personal shortcuts within the navigator. Pin/unpin has immediate feedback and never alters dock configuration. Ship per-user persistence only once its storage and permissions are defined; this prototype keeps pins in memory.
- **Recent pages:** a bounded personal list, newest first, deduplicated by destination. Revalidate visibility before rendering or activating stored destinations. The prototype demonstrates six entries maximum and does not persist them.
- **Settings shortcuts:** the prototype inherited `?section=` entries from the old palette. Current SettingsPage actually consumes `?tab=`. Correct the migration using SETTINGS_TABS and shared allowed-tab rules, including non-admin restrictions. Do not carry forward stale Experimental links or pretend unsupported field-level jumps work. These remain children of Settings, not new top-level pages.
- **Keyboard:** focus search on open; Up/Down moves through results; Enter activates; Escape closes and restores the actual opener. Tab stays inside the modal. Ctrl/Cmd+K opens this same unified navigator and replaces the old palette shortcut handler. Optional `G` then `G` must respect text entry, composition, and existing modal/shortcut rules.
- **Dismissal:** close button, Escape, and outside click. Choosing a real destination should close the panel and use normal router behavior. In the canvas, page selection is explicitly simulated and leaves the underlying page unchanged.
- **Empty results:** explain what is searched, offer examples and a reset. Do not point users to a second palette. Distinguish zero matches from remote asset-search failure; local route results do not need a network loading state.
- **Accessibility:** native modal semantics, visible focus, named buttons, pressed states for pin/filter controls, text alongside icons, current-page semantics, and reduced-motion support. Keep touch pin targets at least 40px and route rows at least 48px in the mobile layout.

## Where the seven workflows could live

The canvas includes a separate **Planned workflows** view with seven links to the previously created design previews. This is review-only scaffolding, not a proposed permanent production tab and not a claim that the features exist.

| Workflow | Proposed home |
| --- | --- |
| Inventory Transfer | Settings / Data management |
| Docker Discovery | Discovery / Docker sources |
| Vulnerability Assessment | Intel / Vulnerabilities |
| Notification Delivery | Notifications / Delivery |
| Dependency Impact | Map / Selected asset |
| Inventory Workspace | Existing Inventory entity pages |
| Metric Alert Rules | Monitors / Alert rules |

For context-dependent tools such as dependency impact, global navigation should lead to the parent page and help users select an asset; it must not invent an asset-specific destination without a selected asset. Enroll-agent and detail flows similarly belong to their parent workspaces or meaningful recent locations.

## Expansion without duplicated navigation logic

Keep `NAV_GROUPS` / `NAV_ITEMS_FLAT` as the source for the unified navigator, dock, and dock preferences. Extend shared destination metadata deliberately with stable IDs, descriptions, aliases, and optional children. Consolidate settings deep-link metadata currently embedded in CommandPalette with the actual settings tab metadata before retiring CommandPalette; do not copy a separate production list.

Route authorization remains owned by `data/routeGuards.js`. Filter routes, children, pins, recents, and search results through the same effective visibility rules. A hidden navigation item is not API authorization. Children inherit the parent gate and may tighten it, never loosen it. The canvas uses an administrator sample; it does not implement authentication or verify RBAC.

New features should first become children or contextual tools under an existing destination. Add a top-level page only when it represents a distinct workspace. Only registered, enabled, authorized destinations enter production navigation. No misleading clickable “coming soon” destinations. Avoid converting dynamic telemetry status into navigation badges; this panel is for moving around, not a second monitoring dashboard.

## Review and later implementation checks

The grouping, layout, and eight designs are approved. Implement the unified search scope and theme requirements in the approved plan set. Keep all current route labels and access expectations honest. Implementation needs route-registry consistency tests, editor/viewer/admin visibility coverage, permission-change cleanup of pins/recents, real router/entity/action activation, keyboard/focus tests, and cross-browser/theme responsive testing.

Prototype source: `.superdesign/tmp/08-global-page-navigator.html` (ignored scratch artifact). Durable canvas IDs and source fingerprints are recorded in `.superdesign/resume.json` after import. No application or backend files are changed by this design work.
