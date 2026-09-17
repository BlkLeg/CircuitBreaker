# Metric alert rules — the surface for a shipped engine

**Status:** design, approved 2026-09-17. Implements the UI half of
[approved-UI plan 08](approved-ui/08-metric-alert-rules.md), whose task list A1–A8 is
unchecked although its backend landed. Supersedes nothing.
**Baseline:** `dev` @ `55592c99`, `VERSION` = `0.4.2`.
**Scope:** the Monitors → Alert rules tab — the rule list, the editor, the evaluation
preview, and the vocabulary that reports what the shipped evaluator decided. No backend
change.

---

## 1. What is actually broken

Nothing is broken. Something complete is unreachable.

The metric alerting engine is built, mounted and scheduled:

| Piece | Where |
|---|---|
| Catalog, preview, CRUD routes | `api/metric_alerts.py`, mounted at `/api/v1/monitors/alert-rules` (`api/routing.py:419-424`) |
| Rule and state models | `MetricAlertRule` (`db/models/monitors.py:29`), `MetricAlertState` (`:61`) |
| Validation and persistence | `services/monitoring/metric_rules.py` |
| The evaluator | `services/monitoring/metric_evaluator.py` |
| Scheduled evaluation | `workers/metric_alert_worker.py`, registered as `metric_alert_evaluation` (`startup/jobs.py:573`) |
| Unit coverage | `tests/services/test_metric_alert_rules.py` |

`grep -rn "metric-alerts\|metric_alerts\|metricAlerts" apps/frontend/src` returns nothing.
Every request an operator could make of this engine is unreachable: they cannot create a
rule, see one, or learn that one is firing. The evaluation job runs on every install and
transitions state nobody can observe.

This is the same shape as INC-10, INC-11, INC-12 and INC-13 — implemented capability with
no way to use it — and the same shape as `FlapIncident`, closed the day before this design
was written.

## 2. Goals

1. An admin can create, inspect, edit and delete a metric alert rule.
2. The page reports what the evaluator actually decided, at the granularity the evaluator
   decided it — six assessments and nine reason codes, not "OK" and "Alerting".
3. Thresholds can be tried against real stored samples before a rule is enabled.
4. The two places where this engine deliberately declines to fabricate a recovery are
   stated to the operator rather than left as a surprise.
5. Nothing is widened: the admin gate, the destination requirement and the revision check
   are the backend's, and the UI mirrors them.

## 3. Non-goals

- **No multi-target rules.** The catalog is per-hardware (§4.1); one rule, one target.
- **No templates, cloning or bulk enable.** YAGNI until somebody has ten rules.
- **No incident history view.** `open_incident_id` is displayed as a correlation handle,
  not as the front door to a timeline that does not exist.
- **No routing changes.** A rule points at an existing notification sink; Settings →
  Notifications continues to own destinations.
- **No widening of the admin gate.** Editors read; admins write. See §7.
- **No backend change of any kind.** If the implementation finds it needs one, that is a
  finding to escalate, not a task to absorb.

## 4. The contract, as shipped

### 4.1 The catalog is five hardware gauges

`services/monitoring/metric_catalog.py` defines exactly `cpu_pct`, `mem_pct`, `disk_pct`,
`temp_c` and `power_w`, each with its own `unit`, its `comparators`, and its own
`default_freshness_s` / `default_max_gap_s` — `disk_pct` gets 300s where the others get
180s. Every definition declares `target_types: ["hardware"]`.

So the target selector is a **hardware** selector. Compute units and services have no
metric path here, and the UI must not offer one.

The unit is not free text: `validate_metric_rule` rejects a payload whose `unit` differs
from the catalog's. The form derives unit and comparator options from the catalog rather
than presenting a list of its own.

### 4.2 Six assessments, nine reason codes

`Assessment` is `disabled | unknown | normal | pending | firing | recovering`
(`metric_evaluator.py:12`). The reason codes it emits are `disabled`, `no_samples`,
`stale_samples`, `sample_gap`, `condition_not_met`, `recovered`, `recovery_duration`,
`threshold_duration` and `breach_duration` (`metric_evaluator.py:66-119`).

