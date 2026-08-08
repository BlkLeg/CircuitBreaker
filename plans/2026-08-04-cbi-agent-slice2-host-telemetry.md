# cbi-agent Slice 2 — Host Telemetry Plan

**Date:** 2026-08-04
**Status:** Reviewed for cross-slice E2E implementation
**Related:** `specs/2026-07-26-cb-agent-design.md`,
`plans/2026-08-04-cbi-agent-slice1-gap-closure.md`

## Summary

Add Linux host telemetry to approved agents and route it through Circuit Breaker's existing
telemetry system with `source="agent"`.

Slice 2 depends on the Slice 1 gap-closure plan being completed first, particularly
acknowledged links, structured capability configuration, readiness reporting, and
spool-integrated outbound data.

The slice ends when an agent reports host metrics every 30 seconds, unlinked agents retain
telemetry on their agent page, linked agents also update their Hardware record and map, and
capability changes take effect without restarting.

Host telemetry begins automatically after central approval because it is part of the default
grant. The installer asks no metric, interface, storage, Docker, or sampling questions; useful
defaults are delivered by `hello.ack` and can be tuned later from the main application.

## Implementation Changes

### 1. Agent collectors and configuration

- Add the shared collector contract and a `collect/host` implementation composed of:
  - Core: CPU utilization, load averages, memory, swap, uptime, boot time, and logical CPU
    count.
  - Filesystems: physical mounted filesystems with size, used, available, utilization, type,
    and read-only state.
  - Disks: physical block-device cumulative counters and calculated read/write rates.
  - Network: non-loopback interfaces with state, speed when available, counters, errors, and
    calculated receive/transmit rates.
  - Thermal: `hwmon` and thermal-zone temperatures, including warning/critical thresholds
    when exposed.
  - Docker: container state and CPU/memory/network summary through the Unix socket;
    implemented but disabled by default.
- Exclude process lists, process command lines, environment variables, systemd service
  inventories, file contents, and virtual filesystems from Slice 2.
- Default filters exclude pseudo filesystems, loop devices, RAM devices, loopback, container
  veth pairs, and down interfaces. `include_virtual=true` allows virtual disks/interfaces.
- Extend the `host_telemetry` grant configuration:

  ```json
  {
    "enabled": true,
    "config": {
      "interval_s": 30,
      "include_filesystems": true,
      "include_disks": true,
      "include_network": true,
      "include_temperatures": true,
      "include_virtual": false,
      "include_docker": false
    }
  }
  ```

- Validate `interval_s` from 10–900 seconds. Invalid server configuration is rejected without
  replacing the last valid configuration.
- Apply configuration changes live:
  - Enabling starts one collector loop.
  - Disabling cancels collection immediately.
  - Changing cadence restarts its timer without restarting the daemon.
  - Collection runs never overlap; a slow run is skipped rather than queued.
- Give each collection run a cryptographically random 128-bit `sample_id`. Preserve collection
  time in the frame timestamp through spooling and ingestion.
- Limit a telemetry payload to 256 KiB and cap each device list deterministically: 128
  filesystems, disks, and interfaces; 256 sensors; 100 Docker containers. Report `degraded`
  readiness when truncation occurs.
- Emit one `telemetry.host` frame per interval. When disconnected, enqueue it as a data frame
  and use the Slice 1 one-spooled-per-four-live drain behavior.

### 2. Payload and readiness contract

- Define a versioned `telemetry.host` payload shared by Go and Python:

  ```json
  {
    "schema": 1,
    "sample_id": "32 lowercase hex characters",
    "status": "healthy",
    "summary": {
      "cpu_pct": 21.4,
      "load_1": 0.42,
      "load_5": 0.37,
      "load_15": 0.31,
      "logical_cpus": 8,
      "mem_total_bytes": 17179869184,
      "mem_used_bytes": 8589934592,
      "mem_available_bytes": 8589934592,
      "mem_pct": 50.0,
      "swap_total_bytes": 2147483648,
      "swap_used_bytes": 0,
      "swap_pct": 0,
      "root_disk_pct": 61.2,
      "net_rx_bps": 12345,
      "net_tx_bps": 6789,
      "max_temp_c": 55.0,
      "uptime_s": 86400
    },
    "filesystems": [],
    "disks": [],
    "interfaces": [],
    "temperatures": [],
    "docker": null
  }
  ```

- Use bytes, bytes/second, seconds, percentages from 0–100, and Celsius consistently. Missing
  measurements are omitted rather than encoded as zero.
- Derive rates from consecutive monotonic counter samples. The first sample and counter resets
  report cumulative totals with rate fields omitted.
