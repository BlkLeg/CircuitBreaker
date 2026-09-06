# Circuit Breaker design system — infrastructure operations console

## Product and operator context

Circuit Breaker is a self-hosted infrastructure discovery, monitoring, topology, and operations product for homelabs and private networks. Operators move between an advanced interactive network map, agent fleets, monitor health, discovery jobs, inventory, security/privacy findings, logs, and settings. The agent detail page must feel like the focused inspection surface for a single machine: live, information-dense, calm under normal conditions, and unmistakable when conditions cross thresholds.

Target: `/agents/:id?tab=telemetry`. Preserve the existing page shell, header, agent identity, state banner, five tabs, readiness alerts, live metric semantics, history range, data tables, and settings. Improve the telemetry visualization layer so it has the situational-awareness and analytic density of a SOC/NOC dashboard without becoming theatrical or illegible.

## Visual foundation

- Keep the existing Gruvbox-derived dark identity. Use only design tokens already present in the app.
- Background: `#282828`; surfaces: `#3c3836`; raised heads: `#32302f`; borders: `#504945`.
- Primary/action/accent: amber `#fe8019`; hover `#d86d15`.
- State colors: danger `#fb4934`, warning `#d79921`, success `#b8bb26`, informational telemetry `#83a598`.
- Text: `#ebdbb2`; muted `#c8bfb0`.
- Do not introduce purple, blue-neon, pink, cyan-neon, gradients outside the existing subtle background, glassmorphism, heavy glow, or a replacement brand palette.
- Use the system sans stack for navigation and explanations. Use `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` for metrics, timestamps, axes, identifiers and table values.
- Radius remains 6px. Panels are bounded and compact, with low-elevation surfaces and thin borders. No oversized floating cards.

## Telemetry information design

- The top metric band should behave like an operational instrument panel, not eight independent marketing cards.
- Preserve all eight readings: CPU, memory, root disk, network receive, network transmit, temperature, load (1m), uptime.
- Group related metrics where useful: compute (CPU/load), memory, storage, network ingress/egress, thermal, uptime. Keep labels explicit and values immediately readable.
- Current value, status/threshold, compact trend, and comparison context should form one visual unit. Use subtle grid lines, axes/tick labels, last/min/max or directional delta only when they improve interpretation.
- History becomes the analytic focal point. Prefer a wide synchronized time-series workbench with a shared time axis and readable scale over several empty miniature boxes. Small-multiple lanes are acceptable when aligned to one time cursor and one time range.
- Network RX/TX should be paired in one comparison panel. CPU and load may be related but must retain separate labels and scales. Missing temperature remains explicitly “Unavailable”; never fabricate a trace.
- Use threshold bands/markers sparingly and only with the existing danger/warning colors. Normal telemetry uses `--color-info`; the primary amber is for focus, range selection, and operator action.
- Show freshness, cadence, sample count, agent-only/projected scope, and selected range in one compact context row near the analysis surface.
- Readiness and capability warnings remain prominent but should not dominate all subsequent data.
- Filesystems, disks, interfaces, temperatures, and Docker remain dense operational tables. They may receive compact status cells, progress bars, or inline micro-visuals but must remain scannable and exact.

## Interaction and motion

- Hover/cursor inspection should reveal exact timestamp and metric values across synchronized charts.
- Range choices remain 1h, 6h, 24h, 7d, 30d. A segmented control is preferred over a native select when space permits.
- Support keyboard focus and the app’s existing ARIA semantics.
- Animate only meaningful changes: threshold crossing, fresh sample arrival, or cursor transitions. Never animate every sample continuously.
- Respect `prefers-reduced-motion`; all information must survive without animation and without color alone.

## Layout and responsiveness

- Desktop target is the supplied 1912×983 view. The app header and detail header stay intact.
- Use a 12-column analysis grid or equivalent. The main history visualization should span most of the width; a narrow rail may hold health/freshness, thresholds, or live summaries.
- Avoid excess vertical scroll before the history view. The operator should see current readings and meaningful history in the first viewport.
- At tablet widths, collapse secondary context beneath the main chart. At narrow widths, stack metric groups, keep touch targets usable, and retain horizontal scrolling for dense data tables.

## Brand and shell invariants

- The global header has the real Circuit Breaker logo at left, brand text, central weather/time/date widgets, route and utility controls at right, plus the bottom route dock. Preserve those positions.
- Do not substitute initials, emoji, a generic logo, an invented SVG mark, or text alone for the supplied logo.
- Preserve the existing top-level dark shell, faint technical grid, amber focus language, and compact density so the telemetry upgrade feels native beside the map.