Three of those reason codes — `no_samples`, `stale_samples`, `sample_gap` — all surface as
assessment `unknown`, and they mean three different things with three different fixes: the
target has never reported this metric, it has stopped reporting recently enough, and it is
reporting with holes too large to evaluate across. Collapsing them into one "Unknown" chip
would discard a distinction the evaluator went to real trouble to make.

**Where a reason code can actually be read, established while planning.** `MetricAlertState`
persists `assessment` and **no reason code** (`db/models/monitors.py:61-73`), and `_out`
copies only `assessment` and `open_incident_id` (`metric_rules.py:58-62`). An
`EvaluationDecision`'s reason is produced during evaluation and discarded. The only endpoint
that returns one is the admin-only `/preview`, and it speaks about a *prospective* rule.

So the rule list shows six assessments and no reasons, and it must not invent one: a row
reading **Not evaluating** points at where the reason can be found rather than guessing
between the three. The nine-code vocabulary is still built, because the editor's preview is
where a reason arrives. Closing this properly is a backend change — a `reason_code` column on
`MetricAlertState`, set in `persist_rule_transition` from the decision already in hand, and a
field on `MetricAlertRuleOut` — and §3 puts that outside this design rather than inside it.

> **Closed 2026-09-17, on the author's instruction.** Migration
> `0116_metric_alert_reason_code` adds the nullable column, `persist_rule_transition` records
> the decision's reason, and `MetricAlertRuleOut` carries it. The list now distinguishes the
> three, for every reader rather than only for an admin who opens the preview. The column is
> nullable with no backfill: NULL means "not evaluated since the column existed", which is
> true of every pre-existing row, and inventing a reason for a state decided before the column
> existed would be fabricating evidence.

### 4.3 Validation, and what it implies for the form

`metric_rules.py:34-56`, in order:

1. Metric must exist in the catalog and the unit must match it.
2. The comparator must be one the metric supports.
3. Thresholds must be finite.
4. **Recovery direction must match the comparator** — at or below the threshold for `>` and
   `>=`, at or above it for `<` and `<=`.
5. The target must exist.
6. **An enabled rule requires a `sink_id`, and that sink must exist and be enabled.**

### 4.4 Optimistic concurrency

`MetricAlertRuleUpdate` carries `revision` (`gt=0`) and `update_rule` raises
`ConflictError("The rule changed; reload it and try again.", error_code="stale_rule")` on a
mismatch. Same shape as the assessment identity, and it gets the same treatment: keep the
operator's values, re-read, explain.

### 4.5 Preview

`POST /preview` takes a whole prospective rule plus `window_seconds` (60–86400, default
3600) and returns `assessment`, `reason_code`, `sample_count`, `window_start`/`window_end`,
`limitations` and `would_emit`. It reads up to 5000 samples (`read_metric_window`), and it
requires **admin**.

It answers "what would this rule conclude from the samples already stored". It is not a
prediction, and §6.3 keeps the copy honest about that.

## 5. Shell and files

`MonitorsPage.jsx` is 476 lines holding seven pieces of state for the monitor grid
(`monitors`, `expandedIds`, `detailsById`, `busyId`, `editing`, `confirmState`, `now`).
Threading a tab through that is worse than moving it: its body moves **verbatim** into
`components/monitors/MonitorsListTab.jsx`, and `MonitorsPage` becomes a shell of about 90
lines — `Tabs` with `panelPropsFor`, `?tab=monitors|alert-rules`, an unknown value falling
back to `monitors`. The move and any change to it are separate commits, because a move and
a rewrite in one commit cannot be reviewed.

```
pages/MonitorsPage.jsx                  (rewrite)  tab shell only
components/monitors/
  MonitorsListTab.jsx                   (create)   today's page body, moved
  MetricAlertRulesPanel.jsx             (create)   list, chips, row actions
  MetricAlertRuleEditor.jsx             (create)   form + live preview
  MetricAlertStateChip.jsx              (create)   assessment -> chip
hooks/useMetricAlertRules.js            (create)   list, CRUD, catalog, sinks
hooks/useRulePreview.js                 (create)   debounced preview
lib/metricAlerts.js                     (create)   vocabulary + client validation
api/client.jsx                          (modify)   metricAlertsApi
styles/monitors.css                     (modify)   rule list and chips
```

