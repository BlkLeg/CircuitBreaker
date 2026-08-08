# cbi-agent Slice 2 — Executable Host Telemetry Plan

**Derived from:** `plans/2026-08-04-cbi-agent-slice2-host-telemetry.md` (authoritative for
product and architecture requirements). Also see `specs/2026-07-26-cb-agent-design.md` and
`plans/2026-08-04-cbi-agent-slice1-gap-closure-tasks.md`.

## Summary

This is the test-first implementation companion to the reviewed Slice 2 architecture document.
Slice 2 may begin before the remaining Slice 1 release tasks: its hard prerequisites—accepted
links, capability push, spool integration, status/readiness plumbing, and Hardware linking—are
already present.

Each numbered task ends in a focused commit and leaves the affected Go, backend, or frontend
suites green.

## Ordered Implementation Tasks

### Task 1: Protocol and capability-schema v2

- Add typed `telemetry.host` and `capability.readiness` payloads in Go and Python.
- Add `capability_schema: 2` negotiation to `hello`; an absent value means legacy schema 1.
- Accept legacy boolean grants and `{enabled, config}` grants everywhere. Send objects only to
  schema-2 agents and booleans to older agents.
- Preserve a producer-supplied frame timestamp instead of replacing it in `link.Run`.
- Mark readiness as control traffic so it is never spooled.
- Extend the cross-language conformance fixtures and tests.

### Task 2: Structured capability configuration

- Replace the Go gate's internal `map[string]bool` with immutable grant snapshots containing
  `Enabled` and validated configuration.
- Apply authoritative grants from both `hello.ack` and `capabilities.set`, persist them
  atomically, and notify the collector runtime.
- Normalize omitted host settings to the approved defaults. Reject intervals outside 10–900
  seconds without replacing the last valid configuration.
- Keep REST requests backward compatible with booleans while returning normalized capability
  objects to current clients.

### Task 3: Telemetry and readiness persistence

- Add `agent_host_samples` with immutable raw payloads, normalized summary columns, the Hardware
  target captured at collection time, and durable projection state.
- Add `agent_host_sample_hourly` for portable 7–30-day rollups.
- Add agent-owned, per-collector readiness records.
- Add `agent_id` and `agent_sample_id` attribution to `hardware_live_metrics`, including
  replay-safe agent/time uniqueness.
- Convert raw agent samples to a Timescale hypertable when available while retaining SQLite
  compatibility.

### Task 4: Collector framework and rate tracking

- Add `internal/collect` contracts, a filesystem abstraction, readiness registry, clock/random
  injection, counter-delta helpers, and cancellable non-overlapping scheduling.
- Skip and report a tick that arrives during an active collection rather than queueing another
  run.
- On counter resets, wraparound, first samples, and removed devices, omit rates instead of
  emitting false zeroes.

### Task 5: Core and filesystem collectors

- Read `/proc/stat`, load averages, memory/swap, uptime, boot time, CPU count, mounts, and
  filesystem usage.
- Exclude pseudo and virtual filesystems by default and derive root-disk utilization from `/`.
- Use fixture-backed tests that do not depend on the test host.

### Task 6: Disk and network collectors

- Read cumulative block-device and interface counters from `/proc` and `/sys`.
- Calculate byte rates, preserve cumulative totals, and apply deterministic filters for
  physical, virtual, down, and loopback devices.
- Aggregate non-loopback interface rates into the host summary.

### Task 7: Thermal and Docker collectors

- Collect `hwmon` and thermal-zone values plus exposed warning and critical thresholds.
- Treat a host with no temperature sensors as thermal-unavailable without degrading the overall
  sample.
- Implement Docker through context-bound HTTP over its Unix socket, disabled by default, with
  bounded container summaries.
- Do not grant Docker socket access automatically; surface an explicit privilege-remediation
  command.

### Task 8: Payload assembly and limits

- Generate cryptographically random 128-bit lowercase-hex sample IDs.
- Define exact filesystem, disk, interface, temperature, and Docker field schemas with stable
  units.