- Add `capability.readiness` as an agent-to-server control frame. Report readiness:
  - On accepted link.
  - After applying capability configuration.
  - Whenever readiness changes.
  - Every 15 minutes as reconciliation.
- Store separate readiness entries for `host.core`, `host.filesystems`, `host.disks`,
  `host.network`, `host.thermal`, and `host.docker`.
- A missing temperature sensor is `unavailable` for that probe but does not degrade the overall
  host sample. Failure of core CPU/memory collection makes the run unavailable and prevents an
  empty sample. Other probe failures produce a partial sample with overall `degraded` status.
- Docker readiness is `disabled` by default. If enabled without socket access, report
  `unavailable` with remediation to rerun the installer and verify Docker-group access.

### 3. Backend ingestion and persistence

- Add `agent_host_samples` as the canonical telemetry history for every agent:
  - `id bigint`, `agent_id` FK, `sample_id`, `collected_at timestamptz`, status, normalized
    summary columns, raw JSONB payload.
  - Unique `(agent_id, sample_id, collected_at)` for idempotent replay.
  - Composite index `(agent_id, collected_at DESC)` for latest/history queries.
  - Convert to a Timescale hypertable when available, following existing SQLite/Postgres
    migration compatibility.
  - Use existing telemetry hot/warm retention defaults: seven days raw, hourly aggregates
    through 30 days, then deletion.
- Add nullable `agent_id` and `agent_sample_id` attribution to `hardware_live_metrics`, with an
  indexed `(agent_id, collected_at DESC)` access path and replay-safe partial uniqueness for
  agent-originated rows.
- Validate incoming samples before persistence:
  - Agent must be active.
  - `host_telemetry` must be enabled server-side.
  - Payload schema, sample ID, ranges, list limits, timestamp, and size must be valid.
  - Reject timestamps over 60 seconds in the future or older than the 30-day retention window.
  - Record repeated invalid telemetry as a capability/protocol violation without logging the
    full payload.
- Persist the agent sample first using an idempotent insert. Redis/NATS retries of the same
  sample must not create duplicates.
- For unlinked agents:
  - Retain and publish the sample under the agent identity.
  - Show telemetry normally on Agent Detail.
  - Do not create a Hardware record automatically.
- For linked agents:
  - Retain the canonical agent sample.
  - Publish a normalized envelope to `telemetry.ingest.{hardware_id}` with `source="agent"`,
    `agent_id`, `sample_id`, and the original collection timestamp.
  - Update `HardwareLiveMetric`, Hardware telemetry fields, Redis cache, telemetry WebSocket,
    analytics, and topology through the existing telemetry pipeline.
- Refactor the telemetry ingest worker to honor supplied collection timestamps and perform
  idempotent agent upserts. Existing collector messages without agent fields retain current
  behavior.
- Do not backfill historical agent samples into Hardware when a link is created later; only
  subsequent samples affect the linked Hardware.
- If multiple agents link to one Hardware record, accept all samples, retain agent attribution,
  and let the newest collection timestamp determine live Hardware state.
- Persist readiness in an indexed agent-owned status record or JSONB field with
  `readiness_updated_at`; broadcast readiness changes to agent-detail viewers.
- Preserve database efficiency by batching inserts, indexing only agent/time and replay lookup
  paths, and avoiding per-device-row tables for filesystem/interface cardinality.

### 4. API and frontend

- Extend capability request/response schemas to support `{enabled, config}` objects while
  continuing to accept legacy booleans.
- Add viewer endpoints:
  - `GET /api/v1/agents/{id}/telemetry` — latest sample and readiness.
  - `GET /api/v1/agents/{id}/telemetry/history?range=1h|6h|24h|7d|30d` — normalized chart
    series.
- Downsample history server-side to bounded results:
  - 1 hour: raw, at most 120 points.
  - 6 hours: one-minute buckets.
  - 24 hours: five-minute buckets.
  - 7 days: 30-minute buckets.
  - 30 days: one-hour buckets.
- Extend the telemetry WebSocket subscription format to accept typed entities:

  ```json
  {
    "subscribe": [
      {"entity_type": "agent", "entity_id": 12}
    ]
  }
  ```

  Continue accepting legacy integer subscriptions as Hardware IDs.
- Publish live agent telemetry only to subscribed agent channels rather than the fleet-wide
  presence stream.
- Add an Agent Detail telemetry section containing:
  - Live CPU, memory, root-disk, aggregate network, temperature, load, and uptime cards.
  - CPU, memory, disk, network, and temperature history charts.
  - Filesystem, disk, interface, sensor, and optional Docker tables from the latest sample.
  - Last sample time, live/stale state, current cadence, spool/catch-up indicator, and source
    status.
  - Probe-level readiness warnings and remediation.
