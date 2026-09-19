# Map Page Refactor Analysis

## Executive Summary

The best split is a feature-oriented map module with a thin route page, a central document controller, domain-specific hooks, and renderer-independent presentation components.

The existing refactor is heading in that direction, but it currently moves some complexity into very wide hooks rather than establishing clear ownership. The next refactor should split around a canonical **map document** and stable command interfaces, not merely around JSX size. This will provide clean extension points for new node types, drawing tools, persistence fields, renderers, and live event sources.

This assessment was performed read-only. No application files were changed as part of the analysis, and the test suite was not run.

## Current Assessment

`apps/frontend/src/pages/MapPage.jsx` is 3,025 lines and currently contains approximately:

- 50 `useState` calls
- 26 effects
- 39 callbacks
- 70 imports
- Canvas state and React Flow integration
- Layout loading, saving, and auto-placement
- Filtering and preference persistence
- Live topology subscriptions
- Node, edge, monitoring, Proxmox, LLDP, and quick-create commands
- Boundary, visual-line, and label editing
- Selection, menus, dialogs, fullscreen, and banners
- Nearly the entire page presentation

Several good extractions already exist, including `useMapLayout`, `useMapDataLoad`, `useMapEdgeInteractions`, `useMapBoundaryInteractions`, and `MapCanvasOverlays`. However, some boundaries remain too porous:

- `useMapDataLoad.js` accepts more than 30 setters, refs, and values.
- `useMapBoundaryInteractions.js` has a similarly broad contract.
- `MapCanvasOverlays.jsx` receives about 30 props.
- The page test mocks almost the entire map subsystem before it can render `MapPage`.

These are signs that code has been relocated, but state ownership has not yet been fully separated.

## Recommended Architecture

The map is large and important enough to justify a self-contained vertical feature module:

```text
src/
├── pages/
│   └── MapPage.jsx                  route loading and providers only
└── features/map/
    ├── MapWorkspace.jsx             compose controllers and views
    ├── model/
    │   ├── graphAdapter.js          API topology → canonical map graph
    │   ├── layoutCodec.js           load/save/migrate layout documents
    │   ├── visibility.js            one combined visibility predicate
    │   └── mapActions.js            action identifiers and capabilities
    ├── hooks/
    │   ├── useMapDocument.js        nodes, edges, annotations, dirty refs
    │   ├── useMapPersistence.js     load, save, auto-place, request ordering
    │   ├── useMapFilters.js         environments, tags, types, saved filters
    │   ├── useMapEditorUi.js        selection, active tool, menus, dialogs
    │   ├── useMapLiveSync.js        topology, telemetry, monitor, discovery
    │   ├── useMapNodeCommands.js    action routing
    │   └── useMapAnnotations.js     boundaries, labels, visual lines
    ├── components/
    │   ├── MapHeader.jsx
    │   ├── MapFilterBar.jsx
    │   ├── MapCanvas.jsx
    │   ├── MapStatusBanners.jsx
    │   ├── BoundaryInspector.jsx
    │   ├── EdgeInspector.jsx
    │   └── MapDialogs.jsx
    └── renderers/
        ├── ReactFlowRenderer.jsx
        └── SigmaRenderer.jsx
```

Existing map components can move into this feature gradually. Compatibility re-exports can prevent a repository-wide import rewrite during the initial refactor.

### Ownership Boundaries

| Owner | State or responsibility |
| --- | --- |
| `MapPage` | Map-list loading, active-map selection, and keyed providers |
| `useMapDocument` | Nodes, edges, edge overrides, boundaries, labels, visual lines, and dirty state |
| `useMapPersistence` | Fetching, layout restoration, serialization, saving, and auto-placement |
| `useMapFilters` | Environment, tag, entity type, hardware role, and default-filter persistence |
| `useMapEditorUi` | Active drawing tool, selection, menus, dialogs, and fullscreen |
| `useMapLiveSync` | WebSocket events and polling fallback |
| Command hooks | Entity mutations and refresh or optimistic-update policy |
| Renderer | Drawing only; renderers should not fetch topology data |

The durable layout document and ephemeral editor UI should not share one reducer. Nodes move frequently, so putting everything in one broad React context would cause unnecessary rerenders.

## Mapping the Current File to the Proposed Split

- Lines 146–380: document initialization and live synchronization
  - Move to `useMapDocument` and `useMapLiveSync`.
- Lines 381–718: environment, type, tag, and role filters
  - Move to `useMapFilters` and `MapFilterBar`.
- Lines 733–839: fetch, placement, and persistence wiring
  - Move to `useMapPersistence`.
- Lines 843–1415: node and entity workflows
  - Move to command hooks and an action registry.
- Lines 1416–1770: selection, derived details, annotations, and edge handling
  - Move to `useMapEditorUi`, `useMapAnnotations`, and the existing edge hooks.