- Sort device lists by stable identity before applying their caps.
- If the encoded payload still exceeds 256 KiB, remove entries deterministically from optional
  lists until it fits, preserving core summary data and reporting degraded/truncated readiness.

### Task 9: Daemon lifecycle, outbound flow, and readiness

- Start from cached grants while disconnected and apply server changes without restarting the
  daemon.
- Enable, disable, or restart the host runner immediately when effective configuration changes.
- Refactor the outbound mux so data produced during dial failures and reconnect backoff is
  written directly to the spool; control frames remain live-only.
- Preserve collection timestamps and the existing one-spooled-per-four-live drain behavior.
- Include current readiness in `hello`, send `capability.readiness` after acceptance,
  configuration changes, readiness changes, and every 15 minutes, and mirror it into
  `status.json`.

### Task 10: Backend validation and canonical ingestion

- Validate active-agent state, the server-side grant, schema, size, sample ID, timestamp window,
  numeric ranges, list bounds, and status before persistence.
- Persist the canonical agent sample idempotently before any Hardware projection.
- Publish agent-detail telemetry immediately on an agent-scoped Redis channel.
- Rate-limit payload-free protocol-violation events while retaining counters for repeated
  invalid samples.

### Task 11: Readiness ingestion

- Validate and upsert all reported probe states transactionally.
- Broadcast only changed readiness snapshots to agent-detail subscribers.
- Expose disabled, ready, degraded, and unavailable states with bounded reason, remediation,
  and missing-resource fields.

### Task 12: Durable linked-Hardware projection

- Capture `Agent.hardware_id` on each new canonical sample. A null target permanently means no
  projection, preventing historical backfill when a link is created later.
- Periodically publish pending projections to `telemetry.ingest.{hardware_id}` with agent/sample
  attribution and the original collection time.
- Extend the ingest worker to insert agent-originated Hardware metrics idempotently and mark the
  canonical sample projected in the same database transaction.
- Retry unprojected rows after application restart or NATS outage.
- Update Hardware live state, cache, and WebSocket only when the incoming collection timestamp
  is not older than current state. Older catch-up samples still enter history.

### Task 13: Retention, rollups, and history queries

- Extend retention processing to build idempotent hourly agent summaries before deleting raw
  samples older than seven days.
- Delete hourly rows after 30 days.
- Return raw data for recent ranges and hourly rollups for older portions without gaps or
  duplicates.
- Bound results to 120 points: evenly decimate one-hour raw data when necessary and use the
  approved 1m, 5m, 30m, and 1h buckets for longer ranges.

### Task 14: REST and typed telemetry WebSocket

- Add latest/readiness and bounded-history agent endpoints using existing agent RBAC and tenant
  rules.
- Extend telemetry subscriptions to typed `{entity_type, entity_id}` values while preserving
  integer Hardware subscriptions and existing `telemetry:{hardware_id}` behavior.
- Publish agent samples only to `telemetry:agent:{agent_id}`.
- Return effective cadence/configuration, latest timestamp, projection/catch-up state, and linked
  Hardware information.

### Task 15: Frontend data layer and capability editor

- Normalize legacy boolean and structured capability responses in the agent API client.
- Extend the telemetry hook for typed subscriptions without changing current Hardware/map
  callers.
- Add cadence and optional-collector controls, validation, optimistic-state rollback, and Docker
  privilege confirmation.

### Task 16: Agent Detail telemetry UI

- Add live/stale summary cards, history range switching, readiness warnings, and latest device
  tables.
- Mark data stale after `max(3 × interval, 90 seconds)` while preserving the last sample.
- Show spool/catch-up and projection state.
- For unlinked agents, show telemetry normally with a link-to-Hardware prompt. Linked agents
  reuse existing Hardware/map navigation and visualization conventions.

### Task 17: Integration and release gate

- Extend Docker E2E to prove approval-to-first-sample, unlinked retention, future-only Hardware
  projection, offline spool catch-up, idempotent replay, live configuration changes,
  disable/revoke enforcement, readiness, retention, and typed WebSocket updates.
