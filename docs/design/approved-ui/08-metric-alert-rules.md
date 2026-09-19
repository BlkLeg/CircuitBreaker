# 08 · Metric alert rules, firing, and recovery

Status: **implemented 2026-09-17.** Backend (catalog, evaluator, CRUD, scheduled
evaluation) landed earlier; the Monitors → Alert rules surface, the reason-code
persistence behind it, and the docs landed 2026-09-17. Two items remain open and are
named at the end of the task list rather than checked off. See
[the UI design](../2026-09-17-metric-alert-rules-ui-design.md) and
[docs/metric-alerts.md](../../metric-alerts.md).

Depends on plans 00, 05 (truthful notification dispatch), 07 (selectors), and the existing
telemetry/freshness contract.

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

- [x] **A1:** Audit available telemetry and existing evaluation/job infrastructure. Define the initial metric/target catalog, permissions, missing-data policy, and preview window.
- [x] **A2:** Write pure evaluator transition tests before UI/backend persistence. Cover durations, gaps, hysteresis, duplicate/out-of-order points, and edits to an active rule.
- [x] **A3:** Build the approved rule list/editor, validation, metric availability hints, current state, and evaluation preview. Preserve unsaved edits and label historical sample coverage.
- [x] **A4:** Add the smallest necessary rule/state schema and migration, authorized CRUD, validation, and bounded list/selector contracts. Decide deletion/disable/edit behavior for an active incident without sending misleading recovery.
- [x] **A5:** Implement evaluation through existing worker/scheduler infrastructure. Batch telemetry reads, bound work, protect against concurrent evaluators, and persist transitions safely.
- [x] **A6:** Connect firing/recovery to the corrected notification pipeline with stable deduplication keys. A failed delivery changes delivery status, not the underlying metric assessment.
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

### What is not done

**A7 — surfaced 2026-09-17; the underlying behaviour is intentional.** The preview, the
no-polling refresh policy and the stale-telemetry states shipped with the tab.

An earlier revision of this note claimed a deleted destination left a rule "firing into
nothing". That was wrong, twice over. `notification_routing.select_delivery_targets` branches
on the event's `sink_id`: set, it delivers directly to that sink if it still exists and is
enabled; null, it falls back to the global severity routes, and a miss there is recorded as a
terminal `no_route` delivery outcome, not a silent drop. So `ON DELETE SET NULL` does not
lose the alert — it **silently moves it** from the destination the operator chose to whatever
the severity routes say.

The fix is visibility rather than behaviour: an enabled rule with no `sink_id` is
unreachable through the API, because `validate_metric_rule` refuses that combination on both
create and update, so the delete cascade is its only possible cause and the row says so
outright. The rule list now reports it, and the editor already refused to save such a rule.
Changing the delivery behaviour — disabling the rule, or refusing the sink delete — was
considered and declined: the fallback is reasonable, it was only ever invisible.

**A8 — no end-to-end test.** The migration chain is verified
(`tests/integration/test_fresh_install_migration_chain.py` runs `alembic upgrade head`
against an empty database), docs and release notes are written, and the axe suite covers
both Monitors tabs. There is no browser test that creates a rule, fires it and observes the
notification.