Reused rather than rebuilt: `EntityPicker` for the hardware target — it already takes
`types` and a `monitor` action; `notificationsApi.listSinks` (`api/client.jsx:661`) for the
destination; `Tabs`, `Panel`, `Banner`, `EmptyState`, `Drawer`, `SkeletonTable` and
`ConfirmDialog` from `components/common/`.

## 6. Behaviour

### 6.1 `lib/metricAlerts.js`

`describeRuleState({ assessment, reason_code })` returns `{ tone, title, detail, guidance }`,
following `lib/vulnerabilityAssessment.js`'s shape. **Every reason code carries a title and a
detail**, and guidance is required for the five an operator can act on — `disabled`,
`no_samples`, `stale_samples`, `sample_gap`, `threshold_duration`.

An earlier draft of this section demanded guidance for all nine. Four of them —
`condition_not_met`, `recovered`, `recovery_duration`, `breach_duration` — describe normal
operation, and inventing an action for a healthy state is the guessing
`vulnerabilityAssessment.js` explicitly refuses ("an unknown code yields no guidance rather
than a guess"). The test asserts description for all nine and guidance for the actionable
five, which still catches the defect that motivated the rule: a reason reaching the operator
with something to fix and no way to fix it, as `credential_unavailable` did in notification
delivery and `fleet_limit` nearly did on Intel.

The lib also mirrors §4.3's rules 1–4 client-side. Duplicating server validation is
normally worth resisting; it is deliberate here, because the alternative is a form that
only reveals a backwards recovery direction after a round trip. The mirror is a
convenience, never the authority: the server's answer always wins, and §7 keeps its
field errors rendered.

### 6.2 `useMetricAlertRules`

Owns the rule list, the catalog, the sink list, and create/update/delete. It exposes
`rules`, `catalog`, `sinks`, `loading`, `error`, `reload`, and the three mutations. The
three reads are independent — `Promise.allSettled`, not `Promise.all`, so a failing sink
list degrades the destination picker rather than blanking the rules.

### 6.3 `useRulePreview` — debounced, with three guards

Preview fires 600ms after the form settles. Three rules keep it truthful:

- **A request token drops late responses**, the guard `VulnerabilityPanel` already uses, so
  an assessment computed for values the operator has since changed can never render.
- **It does not POST a rule that fails client validation.** The local message is shown
  instead of a round trip the server will refuse.
- **It is skipped entirely for non-admins**, who would receive a 403. They see the rule's
  real assessment, which is the part they can use.

The panel renders `assessment`, `sample_count`, the window, every entry in `limitations`,
and `would_emit`. Its heading names what it is — an evaluation against stored samples over
the chosen window. `sample_count: 0` with `no_samples` is the ordinary first-run state and
reads as "this target has not reported this metric", never as `normal`.

### 6.4 Enabling, and the destination it requires

Rules default to `enabled: false` (`MetricAlertRuleCreate`), and §4.3 rule 6 refuses to
enable one without a live destination. The editor follows that grain rather than fighting
it: a rule can always be built and saved disabled, and the **Enable** control is inert,
with an explanation and a link to Settings → Notifications, when no enabled sink exists.
The server's validation error is still surfaced against the field if it arrives anyway.

### 6.5 Two silences the UI must break

From `update_rule`'s own comment: *"Disabling/editing does not fabricate recovery. Preserve
an open incident."*

- **Editing a rule that is firing** resets its assessment to `unknown`, clears
  `pending_since` and `recovery_since`, and **keeps `open_incident_id`**. No recovery
  notification is sent, and none will be. When the rule being edited has an open incident,
  the editor says this before the save, not after.
- **Deleting a rule** deletes the row (`delete_rule`, `metric_rules.py:128`), and with it
  any open incident — so the recovery notification for an alert already delivered never
  arrives. The confirm names that consequence.

Both use the ordinary `ConfirmDialog` the monitor tab already uses (`MonitorsPage.jsx:468`),
with copy that names what happens. `HighRiskConfirmDialog` is deliberately **not** used:
it demands a typed phrase, which is right for clearing a lab and disproportionate for one
rule. The honesty belongs in the sentence, not in the friction.

## 7. Errors, permissions, honesty

- **Read-only for non-admins.** Create, edit, delete and preview are `require_role("admin")`
  (`api/metric_alerts.py`); list and get are open to any signed-in user through the router's
  `require_auth`. The tab mirrors that exactly: everyone sees the rules, their assessments
  and their open incidents; only an admin sees New, Edit, Delete and the preview. Frontend
  visibility tracks the backend gate and nothing is widened.
- **A 409 keeps every entered value**, explains that the rule changed, and re-reads it.
- **Field errors** come through the axios client's existing normaliser
  (`buildUserMessage` and its field-error extraction) rather than a second parser.
- **Loading** is `SkeletonTable`. **Errors** are a `Banner` with Retry that leaves the tab
  usable and the other tab reachable.
- `open_incident_id` is shown on a firing rule as the correlation handle it is, so an alert
  can be tied to the notification that carried it.
- **No polling.** The list refreshes on mount, after a mutation, and on an explicit
  refresh. A rule's assessment changes on the evaluator's schedule, not the browser's, and
  a per-rule poll loop would buy nothing the operator asked for.

## 8. Testing

**Frontend**

- `metric-alerts-lib.test.js` — every one of the six assessments has a title and tone;
  **every one of the nine reason codes has a detail, and each of the five actionable ones has
  non-null guidance** (the test that would have caught `fleet_limit`); recovery-direction
  validation in both comparator directions; unit and comparator derivation from a catalog
  fixture.
- `use-rule-preview.test.jsx` — debounce; a late response for superseded values is
  dropped; no request when client validation fails; no request for a non-admin.
- `metric-alert-rules-panel.test.jsx` — each assessment renders its own chip; a row never
  renders a reason the list endpoint did not return; empty state; admin versus viewer
  controls; the delete confirm names an open incident when there is one.
- `metric-alert-rule-editor.test.jsx` — catalog drives unit and comparators; recovery
  direction refused client-side; Enable inert with no available sink, with the link;
  a 409 keeps entered values; editing a firing rule warns before saving.
- `monitors-page.test.jsx` — tabs, `?tab=` deep link, unknown-value fallback. The existing
  monitor-page tests move to `MonitorsListTab` **unchanged**; needing to edit one means the
  move was not a move.

**Backend** — none. The contract is shipped and covered by
`tests/services/test_metric_alert_rules.py`. No route, schema or service changes here.

**E2E** — `/monitors?tab=alert-rules` joins the axe spec. New tablist, new chips, new form;
the Intel round proved that suite catches serious violations the unit tests cannot see
(a link at 1.23:1 contrast).

**Gates** — `make lint` and `make verify`. Because nothing under `apps/backend/src/app`
changes, `verify` is the correct gate rather than `verify-full`; if the implementation does
touch backend source, that is §3's escalation and the gate changes with it.

## 9. Documentation

No existing document owns monitor alerting. `docs/metrics.md` is the Prometheus exposition
reference — its mentions of "alert" are about alerting on exported series, a different
subject — and `docs/telemetry.md` covers how the gauges are *collected* (iDRAC, iLO, UPS,
SNMP), not what evaluates them.

So this capability gets its own page, matching the per-feature convention already used by
`discovery.md`, `knowledge-base.md`, `audit-log.md` and `tls-certificates.md`:
**`docs/metric-alerts.md`** — the five catalog metrics and their units, the six assessments
and nine reason codes in a table, the destination requirement, the breach/recovery duration
semantics, and the two non-recoveries from §6.5. It is linked from `docs/index.md`, whose
Monitoring bullet (`docs/index.md:41`) currently stops at "live status, uptime history, and
latency history" and gains threshold alerting.

## 10. Acceptance

- [ ] An admin can create a rule against a hardware target and one of the five catalog
      metrics, and see it listed with its assessment.
- [ ] Each of the six assessments renders distinctly. The three `unknown` reasons read as
      three different problems **in the editor's preview** — the list cannot distinguish them
      until `MetricAlertState` persists a reason code, which §4.2 records as a follow-up.
- [ ] Adjusting a threshold re-previews within a second, and a superseded response can
      never overwrite a newer one.
- [ ] A rule cannot be enabled with no live destination, and the page says why and where
      to fix it.
- [ ] Editing a firing rule warns that no recovery will be sent; deleting one says the
      open incident goes with it.
- [ ] A viewer sees every rule and no control that would fail.
- [ ] `make lint` and `make verify` pass; the coverage ratchet is unchanged.
- [ ] `docs/metric-alerts.md` exists and is linked from `docs/index.md`.
