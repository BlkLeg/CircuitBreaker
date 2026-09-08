# 07 · Metric rules, evaluation, and transition delivery

UI consumer: metric alert rule list/editor/evaluation preview. Approved expansion, limited to existing collected telemetry.

## Architectural choice

Place metric-rule domain logic alongside the existing monitoring services, with a separate pure decision function from availability checks. Do not overload MonitorItem.last_status or monitoring/state.decide: uptime retries and sustained numeric breaches have different semantics.

Use the current PostgreSQL telemetry history as truth; Redis is a latency cache, not sufficient evidence of a sustained duration. AgentHostSample can also be projected into HardwareLiveMetric—do not count both copies as independent samples.

## File plan

| File under app/ | Action / responsibility |
| --- | --- |
| schemas/metric_alerts.py | New: rule CRUD, metric catalog, availability, preview, state and transition response models. |
| db/models/monitors.py | Extend: MetricAlertRule, MetricAlertState, MetricAlertEvent; export through models/__init__.py. |
| services/monitoring/metric_catalog.py | New: finite supported metric definitions, units, target/source eligibility and bounded history adapters. |
| services/monitoring/metric_rules.py | New: authorized CRUD/validation, rule revisioning, preview orchestration, persistence coordination. |
| services/monitoring/metric_evaluator.py | New: pure sample-window/state decision; no DB, HTTP, NATS or clock globals. |
| workers/metric_alert_worker.py | New: bounded scheduled evaluation and pending-event publishing; owns sessions, claims and batch lifecycle, not provider HTTP. |
| api/metric_alerts.py | New: thin /api/v1/monitors/alert-rules subresource contract; current monitor prefix is /api/v1/monitors. Mount this router before the existing /monitors/{monitor_id} routes in routing.py. |
| startup/jobs.py | Add one stable metric evaluation job; use SingleOwnerScheduler plus per-rule concurrency checks. |
| core/subjects.py | Add metric alert subjects under existing `alert.>` namespace and validated payload helper. |
| services/notification_routing.py and notification delivery receipts | Reuse plan 02 dispatch/outcome behavior; no alternate notification channel. |

Initial mode is a bounded scheduled batch in the existing application scheduler, not a new dedicated process/deployment role. Confirm scheduler ownership in supported deployment topologies and support shutdown/time budgets. If later throughput demands a dedicated loop, change ownership explicitly rather than registering both.

## Core function plan

| Callable | Responsibility |
| --- | --- |
| list_metric_definitions() -> definitions | Stable key/unit/comparators/source fields and supported target kinds; no arbitrary expression parser |
| get_metric_availability(db, targets, now) -> availability | Supported identity + actual sample coverage/freshness/cadence |
| validate_metric_rule(config, catalog, target, destination) -> validated config | Finite values, unit, direction, duration/gap limits, hysteresis, edit scope, sink eligibility |
| read_metric_windows(db, requested_windows) -> grouped samples | Batch by storage/source/metric, bounded raw windows, preserve source/sample identity and timestamp |
| evaluate_rule(config, prior_state, samples, now) -> EvaluationDecision | Pure transitions, completeness, timers, reason codes, proposed firing/recovery event |
| preview_rule(db, config, window, actor, now) -> PreviewResult | Same catalog/evaluator over bounded history; no writes, no notification |
| persist_rule_transition(db, rule_id, expected_revision, decision) | Lock/version check; persist state and new event in same transaction, no external send |
| evaluate_due_rules(now, limit) -> BatchSummary | Bounded claims/reads/decisions; no per-rule-per-sample SQL loop |
| publish_pending_metric_events(limit) -> PublishSummary | Persisted event-as-outbox; JetStream publish acknowledgement and stable message identity; retry after failure |

Avoid adding a generic outbox framework: MetricAlertEvent already represents the transition the UI needs; small publish fields give that same row a reliable delivery role.

## Rule/state contract

Rule stores explicit target ref, metric/source policy, threshold/comparator, unit, breach duration, recovery threshold/duration, sample-gap/freshness policy, enabled state, severity, destination/routing reference, revision and audit metadata. Target types start only where adapters can provide truthful history; do not imply all inventory entities have CPU telemetry.

