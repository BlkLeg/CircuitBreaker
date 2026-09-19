# Agent Console Redesign — Design

**Date:** 2026-09-05
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `5515de00`; that commit fixed the fleet table's column-grid
regression and is a prerequisite for §8.
**Scope:** The agent detail page and the agent list page, plus a new set of shared
layout primitives that other detail pages may adopt later. No backend, API, or agent
binary changes. No other page is converted in this effort.

## 1. Problem

`AgentDetailPage.jsx` is 975 lines carrying **15 `className` attributes**. It imports
`styles/agents.css` at line 38, but the markup has almost nothing for that stylesheet to
attach to, so the page renders as browser defaults: unpadded headings, bare
`<input type="checkbox">`, an unaligned `<dl>`, and nine `<section>` elements with no
framing. The screenshots that prompted this work are not a styling bug — they are the
absence of a styling layer.

That absence has three separable causes.

### 1.1 The fleet redesign converted the list and stopped there

`AgentsPage.jsx` was decomposed into `FleetTable`/`FleetRow`/`AddAgentPanel` and given
roughly 500 lines of considered CSS (`.fleet-*`, `.agents-page__*`). Its header comment
describes that move explicitly. The detail page never received it, so the feature has
one designed half and one undesigned half sharing a stylesheet.

### 1.2 The page has no spacing or type scale to reach for

`styles/main.css` `:root` defines colour (`--color-bg` `#282828`, `--color-primary`
`#fe8019`, `--color-success` `#b8bb26`, `--color-warning` `#d79921`, `--color-danger`
`#fb4934`, `--color-info` `#83a598`), one radius, and one font size. There is no spacing
ramp, no type scale, and no raised-surface colour. A developer adding a section to this
page has no vocabulary to add it *in*, which is why nine of them were added with none.

### 1.3 The page renders every state at once, for every agent

The screenshots show a **pending, never-connected** agent. For that agent there is
exactly one available action — compare the fingerprint and approve. The page instead
renders eight full sections of nothing: capability toggles for a machine that is not
approved, a metrics section, a probes section, and a discovery section whose collector
table lists four `Never reported` rows. Meanwhile `lib/agentState.js` already derives 15
ordered states (`STATE_ORDER`, `agentState.js:97`) with a `primaryAgentState()` selector
at `agentState.js:471`, and the page throws that ordering away by rendering all matching
states as an undifferentiated `<dl>`.

### 1.4 Two list-page defects remain at HEAD

`5515de00` fixed the column-grid misalignment. Two defects survive it:

- **`PendingCells` runs its fields together.** `FleetRow.jsx:386` emits the bare text
  node `Waiting for approval` immediately followed by `<span className="fleet-muted">`.
  The separator rule is `.fleet-muted + .fleet-muted::before` (`agents.css:614`), an
  adjacent-sibling selector; a text node is not a sibling element, so the rule never
  fires and the cell renders `Waiting for approvallinux / amd64`.
- **`summarizeFleet` reports a fleet of one as empty.** `fleetFilters.js:152` filters
  pending agents out of `fleet` before counting, then returns `total: fleet.length`. A
  deployment whose only agent is pending renders `0 of 0 agents · 1 awaiting approval`,
  which contradicts the row visible directly beneath it.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Information architecture may be restructured freely | Padding alone does not fix §1.3. Content may be regrouped, reordered, demoted, and hidden; nothing is deleted. |
| D2 | Shared primitives in `components/common/`, agents as first consumer | Per §1.2 the missing layer is generic. Building it agent-scoped guarantees the next detail page repeats this work. Only agents is converted here. |
| D3 | Operator prose is condensed with progressive disclosure | The AGT-14/15/16 wording is retained **verbatim** behind a disclosure control; the always-visible line becomes a short imperative. |
| D4 | The detail page becomes a tabbed console | Telemetry and Discovery are each near-page-sized; `DiscoveryScopeSection.jsx` alone is 779 lines with four tables. |
| D5 | Live subscriptions stay up on every tab; only expensive fetches are gated | See §5. A spike on a hidden tab must still be visible, so tabs must not go deaf. |
| D6 | The list page gets its two defects fixed and its chrome aligned to the primitives | The table itself is the strongest part of the feature and keeps its 34px density and `.fleet-*` vocabulary. |

## 3. Architecture

### 3.1 Routing

`App.jsx:243` keeps `path="/agents/:id"`. The active tab is a **search param**, not a
route segment:

```
/agents/:id?tab=overview | telemetry | probes | discovery | events
```

Absent or unrecognised values resolve to `overview`. This keeps deep links and the back
button working with no router change and no new lazy chunks.

### 3.2 Decomposition

