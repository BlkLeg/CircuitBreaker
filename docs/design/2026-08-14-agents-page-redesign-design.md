# Agents Page Redesign — Design

**Date:** 2026-08-14
**Status:** Approved design, not yet implemented
**Scope:** `apps/frontend/src/pages/AgentsPage.jsx` and the fleet-read side of the agents API

## Problem

The Agents page is unfinished, not merely dated. Every `agents-page__*` class in the
JSX — `__header`, `__pending-banner`, `__install-panel`, `__table`, `__online` — is
defined in **zero** CSS files. The only classes that resolve are `.filter-bar` and
`.filter-select`, borrowed from `main.css:1040`. What renders is browser defaults: an
unstyled `<h1>`, a bare `<ul>` of buttons for pending approvals, a raw `<pre>` for the
install command, and a default-rendered 11-column `<table>`.

By comparison `/monitors` has a designed card wall with status pings, semantic color
tokens and reduced-motion handling in `monitors.css`. The Agents page never got that pass.

Beyond appearance, the page under-serves its two jobs:

1. **Adding an agent** hands over a command and then abandons you. Enrollment surfaces
   later in a separate pending banner, and a third path (pairing code) sits in a corner
   of the install panel.
2. **Watching the fleet** shows presence and metadata but no health. The operator
   question — "is anything struggling?" — is unanswerable from this page, despite the
   data being collected and stored already.

## Goals

- The page reads as a finished product surface, consistent with the rest of the app.
- Adding an agent is one continuous flow that ends when the agent is approved.
- The fleet table answers "what is the state of my fleet" at a glance, live.
- No new telemetry collection, no schema change, no new agent-side work.

## Non-goals

- Replacing `AgentDetailPage` (827 lines) — it keeps capabilities, host telemetry
  charts, linked hardware and the event log. The fleet view links into it.
- Row virtualization. Designed for a homelab fleet of tens of agents; the whole fleet
  renders. Revisit past ~200 rows.
- Changing the enrollment protocol, the approval security model, or agent-side code.

## Design direction

Two references, chosen by the product owner:

- **Cloudflare** for the add-agent flow: a guided panel that hands over a command and
  then watches for the machine to appear.
- **Netdata** for the fleet table: dense rows, live values, sparklines showing movement
  rather than a single number.

Selected layout, from mockup review:

- **Dense flat list.** 34px rows, ~16 agents visible before scrolling, tabular numerals
  so columns do not jitter as values update. No grouping.
- **Pending agents pin to the top** of that same list with an amber left edge until
  approved, then settle into normal order. No floating banner, no filter chips.
- **Install panel inline**, above the table, guided and self-completing.

## 1. Data and API

Two reads, because the head values and the sparkline series have different costs and
therefore different cadences.

### 1.1 Head values — extend `GET /agents/presence`

`AgentPresenceRead` already returns exactly one row per agent for this table
(`agent_id`, `online`, `connected_since`, `last_seen_at`, `capabilities`, `hardware`).

Add a `latest` object carrying the summary already stored on every sample
(`api/agents.py:80-97`): `cpu_pct`, `mem_pct`, `root_disk_pct`, `net_rx_bps`,
`net_tx_bps`, `max_temp_c`, `load_1`, `uptime_s`, `collected_at`. `null` when the agent
has no samples.

Implemented as a single `DISTINCT ON (agent_id) … ORDER BY agent_id, collected_at DESC`
over `agent_host_samples`, which lands on the existing composite index
`ix_agent_host_samples_agent_time` (`db/models.py:570`). No new index, no new
collection, no schema change. Rides the page's existing 30s presence poll.

### 1.2 Sparkline series — new `GET /agents/metrics/series`

Returns a 30-minute window of downsampled points per agent, capped at 24 points each
(one per 75s bucket), the cap enforced as a SQL `LIMIT` so the payload cannot grow with
sample cadence — the same discipline `/telemetry/history` already applies via
`_HISTORY_DURATIONS` (`api/agents.py:104-110`).

Refetched every 120s — 4× the presence tick. The sparkline shows a 30-minute shape, so a
2-minute-old series is visually indistinguishable from a fresh one; the head value beside
it is what stays current.

A separate endpoint rather than a flag on presence, precisely because the cadences
differ: folding them together means paying the series cost on every fast tick.

### 1.3 Shared rules

- Both routes require `require_role("viewer")`, matching `/agents/{id}/telemetry`.
- **The backend does not judge staleness.** It returns the newest sample with its
  `collected_at`; the client decides what counts as stale. Otherwise "telemetry was
  disabled an hour ago" and "the agent is wedged" become indistinguishable server-side.
- `latest: null` is a real state and must never render as `0%`.

## 2. Page composition

`AgentsPage.jsx` is 430 lines doing six jobs: fetching, filter state, live merge, the
install flow, the approval flow, and all table markup. The redesign roughly doubles what
it renders, so it splits rather than grows.

| New unit | Responsibility |
|---|---|
| `components/agents/AddAgentPanel.jsx` | Platform tabs, command block with copy, TLS mode and pin, live waiting state, inline approve step |
| `components/agents/FleetTable.jsx` | Header, sort state, empty and filtered-empty states, pinned-pending ordering |
| `components/agents/FleetRow.jsx` | One agent: status dot, name, platform, version, uptime, metric cells, actions; owns the offline variant |
| `components/agents/Sparkline.jsx` | Inline SVG sparkline |
| `hooks/useFleetMetrics.js` | Both fetches and their cadences; returns one merged per-agent shape |
| `styles/agents.css` | The stylesheet that does not exist today |

