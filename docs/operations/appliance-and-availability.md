# Single-Node Appliance and Availability

What topology Circuit Breaker 1.0.0 actually runs in, what "appliance" means for the container
image, and what happens when the one node goes away.

For *which install method to choose*, the authoritative comparison is the
[installation overview](../installation/index.md#deployment-modes). This page does not repeat it —
it answers the availability question that comparison does not.

---

## The mono container is a single-node appliance

One image — `ghcr.io/blkleg/circuitbreaker`, built from `Dockerfile.mono` — runs **twelve
supervised programs in one container**:

| Program | Role |
|---|---|
| `postgres` | The source of truth |
| `pgbouncer` | Transaction-mode connection pooler |
| `redis` | Shared rate limits, session coherence, cache, pub/sub |
| `nats` | Worker dispatch, notifications, event fan-out |
| `backend-api` | The API and the bundled web UI |
| `worker-discovery`, `worker-notification`, `worker-telemetry`, `worker-monitor-scheduler`, `worker-monitor-poll`, `worker-monitor-probe-dispatch` | The six background workers |
| `nginx` | TLS termination and reverse proxy |

Calling that an **appliance** is a precise claim, not marketing. It means:

- **One unit of deployment.** You start it, you stop it, you back it up. There are no independently
  scalable pieces.
- **One unit of failure.** Everything above shares a process namespace, a filesystem and a lifecycle.
  A restart of the container is a restart of the database.
- **One node.** There is no second instance to fail over to, and no mechanism that would coordinate
  one.
- **Loopback-only dependencies.** No database port, no Redis port and no NATS port is exposed to the
  network. That is a real security benefit — and the direct consequence of the same decision that
  removes isolation *between* those components. The trade-off is analysed in the
  [threat model's appliance boundary](../security/threat-model.md#tb6-the-appliance-boundary).

A **native systemd install** is the same single-node topology with the same components as host
services rather than supervised programs. It is not a distributed deployment either; it separates
the components at the OS level instead of the container level.

---

## Split services do not ship in 1.0.0

The [support contract](../release/1.0.0-support-contract.md#deployment-support-matrix) records
**"Split multi-container Compose — Does not ship in 1.0.0."** The reason is concrete, not a
roadmap position: no Compose file in the repository wires separate backend, frontend, database and
Redis containers together, so there is nothing to install, and nothing CI builds, scans or
smoke-tests.

Two files look like a split stack and are not:

- `docker-compose.deps.yml` starts PostgreSQL, Redis and NATS with development credentials for
  `make dev`. It starts no Circuit Breaker process at all.
- `docker/backend.Dockerfile` and `docker/frontend.Dockerfile` are development images that no
  shipped Compose file references.

The reasoning in full: [Why there is no split mode](../installation/index.md#why-there-is-no-split-mode).

!!! note "What this means for the 'production mode' question"
    The [server product contract](../release/1.0.0-support-contract.md) anticipated a shipped split
    topology as the scalable production mode alongside a single-node appliance. **That topology is
    not part of 1.0.0.** For this release the production-grade choice is a native systemd install —
    which separates the components as host services, lets you point `CB_DB_URL` at an external
    PostgreSQL, and lets you run the workers as their own units — not a split container stack. If a
    document tells you split Compose is a supported 1.0 channel, that document is wrong; please open
    an issue.

The one axis along which the topology genuinely does split today is the **database**: set
`CB_DB_URL` (and `CB_DB_POOL_URL` if you have a pooler) and PostgreSQL runs wherever you want it.
The application node stays single. See [Sizing profiles § External PostgreSQL](sizing-profiles.md#external-postgresql).

---

## High availability is explicitly unsupported

**Circuit Breaker 1.0.0 supports exactly one active application server.**

The support contract states it twice — as a
[deployment row](../release/1.0.0-support-contract.md#deployment-support-matrix) ("High availability
deployment — Unsupported for 1.0.0 — Single-node application server only") and as a
[known limitation](../release/1.0.0-support-contract.md#known-limitations-for-100) ("1.0.0 is not a
high-availability product"). This page is the operational reading of that decision.

### What is not there

| Absent | Consequence |
|---|---|
| Clustering between application nodes | Two nodes pointed at one database is not a supported configuration and has no acceptance evidence |
| Cross-node leader election | Nothing arbitrates which node owns scheduling |
| Automated failover or a virtual IP | Recovery is an operator action |
| Replicated Redis or NATS | Both are disposable coordination layers, not replicated ones |
| A standby that takes over | Write admission refuses mutating requests when a dependency is gone — that is *failing safe*, not *failing over*. Nothing else picks the work up |

### What *is* there, and why it is not HA

The software does contain single-execution machinery, and it is easy to mistake for clustering. It
is not:

- **Worker ownership and leases.** Discovery, notifications, telemetry, monitor scheduling and
  probe dispatch each have an unambiguous owner, so mixed in-process and dedicated worker modes
  cannot duplicate work. That prevents *double execution*; it does not provide *failover*.
- **Cross-worker session coherence.** Session revocations are published to Redis so a logout on one
  uvicorn worker is honoured by the others. That is coherence between processes on one node.
- **A cross-worker Redis lock on agent enrollment.** It stops two uvicorn workers overshooting the
  concurrent-pending cap. Same node, different processes.
- **Graceful drain on SIGTERM.** `/readyz` reports `state: "stopping"` so a load balancer stops
  sending new requests, mutating requests are refused with `503 SERVER_DRAINING`, and `/livez` and
  `/startupz` stay `200` so the supervisor does not kill the drain. That makes a *restart* clean. It
  does not make a *failure* survivable.

If you set `CB_RUN_INPROCESS_WORKERS=false` and run dedicated worker processes, you are separating
*processes*, not adding *nodes*. All of them still talk to one Redis, one NATS and one database on
the path the support contract covers.

---

## What downtime looks like

| Event | Effect | Recovery |
|---|---|---|
| Container or service restart | Full outage for the restart duration. Agents reconnect on their own; their assignments become due again, jittered so the fleet does not stampede | Automatic |
| Upgrade | Planned outage: migrations run before the API serves. Downgrade after migrations is **rejected** — restore a pre-upgrade backup instead | [Upgrading](../installation/upgrading.md) |
| Host failure | Total outage. There is no standby | Restore a snapshot onto a clean supported host |
| Data-directory loss | Total data loss unless a snapshot exists — the database, uploads, TLS material and the vault key all live under `$CB_DATA_DIR` | [Backup & Restore](../backup-restore.md) |
| Database unreachable | `/readyz` goes `503` and mutating API requests are refused with `503 SERVICE_NOT_READY` and `Retry-After: 5`; reads, WebSocket sessions and health endpoints stay open, and `/livez` stays `200` so the supervisor does not restart-storm a backend that is serving fine | Fix the dependency |
| Redis or NATS unreachable | Startup fails closed unless degraded mode is explicitly enabled; a running instance reports not-ready | Fix the dependency, or break glass with `CB_ALLOW_DEGRADED_DEPENDENCIES` for long enough to fix it |

### Agents keep working, briefly

An agent whose link drops **spools** data frames to disk — capped at 64 MiB, oldest-dropped at the
cap — and drains them at a deliberately paced rate on reconnect. So a short server outage costs
latency rather than data. A long one costs the oldest frames.

Control frames are never spooled: replaying a stale probe assignment after an outage is worse than
losing it.

---

## Availability planning, given all of that

Since redundancy is not available, availability comes from the other three levers.

1. **Backups are the availability strategy.** The published objectives are **RPO 24 hours** for
   scheduled backups and **RTO 4 hours** for a documented restore to a clean host at the medium
   dataset — both [candidate values pending ACC-14/ACC-15 evidence](../release/1.0.0-service-objectives.md#recovery-and-retention-objectives).
   Take a manual snapshot before every upgrade and every destructive action.
2. **Practise the restore.** An RTO you have never exercised is a guess. `cb restore` verifies the
   archive *before* it stops anything, and takes a safety snapshot of current state before it
   destroys any — so a rehearsal on a scratch host is cheap.
3. **Store the vault key separately.** A database restored without its vault key has unreadable
   encrypted credentials. The snapshot contains the key in plaintext, which is exactly why the
   archive must be protected like a credential.
4. **Use maintenance windows.** Restarts and upgrades are outages. Schedule them.
5. **Watch the right probe.** Restart decisions turn on `/livez` and nothing else. Wiring a
   watchdog to `/readyz` turns a dependency blip into a restart loop.

---

## Related

- [Installation overview](../installation/index.md) — the authoritative deployment-mode comparison
- [Sizing profiles](sizing-profiles.md) — resources and bounds per profile
- [Backup & Restore](../backup-restore.md) — the recovery procedure this page depends on
- [Service objectives](../release/1.0.0-service-objectives.md) — health states, SLOs, RPO/RTO
- [Support contract](../release/1.0.0-support-contract.md) — the supported deployment matrix
- [Threat model](../security/threat-model.md) — the appliance boundary analysed
