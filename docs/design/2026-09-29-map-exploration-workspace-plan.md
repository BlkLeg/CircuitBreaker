# Exploration topology workspace implementation plan

Date: 2026-09-29  
Status: design selected; implementation pending. This request authorizes planning,
not application or backend changes.

## Design of record

- [Exploration workspace, version 6](https://p.superdesign.dev/draft/9d6e2496-9e84-47fb-a273-df6b88c698f8).
- [Shared canvas](https://superdesign.dev/teams/4281dc54-7c08-491e-9c06-483e758fa325/projects/a44eac63-f5b5-4185-b1c9-18d768ecbc40).
- [Approved native map console and connection walkthrough](2026-09-29-map-console-and-connection-walkthrough.md).
- Companion: [Operations workspace plan](2026-09-29-map-operations-workspace-plan.md).

The selected design supersedes Exploration versions 1–2. The prototype uses the
approved native-map screenshot, illustrative inventory and telemetry, and local
controls. Search and scope controls do not establish production graph filtering,
renderer parity, persistence, accessibility or performance. Preview links show
the draft's current head; version 6 is the selected baseline recorded here.

## Outcome and scope

An operator can find an asset on the active map, focus its connected neighborhood,
inspect a relationship, and restore the full map without losing their layout or
selection. Exploration is a mode of the existing map console, not a new inventory
page, graph engine or global search experience.

Keep the map dominant. Use a compact command strip and scope breadcrumb, a narrow
search/scope rail, a right entity/relationship inspector, and a full-width lower
Relationships / Telemetry workbench. Relationships is the default lower tab.
The 1810×1023 reference uses approximately 236px and 310px side rails and a 264px
workbench; adapt these sizes to preserve usable map space and readable text.

## Shared console foundation

Implement this foundation once for both modes, following the approved console
record. Proposed filenames below describe responsibilities, not existing APIs.
All new frontend modules and tests use TypeScript/TSX under
`apps/frontend/src/features/map/`. Integrate incrementally into the existing JSX.

| Proposed module | Responsibility |
| --- | --- |
| `components/console/MapConsole.tsx` | Command area, mode-specific left rail, native canvas, inspector and lower workbench. Explicit pane placement and responsive layout. |
| `hooks/useMapConsoleState.ts` | Mode, pane visibility/collapse, active tabs, prior configuration for restore. Reuse the workspace's canonical selection and viewport. |
| `components/console/SelectedAssetInspector.tsx` | Shared identity, health, freshness, readings and relationships, with mode-specific tabs/actions. |
| `components/console/TelemetryWorkbench.tsx` | Shared three-pane analysis surface and synchronized cursor. |
| `model/consoleTelemetry.ts` | Typed adapters for available agent, monitor and generic entity readings/history. |

Reuse `MapWorkspace.jsx`, `useMapDocument.js`, `MapCanvas.jsx`, `CustomNode.jsx`,
`CustomEdge.jsx`, `Sidebar.jsx`, `TelemetrySidebar.jsx`, `EdgeInspector.jsx`,
`graphAdapter.js`, `layoutCodec.js`, existing streams/polling and theme resolution.
Reuse the existing relationship helpers and canonical connection rules. Preserve
all existing map actions and the secondary Connection Walkthrough entry point.
The walkthrough is separately planned and is not a prerequisite for read-only
Exploration delivery.

The console must preserve native silhouettes, branded/vendor artwork, user icons,
badges, handles, annotations, boundaries and edge overrides. Equipment tiles
remain exclusive to the structured walkthrough. Do not ship screenshot surfaces,
CDN scripts, standalone prototype HTML or uploaded prototype URLs as production UI.

Use the active theme's semantic tokens, system sans and system monospace, compact
rectangular controls, quiet dividers and precise data alignment. No new fonts,
decorative gradients, floating pill shelves, radar, scanlines, attention-seeking
motion or invented security indicators. Protect existing node styling rather than
adding decorative effects to the console. Preserve the actual logo and navigator.

## Search, graph scope and selection

1. Search only the active map's authorized, loaded entity graph. Match supported
   name, address and entity-type fields using normalized text. Include aliases
   only when authoritative data supplies them. Do not query global inventory or
   imply entities omitted by server-side environment/type filters were searched.
2. Define the base graph after existing environment/type/tag/role filters. Display
   this scope and loaded totals. Search results may identify a base-graph asset
   outside the current neighborhood; selecting it makes it the focus root.
3. Keep the focus root independent of transient entity/edge inspection. Selecting
   a relationship or browsing a neighbor must not silently move the root. Offer
   an explicit Focus here action when changing the root from the inspector.
4. All / 1 hop / 2 hops means bounded graph adjacency, not network packet routing
   or directed dependency impact. Traverse accepted domain relationships in both
   directions for neighborhood membership; display canonical edge direction and
   semantics separately. Exclude decorative lines, annotations and boundaries.
5. Apply relationship filters before traversal. Apply entity visibility filters
   after traversal so hiding an intermediate entity does not silently redefine
   graph distance. Explain this behavior beside scope controls. Keep the root
   visible and show when it is retained outside an entity filter.
6. Use an indexed, visited-set breadth-first traversal bounded to two hops;
   cycles, parallel edges, self-links and dangling endpoints cannot duplicate
   entities or cause unbounded traversal. Count unique domain entities and
   actual included relationships, excluding decorative/grouping nodes.
7. Make In scope / Total in filtered map counts exact. If context is dimmed rather
   than hidden, label counts as In scope, not Visible. Provide a consistent
   dimmed-context presentation with textual scope cues and readable labels.
8. Selecting a search result explicitly centers that asset once. Scope changes,
   live updates, inspection and console toggles preserve viewport and positions.
   Restore full map clears Exploration's root/hop/entity/relationship scope and
   restores the viewport captured on entering focus; retain base map filters and
   current valid selection. Explicit Fit remains a separate user action.

Add one composed visibility/presentation predicate to the existing filter path.
`useMapFilters.js` currently writes node/edge visibility; a second independent
effect must not overwrite its decisions. Keep canonical graph/document data
intact and derive presentation without deleting entities or persisting scope as
layout changes. Group containers must not leave misleading empty boundaries.

On map switch, clear map-local focus/search/edge selection, cancel prior requests
and use the destination map's normal viewport restoration. On removal of the
root, exit focus with a concise notice. On removal of an inspected neighbor or
edge, clear only the invalid inspection. Newly arriving entities update scope
membership without automatic refit. Renderer switching retains supported scope
and identity; capability differences must be explicit.

## Entity and relationship inspection

Entity identity, health source, freshness, readings and relationships follow the
same stable entity identity in the map, inspector and workbench. Resolve current
data by ID instead of retaining a stale copied node object. Type plus entity ID
is the identity boundary where numeric IDs can overlap between collections.

Relationship rows and the lower table show source, target, semantic relationship,
canonical connection type and configured capacity where actually supported.
Selecting a row highlights the native edge and opens its inspector; keyboard
activation has the same result. Respect existing endpoint rules and permissions.
Do not manufacture a physical connection type or capacity for ownership edges.
Use Unavailable / Not applicable appropriately. Capacity is configuration, not
measured utilization; particles are not observed traffic direction.

Reuse `EdgeInspector.jsx` for existing anchors and bend reset. Mutation controls
remain permission-aware and use established APIs. Exploration adds no arbitrary
relationship-name editor, per-link throughput API, removal workflow or inferred
provenance. Source/update timestamps appear only when returned by real data.

## Telemetry and console state

Use the approved three adjoining panes: host/source/freshness left, synchronized
CPU/memory middle, RX/TX right. Middle chart grids and traces span divider to
divider. Percent scales remain 0–100 with numeric ticks; network rates share an
explicit appropriate scale. Position samples by timestamps, preserve gaps and
show range, source, cadence/count, last/min/max and exact cursor values. Share
pointer and keyboard time inspection. Thresholds require real configuration.

Reuse the analysis standard in `AgentTelemetryTab.jsx` and monitor latency
history. Generic entity telemetry returns at most 20 recent metric rows total;
it is not a complete history for each metric. A missing source or short series
shows an honest unavailable/insufficient-history state. Cancel or ignore stale
responses after selection/source/map changes; never splice histories.

Inspector and workbench collapse/hide independently. Hidden means zero reserved
space. Hide Console hides operational chrome and panes, retains a reachable
restore control and restores the previous mode, tabs and pane configuration.
Fullscreen preserves this behavior. These actions do not mark the document dirty,
trigger relayout/refit, reset selection or interrupt live data. Switching to
Operations retains shared asset selection, document and viewport; Exploration
scope is inactive there and restored when returning to the same map. Mode and
pane preferences are presentation state, not a new backend persistence layer.

## Delivery packages

| Package | Work | Exit condition |
| --- | --- | --- |
| E0 | Confirm current integration points, renderer capabilities, identity mappings and available source histories. Freeze prototype HTML/screenshots locally before implementation. | Capability matrix and source contracts documented; no assumed APIs. |
| E1 | Implement/reuse shared console foundation and selected-asset/telemetry adapters. | Native map and original actions remain intact; panes reclaim space and preserve state in both modes. |
| E2 | Add `model/explorationScope.ts`, `hooks/useMapExploration.ts` and `components/console/ExplorationRail.tsx`. Compose with existing filters. | Search, explicit focus, bounded adjacency, exact counts and restore work against real graph data. |
| E3 | Connect entity/relationship inspector and relationship table to native selection and existing edge controls. | Identity, semantics, direction, capacity and permissions remain consistent. |
| E4 | Wire honest telemetry and request cancellation; validate renderer switching and live graph changes. | No stale-source contamination or lost layout/viewport. |
| E5 | Accessibility, theme, responsive and performance verification; update operator docs. | Release acceptance below passes with evidence. |

E1 is shared with Operations O1; implement it once. E2–E3 can proceed while the
Operations change-feed contract is resolved. No new backend endpoint or schema
is required for local search/adjacency over the loaded graph. Any expansion to
unloaded topology requires separately specified authorization and pagination.

## Acceptance and verification

- [ ] Meaningful unit fixtures cover cycles, two-hop boundaries, missing endpoints,
  parallel relationships, colliding cross-type IDs, filter composition and counts.
- [ ] Browser checks cover search/focus, edge selection, root removal, live arrivals,
  map/renderer switching, restore full map and independent pane/fullscreen states.
- [ ] Canonical positions, viewport, annotations, overrides, saved filters and dirty
  state survive console-only interactions. Existing edit/save tools retain parity.
- [ ] Delayed telemetry for a previous asset/source cannot populate the current
  inspector or charts; gaps, short histories and unknown values remain truthful.
- [ ] Keyboard navigation, focus return, labeled tabs, table interaction, enlarged
  text, reduced motion and responsive drawers/local table scrolling work.
- [ ] Dark/light/preset/custom/auto theme coverage uses actual theme resolution.
- [ ] Measure search/scope and update cost on representative graph sizes; record
  dataset sizes and timings. Test React Flow and Sigma separately; do not infer
  performance or parity from screenshots.
- [ ] TypeScript checking, relevant frontend tests and production build pass.
  Backend verification is required only if implementation changes backend behavior.
- [ ] Remove prototype fixtures from production paths; document mode/scope behavior
  and any genuine renderer limitations before marking implementation complete.

## Planning evidence and limits

The selected desktop draft was visually reviewed; its real logo loaded, inspector
and workbench tabs worked, and console restoration retained a hidden inspector
without browser errors. Its map is a reference image and neighborhood controls
are illustrative. Production scope, map focus, graph highlighting, responsive
behavior and calibrated telemetry remain implementation work. See the
[capability audit](../../plans/v0.5.0-map-feature-audit.md) for existing behavior.