`AgentsPage.jsx` retains orchestration only: fetch, filters, live merge, composition.

### 2.1 Sparklines do not use Recharts

Recharts is the house chart library (`components/monitors/LatencyChart.jsx` and the three
privacy charts). It is deliberately **not** used here: Recharts mounts a
`ResponsiveContainer` with its own resize observer per instance, so 16+ live rows means
16 observers re-rendering every tick. `Sparkline.jsx` is a hand-rolled inline
`<svg><polyline>` — no dependency, no observer. Recharts remains correct for the detail
page's real charts.

### 2.2 The fingerprint comparison is shared, not duplicated

Approval becomes reachable two ways: inline in the panel, and via **Review** on a pinned
row. The fingerprint comparison is the control that prevents approving an impostor, so
both paths render the same component. Extract the comparison body out of
`AgentApprovalModal.jsx`; the modal remains the wrapper for the row path.

This also preserves the duplicate-machine warning at `AgentApprovalModal.jsx:162` and the
proposed-hardware link — reimplementing the comparison inline would have quietly dropped
a security signal.

## 3. Live behaviour

Two clocks already exist with a deliberate merge policy between them. This design adds a
third, so the slices are kept disjoint and no new arbitration is introduced.

**Existing policy, unchanged.** `utils/agentPresenceFreshness.js` arbitrates WS pushes
against the 30s presence poll with two guards: a poll landing after a push wins outright
(closing the missed-`disconnected`-during-reconnect gap), plus a 45s absolute cap, set at
1.5× `REFRESH_MS` for one full poll cycle of slack.

**Ownership:**

| Signal | Owns | Cadence |
|---|---|---|
| WebSocket `/agents/stream` | Presence transitions only — dot, `connected_since` | Push, gated by `isLivePushFresh` |
| `GET /agents/presence` | Head metric values (`latest`) and presence | 30s |
| `GET /agents/metrics/series` | Sparkline shape only | 120s |

Because the slices do not overlap, the third clock cannot contradict the other two.

**Series/head coherence.** The series usually lags the head by a tick, which would render
"81%" beside a line ending at 74%. The client appends the current head value as the
series' final point so the right edge always agrees with the number beside it.

**Reacting rather than waiting.** Enrollment, approve, reject and revoke each trigger an
immediate presence refetch, so a pinned row never sits invisible for up to 30 seconds.

**Degradation.** WS down is already handled — the poll runs independently and the
`live` / `reconnecting…` indicator exists (it is simply unstyled). An agent that just came
online has no series yet: the sparkline renders empty, never a row of zeros.

## 4. States

| State | Behaviour |
|---|---|
| No agents at all | The Add-agent panel *is* the page: expanded, no table chrome. Today: an empty 11-column table with headers |
| Filters match nothing | Proper empty state with a clear-filters action. Today: a bare `<td colSpan={11}>` |
| Install command fails | The 503 detail renders inline in the panel, where the operator is looking — not only as a toast |
| Presence fetch fails | Stale treatment: dimmed values plus a last-updated note. Today `AgentsPage.jsx:114` swallows this with `.catch(() => {})`, which now would freeze every metric while it still looks live |
| Series fetch fails | Sparklines do not draw; head values, presence and the table are unaffected |
| `latest: null` | Reads "telemetry off", never `0%`; hints that it is a capability grant |
| Offline | Metric cells collapse into one line: offline duration, last seen, spool depth |
| Spooling while online | Backlog chip — the one signal that predicts trouble before anything goes red |
| Duplicate machine id | Inherited from the shared comparison component |

## 5. Testing

Two tests carry most of the weight.

**Query count on `/agents/presence`.** The whole justification for putting `latest` on
the bulk endpoint is that a fleet costs one query. Nothing prevents a later change from
making it one query per agent, and nothing would look wrong — it would only get slower as
fleets grow. No query-counting harness exists in the suite; this needs a fixture hanging
a SQLAlchemy `before_cursor_execute` listener on the session, then seeding N agents and
asserting the count does not scale with N.

**Presence-failure rendering.** A failed presence fetch must show the stale treatment
rather than confidently displaying frozen numbers.

**Backend:** `DISTINCT ON` returns the newest sample per agent with out-of-order inserts;
`latest: null` with no samples; the series point cap holding as a SQL `LIMIT` regardless
of sample cadence; `require_role("viewer")` on both routes.

**Frontend:** `Sparkline` with zero, one and N points plus the head-value append;
`FleetRow`'s four variants (online, offline, telemetry-off, pending-pinned); pinned
ordering surviving a column sort; `AddAgentPanel`'s waiting → checked-in transition
driven by a WS event, and its inline 503 detail.

**Invariant:** a WS push never overrides a metric value. The existing
`agentPresenceFreshness` tests must keep passing untouched — they encode the policy that
lets three clocks coexist.

## Assumptions

- Homelab fleet scale: tens of agents. No virtualization; revisit past ~200 rows.
- The existing three filters (status, capability, online) are kept and styled. The
  pinned-row choice replaced the pending *banner*, not filtering.
- Default theme is gruvbox dark (`--color-primary: #fe8019`); the design uses existing
  tokens from `main.css:11-34` and adds none.
