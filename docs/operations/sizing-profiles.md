# Sizing Profiles

Three profiles — **Small**, **Medium** and **Fleet** — with the host resources each needs, the
database sizing behind it, and every bound the software enforces so it refuses work rather than
growing without limit.

---

## How to read the numbers

Each figure carries a basis, because they are not all the same kind of statement:

| Basis | Meaning |
|---|---|
| **Enforced** | The software or the installer applies this value. Exceeding it produces a defined refusal, not a slowdown. |
| **Published** | Already a published boundary — the [support contract](../release/1.0.0-support-contract.md) or the [installation overview](../installation/index.md). |
| **Candidate** | A planning figure for operators. **REL-21 through REL-26 have not been run against a release candidate**, so no measurement backs it yet. Treat it as a starting point and watch your own instance. |

!!! warning "Candidate figures are not benchmark results"
    [SRV-07](../release/1.0.0-service-objectives.md#candidate-scale-ceilings) requires sizing values
    derived from the REL-21–REL-26 performance and soak work. That work has not produced evidence
    against a release candidate. Every CPU, RAM and disk row below marked *candidate* is engineering
    judgement from what the components are configured to consume, not a measurement. Rows marked
    *enforced* are exact.

---

## Profile ceilings

The workload each profile is defined by. These are the
[candidate scale ceilings](../release/1.0.0-service-objectives.md#candidate-scale-ceilings) from the
service objectives.

| | Small | Medium | Fleet |
|---|---|---|---|
| Inventory objects | 100 | 1,000 | Deferred |
| Agents | 10 | 50 | Deferred |
| Monitors | 50 | 500 | Deferred |
| Concurrent users | 1 | 5 | Deferred |
| Support status | Supported candidate | Supported candidate | **Deferred for 1.0.0** |

**Fleet is not a supported 1.0.0 profile.** Beyond the Medium ceiling, support is best-effort until
REL-26 and the AGT fleet evidence expand it. The Fleet column below exists so an operator who is
already past Medium knows which knobs to turn — not as a promise that it works.

---

## Host resources

Per application node. Circuit Breaker runs **one** application node; see
[Single-node appliance and availability](appliance-and-availability.md).

| Resource | Small | Medium | Fleet | Basis |
|---|---|---|---|---|
| CPU minimum | 1 core | 2 cores | 4 cores | Candidate. The shipped Compose file reserves `0.5` CPU and limits the appliance to `2.0`. |
| CPU recommended | 2 cores | 4 cores | 8 cores | Candidate |
| RAM minimum | 1 GB | 2 GB | 4 GB | **Enforced-adjacent:** the native installer warns below 1024 MB and reduces the Redis `maxmemory` from 256 MB to 128 MB below 2048 MB. Medium and Fleet are candidate. |
| RAM recommended | 2 GB | 4 GB | 8 GB | Candidate. The mono container's own memory limit is `2G` as shipped — raise it before raising the host. |
| Free disk minimum | 3 GB | 10 GB | 40 GB | **Enforced for Small:** the native installer *fails* below 3 GB free on `/`. No equivalent gate exists on the container path. Medium and Fleet are candidate, sized by the formula below. |
| Free disk recommended | 10 GB | 40 GB | 100 GB+ | Candidate |

On `docker`, `compose` and `binary` installs, `cb doctor` warns when the data directory has **under
1 GiB free**. That is the floor at which Postgres, the WAL, uploads and the snapshot you are about
to take start competing. The native `cb doctor` checks service and port health rather than free
space, so watch `df -h ${CB_DATA_DIR}` yourself on a native install.

### Sizing the disk properly

The minimum keeps the software running; the formula keeps it running *with your data*.

```text
disk  =  3 GB base
      +  database growth        (inventory + telemetry + monitor history + audit log)
      +  uploads                (icons, branding, document images, avatars)
      +  7 × snapshot size      (the default local snapshot retention)
      +  headroom for one more snapshot being written
```

The snapshot term dominates on a mature install: a full-state snapshot contains a gzip-compressed
`pg_dump` of the *whole* database plus the uploads tree, and seven of them are kept by default
(`backup_local_retention_count`), pruned by age at 30 days
(`db_backup_retention_days`). Halving retention halves that term.

The four retention settings that bound database growth — audit log at 90 days, discovery results at
30 days, probe runs at 7 days, the NATS event stream at 24 hours — are listed with their defaults in
[Privacy § Retention](../security/privacy.md#retention).

---

## Database sizing

PostgreSQL is the source of truth. Redis and NATS are disposable coordination layers.

### As shipped, embedded

The mono image and the native installer both configure a local PostgreSQL fronted by PgBouncer in
transaction mode:

| Setting | Value | Where |
|---|---|---|
| PostgreSQL `max_connections` | 100 | `docker/10-init-postgres.sh` |
| PostgreSQL `shared_buffers` | 128 MB | `docker/10-init-postgres.sh` |
| PgBouncer `max_client_conn` | 200 | `docker/pgbouncer.ini` |
| PgBouncer `default_pool_size` | 20 | `docker/pgbouncer.ini` |
| Redis `maxmemory` | 256 MB, or 128 MB when host RAM < 2 GB | `deploy/config/redis.conf`, set by the installer |
| Redis eviction policy | `allkeys-lru` | `deploy/config/redis.conf` |
| NATS `max_memory_store` | 256 MB | `deploy/config/nats.conf` |
| NATS `max_connections` | 1000 | `deploy/config/nats.conf` |

All **enforced** — these are the shipped configuration files.

### Application connection pool

| Setting | Default without PgBouncer | Default with PgBouncer | Variable |
|---|---|---|---|
| SQLAlchemy pool size | 20 | **5** | `DB_POOL_SIZE` |
| Overflow above the pool | 20 | **5** | `DB_MAX_OVERFLOW` |
| Pool checkout timeout | 5 s — fail fast rather than block the event loop | — | not configurable |

The pool shrinks automatically when `CB_DB_POOL_URL` differs from `CB_DB_URL`, because pooling twice
is worse than pooling once. Both are **enforced**.

Budget connections per process, not per deployment: the API process and each worker process opens
its own pool. With in-process workers (`CB_RUN_INPROCESS_WORKERS=true`, the default) that is one
pool per uvicorn worker; with dedicated workers it is one per worker service. Six worker programs
ship in the appliance — `discovery`, `notification`, `telemetry`, `monitor-scheduler`,
`monitor-poll`, `monitor-probe-dispatch`.

### External PostgreSQL

Point `CB_DB_URL` at it and, if you have a pooler, `CB_DB_POOL_URL`. Sizing guidance for an
external server, **candidate**:

| | Small | Medium | Fleet |
|---|---|---|---|
| `shared_buffers` | 128 MB | 512 MB | 2 GB |
| `max_connections` | 100 | 200 | 300 |
| Storage | 5 GB | 20 GB | 60 GB+ |

Set `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` so that
`(pool + overflow) × process count` stays comfortably under the server's `max_connections`.

TimescaleDB is optional. Hypertable migrations are skipped on a plain PostgreSQL unless
`CB_REQUIRE_TIMESCALE=true`, in which case its absence is an error rather than a fallback.

---

## Bounded queues and concurrency

Everything in this section is **enforced** by the code. Each row is a place the system refuses work
instead of queueing without limit. Names in the last column are the environment variables in the
[configuration catalogue](../reference/configuration-precedence.md#bounds-and-concurrency).

### Monitor scheduling and execution

| Bound | Default | Behaviour at the bound | Variable |
|---|---|---|---|
| Scheduler tick | 1.0 s | — | `CB_MONITOR_SCHED_TICK_S` |
| Checks claimed per tick | 200 | Remaining checks wait for the next tick | `CB_MONITOR_SCHED_BATCH` |
| Per-vantage claim ceiling | 50 | One agent cannot starve the rest of the fleet | `CB_MONITOR_SCHED_PER_VANTAGE` |
| Rows examined per selection | 1000 | — | `CB_MONITOR_SCHED_OVERSAMPLE` |
| Concurrent server-side checks | 50 | Further checks wait | `CB_MONITOR_POLL_PARALLEL` |
| Poll-stream message age | 300 s | A message older than this is **dropped, not executed late** | `CB_MONITOR_POLL_MAX_AGE_S` |
| Probe-stream message age | 60 s | Same — a stale remote probe is discarded | `CB_MONITOR_PROBE_MAX_AGE_S` |
| Probe execution budget | 20 s floor, 600 s ceiling, 10 s headroom | Probe is cut off at its deadline | `CB_MONITOR_PROBE_DEADLINE_MIN_S`, `..._BUDGET_MAX_S`, `..._DEADLINE_HEADROOM_S` |
| Probe-run retention | 7 days | Older rows purged | `CB_MONITOR_PROBE_RETENTION_DAYS` |
| Agent readiness staleness | 2700 s | The agent stops being probe-eligible | `CB_PROBE_READINESS_MAX_AGE_S` |

Reconnect behaviour is bounded too: an agent's assignments become due again on reconnect, but
**jittered** across `least(interval_secs, 30)` — so 300 assignments waking at once do not all land
on the next scheduler tick.

### Discovery

| Bound | Default | Behaviour at the bound |
|---|---|---|
| Concurrent scans | 2 | Further scans queue (`max_concurrent_scans` in Settings) |
| Dispatch deadline | 900 s | The job is closed out rather than left outstanding (`CB_DISCOVERY_DISPATCH_DEADLINE_S`) |
| Reconcile interval | 60 s | — (`CB_DISCOVERY_RECONCILE_INTERVAL_S`) |
| Discovery-result retention | 30 days | Older results purged (`discovery_retention_days`; `0` or less disables the purge) |
| Agent-side job scope | 1024 addresses per job, 64 concurrent hosts, 1500 ms host timeout, 300 s job timeout | Refused at validation with a machine-readable reason |
| Prefix width | Wider than `/16` (IPv4) or `/48` (IPv6) | Refused whatever the grant says |

### Telemetry

| Bound | Default | Variable |
|---|---|---|
| Poll interval | 30 s, floored at 10 s | `CB_TELEMETRY_POLL_SECONDS` |
| Per-device timeout | 20 s, floored at 5 s | `CB_TELEMETRY_DEVICE_TIMEOUT_SECONDS` |
| Devices polled concurrently | 8, floored at 1 | `CB_TELEMETRY_MAX_PARALLEL` |
| Proxmox node / guest / RRD polls | 30 s / 120 s / 300 s | `PROXMOX_NODE_POLL_SECONDS`, `PROXMOX_VM_POLL_SECONDS`, `PROXMOX_RRD_POLL_SECONDS` |

### Notifications and events

| Bound | Default | Behaviour at the bound | Variable |
|---|---|---|---|
| Alert de-duplication window | 60 s | Duplicate alerts inside the window are suppressed | `CB_ALERT_DEBOUNCE_S` |
| Delivery retries | 2 | Then the delivery fails and is recorded | `CB_NOTIFICATION_RETRIES` |
| Event stream age | 24 h | NATS drops older messages | `CB_EVENTS_RETENTION_HOURS` |
| Outbound circuit breaker | 500 tracked endpoints, 3600 s entry TTL | Oldest entries evicted | `CB_CIRCUIT_BREAKER_MAX_ENTRIES`, `CB_CIRCUIT_BREAKER_TTL_SEC` |

### WebSocket connection caps

A refused connection receives `{"error": "connection_limit_exceeded"}` and closes with code `1008`.
Both a global and a per-IP cap apply to each endpoint.

| Endpoint group | Global | Per IP | Variables |
|---|---|---|---|
| Shared manager — discovery, agent presence | 50 | 5 | `CB_WS_MAX_CONNECTIONS`, `CB_WS_MAX_PER_IP` |
| Monitors | 100 | 10 | `CB_WS_MON_MAX_CONNECTIONS`, `CB_WS_MON_MAX_PER_IP` |
| Telemetry | 100 | 10 | `CB_WS_TELEM_MAX_CONNECTIONS`, `CB_WS_TELEM_MAX_PER_IP` |
| Topology | 50 | 5 | `CB_WS_TOPO_MAX_CONNECTIONS`, `CB_WS_TOPO_MAX_PER_IP` |

Every browser tab viewing a live page holds a socket. Multiply concurrent users by the number of
live views they keep open, not by the number of people.

### Agent enrollment

| Bound | Default | Behaviour at the bound |
|---|---|---|
| Enroll/link attempts per IP | 20 per 60 s | WebSocket close `1013`, no payload |
| Enroll/link attempts globally | 200 per 60 s | WebSocket close `1013` |
| Concurrent pending agents | 100 | WebSocket close `1013` |
| Wrong pairing codes per IP | 10 per 15 min | HTTP `429` |
| Wrong pairing codes globally | 50 per 15 min | HTTP `429` |
| Pending row lifetime | 7 days | Auto-rejected |
| Handshake timeout | 10 s | Connection closed |

Enrolling more than 100 agents is therefore a staged operation, not a single burst. Approve in
batches.

### Uploads

Rejected above the limit — the request fails, nothing is truncated.

| Upload | Limit |
|---|---|
| User icon / compute-unit icon | 2 MB |
| Branding logo | 2 MB |
| Login background | 5 MB |
| Document image | 5 MB |
| Document import — single `.md` | 1 MB |
| Document import — whole ZIP | 10 MB |
| Threat-feed response | 5 MB |

### Agent spool

| Bound | Default | Behaviour at the bound |
|---|---|---|
| Disconnected spool cap | 64 MiB (`spool_cap_bytes` in `agent.toml`) | The **oldest** frames are dropped; control frames are never spooled |
| Reconnect drain rate | 4 frames or 256 KiB per 100 ms | Deliberately paced so a backlog cannot stall live telemetry |

Spool depth is reported on every heartbeat, so the fleet view shows backlog without waiting for a
reconnect. A depth that sits flat at the cap means frames are being evicted — the outage is longer
than the buffer. See [cb-agent § Spool pressure](../agent.md#spool-pressure).

### Logs

| Bound | Default |
|---|---|
| Container log rotation | 100 MB × 5 compressed files (`logging` options in the Compose file) |
| Audit-log retention | 90 days (`audit_log_retention_days`) |
| Activity log | Cleared explicitly via `DELETE /api/v1/logs` |

---

## Rate-limit budget per profile

The per-route limiter has three profiles, selected by `rate_limit_profile` in **Settings**. The
values are in the [API reference](../reference/api.md#rate-limits). Sensible pairing:

| Sizing profile | Suggested rate-limit profile | Why |
|---|---|---|
| Small | `normal` or `strict` | One user; a tight `auth` limit costs nothing |
| Medium | `normal` | The shipped default |
| Fleet | `relaxed` for `telemetry` and `scan` categories | More agents means more legitimate telemetry submissions |

Rate limits are keyed by the trusted client identity. Behind a proxy this **requires** a correct
`CB_TRUSTED_PROXY_CIDRS`, or every client shares one bucket regardless of profile — see
[Remote Access § Trusted proxies](../remote-access.md#trusted-proxies).

---

## Growing past a profile

In order, cheapest first:

1. **Give the appliance more of the host.** The Compose file limits the container to 2 CPUs and 2 GB
   before the host is the constraint. Raise `deploy.resources.limits` first.
2. **Move PostgreSQL off the node.** Point `CB_DB_URL` at an external server, tune `DB_POOL_SIZE`
   and `DB_MAX_OVERFLOW` to match its `max_connections`, and the appliance stops competing with its
   own database for RAM and IO.
3. **Cut retention.** Audit log, discovery results and local snapshot count are the three largest
   terms in disk growth, and all three are settings.
4. **Widen the specific bound you are hitting** — not all of them. Every value in this page has a
   named variable; raise the one your logs name.
5. **Split the trust domain.** Two deployments are supported; one deployment serving two trust
   domains is [not](../security/threat-model.md#trust-boundaries).

What is **not** on this list is running a second application node. That is high availability, and it
is [unsupported for 1.0.0](appliance-and-availability.md#high-availability-is-explicitly-unsupported).

---

## Related

- [Single-node appliance and availability](appliance-and-availability.md)
- [Configuration precedence and environment catalogue](../reference/configuration-precedence.md)
- [Service objectives](../release/1.0.0-service-objectives.md) — SLOs, RPO/RTO and the scale ceilings
- [Installation overview](../installation/index.md) — system requirements and deployment modes
- [Backup & Restore](../backup-restore.md)