`AgentDetailPage.jsx` becomes wiring only — params, confirm dialogs, composition —
targeting ~250 lines. Its own comment at `AgentDetailPage.jsx:883` ("This page is
already far past the component budget") is the standing acknowledgement that this is
overdue.

```
components/common/            ← new; nothing here knows the word "agent"
  DetailHeader.jsx  Tabs.jsx  Panel.jsx  PanelGrid.jsx
  KeyValue.jsx  StatTile.jsx  EmptyState.jsx  Banner.jsx
  CopyField.jsx  Toggle.jsx
styles/panels.css             ← new

components/agents/            ← new
  AgentIdentityHeader.jsx     AgentStateBanner.jsx
  AgentLiveStrip.jsx          AgentOverviewTab.jsx
  AgentCapabilitiesPanel.jsx  AgentTelemetryTab.jsx
  AgentEventsPanel.jsx        AgentHardwarePanel.jsx
hooks/useAgentDetail.js       ← new

components/agents/            ← re-skinned onto Panel, logic unchanged
  AssignedProbesSection.jsx   DiscoveryScopeSection.jsx
```

`HistoryChart` and `DeviceTable`, currently defined inline in the page, move into
`AgentTelemetryTab.jsx`.

## 4. The primitives

Ten components over the existing tokens. **No new colour vocabulary.** The tone ramp
stays the one `AgentStateChip` and `.fleet-chip` already use, so a state means the same
colour in the table and on the detail page. The accessibility note on
`--color-text-muted` in `main.css` is not disturbed.

`styles/panels.css` adds what §1.2 found missing:

| Token | Value |
|---|---|
| `--space-1` … `--space-6` | 4 / 8 / 12 / 16 / 24 / 32 px |
| `--panel-pad`, `--panel-gap` | `var(--space-3)`, `var(--space-3)` |
| `--fs-micro` … `--fs-xl` | 9.5 / 11 / 12.5 / 13 / 19 / 21 px |
| `--color-surface-raised` | `#32302f` — lets a panel read as sitting above the page |

| Primitive | Replaces |
|---|---|
| `Panel` / `PanelGrid` | Nine bare `<section><h2>` → bordered, padded surfaces on an auto-fit grid (`minmax(232px, 1fr)`) |
| `DetailHeader` | The header at `AgentDetailPage.jsx:609-627`, which wraps name, status, online chip, fingerprint, version and two buttons into one unstyled run |
| `Banner` | The two "…is disabled for this agent" warnings, already `<aside>`-shaped but rendered as body text; carries tone, icon, actions, and the D3 disclosure |
| `EmptyState` | Five bare `<p>`s — "No host samples received yet.", "No hardware linked", "No monitors run from this agent.", "No discovery subnets are assigned…", "This agent has not reported any discovered devices yet." |
| `StatTile` | The `SUMMARY_LABELS` metric cards; renders `—` for null rather than blank |
| `KeyValue` | The scope-mode block (scope mode, addresses per job, concurrent hosts, host timeout, job timeout, TCP ports) |
| `CopyField` | The fingerprint and the scope version — values operators compare character by character |
| `Toggle` | The three raw capability checkboxes at `AgentDetailPage.jsx:666-674` |
| `Tabs` | New; URL-backed tablist with roving focus and `aria-selected` |

## 5. The reactivity model

The requirement is that activity spikes are **visible when they happen**. Three
mechanisms, in order of importance.

### 5.1 The header live strip

Five micro-sparklines (CPU, memory, disk, network, temperature) and a freshness pill sit
in the **sticky header**, outside the tab panel. They are on screen on every tab,
including Discovery and Events, which have no telemetry of their own. This is what makes
D4 safe: tabs hide detail, never the pulse.

### 5.2 Motion is only ever real

The pill reads `LIVE` only while samples are arriving, and degrades through `LAGGING`,
`STALE`, `OFFLINE` using thresholds that already exist:

| Threshold | Source |
|---|---|
| `LAST_SEEN_FRESH_SECONDS = 90` | `agentState.js:74` |
| `LAST_SEEN_LAGGING_SECONDS = 900` | `agentState.js:75` |
| `STALE_SAMPLE_INTERVAL_MULTIPLIER = 3`, `STALE_SAMPLE_FLOOR_SECONDS = 90` | `agentState.js:63-64` |

Sparklines dim and animation stops when the source is not live. A chart that looks alive
on a dead agent is worse than no chart, and the page must not imply freshness the data
does not have.

### 5.3 Spikes reach you on the wrong tab

A threshold crossing, a discovery job transition, or a new event raises an indicator on
the owning tab — a dot for "something changed", a count for events. Clicking the tab
clears it. This is the one genuine weakness of a tabbed shape and it is why D5 exists.

### 5.4 Subscription policy

The current page fires everything at once: eight `useEffect` blocks
(`AgentDetailPage.jsx:229-328`), a 30-second telemetry `setInterval` at
`AgentDetailPage.jsx:293`, plus `useAgentLive` and `useTelemetryStream`.
`useAgentDetail(id, activeTab)` splits this in two:

- **Always on, every tab** — identity, presence, derived state, and both live stream
  subscriptions. These are one WebSocket each and already exist; they feed §5.1–5.3.
- **Gated on the active tab** — history range fetches, the discovery job/subnet/device
  tables, the probe assignment list, and the device tables. These are the expensive
  calls and nothing off-tab needs them.

The 30-second poll is retained as a reconciliation fallback and backs off while the
stream is delivering, rather than running unconditionally alongside it.

### 5.5 Flash policy

A full border flash is reserved for **threshold crossings and state changes**. Ordinary
sample arrival is expressed by the sparkline advancing, which is already motion. At a
10-second cadence a per-sample flash reads as fidgeting rather than signal.

Under `prefers-reduced-motion: reduce`, all animation is suppressed and threshold
crossings are expressed as a colour step instead.

## 6. Lifecycle-adaptive composition

The page composes from `primaryAgentState()` (`agentState.js:471`) rather than rendering
a fixed section list.

| Primary state | Header | Banner | Tabs | Overview |
|---|---|---|---|---|
| `pending_approval` | No live strip; Approve / Reject as primary actions | Warning, "Compare the fingerprint…", Approve/Reject repeated | All present; non-overview tabs render a single `EmptyState` naming approval as the blocker | Capabilities (disabled, "locked until approved"), Linked hardware, Recent activity |
| `revoked` / `rejected` | No live strip; Delete only | Danger, states the credential is dead | Overview and Events only | Terminal summary and Events |
| `online` | Live strip active | None | All present | Stat tiles, then Capabilities, Discovery, Probes, Hardware, Recent activity |
| `offline` / `presence_unknown` | Live strip dimmed, pill `OFFLINE` | Warning with last-seen | All present | Last known values, marked as last known |
| `no_capabilities` | Live strip active | Info, points at the capability toggles | All present | Capabilities panel raised to first position |

Every other `STATE_ORDER` entry (`clock_skew`, `update_failed`, `spool_pressure`,
`capability_degraded`, …) renders as a secondary chip in the header and, where it has an
action, as an additional `Banner` beneath the primary one. No state loses its wording.

## 7. Per-tab composition

- **Overview** — condensed panels, each linking into its own tab. Never contains a table.
- **Telemetry** — stat tiles, the five `HistoryChart`s, the four `DeviceTable`s, the
  Docker block, the readiness alerts, and the host-telemetry cadence settings.
- **Probes** — `AssignedProbesSection` plus `RemoteProbeConfigEditor`, re-skinned only.
- **Discovery** — `DiscoveryScopeSection` unchanged in logic; its four `<h3>` groups
  (collector readiness, active work, recent jobs, devices found, subnets) each become a
  `Panel`.
- **Events** — the `describeAgentEvent` feed as a live tail, new rows animating in.
  Redaction behaviour from AGT-15 is untouched.

## 8. The Agents list

Defect fixes:

- **`PendingCells`** (`FleetRow.jsx:386`) — wrap the leading text in an element so the
  `.fleet-muted + .fleet-muted::before` separator applies, and lay the cell out as a
  proper inline row rather than three adjacent inline boxes.
- **`summarizeFleet`** (`fleetFilters.js:152`) — pending agents stay excluded from
  `matching`/`total`, because the filter predicates genuinely do not apply to them, but
  the rendered sentence must not claim a fleet of one is empty. `FleetSummary`
  (`AgentsPage.jsx:246`) suppresses the "N of M agents" clause when `total === 0` and
  `pending > 0`, rendering `1 awaiting approval` alone.

Alignment, no redesign:

- The server-key card, the Add-agent card and the filter bar become `Panel`s.
- Empty metric cells render `—` via `StatTile`'s null handling rather than blank.
- Row density, the `.fleet-*` vocabulary, sort headers and chips are unchanged.

## 9. Accessibility

- `Tabs` implements the tablist pattern: `role="tablist"`, roving `tabindex`, arrow-key
  navigation, `aria-selected`, and `aria-controls` onto each panel.
- The header live strip is `aria-hidden`; its values are also present as text in the
  Telemetry tab, so a screen reader is not asked to track an animating sparkline.
- Tab indicators announce through the existing `role="status"` pattern used by
  `FleetSummary`, not through motion alone.
- `prefers-reduced-motion` is honoured throughout (§5.5).
- Text truncation stays CSS-only, preserving the existing rule that a truncated string
  must remain reachable to a screen reader (`FleetRow.jsx:372`).

## 10. Testing

Roughly 2,800 lines of existing tests query this markup and will need updating. D1
authorises the churn; the tests are not deleted, they are re-pointed.

| Suite | Lines | Effect |
|---|---|---|
| `agent-detail-page.test.jsx` | 1,434 | Largest rewrite. Content behind a non-active tab is not in the DOM, so assertions must select the tab first. |
| `agent-discovery-scope.test.jsx` | 627 | Mount `DiscoveryScopeSection` directly; behaviour unchanged. |
| `agent-assigned-probes.test.jsx` | 390 | As above. |
| `agents-page.test.jsx` | 769 | Two defect assertions added; the rest is chrome-only. |
| `agent-safety-confirmations.test.jsx` | 279 | Confirm dialogs are unchanged; selectors move. |
| `agent-state-rendering.test.jsx` | 188 | Extended to cover §6's state→composition mapping. |
| `agent-live-stream.test.jsx` | 96 | Extended to cover §5.4's subscription policy. |

New suites:

- `common-primitives.test.jsx` — each primitive in isolation, including `StatTile` null
  handling and `Banner` disclosure.
- `agent-tabs.test.jsx` — `?tab=` round-trips, unknown values fall back to `overview`,
  back button restores the prior tab.
- `agent-reactivity.test.jsx` — a sample arriving on a hidden tab raises that tab's
  indicator; freshness degrades LIVE → LAGGING → STALE → OFFLINE at the
  `agentState.js` thresholds; `prefers-reduced-motion` suppresses animation.

`make lint` and `make verify` gate the work. The coverage ratchet is not lowered.

**A known limit.** `5515de00`'s own commit message records that jsdom performs no
layout, so the column-grid regression it fixed was invisible to the rendered tests. The
same blind spot applies to every layout claim in this design. Layout correctness is
verified by eye against the running app, not asserted in jsdom.

## 11. Out of scope

- Converting `MonitorDetailPage` or any other page to the new primitives. They are
  built to be adoptable; adoption is a separate effort.
- Refactoring `styles/main.css` (4,524 lines) or folding `monitors.css` into the
  primitives.
- Any backend, API-contract, NATS-subject or agent-binary change.
- The `AddAgentPanel` enrollment flow, which was designed in the fleet redesign.
- Rewording the AGT-14/15/16 prose. D3 permits relocating it behind disclosure, not
  editing it.
- A card/grid alternative to the fleet table.

## 12. Files touched

**New:** `components/common/{DetailHeader,Tabs,Panel,PanelGrid,KeyValue,StatTile,EmptyState,Banner,CopyField,Toggle}.jsx`,
`components/agents/{AgentIdentityHeader,AgentStateBanner,AgentLiveStrip,AgentOverviewTab,AgentCapabilitiesPanel,AgentTelemetryTab,AgentEventsPanel,AgentHardwarePanel}.jsx`,
`hooks/useAgentDetail.js`, `styles/panels.css`, three new test suites.

**Modified:** `pages/AgentDetailPage.jsx` (975 → ~250), `pages/AgentsPage.jsx`,
`components/agents/{AssignedProbesSection,DiscoveryScopeSection,RemoteProbeConfigEditor,LocalDiscoveryConfigEditor,FleetRow}.jsx`,
`lib/fleetFilters.js`, `styles/agents.css`, seven existing test suites.

**Unmodified:** every backend file, `lib/agentState.js`, `lib/agentErrors.js`,
`lib/agentLabel.js`, `api/agents.js`, `App.jsx`.

## 13. Sequencing

1. **Primitives and tokens.** `styles/panels.css` and the ten components, with
   `common-primitives.test.jsx`. Nothing consumes them yet; nothing can regress.
2. **List-page defects.** The two fixes in §8 with their assertions. Independently
   shippable and independently valuable.
3. **Page shell.** `DetailHeader`, `Tabs`, `AgentStateBanner`, the `?tab=` param, and
   §6's state→composition mapping. Existing sections render inside the new shell
   unchanged.
4. **`useAgentDetail` and the reactivity model.** §5 in full, with
   `agent-reactivity.test.jsx`.
5. **Tab contents.** Overview, Telemetry, Events built from the primitives; Probes and
   Discovery re-skinned.
6. **List-page alignment.** §8's chrome changes onto the primitives.

Steps 1 and 2 are independent of each other and of the rest. Steps 3–5 are ordered.
Step 6 is last so the primitives have settled against the harder consumer first.
