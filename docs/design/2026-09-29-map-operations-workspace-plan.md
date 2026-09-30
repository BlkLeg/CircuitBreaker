# Operations topology workspace implementation plan

Date: 2026-09-29  
Status: design selected for planning; implementation pending. This request
authorizes plans, not application or backend changes.

## Design of record

- [Operations workspace, version 4](https://p.superdesign.dev/draft/4ae640b7-5c58-4123-947e-3f6d28be602b).
- [Shared canvas](https://superdesign.dev/teams/4281dc54-7c08-491e-9c06-483e758fa325/projects/a44eac63-f5b5-4185-b1c9-18d768ecbc40).
- [Approved native map console and connection walkthrough](2026-09-29-map-console-and-connection-walkthrough.md).
- [Exploration plan and shared console foundation](2026-09-29-map-exploration-workspace-plan.md).

Operations versions 1–2 are superseded. The current prototype preserves the
approved native-map screenshot and uses illustrative health, changes and
telemetry. Its local interactions are composition evidence, not functioning
monitoring or a durable event feed. Preview links track the current head;
version 4 is the selected planning baseline.

## Outcome and composition

An operator can see which assets need attention, distinguish known health from
stale or missing observations, inspect a selected asset, and review attributable
inventory changes without leaving the native map.

Use the same enterprise console as Exploration: compact map commands, an active-map
health/freshness strip, a narrow Attention / Recent changes rail on the left,
dominant native topology, selected-asset inspector on the right, and full-width
Telemetry / Recent changes workbench below. Telemetry is the default lower tab.
Reference widths are approximately 236px / flexible map / 310px, with a 264px
lower workbench. Preserve usable map space and readable text at other viewports.

Reuse the shared modules and invariants in the Exploration plan; do not create a
second console, inspector, chart system or selection store. New code/tests use
TypeScript/TSX. Preserve native artwork, renderer behavior, annotations, layout,
edge overrides, shared header/logo, navigator, themes and existing map actions.
Do not ship prototype screenshots, sample values, CDN scripts or canvas links in
the application. Enterprise quality comes from alignment, quiet surfaces,
readable data and semantic status—not decorative dashboard effects.

## Health, freshness and attention contract

### Scope and counting

Define the operational population as unique authorized domain entities in the
active map after environment/type/tag/role filters. Exclude annotations,
decorative lines and synthetic group containers. Label the scope in the strip;
do not imply unloaded entities were counted. Exploration's neighborhood scope
does not constrain Operations counts. Incomplete loads retain an explicit
loading/partial state rather than displaying complete-looking totals.

Normalize existing effective-status logic used by the native nodes and
`buildNodeStatusDetails`; the console must not invent another health resolver.
Map current statuses to Healthy / Attention / Unknown with documented precedence.
Retain maintenance/suppression semantics and original status text. An override,
observed monitor state and telemetry-derived state remain distinguishable.

Health categories are mutually exclusive and sum to the operational population.
Stale telemetry is a separate overlapping count and never added as a fourth
health category. Count staleness only for eligible sources with valid sample
timestamps and an established cadence/staleness policy. Distinguish stale,
unconfigured, unsupported, never sampled and unavailable; never sampled is not
an infinitely old sample. Future/invalid timestamps require an explicit invalid
or unknown freshness state.

Transport connection state describes the topology/telemetry stream or polling
fallback, not the health of every host. Display per-source sample age rather
than a single ambiguous age for mixed sources. Disconnected transport does not
erase current readings or prove every asset is offline.

### Attention rail

- All / Attention / Stale filters act on operational rows and show exact matching
  unique-asset counts. An asset may match both Attention and Stale but appears
  once per view with separate reasons.
- Use existing explicit statuses, actual monitor/alert results or configured
  thresholds for attention. A disk percentage alone is not an alert; the
  prototype's watch-state and capacity-review text is illustrative, not a new
  rule engine. Maintenance is displayed according to existing suppression policy.
- Every row provides identity/type/address, textual state/reason, source and
  observation timestamp when available. Sort attention deterministically by
  actual severity, then observation time and stable identity; stale rows use age.
- Selection updates the native selected asset, inspector and workbench together.
  Selection alone preserves viewport; an explicit Locate action centers it.
  A no-longer-present entity gets a truthful unavailable state, not another ID.
- Do not add acknowledgement, ticket creation, remediation or security findings
  without corresponding authorized services and workflows. Reuse real security
  signals only where already available and permission-aware.

Evaluate freshness with a shared coarse clock and update subscriptions, not a
timer or network request per row. Reuse telemetry pushes and batched polling.
Aggregate normalized data once per revision and keep unrelated UI changes from
rebuilding the graph. Live updates preserve selection, viewport and positions.

## Recent changes: existing capability and required extension

Source inspection on 2026-09-29 confirmed:

| Existing foundation | Current contract and limit |
| --- | --- |
| `components/common/RecentChanges.jsx` | Header list calls `adminApi.recentChanges(10)` and navigates to entity collections. |
| `apps/backend/src/app/api/admin.py` recent-changes handler | Admin-only; global supported-entity log query; limit 1–50. Returns entity type/ID/name and action/update timestamps. |
| `MapWorkspace.jsx` topology subscriptions | Node movement, cable add/remove and status events drive current graph updates. This is not a persisted historical feed. |

The current admin response lacks a stable event ID, structured action, source,
relationship endpoints and server-side active-map filtering. Filtering its last
ten global items on the client can miss relevant map events. Do not present this
as a complete map history or relax the admin route's authorization to make the
mock work. Keep the existing header consumer compatible.

### Proposed map-scoped feed

Add a narrowly scoped read contract through the existing logs/audit infrastructure,
not a separate event database. Before implementation, trace actual log producers,
entity/map permissions, retention and timestamp ordering. Proposed route:
`GET /api/maps/{map_id}/changes?limit=25&cursor=...&kind=...`; the exact route must
follow the repository's real map API conventions. This is a proposed API, not an
existing endpoint.

Required behavior:

1. Authenticate and authorize the map and every returned entity/event. Map read
   access alone does not imply permission to view audit details. Keep existing
   admin-only audit visibility unless an explicit narrower policy already exists;
   otherwise show Recent changes unavailable for the current role. Do not leak
   names, counts, relationships or actor details through denied results.
2. Filter map membership and supported event kind before limiting/pagination.
   Use a stable `(timestamp, event ID)` cursor; support deterministic ordering,
   deduplication and bounded page sizes. Define membership as current authorized
   map entities unless event-time membership is actually recorded. Do not claim
   historical completeness for removed assets or past map membership.
3. Return stable event ID, occurrence time, entity type/ID and safe display name,
   normalized supported action, source when recorded, and map scope. Relationship
   events additionally require real endpoint identities and semantics. Unknown
   source stays unavailable; do not label every log entry Inventory API.
4. Expose only supported Inventory / Discovery / Relationship classifications.
   Audit actual writers before enabling a category. Missing relationship or
   discovery history needs producer instrumentation and tests, not inferred text
   from timestamps. Document any logging extension and existing retention limits.
5. Clearly distinguish persisted changes from optional transient session updates.
   Stream events are not replay or durable history. A reconnect refetches the
   bounded persisted feed and deduplicates; it cannot guarantee recovery of events
   the data source never stored. There is no incident correlation or time replay.
6. Return pagination/availability information sufficient to distinguish loading,
   empty, error, forbidden and partial/unavailable sources. Do not turn failures
   into No changes. Abort/ignore previous-map responses after switching maps.

A permission-gated admin feed filtered to map membership can be an interim view
only if labeled Recent matching global entries with its bounded coverage. It
does not satisfy the final map-scoped feed acceptance gate. Prefer delivering
the health/telemetry slice while the final feed is implemented over shipping
misleading history.

Rail and lower table consume one feed/query cache with the same timestamps,
entity identities, supported filters and selection behavior. Lower-table columns
are Timestamp / Entity and action / Source / Scope. Local rail filters may apply
to the loaded page if labeled accordingly; full-history filters must be server
side. Never display fictional total matching counts. Preserve selected row on
refresh, provide a new-items indicator instead of continually moving the user's
reading position, and resolve removed entities honestly.

## Selected-asset analysis and state

Use the shared selected-asset inspector and telemetry adapters from Exploration.
Resolve current identity by stable type/ID and invalidate requests on
selection/source/map changes. Show health and freshness independently. Source
selection determines which CPU/memory/network history is available; service
monitor latency does not become host telemetry.

Use the approved adjoining host / CPU-memory / RX-TX panes. Middle plots meet
neighbor dividers, percent scales have numeric 0–100 ticks, timestamp spacing is
real, gaps remain gaps, and source/range/cadence/count/last/min/max/cursor values
are explicit. Generic entity telemetry's 20 recent metric rows are not a complete
series per metric. Unknown readings, unavailable temperature, short history and
stale histories retain useful truthful states. No threshold bands without actual
configuration, smoothed invented samples or capacity-as-utilization.

Mode switches preserve canonical selection, viewport and document. Operations
does not inherit Exploration's adjacency restriction. Independent hide/collapse,
Hide Console, Restore Console and fullscreen follow the shared contract: zero
space when hidden, prior configuration restored, no dirty layout or relayout,
and live updates continue. Persist preferences only through existing supported
presentation storage if necessary; this design requires no new settings table.

## Delivery packages and proposed ownership

| Package | Work | Exit condition |
| --- | --- | --- |
| O0 | Audit status precedence, timestamps/cadence, entity identity and event producers/permissions. Freeze design artifacts. | Document exact health/freshness mappings and supported feed categories. |
| O1 | Reuse shared console E1, selected inspector and telemetry adapters. | Native map and selected-asset analysis work with all console visibility states. |
| O2 | Add `model/operationsSummary.ts`, `hooks/useMapOperations.ts`, `components/console/OperationsSituationStrip.tsx` and `OperationsRail.tsx`. | Real scoped health/freshness counts and deterministic attention selection. |
| O3 | Specify/implement authorized map-scoped change query, compatible log instrumentation if needed, pagination and typed frontend adapter. | Real attributable events, explicit coverage, role enforcement and no global-feed truncation masquerading as completeness. |
| O4 | Add shared rail/table change presentation, selection, filters and live refresh handling. | One consistent feed; stable reading position and selected asset; truthful empty/error states. |
| O5 | Integrated accessibility, themes, renderer/live-update/performance verification and operator docs. | Release acceptance below passes with measured evidence. |

O1 is the same shared package as Exploration E1. O2 can ship independently of O3
with unavailable history made explicit. O3–O4 are required before calling the
complete Operations workflow delivered. Reuse existing authenticated API clients,
log models, services and retention. If producer/schema changes become necessary,
document migration/rollback before execution; do not presume they are required.

## Acceptance and verification

- [ ] Health fixtures cover overrides, monitor/telemetry disagreement, maintenance,
  unknown/unconfigured sources and mutually exclusive health totals. Freshness
  fixtures cover stale/fresh/never sampled/invalid/future timestamps and source cadence.
- [ ] Attention filtering deduplicates overlapping reasons and uses truthful source
  severity. Active-map/filter changes update counts without exposing unloaded assets.
- [ ] Backend feed tests cover forbidden roles/maps/entities, redaction, filter-before-limit,
  cursor ties, deduplication, deletion and unsupported categories. Existing admin
  recent-changes clients remain compatible.
- [ ] Browser checks cover selected-host consistency, missing history, delayed old
  responses, live updates, feed pagination/errors and selection of removed assets.
- [ ] Pane collapse/hide/restore, mode/fullscreen/map/renderer switching preserve
  selection, viewport, original artwork, overrides and document dirty state.
- [ ] Keyboard/focus, labeled tabs, textual status, reduced motion, enlarged text,
  responsive rails/local table scrolling and theme variants work in a real browser.
- [ ] Measure aggregation/update cost and change-query plans on representative data;
  avoid per-asset requests, per-row timers and unbounded history buffers. Record
  React Flow and Sigma behavior separately, including burst/reconnect handling.
- [ ] TypeScript, focused frontend/backend contract tests and production build pass.
  For backend changes run the relevant integration checks and repository verification
  ladder; `make verify` alone is not full backend coverage.
- [ ] Remove synthetic fixtures and prototype-only controls from production. Publish
  operator documentation on count scope, health versus freshness, history coverage,
  roles and genuine renderer limits. Record evidence before closing packages.

## Planning evidence and limits

Desktop draft inspected at 1810×1023. The real logo loaded; selecting stale
`pve4` updated inspector and workbench identity and showed unavailable history;
Attention/Recent changes and lower tabs worked; Hide/Restore Console retained a
previously hidden inspector; no browser script errors were observed. The final
version makes small copy corrections only. Production graph selection, stream
aggregation, authorized history, responsive/accessibility compliance and measured
performance remain unimplemented. See the
[capability audit](../../plans/v0.5.0-map-feature-audit.md).