State stores last evaluated sample cursor, pending/recovery start, current assessment, and separately whether a firing incident is open. **Unknown due to stale data must not erase the open incident.** Fresh recovery after Unknown still needs the correct recovery transition.

| Condition | Evaluation behavior |
| --- | --- |
| Disabled rule | Disabled; no firing/recovery dispatch |
| Unsupported target/metric/configuration | Invalid/unavailable configuration with reason; reject enabling |
| No fresh usable samples / excessive gap | Unknown; reset unproven duration, retain open incident identity |
| Fresh normal condition without open incident | Normal |
| Sustained breach not yet proven | Pending |
| Breach duration met with required coverage | Firing once for the incident |
| Fresh valid recovery condition with open incident | Recovering, then Normal + one recovery event after duration |

Strictly specify >=/>/<=/< equality behavior, hysteresis direction and allowed zero durations. Reject NaN/infinity and units that do not match catalog metadata. Missing samples are not zero; counter rates require a supported conversion rather than treating counters as gauges.

Use collected-at time and trusted receipt bounds, not browser time. Duplicate/out-of-order samples cannot extend a pending interval twice. On source change or rule revision, reset/reassess relevant windows; never combine unrelated sources into a synthetic sustained breach. Hourly averages do not prove continuous threshold violation—preview must disclose aggregation limits or request raw data.

## Persistence and delivery

- MetricAlertRule: validated configuration and revision. MetricAlertState: unique rule state, sample cursor and incident identity. MetricAlertEvent: unique transition identity including rule revision/incident, state change timestamps, safe context, publish status.
- Use row-level locking/revision checks as well as scheduler ownership; manual edits/preview and stale batches can race even with a single scheduled owner.
- Commit state + transition together. Publish after commit with stable NATS message identity and acknowledgement; retry unpublished events on the next bounded pass.
- The notification worker's `alert.>` filter and CB_EVENTS subjects already cover the proposed namespace; verify end-to-end delivery, not just constant names.
- Rule destination choice must be enforced by persisted routing intent. Existing severity routes must not broaden a specifically selected destination or suppress recovery merely because recovery severity falls below the original firing floor. Define recovery delivery to the incident's eligible destinations, rechecking disabled/deleted targets.
- Plan 02 per-sink receipts prevent replaying already accepted targets. Document ambiguous provider acceptance; do not promise exactly-once webhooks.
- Edits/disable/delete do not fabricate recovery. Preserve active-incident audit/event state and explicitly define pending-event handling; user-requested deletion must not orphan endless retries.
- Retention for terminal events/receipts exceeds replay horizon; keep state needed by active incidents.

## APIs, migrations, and tests

Proposed operations under /api/v1/monitors/alert-rules: list/create/read/update/delete rules, metric catalog/availability, pure preview, state/event reads. Register static catalog/preview paths before rule-ID routes, and mount the entire subrouter before the existing monitor-ID router so “alert-rules” is not parsed as a monitor ID. Defaults: admin-only mutations while matching existing read scopes; narrow non-admin editing must be an explicit policy choice, not inferred from a visible Monitors page. No maintenance/escalation/acknowledgement API.

- [ ] Pure evaluator truth-table tests with injected clocks and irregular/gapped/out-of-order sample sequences.
- [ ] Query batching/source deduplication and preview/live evaluator parity tests.
- [ ] Rule revision, competing batches, crash-before-publish, crash-after-publish-ack, NATS disconnect, receipt replay and deleted destination tests.
- [ ] Migration tests for model discovery, uniqueness/FKs/indexes, upgrade/rollback and active-state preservation.
- [ ] Worker registration/topology test proves only intended owner runs; bounded shutdown and no unowned loop.
- [ ] End-to-end real state transition → existing stream → notification worker → fake provider → recorded outcome, including recovery after stale data.
- [ ] Measure evaluation cost, backlog and transition-to-dispatch latency using a stated fixture before release claims.

No arbitrary metrics language, external metric ingestion, second scheduler/queue, or advanced alert policy.
