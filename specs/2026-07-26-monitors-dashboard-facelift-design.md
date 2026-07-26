# Monitors Dashboard Facelift — Design

**Date:** 2026-07-26
**Status:** Approved
**Prior art:** `specs/2026-07-25-native-monitoring-engine-design.md` (the engine and API this page reads),
`plans/2026-07-25-native-monitoring-slice1.md` (Tasks 11–12 built the page being replaced)

## Context

`/monitors` renders the shared `EntityTable` with a status pill, a check-history bar, uptime and
latency text columns, and a Pause button. Every piece of live data the engine produces already
reaches the page — WebSocket status pushes via `useMonitorStream`, events, latency history — but the
layout does nothing with it. Two specific complaints:

- **It is a table, not a dashboard.** No fleet-level read at a glance, no grouping, filtering,
  search or sort. Just rows.
- **It looks generic.** Reusing `EntityTable` gives monitoring the same chrome as Hardware and
  Services, so it has no visual identity of its own.

This design replaces the table with a purpose-built card wall plus a summary strip, and makes the
page interactive: tiles and chips filter, cards expand in place, and group headers carry a pulsing
status ping.

## Scope

**In scope:** the `/monitors` list page, its new components, a `styles/monitors.css` stylesheet, the
theme tokens the status colours need, and one new backend endpoint that feeds the card faces.

**Out of scope:** `/monitors/{id}` keeps its current design (it gains nothing but a shared chart
component extracted out of it); the Monitor columns on the Hardware/Compute/Services/External pages
and the `MonitorPanel` drawers are untouched; `MonitorForm` is reused unchanged.

## Decisions

| Question | Decision |
|---|---|
| Layout | Card grid ("wall of status"), not a dense list or a master/detail inspector |
| Fleet size target | 15–50 monitors: tight cards, status grouping, filters that do real work |
| Card interaction | Click expands the card in place; the detail page stays for deep links |
| Group ping cadence | Constant pulse, faster while down — not tied to check arrivals |
| Density toggle | None. Cards are tight enough for 50; a card/row toggle doubles layout code for an unproven preference |
| Inspector pane | None. The expanded card covers it and `/monitors/{id}` already exists |
| Card-face data | New `GET /monitors/overview` — one request per refresh, replacing today's per-monitor event fetches |

## 1. Page anatomy

Top to bottom:

1. **Header** — title, `+ Add monitor`, and a live indicator: a green dot plus the most recent check
   as relative time ("pve checked 4s ago"), re-rendered on a 1s interval from the newest
   `last_polled_at`.
2. **Summary strip** — five tiles: Total, Up, Down, Pending, Paused, each with its count in the
   status colour. Clicking a tile filters the wall to that status; clicking the active tile clears
   it. Total clears all status filtering.
3. **Toolbar** — search over name and target; check-type chips (HTTP / ICMP / TCP / DNS) with counts,
   toggling a type filter; a sort control.
4. **Status groups** — Down, Pending, Up, Paused in that order, each rendered only when non-empty.
   Header shows the pulsing ping, the status word, and the count.
5. **Card grid** — 4 columns at desktop width, collapsing to 3 / 2 / 1 responsively.

### Card face

- Status as a 2px coloured top border; paused cards additionally dimmed to ~62% opacity.
- Name (bold) and check-type badge on one line.
- Target subtitle: `config.url` for HTTP else `host`, plus the linked entity type when
  `target_type` is set ("192.168.0.4 · hardware"), truncated with ellipsis.
- Middle row: `LatencySparkline` over `latency_series` when the monitor is up, `CheckHistoryBar` over
  `recent_checks` when it is anything else — a monitor in trouble should show its pattern of
  failures, a healthy one its latency trend. An up monitor with an empty `latency_series` (a check
  type that records no latency, or a monitor polled for the first time) falls back to the history
  bar.
- Footer: the headline figure (latency for up, "Down" / "Retry 1/2" / "Paused" otherwise) and 24h
  uptime.

### Expanded card

Clicking a card expands it to span the full grid width, revealing:

- The 24h latency chart (shared recharts component).
- Four stats: 24h uptime, current latency, retries used (`retries` / `max_retries`), time in current
  state (from `last_status_change_at`).