- Mark telemetry stale after the greater of three configured intervals or 90 seconds. Preserve
  the last sample while clearly displaying stale/offline state.
- Expand the host-telemetry capability controls to edit cadence and optional collectors. Show a
  Docker privilege warning before enabling Docker collection.
- Reuse linked Hardware telemetry/map components and existing telemetry WebSocket updates; do
  not create a separate Hardware visualization path.
- Show unlinked-agent telemetry only on Agent Detail and prompt the user to link Hardware if
  they want topology, analytics, and Hardware views.

## Public Interfaces and Data Changes

- New frame type: `capability.readiness`.
- Versioned `telemetry.host` schema with stable units and bounded device lists.
- Capability values evolve from booleans to `{enabled, config}` while remaining backward
  compatible.
- New `agent_host_samples` hypertable and agent attribution on `hardware_live_metrics`.
- New latest/history REST endpoints and typed telemetry WebSocket subscriptions.
- Agent responses gain host-telemetry readiness, last-sample timestamp, and effective
  configuration.
- No host telemetry is accepted from inactive agents or agents without the server-side grant.

## Test and Acceptance Plan

### Agent tests

- Deterministic `/proc` and `/sys` fixtures for every probe.
- CPU, disk, and network rate calculation across normal samples, first sample, wraparound,
  reset, and device removal.
- Filesystem and virtual-device filtering.
- Missing/unreadable sources and partial readiness.
- Thermal systems with no sensors.
- Docker disabled, available, inaccessible, daemon error, and container-limit cases.
- Configuration validation and live restart without overlapping runs.
- Payload size/list limits and deterministic truncation.
- Capability disable stops emission immediately.
- Offline collection, spool recovery, original timestamps, and 1:4 draining.

### Backend tests

- Payload validation, grant enforcement, inactive-agent rejection, and future/expired timestamp
  rejection.
- Idempotent replay in both agent history and Hardware projection.
- Unlinked persistence and linked NATS dispatch.
- Original collection timestamp survives the ingest worker.
- Multiple agents linked to one Hardware use newest-timestamp live state.
- Readiness persistence and broadcast.
- Latest/history endpoint RBAC and bounded downsampling.
- Retention/downsampling preserves agent attribution.
- Migration upgrade/downgrade, indexes, SQLite compatibility, and fresh Postgres/Timescale boot.

### Frontend tests

- Live metric updates without page refresh.
- Stale/offline behavior retains the last sample.
- History range switching.
- Device tables and partial/unavailable readiness.
- Editing cadence and optional collectors.
- Docker warning and remediation.
- Unlinked-agent prompt and linked-Hardware navigation.
- Legacy Hardware telemetry subscriptions remain functional.

### End-to-end acceptance

1. Approve an agent with default host telemetry.
2. Observe a sample within 30 seconds on Agent Detail.
3. Confirm CPU, memory, disk, network, uptime, and available sensors/devices.
4. Verify an unlinked agent stores telemetry without creating Hardware.
5. Link Hardware and verify subsequent samples update Hardware, map, cache, and history with
   `source="agent"`.
6. Disconnect the backend, collect several samples, reconnect, and verify ordered catch-up with
   original timestamps and no duplicates.
7. Change cadence and collector settings live.
8. Disable host telemetry and verify collection stops.
9. Revoke the agent and verify no further samples are accepted.
10. Run retention/downsampling and confirm history remains queryable.
11. Install on the isolated remote-subnet fixture using only the Slice 1 command and confirm the
    first host sample arrives without editing a file or opening an inbound port.

## Assumptions and Defaults

- The Slice 1 gap-closure plan is a hard prerequisite.
- Linux amd64/arm64 remain the only supported platforms.
- Default cadence is 30 seconds; permitted range is 10 seconds to 15 minutes.
- Core and device metrics are enabled by default; Docker and virtual-device collection are
  disabled.
- Docker collection is part of `host_telemetry`, not a separate capability.
- Unlinked agents retain telemetry under their agent identity; linking affects future Hardware
  projection only.
- Existing seven-day hot and 30-day warm telemetry retention applies.
- Device-level details are persisted in bounded JSONB; normalized summary columns support
  charts, analytics, and indexes.
- The Postgres design uses composite agent/time indexes and idempotent batch ingestion to avoid
  sequential scans and duplicate rows as telemetry volume grows.
- Capability settings are centrally managed enhancements, not deployment prerequisites. Missing
  optional sensors or Docker access degrades only those collectors and never blocks core telemetry.
