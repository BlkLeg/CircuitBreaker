# Metric Alert Rules

A metric alert rule watches one collected hardware gauge on one host and
notifies a destination when it stays past a threshold. It answers a different
question from a monitor: a monitor asks "is the probe still succeeding?", a rule
asks "has this measured value been bad for long enough to matter?"

**Where:** Monitors → Alert rules. Any signed-in user can read the rules and
their states; admins create, edit, delete and preview them.

## What a rule is

One rule = one metric on one hardware target, with a threshold, a direction and
two durations:

- **Threshold and comparator** — the condition that counts as a breach, e.g.
  `CPU utilization > 90%`.
- **Breach duration** — how long the condition must hold, continuously, before
  the rule fires. A spike that lasts one sample never sends anything.
- **Recovery threshold and recovery duration** — the condition must hold for
  this long before the incident closes and a recovery notification is sent.
- **Freshness** — how old the newest sample may be before the rule stops
  evaluating and reports *Not evaluating* instead of guessing.
- **Maximum gap** — the largest hole between two samples the rule will measure
  across. Samples arriving with wider gaps restart the measurement.

## The metrics

Rules read the gauges telemetry collection already stores. The catalog is
closed — a rule cannot watch anything else, and the unit is fixed per metric:

| Metric | Unit | Default freshness / max gap |
|---|---|---|
| CPU utilization (`cpu_pct`) | `%` | 180s / 180s |
| Memory utilization (`mem_pct`) | `%` | 180s / 180s |
| Disk utilization (`disk_pct`) | `%` | 300s / 300s |
| Temperature (`temp_c`) | `°C` | 180s / 180s |
| Power (`power_w`) | `W` | 180s / 180s |

All five are hardware-only. Compute units and services have no metric path
here — for those, monitors are the tool.

## Recovery sits on the safe side

The recovery threshold must sit at or **on the safe side of** the firing
threshold: at or below it for `>` and `>=`, at or above it for `<` and `<=`.
A rule that fires when CPU passes 90% cannot recover while CPU is still above
90% — recovery at 95 would mean the alert never closes. The form checks this
before saving; the server checks it again.

## The six states

| State | Meaning |
|---|---|
| **Firing** | The breach held for the full breach duration; a notification was dispatched |
| **Pending** | The threshold is breached but the breach duration has not elapsed |
| **Recovering** | The recovery condition is holding but the recovery duration has not elapsed |
| **Normal** | On the safe side of the threshold |
| **Not evaluating** | The rule cannot conclude anything from the samples it has |
| **Disabled** | The rule is turned off |

**Not evaluating** has three different causes — the target has never reported
this metric, it has stopped reporting recently enough, or it reports with gaps
too wide to measure across — and they are three different fixes. The rule list
cannot tell them apart (the list carries the state, not the reason); open the
rule and read the **Evaluation preview**, which reports the evaluator's own
reason, or check the host's telemetry integration.

The preview is honest about what it is: what this rule *would* conclude from the
samples already stored over the chosen window. It is an evaluation of collected
telemetry, not a prediction of the future, and it sends nothing.

## Enabling a rule and destinations

Rules are created disabled. An **enabled** rule needs a notification
destination that exists and is enabled — Settings → Notifications owns
destinations; a rule only points at one. Until an enabled destination exists,
a rule can be built and saved but the Enabled control stays inert and says
where to fix it.

## Two silences worth knowing

The engine deliberately does not fabricate recoveries in two cases, and both
are stated where they happen rather than left as surprises:

- **Editing a rule that is firing** resets its state and starts evaluating
  again from the next sample. Its open incident stays open, and the recovery
  notification for the alert already delivered will never be sent. The editor
  warns before the save.
- **Deleting a rule** deletes its state with it. An open incident is closed
  silently, and no recovery notification is sent for the alert already
  delivered. The delete confirmation names this when it applies.

## Who can do what

| Action | Who |
|---|---|
| Read the rules, their states and open incidents | Any signed-in user |
| Create, edit and delete rules | Admin |
| Preview a rule against stored samples | Admin |

Rules are evaluated on the server's schedule, not the browser's — the list
refreshes on open, after a change, and on retry; it does not poll. A firing
rule shows its open incident ID, the correlation handle that ties the alert to
the notification that carried it.
