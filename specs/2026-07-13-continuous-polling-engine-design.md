# Design — Continuous Polling Engine (Observability, Slice 1)

**Date:** 2026-07-13
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude

## Context & motivation

CircuitBreaker's "enterprise observability like Zabbix" goal (network history, packet loss,
bandwidth tracking) decomposes into several independent subsystems. This spec covers **only the
first slice: the continuous polling engine** plus the ICMP/TCP/HTTP collectors that validate it
end-to-end. Later slices (SNMP interface bandwidth, triggers/alerting, history dashboards, device
templates) each get their own spec and build on this foundation.

### What exists today (and why it's insufficient)

- `services/monitor_service.py` — `HardwareMonitor` rows and a `run_all_monitors_job` APScheduler
  job that loops over enabled monitors **sequentially** each tick, running an ICMP/TCP/HTTP/SNMP
  up/down cascade. Weaknesses: sequential (one slow/timing-out SNMP probe stalls the whole cycle),
  single-process, **host-granular** (one interval per host, fixed metric set), and up/down + latency
  only — no packet loss, no per-metric items, no horizontal scale.
- `workers/telemetry_collector.py` — a separate interval poller focused on Proxmox-style
  cpu/mem telemetry.
- `db.models.TelemetryTimeseries` — a generic `(entity_type, entity_id, metric, value, source, ts)`
  time-series table backed by TimescaleDB hypertables (migrations 0041/0048/0050).
- `workers/rollup_worker.py` — trend aggregation. Retention settings already exist.

The engine below **evolves** this: it replaces the host-granular sequential monitor with a durable,
horizontally scalable, **item-based** poller, and reuses the existing time-series store, rollup, and
retention rather than inventing new storage.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Scale target | Mid-market (~500–5k items): scheduler → NATS queue → N poll workers, batched inserts |
| Poll granularity | **Item-based** (Zabbix-style `MonitorItem`); replaces `HardwareMonitor` via migration |
| Overdue policy | **Poll-once-now, no backfill**; jittered catch-up to avoid thundering herd; self-healing |
| Packet loss/jitter | **In scope** for this spec (multi-packet ICMP) |
| Old `run_all_monitors_job` | **Retired** (not run in parallel) |
| Storage | Reuse `TelemetryTimeseries` hypertable (+ `item_id` dimension); existing rollup + retention |

## Scope

**In scope**
- `MonitorItem` model + CRUD + migration from `HardwareMonitor`.
- Durable scheduler (single active instance via advisory lock).
- NATS JetStream `monitor.poll` queue + horizontally scalable poll workers.
- Collectors: ICMP (avail, latency, packet loss, jitter), TCP (avail, latency), HTTP (avail,
  latency, status class).
- Batched sample writes to `TelemetryTimeseries`.
- Loud failure semantics for missing tools/unreachable targets.

**Out of scope (own specs later)**
- SNMP interface counters / bandwidth & throughput.
- Trigger / alerting expression engine.
- History-graph UI beyond existing telemetry rendering.
- Device templates / auto-binding.
- Unifying `IntegrationMonitor` (public status pages) — left untouched for now.

## Architecture

```
                 ┌──────────────────────────────────────────┐
   Postgres      │  MonitorItem (next_due_at indexed)         │
   (state)       └──────────────────────────────────────────┘
                        ▲ advance next_due          ▲ CRUD
                        │                            │
   ┌────────────┐  select due (SKIP LOCKED)     ┌────────────┐
   │ Scheduler  │──── publish monitor.poll ────▶│  NATS/JS   │
   │ (singleton,│                                │  stream    │
   │  adv lock) │                                └─────┬──────┘
   └────────────┘                                      │ durable consumer (queue group)
                                                       ▼
                                          ┌───────────────────────────┐
                                          │  Poll worker(s)  (N)        │
                                          │  collector → samples        │
                                          │  batch writer → hypertable  │
                                          └───────────────────────────┘
                                                       │ batched INSERT
                                                       ▼
                                          TelemetryTimeseries (TimescaleDB)
                                                       │
                                          existing rollup_worker → trends
```

### Scheduler (single active instance)

- Guarded by a Postgres advisory lock (reuse `core/job_lock.py`) so exactly one scheduler is active
  even with multiple backend processes.
- Loop cadence ~1 s. Each tick:
  1. `SELECT id, ... FROM monitor_items WHERE enabled AND next_due_at <= now()
     ORDER BY next_due_at FOR UPDATE SKIP LOCKED LIMIT :batch`.
  2. For each row, publish a `monitor.poll` JetStream message `{item_id, check_type, host, params,
     scheduled_for}`.
  3. **Immediately** set `next_due_at = now() + interval_secs` (+ small deterministic jitter) so the
     item is not re-selected on the next tick. Commit.
- Because `next_due_at` is advanced at *enqueue* time and lives in the DB, a scheduler or worker
  crash self-heals: on restart, whatever is due is simply selected again. There is no in-memory
  "running" state to strand (contrast: the discovery scan path leaves jobs wedged in `running`).
- **Overdue / thundering herd:** after downtime many items may be due at once. The `LIMIT :batch`
  per tick plus per-item deterministic jitter spreads catch-up polls across roughly one interval.
  No backfill — a gap in history is a real, visible gap.

### Poll workers (horizontally scalable)

