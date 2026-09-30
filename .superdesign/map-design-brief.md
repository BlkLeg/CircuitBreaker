# Circuit Breaker map — enterprise NOC/SOC visual direction

The map is the main product experience for a self-hosted homelab operations app.
The user explicitly rejected the first two drafts as too modest, redundant with
existing capabilities, and visually basic. The CPU chart was especially weak.
The latest user correction preserves the mature map identity. The original
March screenshot was stale. Updated screenshots are on the project canvas.
Current node shapes, branded SVGs, vendor imagery, badges, handles and status
treatment are protected. The upgrade targets the surrounding console and a new
structured connection walkthrough, not a replacement node renderer.

## Visual composition

- The familiar topology remains the protagonist. Match the updated screenshots
  and current CustomNode implementation, including device silhouettes and real
  brand imagery. Never replace the primary map nodes with equipment cards.
- Use a disciplined NOC/SOC instrument-panel composition: strong alignment,
  crisp dividers, compact data hierarchy, professional typography, small precise
  labels, clear focal points and meaningful semantic accents.
- Rectangular equipment tiles belong ONLY to the structured connection
  walkthrough, where users choose endpoints, define supported relationships and
  connection types, review a structured diagram, and press **Present Layout**.
  The result appears on the native map using existing node shapes and artwork.
- Region headers expose identity, subnet or role, and scoped counts. Region
  borders are subtle; connectors stay readable across region boundaries.
- Create visible link hierarchy: stronger backbone paths, quieter dependencies,
  dashed wireless/tunnel semantics, sharp capacity labels and precise endpoints.
  Preserve user placement and editing behavior in implementation.
- Compact command strip groups existing map switcher/filter/layout/drawing/save
  actions. A restrained situation strip exposes current health and existing
  security/freshness signals. Operational facts outrank equally weighted buttons.
- A narrow inspector summarizes selected identity, health sources, last sample,
  key readings and relationships. It is independently collapsible and hideable.
- A dockable lower analysis drawer gives the selected entity enough horizontal
  room for real charts. Expand, collapse, and hide are distinct actions. Hidden
  means zero reserved space. A small restore control remains available on the
  canvas. Do not replace the workbench with a miniature decorative sparkline.
- A **Hide Console** action hides inspector, telemetry drawer and console
  chrome together. Fullscreen has a clean-map state and an obvious restore/exit
  control. The graph, viewport, selection and live updates survive every toggle.

## Connection walkthrough and handoff

- The structured view is an optional workflow from the map, not its default
  replacement. Keep the map's entity IDs, icons, shapes and metadata intact.
- Select source and target; explain physical connection type separately from
  relationship semantics. Only supported endpoint/relationship combinations
  are offered. Show pending, existing and invalid links distinctly.
- Review endpoint names, connection type, relationship and capacity before the
  user presses **Present Layout**. Preview positions without modifying the live
  saved map during draft editing.
- Present Layout applies the reviewed graph/positions to the active map and
  returns to the native renderer. Preserve node artwork, shapes, annotations,
  existing user edge overrides and unaffected entities.
- Do not claim an atomic multi-relationship save: existing APIs persist links
  individually. Partial failures need an explicit retryable result and must not
  silently publish an incomplete layout or create duplicate links.
- Permission-aware editing, map identity, unsaved-change handling and stale
  entity checks are required. Do not promise destructive replacement or undo of
  persisted relationships without a corresponding data contract.

## Telemetry visualization standard

- At least two aligned real chart lanes with shared timestamp cursor: CPU and
  memory percent, plus paired RX/TX where the selected source supports history.
- CPU has labeled 0, 25, 50, 75, 100% ticks. Time ticks show actual elapsed time.
  Use a sharp, detailed sampled line with restrained area fill and a subtle grid.
- Show units, visible range, source, sample cadence/count, last value, min/max,
  selected timestamp and exact cursor values. CPU and load retain separate units.
- Show threshold bands only when thresholds are actually configured. Mock
  thresholds are marked illustrative. Percent scales are fixed; network rates
  have an explicit appropriate scale. Do not visually compare unlike units.
- Draw missing data as gaps, never smooth invented samples across missing time.
  Empty/short series show insufficient-history states; absent temperature says
  unavailable. Source changes must never splice unlike histories together.
- Use the established agent telemetry workbench as the quality floor. Map
  histories are source-dependent: agent history and monitor latency already
  exist; generic entity telemetry returns only 20 recent metric rows total.
- Draft traces and values are clearly labeled illustrative data. No fictional
  incident correlation, measured link utilization, traffic direction or replay.

## Identity, theme, and motion

- Follow the user's active theme using existing semantic CSS tokens. The draft
  demonstrates Gruvbox, not a hardcoded production palette. No new fonts.
- System sans for UI; ui-monospace / SFMono-Regular / Menlo / Consolas for data.
  Never import JetBrains, Inter, or decorative typography.
- Keep the real Circuit Breaker logo in the shared header. Preserve the current
  shell/navigator so this work remains about the map.
- Enterprise polish comes from geometry, routing, precision, typography and
  composition. Avoid oversized marketing cards, heavy bloom, fake radar,
  decorative scanlines and meaningless continuous animation.
- Show meaningful updates briefly; preserve positions and selection; provide
  reduced motion and textual health meaning.
- New application implementations and tests must be TypeScript / TSX.