- The full-width check-history bar.
- The last few events with their messages and timestamps.
- Actions: Check now, Pause/Resume, Edit (opens `MonitorForm`), Delete (via `ConfirmDialog`), and
  "Open full page →".

Several cards may be expanded at once, so two flapping monitors can be compared side by side.
Expansion state is local component state and is not persisted.

## 2. Components

| File | Responsibility |
|---|---|
| `pages/MonitorsPage.jsx` | Orchestrator: fetch, filter/sort/search state, grouping, compose the pieces |
| `components/monitors/MonitorSummaryStrip.jsx` | Five count tiles; emits the status filter toggle |
| `components/monitors/MonitorFilterBar.jsx` | Search input, type chips with counts, sort control |
| `components/monitors/MonitorGroup.jsx` | Group header (ping, label, count) plus the card grid |
| `components/monitors/StatusPing.jsx` | Pulsing dot: status colour, cadence, reduced-motion handling |
| `components/monitors/MonitorCard.jsx` | Card face; owns its expanded state and lazy detail fetch |
| `components/monitors/MonitorCardDetail.jsx` | Expanded body: chart, stats, history, events, actions |
| `components/monitors/LatencySparkline.jsx` | 12-bar inline sparkline from `latency_series` |
| `components/monitors/LatencyChart.jsx` | The recharts chart, extracted from `MonitorDetailPage.jsx` |
| `styles/monitors.css` | Grid, cards, ping keyframes, hover and focus states |

Reused unchanged: `StatusPill`, `MonitorForm`, `ConfirmDialog`, `useMonitorStream`, the toast and
skeleton helpers. `CheckHistoryBar` gains a `size` prop (`sm` for the card face, `md` for the
expanded body) and nothing else.

`MonitorDetailPage.jsx` changes only by importing the extracted `LatencyChart` instead of defining
it inline — a deduplication, not a redesign.

**Styling convention:** a dedicated `styles/monitors.css` following the existing
`styles/discovery.css` precedent, imported the same way. Keyframes, `:hover`, `:focus-visible` and
`prefers-reduced-motion` cannot live in inline styles, which is why this page needs a stylesheet
rather than the inline-style approach the current monitor components use.

**Theme tokens:** `StatusPill` and `CheckHistoryBar` reference `--color-warning`, `--color-info` and
`--color-muted`, none of which exist in `styles/main.css`, so pending/maintenance/paused currently
render their off-palette hex fallbacks. Add all three to the theme (`--color-warning: #d79921`,
`--color-info: #83a598`, `--color-muted: var(--color-text-muted)` in gruvbox terms) and drop the
hardcoded fallbacks from both components. `applyTheme` does not need to touch them: like
`--color-success` and `--color-danger` they are palette constants, not preset-driven.

## 3. Group ping

A solid 8px core in the status colour with an expanding, fading ring behind it:

- Down: 1.1s period — trouble reads as more urgent.
- Pending: 1.5s.
- Up: 1.9s.
- Paused: static dot, no ring — nothing is being checked.

The animation is pure CSS (`@keyframes` scaling the ring to 3.4× while fading to zero) and runs
constantly; it does not depend on check arrivals or WebSocket state. Under
`prefers-reduced-motion: reduce` the ring is suppressed and only the core dot remains.

Pings are decorative: `aria-hidden="true"`, with the status word and count carried as text in the
heading.

## 4. Data

### `GET /api/v1/monitors/overview`

Returns one row per monitor: every `MonitorRead` field plus

- `latency_series: list[float]` — up to the last 12 `latency_ms` samples, **oldest → newest**, the
  order a sparkline draws in.
- `recent_checks: list[{id, status_to, msg, created_at}]` — up to the last 20 `monitor_events` rows,
  trimmed to those four keys, **newest first**.

The two orderings differ deliberately, each matching its consumer: `CheckHistoryBar` already expects
newest-first (it reverses internally, as `GET /monitors/{id}/events` returns), so `recent_checks`
matches that shape exactly and the component needs no adapter or `order` prop. `latency_series` is a
bare number list because the sparkline draws bars, not tooltips.

Both are computed in bulk, one query each, with
`ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY ts DESC)` over `telemetry_timeseries` (filtered to
`metric = 'latency_ms'`) and over `monitor_events` by `created_at`. No per-monitor queries.