- JetStream **durable pull consumer** in a queue group; run N replicas to scale.
- Per message: dispatch to the collector for `check_type`, enforce a **hard per-poll timeout**
  (from `params.timeout`, default per check), produce `list[Sample]`, hand to the batch writer,
  `ack`. On collector exception/timeout: emit an `avail=0` sample with a recorded `error_reason`
  and still `ack` (the failure *is* the datum).
- **Delivery semantics:** at-least-once. A duplicate delivery writes one extra near-duplicate
  sample — harmless for time-series. An optional short Redis lease keyed `poll:{item_id}:{window}`
  prevents two workers polling the same item in the same window under redelivery.
- **Backpressure:** provided by JetStream (unacked messages redeliver; consumer `max_ack_pending`
  bounds in-flight work). Bounded async probe pool per worker caps concurrent sockets.
- Explicitly **not** `asyncio.create_task` on the API event loop (the discovery-scan anti-pattern).

### Batch writer

- Each worker buffers `Sample` rows and flushes batched `INSERT`s to `TelemetryTimeseries` on a
  timer (~1 s) or size threshold (~500 rows), whichever first, with a flush on shutdown.
- Keeps ingest cheap at 5k items × mixed intervals.

## Data model

### New table: `monitor_items`

| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| target_type | str | `hardware` \| `compute_unit` \| `external_node` \| `ip` |
| target_id | int null | null when `target_type = ip` |
| host | str | resolved IP/hostname actually probed |
| check_type | str | `icmp` \| `tcp` \| `http` (snmp reserved for next spec) |
| params | JSONB | `{ports, url, packet_count, timeout, expect_status, ...}` |
| interval_secs | int | per-item interval |
| enabled | bool | |
| next_due_at | timestamptz | **indexed**; drives scheduling |
| last_polled_at | timestamptz null | |
| last_status | str null | `up` \| `down` \| `error` |
| consecutive_failures | int | for future trigger/flap logic |
| created_at / updated_at | timestamptz | |

Index: `(enabled, next_due_at)` to make the due-selection query cheap.

### Samples: reuse `TelemetryTimeseries`

- Add a nullable `item_id` FK dimension (keep `entity_type`/`entity_id` populated for back-compat and
  generic entity queries).
- Metrics emitted:
  - ICMP: `avail` (1/0), `latency_ms` (avg), `latency_min_ms`, `latency_max_ms`,
    `packet_loss_pct`, `jitter_ms`.
  - TCP: `avail`, `latency_ms`.
  - HTTP: `avail`, `latency_ms`, `http_status_class` (2/3/4/5).
- Trends via existing `rollup_worker`; raw pruning via existing retention settings.

## Collectors

Each collector is a pure function `collect(host, params) -> list[Sample]` with no DB access
(testable in isolation, mockable transport):

- **ICMP** — send `packet_count` (default 5) echo requests; compute avail (any reply),
  min/avg/max latency, `packet_loss_pct = lost/sent`, jitter (mean abs consecutive delta). Extend
  `monitor_service.probe_icmp` (ping3 with `/bin/ping` fallback) to multi-packet. Missing binary →
  `avail=0`, `error_reason="icmp_unavailable"`.
- **TCP** — connect to each `params.ports`; avail if any connects; latency of first success.
- **HTTP** — HEAD (fallback GET) to `params.url`; avail on response, record latency and status
  class; honor `params.expect_status` if set.

## Reliability / repeatability guarantees

1. **Self-healing after restart** — scheduling state lives entirely in `monitor_items.next_due_at`;
   no in-memory running state, so process restarts resume cleanly.
2. **Loud failure** — missing tools / unreachable targets produce an explicit `avail=0` +
   `error_reason` sample, never a silent success.
3. **Deterministic methodology** — fixed packet count and fixed timeouts per item make results
   reproducible given network conditions.
4. **No double-scheduling** — advisory-lock singleton scheduler + `FOR UPDATE SKIP LOCKED`.
5. **Bounded catch-up** — `LIMIT :batch` + per-item jitter prevents post-downtime probe storms;
   poll-once-now with no backfill keeps history honest.

## Migration / coexistence

- One-time migration converts each **enabled** `HardwareMonitor` into an ICMP `MonitorItem`
  (interval preserved) plus TCP `MonitorItem`s for its configured ports.
- Retire `run_all_monitors_job` and its APScheduler registration.
- Keep `HardwareMonitor` table until cutover is verified (drop in a follow-up migration).
- `IntegrationMonitor` (public status pages) is untouched; note future unification.

## Testing

- **Unit:** each collector against mocked ping/socket/http (success, timeout, missing-tool);
  scheduler due-selection with `SKIP LOCKED`; `next_due_at` advancement + jitter; overdue
  self-heal (many due at once → bounded batch).
- **Integration:** enqueue → poll → batched write against a fake target; kill a worker mid-cycle and
  assert resumption with no wedged items; duplicate delivery tolerated (lease prevents concurrent
  double-poll).
- **Load:** 5k mixed-interval items — assert scheduler tick stays < cadence and batch-write
  throughput keeps the queue drained.

## Open questions for the plan phase

- Should the scheduler live inside the existing backend process (advisory-lock guarded) or as its
  own supervised worker in `supervisord.mono.conf`? Leaning own worker for isolation.
- Exact NATS subject/stream naming and consumer config (`max_ack_pending`, ack wait) — settle when
  wiring JetStream.
- Whether the `item_id` addition to `TelemetryTimeseries` warrants a partial index for
  per-item history queries (likely yes; confirm with the history-UI slice).
