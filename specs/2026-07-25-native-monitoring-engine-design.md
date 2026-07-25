# Native Monitoring Engine — Design (Uptime Kuma port)

**Date:** 2026-07-25
**Status:** Approved
**Prior art:** `specs/2026-07-13-continuous-polling-engine-design.md` (retrieve via `git show bbea2061:specs/...`), vendored reference repo at `uptime-kuma/`

## Context

Circuit Breaker's observability polling engine (merged in `bbea2061`) covers network
reachability of inventory hardware: ICMP, TCP connect, and basic HTTP collectors driven by
`monitor_items` → NATS JetStream → poll workers → TimescaleDB. Separately, an integration
bridge (`IntegrationMonitor` models, `integration_sync_worker`, `uptime-kuma-api-v2`) syncs
monitors from an *external* Uptime Kuma instance.

We want full service monitoring as a native capability: Uptime Kuma's check engine ported to
Python inside the existing polling architecture, a custom frontend (no Kuma UI), and removal
of the external-Kuma bridge. The vendored `uptime-kuma/` repo is a **reference spec only** —
no Node runtime ships. Key reference files: `uptime-kuma/server/model/monitor.js` (beat loop,
retry/state logic), `uptime-kuma/server/monitor-types/*.js` (pluggable checks),
`uptime-kuma/server/notification-providers/*.js` (delivery providers),
`uptime-kuma/server/uptime-calculator.js` (rollups).

## Decisions

| Question | Decision |
|---|---|
| Integration strategy | Port check logic to Python; extend existing polling engine |
| Check-type scope | All four groups: core web/network, push, infra probes, docker/host |
| External Kuma bridge | Replace and remove, with one-time import of `IntegrationMonitor` rows |
| Target model | Standalone monitors with **optional** inventory link |
| Notifications | Reuse NATS `alert.>` pipeline; port 4 providers (Discord, Telegram, ntfy, webhook) |
| Frontend scope | Monitoring dashboard only (no inventory embeds or public status pages this round) |
| Stateful semantics | Retries + PENDING state; maintenance windows. No cert-expiry alerting, no resend-while-down (cert info is still *collected and displayed*) |
| Data model | Evolve `monitor_items` into the first-class monitor entity |
| Nomenclature | Ported code uses Circuit Breaker naming throughout; **zero uptime-kuma references in production code** |

## Nomenclature & provenance

The port is a re-implementation, not a translation: production code (identifiers, comments,
docstrings, config keys, API fields, UI strings, migrations, tests) must carry Circuit
Breaker nomenclature only — no "kuma", "uptime-kuma", or Kuma-specific terms ("beat"/
"heartbeat" as Kuma jargon; CB uses *check*, *sample*, *event*). Concretely:

- Kuma reference-file pointers live **only** in this spec and in plan docs, never in code.
- The vendored `uptime-kuma/` directory stays untracked — add it to `.gitignore` in slice 1
  so it can never be committed; it is deleted locally when the port is complete.
- Existing Kuma-named surface (`IntegrationMonitor` "uptime-kuma" provider strings,
  `uptime-kuma-api-v2` dependency, integration workers) is already scheduled for removal in
  slice 4; after that, `grep -ri "kuma" apps/ docker/ migrations/` must return nothing.
- Kuma semantics are adopted where useful (accepted status ranges, retry/PENDING behavior)
  but described in CB terms in code and docs.

## 1. Data model

Alembic migration evolving `monitor_items` (`apps/backend/src/app/db/models.py:226`):

- Add: `name` (text), `check_type` (text: `icmp|tcp|http|dns|push|postgres|mysql|redis|mongodb|mqtt|smtp|snmp|ntp|rabbitmq|grpc|docker|systemd`), `config` JSONB (per-type settings: URL/method/headers/body/auth/accepted status codes/keyword/JSON query/DNS record type & resolver/connection string/push token/etc.), `max_retries` (int, default 0), `retry_interval_s` (int), `status` (smallint: 0=DOWN 1=UP 2=PENDING 3=MAINTENANCE), `retries_count` (int, default 0), `last_status_change_at`.
- Relax: `target_type`/`target_id` become nullable — a monitor may be standalone or linked to `hardware`/`compute_unit`/`external_node`/`service`.
- Existing rows migrate in place: current `icmp|tcp|http` items get `check_type` from their metric kind, a generated `name` from the linked hardware, and defaults for new columns.

New tables:

- `monitor_events` — `id, monitor_id FK, event_type (up|down|pending|maintenance|paused|resumed), status_from, status_to, msg, duration_s, created_at`. Feeds the event log and drives alerting. Indexed `(monitor_id, created_at)`.
- `maintenance_windows` — `id, name, starts_at, ends_at, rrule (nullable, for recurrence), enabled` plus join table `monitor_maintenance` (`monitor_id`, `window_id`).

Removal (final slice): one-time importer converts `IntegrationMonitor` rows (models.py:1994)
to native monitors, then drop `IntegrationMonitor`/`IntegrationMonitorEvent` models + tables,
delete `workers/integration_sync_worker.py` and `workers/integration_worker.py`, remove the
`uptime-kuma-api-v2` dependency and supervisord entries.

> **Migration convention:** new tables require `0001_init` metadata-bootstrap exclusion-list
> updates; verify with a fresh-volume mono boot.

Samples continue to live in `telemetry_timeseries` (`source="monitor"`, keyed by `item_id`);
uptime % continues through `workers/rollup_worker.py` → `daily_uptime_stats`.

## 2. Collectors

Convert `services/monitoring/collectors.py` into a package `services/monitoring/collectors/`
with one module per family, preserving the existing contract (registered in a `COLLECTORS`
dict, never raise) but extending the return to `CheckResult(samples, up: bool, msg: str,
details: dict)` — `details` carries display data such as TLS cert chain info.