The route must be declared **before** `/{monitor_id}` in `api/monitor.py`, or FastAPI parses
"overview" as a monitor id — the same ordering constraint `target-summary` and the `target/...`
routes already carry. Schema: `MonitorOverview` extending `MonitorRead` with the two lists, so the
page keeps every field it renders today.

This one request replaces the current `refresh()` fan-out, which issues a `getMonitorEvents` call per
monitor — 15–50 requests every 60 seconds at the target fleet size, and it would have doubled once
card faces needed latency series too.

### Loading strategy

- Page load and the 60s safety-net refresh: one `GET /monitors/overview`.
- Expanding a card: `GET /monitors/{id}/history?hours=24` and `GET /monitors/{id}/events?limit=40`,
  fetched once per monitor and cached for the session. "Check now" invalidates that monitor's cache
  so the chart and event log reflect the fresh probe.
- WebSocket pushes (`useMonitorStream`, already wired): update the card's status, append the new
  latency to `latency_series` (dropping the oldest past 12), prepend the pushed check to
  `recent_checks` (dropping the oldest past 20 — it is newest-first), and recompute group membership
  so a monitor that goes down moves into the Down group without a refetch. The push payload carries
  `monitor_id`, `status`, `msg` and `ts`, which is exactly what a `recent_checks` entry needs; it has
  no event id, so synthesise a key from `ts`.

### Filter, sort and search state

Held in URL query params via `useSearchParams`: `?status=down&type=http&q=graf&sort=worst`. A
filtered view is then bookmarkable and survives navigating into a monitor and back. Sort options:

- `worst` (default) — Down, Pending, Up, Paused; within a group, lowest 24h uptime first.
- `name` — alphabetical.
- `latency` — highest first, monitors without latency last.
- `uptime` — lowest 24h uptime first.

Grouping always applies; sort orders cards within each group.

## 5. States

- **Loading** — six skeleton cards in the grid.
- **No monitors at all** — one centered empty card: a line of copy, `+ Add monitor`, and a note that
  inventory entities can also be monitored from the Hardware, Compute, Services and External pages.
- **Filters exclude everything** — "No monitors match" plus a "Clear filters" button that resets the
  query params.
- **Request failure** — existing behaviour: a toast, with the last good data left on screen.

## 6. Accessibility

- Cards are keyboard-operable (Enter/Space toggles expansion) and carry `aria-expanded`. Nested
  action buttons stop propagation so they never toggle the card.
- `:focus-visible` outlines on cards, tiles and chips.
- Status is never conveyed by colour alone: the card face always carries a word or a number, paused
  cards say "Paused", and group headings name their status.
- Ping rings and sparkline bars are `aria-hidden`; the sparkline's numbers are available in the
  footer and the expanded chart.
- `prefers-reduced-motion: reduce` disables the ping ring and the expand transition.

## 7. Testing

**Backend** (`tests/api/test_monitor_api.py`):

- `/monitors/overview` payload shape: `MonitorRead` fields plus both series.
- Series ordering — `latency_series` oldest-first, `recent_checks` newest-first — and length caps
  (12 / 20).
- A monitor with no samples and no events returns empty lists rather than nulls.
- Route precedence: `/monitors/overview` resolves to the overview handler, not `/{monitor_id}`.

**Frontend** (`src/__tests__/monitors-dashboard.test.jsx`):

- Summary tiles show correct counts and filter the wall on click; clicking the active tile clears.
- Type chips and search narrow the wall; combined filters intersect.
- Groups render in Down → Pending → Up → Paused order, only when non-empty, each with a ping in the
  matching status colour.
- Expanding a card fetches history and events exactly once and renders the chart, stats and events;
  collapsing and re-expanding does not refetch.
- Each action calls its endpoint and refreshes; Delete goes through the confirm dialog.
- Filter state round-trips through URL query params.
- Both empty states render, and "Clear filters" restores the full wall.
- **Regression guard:** rendering N monitors issues exactly one overview request — the N+1 event
  fan-out must not come back.

## 8. Out of scope, deliberately

- No card/row density toggle.
- No permanent inspector pane.
- No bulk selection or bulk pause/delete.
- No changes to the check engine, the collectors, or the alerting path.
- No redesign of `/monitors/{id}` beyond the chart extraction.