- Lines 1784–2983: presentation
  - Move to `MapHeader`, `MapCanvas`, inspectors, banners, and dialogs.
- Lines 2985 onward: route shell
  - Keep in `MapPage.jsx`.

A reasonable endpoint is a 40–80-line `MapPage.jsx` and a roughly 300–500-line `MapWorkspace.jsx`.

## Safe Extraction Order

### 1. Extract Presentation-Only Sections

Move the header, status banners, boundary inspector, edge inspector, quick-action dialog, and dialog composition without altering their logic or inline styles.

This removes hundreds of lines with minimal behavioral risk. Styling cleanup should remain a separate change so visual regressions are not mixed with structural changes.

### 2. Introduce `useMapEditorUi`

The current Escape handler resets many independent fields at once. A reducer can represent mutually exclusive modes such as:

- Idle
- Drawing a boundary
- Drawing a visual line
- Editing a boundary
- Editing a label
- Choosing a connection type

This prevents future tools from adding more invalid boolean combinations. Events such as `CANCEL_ACTIVE_TOOL`, `SELECT_NODE`, `OPEN_DIALOG`, and `CLOSE_ALL_TRANSIENT_UI` can replace long sequences of setter calls.

This reducer should own only transient editor UI. It should not own nodes, edges, or other high-frequency document state.

### 3. Extract Filters as One Unit

Keep query inputs and client-side visibility together. Use one combined visibility calculation instead of independent effects writing `node.hidden`.

The combined visibility rule should account for:

- Server-side environment filtering
- Included entity types
- Tag search
- Hardware role
- Renderer-specific limitations, if any

### 4. Extract Node Workflows

Create a small command router backed by separate handlers for:

- Entity alias, status, icon, role, and deletion
- Monitoring
- Proxmox operations
- LLDP and discovery
- Related-entity quick creation

Context-menu action strings should be exported constants rather than an indefinitely growing `if/else` chain. Unknown actions should fail explicitly instead of displaying a generic success-like message.

### 5. Separate Topology Transformation from Persistence

Break `useMapDataLoad` into:

1. A pure topology adapter.
2. A versioned layout codec.
3. An asynchronous persistence hook.
4. An auto-placement coordinator.

The persistence hook should consume a document interface instead of dozens of individual setters and refs.

### 6. Establish the Renderer Boundary

Both React Flow and Sigma should receive the same canonical graph, filters, active map, and applicable commands. A renderer should not own API fetching.

This separation allows future changes to React Flow, Sigma, or another WebGL renderer without duplicating topology-loading and filtering behavior.

### 7. Relocate Existing Map Files

Move the established components, hooks, constants, and model helpers into `features/map` only after their ownership boundaries stabilize.

Moving paths and changing behavior simultaneously would make regression diagnosis harder. Temporary compatibility re-exports are preferable to a single repository-wide import rewrite.

## Existing Risks to Characterize Before Refactoring

The following current behaviors should be covered by tests before or during extraction.

### Node Deletion Uses the Wrong `Map` Access

`ENTITY_API_DELETE` is declared as a JavaScript `Map` in `components/map/mapConstants.js`, but `useMapMutations.js` accesses it with bracket syntax:

```js
ENTITY_API_DELETE[targetNode.originalType]
```

and:

```js
ENTITY_API_DELETE[deleteConflictModal.nodeType]
```

Both accesses should use `.get(...)`. As written, supported node types appear unable to resolve their delete function.

### Tag and Hardware-Role Filters Overwrite One Another

The tag-filter effect writes `hidden` for every node. The hardware-role effect later rewrites `hidden` for hardware nodes using only the role condition.

Consequences include:

- Changing the role can unhide hardware excluded by the tag filter.
- Changing the tag can unhide hardware excluded by the role filter.
- The final result depends on which effect ran most recently.

A single visibility predicate eliminates this ordering dependency.

### Cloud View Has Competing Update Paths

Toggling Cloud View directly transforms the current nodes. The same toggle also changes the identity of `fetchData`, causing the data-fetch effect to run again.

This creates avoidable double-transformation and request-ordering risk. Cloud View should either be a derived renderer projection or an explicit document transformation, not both.

### Topology Requests Can Resolve Out of Order

Topology requests have no cancellation or request-generation guard. Rapid changes to the active map, environment, included types, or Cloud View can allow an older response to replace newer state.

`useMapPersistence` should use an `AbortController` where supported and a monotonically increasing request generation to reject stale results.

### Sigma Does Not Share the Active Map Document

`SigmaMap` fetches topology independently and does not receive the active `mapId`. It can therefore display data inconsistent with:

- The selected map
- React Flow
- Current saved positions
- Annotations and overlays
- Map-specific entity membership

Sigma should become a renderer of the canonical map document rather than a nested data-owning page.

### Layout Persistence Has No Explicit Schema Version