- Run Go tests and race checks, backend SQLite and Postgres/Timescale suites, frontend RTL and
  build checks, migration upgrade/downgrade, payload conformance, and the isolated remote-subnet
  acceptance flow.

## Public Interfaces and Data Contracts

- New agent frame: `capability.readiness`.
- Versioned `telemetry.host` schema 1 with fixed units and bounded collections.
- Capability negotiation through `hello.capability_schema`; legacy boolean wire behavior remains
  supported.
- New raw and hourly agent telemetry tables plus readiness persistence.
- Agent attribution and original timestamps in Hardware telemetry ingestion.
- New agent latest/history endpoints and typed telemetry WebSocket subscriptions.

## Test and Acceptance Plan

### Agent tests

- Cross-language schema compatibility for legacy and schema-2 capabilities, telemetry, and
  readiness frames.
- Deterministic `/proc` and `/sys` fixtures for all probes.
- CPU, disk, and network rates across first samples, normal deltas, resets, wraparound, and
  device removal.
- Filesystem, interface, and virtual-device filtering.
- Missing sources, partial readiness, no thermal sensors, Docker availability, and Docker socket
  failures.
- Live configuration changes, non-overlapping runs, payload/list limits, and deterministic
  truncation.
- Immediate disable, collection during disconnect, spool recovery, original timestamps, and 1:4
  draining.

### Backend tests

- Payload validation, grant enforcement, inactive-agent rejection, timestamp bounds, and
  violation rate limiting.
- Idempotent canonical persistence and Hardware projection.
- Unlinked persistence, future-only projection after linking, NATS outage recovery, and original
  timestamp preservation.
- Multiple agents linked to one Hardware record with newest-timestamp live-state selection.
- Readiness persistence and change-only broadcasts.
- Latest/history RBAC, bounded downsampling, rollups, and retention.
- Migration upgrade/downgrade, indexes, SQLite compatibility, and fresh Postgres/Timescale boot.

### Frontend tests

- Live telemetry updates without refresh and polling fallback during stream loss.
- Stale/offline display while preserving the last sample.
- History range switching, device tables, and partial/unavailable readiness.
- Cadence and optional-collector editing, invalid configuration rollback, and Docker warning.
- Unlinked-agent prompt, linked-Hardware navigation, and legacy Hardware subscriptions.

### End-to-end acceptance

1. Approve an agent with default host telemetry and observe a sample within 30 seconds.
2. Confirm CPU, memory, disk, network, uptime, and available sensors/devices.
3. Verify an unlinked agent stores telemetry without creating Hardware.
4. Link Hardware and verify only subsequent samples update Hardware, map, cache, and history with
   `source="agent"`.
5. Disconnect the backend, collect several samples, reconnect, and verify ordered catch-up with
   original timestamps and no duplicates.
6. Stop NATS independently and verify canonical samples are later projected without loss.
7. Change cadence and collector settings live, then disable telemetry and verify collection
   stops.
8. Revoke the agent and verify no further samples are accepted.
9. Run retention/downsampling and confirm 30-day history remains queryable.
10. Install on the isolated remote-subnet fixture using only the Slice 1 command and confirm the
    first host sample arrives without editing a file or opening an inbound port.

## Assumptions and Defaults

- Linux amd64/arm64 only; direct `/proc` and `/sys` collection avoids a new host-metrics
  dependency.
- Default interval is 30 seconds; core and device collectors are enabled, while Docker and
  virtual devices are disabled.
- First-sample rate fields may be absent until a valid prior counter sample exists.
- Missing optional sensors do not block core telemetry.
- Canonical agent persistence is authoritative; Hardware projection is durable and restart-safe.
- Raw samples are retained for seven days and portable hourly rollups for 30 days.
- Remaining Slice 1 server-key rotation, uninstall, and release-gate work does not block
  collector development, but the combined E2E release gate requires both slices' outstanding
  acceptance work to pass.