- `net.py` — existing `collect_icmp`, `collect_tcp` (moved).
- `http.py` — full HTTP: method, request headers/body, basic/bearer auth, accepted status
  ranges (Kuma `accepted_statuscodes` semantics), keyword match / negation, JSON-query
  (jsonpath) assertions, TLS certificate capture (subject, issuer, expiry) into `details`.
  Reference: `uptime-kuma/server/model/monitor.js` lines ~681–728.
- `dns.py` — record resolution (A/AAAA/CNAME/MX/TXT/NS/SOA…) against a configurable resolver,
  optional expected-value match. Reference: `uptime-kuma/server/monitor-types/dns.js`.
- `db.py` — postgres (asyncpg), mysql, redis, mongodb: connect + optional query/ping.
- `msg.py` — mqtt, rabbitmq (management API), smtp, ntp, snmp, grpc health/connect.
- `host.py` — docker container state (via docker socket/host config), systemd service state.

Push monitors are **passive**: `POST /api/v1/push/{token}` records a beat directly (no poll
job); the scheduler's due-scan also flags push monitors whose last beat is older than
`interval + grace` and routes them through the same state machine as a failed check.

## 3. State machine & event flow

Runs in `workers/monitor_poll_worker.py` after each check (and in the scheduler for overdue
push monitors), mirroring `monitor.js` beat semantics:

- Success → `UP`, `retries_count = 0`.
- Failure while `retries_count < max_retries` → `PENDING`, increment, reschedule at
  `retry_interval_s` (scheduler honors per-item override of `next_due_at`).
- Failure at limit → `DOWN`.
- Transitions (UP↔DOWN, entry to PENDING, maintenance entry/exit) write a `monitor_events`
  row, publish to NATS `alert.>` (existing notification pipeline, `core/subjects.py`), and
  publish a compact status payload to Redis pub/sub channel `monitor:{id}` for live UI.
- Maintenance: scheduler checks active windows; polls continue, samples recorded, alerts
  suppressed, status reported as `MAINTENANCE`.
- State updates are guarded against the concurrent 2-replica poll workers (row-level update
  keyed on `monitor_items.id`; last-writer-wins is acceptable for status, events are
  append-only).

## 4. Notifications

Monitor transitions become alert events consumed by the existing `workers/
notification_worker.py` (dedup/debounce already handled). Four new `NotificationSink` types
ported from Kuma providers: **Discord**, **Telegram**, **ntfy**, **generic webhook**
(references: `uptime-kuma/server/notification-providers/{discord,telegram,ntfy,webhook}.js`).
Secrets in sink config follow the existing sink credential handling.

## 5. API & real-time

Extend `apps/backend/src/app/api/monitor.py` + `services/monitor_service.py`:

- Monitor-id-based CRUD (`GET/POST/PATCH/DELETE /api/v1/monitors`), with per-`check_type`
  config validated by Pydantic discriminated unions.
- `GET /api/v1/monitors/{id}/events`, `/history` (latency series from telemetry),
  `/uptime` (24h/7d/30d from rollups), `POST /{id}/pause|resume|check-now` (reuses
  `run_immediate_check`).
- `POST /api/v1/push/{token}` — unauthenticated-by-token push beat endpoint (rate-limited).
- Maintenance windows CRUD: `/api/v1/maintenance-windows`.
- WS: `ws_monitors.py` following the `api/ws_telemetry.py` pattern — JWT-first-message auth,
  subscribe by monitor ids, bridges Redis `monitor:{id}` channels.

Existing hardware-scoped endpoints in `monitor_service.py` are reworked to read the evolved
schema (the synthesized per-hardware view becomes a filter: monitors linked to that hardware).

## 6. Frontend

New **Monitors** section in `apps/frontend` (React, follows existing `pages/` +
`hooks/` + `api/` structure):

- **List page** — status dot, name, check type, target, uptime %, Kuma-style heartbeat bar
  built from recent `monitor_events` + latest samples; live updates via a
  `useMonitorStream` hook (modeled on `hooks/useTelemetryStream.js`).
- **Detail page** — latency chart (telemetry history endpoint), uptime stats, event log,
  cert info panel for TLS-capable checks, pause/resume/check-now actions.
- **Create/edit form** — check-type selector driving per-type config fields (mirrors the
  discriminated-union API schema).

All configuration in-app; no terminal steps (per project principle).

## 7. Phasing

1. **Slice 1 — core:** `.gitignore` entry for `uptime-kuma/`; schema migration, state
   machine, full HTTP/DNS collectors (+ moved icmp/tcp), events, alert publishing, REST API,
   WS bridge, dashboard (list/detail/forms).
2. **Slice 2 — passive & maintenance:** push monitors + endpoint, maintenance windows
   (model, scheduler integration, API, UI).
3. **Slice 3 — infra probes & sinks:** db/msg collector families; Discord/Telegram/ntfy/
   webhook sinks.
4. **Slice 4 — host probes & bridge removal:** docker/systemd collectors; IntegrationMonitor
   import + bridge/dependency removal; final nomenclature sweep — `grep -ri "kuma" apps/
   docker/ migrations/` returns nothing.

Each slice is independently shippable.

## 8. Testing

- Collector unit tests against local mock servers/sockets (pattern: existing collector tests),
  including keyword/json-query/status-range matrices for HTTP.
- State-machine transition tests (UP→PENDING→DOWN, retry reset, maintenance suppression).
- Migration test + **fresh-volume mono boot** verification (0001_init exclusion list).
- API tests for CRUD/config validation, push endpoint, pause/resume.
- WS smoke test: transition → Redis publish → WS frame.
- Known pre-existing failures on this host (pg_dump, nmap gate, webhooks) are not regressions.