Layout persistence handles a legacy flat node-position map and the current structured object, but it has no explicit version marker.

The saved document should gain a `schemaVersion`, for example:

```js
{
  schemaVersion: 2,
  nodes: {},
  nodeShapes: {},
  edges: {},
  boundaries: [],
  labels: [],
  visualLines: [],
  view: {
    edgeMode: 'smoothstep',
    edgeLabelVisible: true,
    nodeSpacing: 1,
    groupBy: 'none'
  }
}
```

`layoutCodec.js` should be the only module that knows about stored layout versions and migrations.

### Module Responsibilities Are Inconsistent

Examples include:

- `mapDataUtils.js` describes itself as pure but imports APIs and performs mutations.
- Entity API mutation registries live in a component constants file.
- `components/map/linkMutations.js` is an API command module rather than a component.
- Layout persistence parsing lives alongside geometry utilities.

Pure model code, API commands, React hooks, and presentation constants should live in separate modules.

### Existing Map Components Are Also Large

Refactoring `MapPage.jsx` should not hide the next set of maintenance hotspots:

- `Sidebar.jsx`: approximately 1,120 lines
- `TelemetrySidebar.jsx`: approximately 982 lines
- `ContextMenu.jsx`: approximately 905 lines
- `CustomNode.jsx`: approximately 680 lines
- `BulkQuickCreateModal.jsx`: approximately 631 lines
- `linkMutations.js`: approximately 572 lines
- `MapCanvasOverlays.jsx`: approximately 495 lines

These do not all need to be changed in the first pass, but the feature structure should give them logical places to split later.

## Regression Contract

Before substantive controller changes, add or preserve explicit coverage for the following behavior.

### Route and Map Switching

- Switching maps resets React Flow state through the keyed provider.
- The selected map ID reaches every topology request and renderer.
- Map-list loading failures remain recoverable.

### Nodes and Edges

- Structural edge changes emitted by React Flow remain rejected.
- Node clicks do not recompute edge anchors.
- Zero-distance drag operations do not modify edges.
- Actual drag operations preserve every edge.
- Connection creation, reconnection, type changes, bend points, and endpoint anchors round-trip.

### Persistence

- Legacy layouts still load.
- Current layouts round-trip without data loss.
- Positions, node shapes, edge overrides, boundaries, labels, visual lines, and view options are saved.
- Auto-generated Docker boundaries remain excluded from saved layouts.
- Auto-placement remains serialized and saves once per completed batch.

### Filters

- Environment, tag, type, and hardware-role filters compose correctly.
- Saved default filters restore without overriding subsequent user input.
- Late responses are ignored after switching filters or maps.

### Live Updates

- Topology events update only their affected nodes or edges.
- Existing edge overrides survive live edge additions.
- WebSocket pushes and polling do not fight over status.
- Polling remains disabled while a healthy live stream is connected.

### Editing and Permissions

- Read-only users cannot open editing workflows.
- Escape consistently cancels the active drawing or editing operation.
- Node deletion resolves the correct entity API.
- Unsupported commands fail explicitly.

### Renderer Parity

- React Flow and Sigma show the same active map and filters.
- Switching renderers does not issue a second independent topology request.
- Renderer changes do not discard unsaved document state.

## Approaches to Avoid

### A Single `useMapPage` God Hook

Moving the entire component body into one hook would reduce the page's line count without improving coupling, testing, or extension points.

### A Broad Map Context for All State

Node positions, viewport changes, telemetry, menus, and dialogs update at very different rates. A single context would cause broad rerenders and make dependencies less visible.

Use narrow hook contracts and component props. Context should be reserved for genuinely cross-cutting, stable values such as the existing edge callback and view-option contexts.

### Adding a New Global State Dependency During Extraction

The current problem does not require Redux, Zustand, or another store. React Flow state, focused reducers, refs for pointer interactions, and domain hooks are sufficient.

A state-library migration could be evaluated later, based on measured coordination or performance problems.

### Combining Structural Refactoring With Visual Redesign

Moving inline styles, redesigning controls, changing renderers, or altering interaction behavior in the same changeset would make regressions difficult to isolate.

The structural split should preserve visual output first. Styling and UX improvements can follow once ownership and tests are stable.

## Expected Outcome

After the refactor:

- `MapPage.jsx` is a small route shell.
- `MapWorkspace.jsx` visibly describes the page's major subsystems.
- Remote topology, persisted layout, and transient editor state have distinct ownership.
- Renderers consume the same canonical document.
- New actions are added through explicit command modules rather than a growing dispatcher.
- New saved fields are introduced through a versioned layout codec.
- Filters have one source of truth.
- Hooks expose cohesive objects instead of dozens of unrelated setter arguments.
- Unit tests target pure adapters and codecs, hook tests target workflows, and a smaller integration test validates composition.

This structure preserves the current product while creating a practical foundation for the map to remain the application's primary extensible workspace.
