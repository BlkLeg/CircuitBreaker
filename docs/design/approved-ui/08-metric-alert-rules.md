# 08 · Metric alert rules, firing, and recovery

Status: selected and approved product expansion. Depends on plans 00, 05 (truthful notification dispatch), 07 (selectors), and the existing telemetry/freshness contract.

## Outcome and location

Monitors gains an Alert rules section with a compact list and rule editor for already collected metrics. Users select a target/metric, comparison, threshold/unit, duration, recovery/hysteresis, severity, and notification destination, then inspect an evaluation preview before enabling the rule.

Existing integration points: frontend `pages/MonitorsPage.jsx`, monitor components, telemetry adapters, `lib/alertSeverity.js`; backend `services/telemetry_service.py`, `services/agent_telemetry.py`, telemetry models/ingestion worker, notification worker/routing, and existing background scheduling infrastructure.

Proposed boundaries: `components/monitors/MetricAlertRulesPanel.jsx` plus a focused editor/preview; a small rules model/schema/service and evaluator in the current backend. Reuse existing equivalents if present on the implementation branch. No separate alerting service or broker.

## Rule and evaluation contract

- Rule identity/revision, enabled state, target identity/scope, supported metric key, unit, comparator, threshold, breach duration, recovery threshold/duration, severity, and existing notification routing reference.
- Define a bounded metric catalog from actual collected telemetry, including units, cadence, supported target types, and freshness. Do not invent historical data, arbitrary query expressions, or unsupported aggregations.
- Separate configuration validity from runtime health. Unsupported target/metric disables creation/enable with an explanation. An existing enabled rule losing fresh data becomes Unknown/stale; do not silently disable or delete it.
- States: Disabled, Unknown/no fresh data, Normal, Pending, Firing, Recovering. Specify allowed transitions, clocks, minimum sample coverage, threshold equality, maximum sample gap, and out-of-order/duplicate handling in pure tests.
- A single old or repeated sample cannot satisfy an entire breach duration. Use observed timestamps and an explicit continuity policy. Missing/stale data must not falsely recover a firing alert or trigger a fresh threshold notification.
- Recovery/hysteresis must be valid for the comparator direction. Boundary noise should not alternate firing/recovery notifications continuously.
- Persist rule state/transition identity where needed for restart-safe duration and duplicate prevention. Reuse existing job/transaction/notification mechanisms; document at-least-once delivery limitations honestly.
- Preview evaluates available historical samples without creating a rule or dispatching notifications. Return sample coverage, window, observed result, and missing-data limitations; never imply a simulation guarantees future behavior.
- Emit existing notification events on supported transitions (initial firing and recovery), not on every sample. No recurring reminders/escalation in this initial scope.

## Work packages

- [ ] **A1:** Audit available telemetry and existing evaluation/job infrastructure. Define the initial metric/target catalog, permissions, missing-data policy, and preview window.
- [ ] **A2:** Write pure evaluator transition tests before UI/backend persistence. Cover durations, gaps, hysteresis, duplicate/out-of-order points, and edits to an active rule.
- [ ] **A3:** Build the approved rule list/editor, validation, metric availability hints, current state, and evaluation preview. Preserve unsaved edits and label historical sample coverage.
- [ ] **A4:** Add the smallest necessary rule/state schema and migration, authorized CRUD, validation, and bounded list/selector contracts. Decide deletion/disable/edit behavior for an active incident without sending misleading recovery.
- [ ] **A5:** Implement evaluation through existing worker/scheduler infrastructure. Batch telemetry reads, bound work, protect against concurrent evaluators, and persist transitions safely.
- [ ] **A6:** Connect firing/recovery to the corrected notification pipeline with stable deduplication keys. A failed delivery changes delivery status, not the underlying metric assessment.
- [ ] **A7:** Wire preview and real-time/refresh updates without per-rule polling loops. Handle deleted targets/destinations and stale telemetry explicitly.
- [ ] **A8:** Add restart/migration and end-to-end tests; update release notes, monitoring docs, and support-contract scope to reflect this newly selected capability.

## Acceptance and tests

- Only supported metric/target/unit combinations can be enabled; thresholds/durations/recovery values are validated client- and server-side.
- Pending becomes Firing only after the defined fresh sustained breach; recovery requires its own valid condition.
- Missing/stale data yields Unknown and does not fabricate Normal, a threshold breach, or recovery.
- Duplicate samples, worker restart, evaluator races, and retries do not create avoidable duplicate transition events.
- Notification rejection is visible and not confused with successful rule delivery; destination deletion is actionable.
- Preview sends nothing and changes no saved configuration; real firing/recovery goes through the tested delivery path.
- Theme changes preserve charts/threshold labels/editor state; keyboard, role, and mobile flows pass.
- Load tests measure evaluator cost and dispatch latency on a stated fixture before performance claims.

Acknowledgement, escalation, correlation, maintenance windows, advanced alert policy, expression languages, and external metric ingestion remain deferred. Approval of metric rules does not expand those boundaries.
