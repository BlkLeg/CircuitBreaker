# cb resources — application resource accounting

Date: 2026-09-26
Status: Approved; first release implemented (2026-09-27)

Delivery notes: the first release uses disjoint verified service cgroups for native
totals, explicitly leaving parent-slice residual charges unattributed. The Docker
proxy launcher and verified local container are measured when the local daemon is
readable. Mono process detail and `--storage` remain follow-up work as scoped below.
The command reference in `docs/cb-cli.md` describes the available flags.

## Purpose

Answer three questions from the terminal: how much resource capacity Circuit
Breaker consumes, which components consume it, and whether resource limits are
constraining the installation. Collect locally so the command still works when
the API or database is unhealthy. No persistent monitoring service is required.

“Application usage” means resources accounted to the local installation's owned
services and containers. Shared services, external dependencies, and unavailable
measurements must remain visible as coverage gaps. This is an accounting view,
not a claim to measure every indirect kernel or shared-daemon cost of the app.

## Command surface

```sh
cb resources                            # snapshot, sampled over 2 seconds
cb resources --watch                    # refresh every 2 seconds; q/Ctrl-C exits
cb resources --watch --interval 5        # seconds; minimum 1
cb resources --json                     # one versioned JSON document
cb resources --watch --json             # one JSON document per line per sample
cb resources --storage                  # add a one-time disk footprint scan
```

Keep `cb status` for service state and `cb doctor` for diagnosis. Use one command
name initially. Resource collection is read-only and does not change limits,
enable accounting, restart services, or automatically invoke sudo.

`--interval` also controls the snapshot sampling window. Interactive watch uses
in-place refresh and restores the terminal on exit; redirected output uses plain
timestamped snapshots. JSON stdout contains only data, with diagnostics on stderr.
No authentication token or running backend is needed.

## Example display

Illustrative native installation; values below are not measurements:

```text
Circuit Breaker resources       native       sampled over 2.0s
Scope: local app-owned services | shared nginx excluded

CPU        0.72 cores     9.0% of 8 visible CPUs
Memory     1.84 GiB       11.5% of 16 GiB visible RAM
Swap       24 MiB
Disk I/O   128 KiB/s read    1.2 MiB/s write
Network    unavailable: per-service accounting is not enabled

Component                  CPU cores     Memory       Read/s    Write/s
API                             0.18    420 MiB            0          0
Workers (7)                     0.31    680 MiB       16 KiB    256 KiB
PostgreSQL                      0.17    520 MiB      112 KiB    960 KiB
Redis                           0.02    120 MiB            0          0
NATS                            0.02     80 MiB            0     13 KiB
PgBouncer                       0.01     32 MiB            0          0
Other app services              0.01     32 MiB            0          0

Limits: app slice 1.30 / 3.00 GiB; PostgreSQL/helper are outside it
Events: telemetry worker CPU throttled in 18% of periods this sample
Shared: nginx 0.03 cores / 46 MiB, excluded from app totals

[q] quit  [c] CPU sort  [m] memory sort  [e] expand workers
```

Default order is CPU descending; retain stable ties to avoid distracting movement.
Expand workers by role. Narrow terminals retain component, CPU, and memory first.
The snapshot includes individual worker rows without requiring interaction.
Show sample age and collection errors; never leave stale values looking current.

## Scope and discovery

Use the existing install identity resolution and explicitly distinguish unreadable
identity from missing identity. Do not select processes by executable name or
username. Normalize systemd aliases and container IDs before deduplication.

| Installation | Collection boundary |
|---|---|
| Native / Proxmox LXC | Owned systemd service cgroups, including descendants |
| Mono Docker / Compose | Exact container recorded in install identity |
| Package | Recorded application units and explicitly registered dedicated dependencies |

Repository findings that affect correctness:

- `deploy/systemd/circuitbreaker.slice` exists, with `MemoryHigh=2G` and
  `MemoryMax=3G`. API, workers, Redis, NATS, PgBouncer, and Docker proxy templates
  reference it. Read installed settings; these defaults are not runtime facts.
- `circuitbreaker-postgres.service` and `cb-helperd.service` do not specify that
  slice. A slice-only total would miss them. Include their separate cgroups.
- `deploy/setup.sh` currently writes six service names into identity, omitting
  workers and helper services. Identity alone is presently an incomplete manifest.
- Native nginx is the system `nginx.service`; ownership of the entire service
  cannot be assumed. Display its usage separately as shared/unattributed.
- The mono container supervises the API, workers, dependencies, and nginx together.
  Its container total is the primary measurement. Internal component detail needs
  a separate process collector and has different memory semantics.

Implementation must reconcile identity with a mode-specific, explicit component
registry: known worker instances, dedicated PostgreSQL, helper, optional Docker
proxy, and app-owned active maintenance units. Verify each unit belongs to the
selected installation using installed unit/configuration metadata. Never include
all of `system.slice`, all Docker containers, or arbitrary services pulled in by
a systemd target. Update installer identity generation to list managed units;
retain registry reconciliation for existing installs.

For aggregation, choose disjoint accounting boundaries. A verified app-only slice
can supply its subtotal; its children explain that subtotal and are not added
again. Add owned units outside it once. If slice ownership cannot be verified,
sum verified disjoint unit cgroups and mark uncovered usage. Unexpected members
must be identified rather than silently assigned to Circuit Breaker.

Remote databases and agents on other machines are outside local totals. Browser
CPU and memory are also outside scope. Local shared dependencies appear separately.
Manual shell-launched jobs cannot be reliably attributed without an owned cgroup;
state this limitation. Do not claim fleet-wide resource coverage.

LXC and Docker Desktop must label visible guest/VM capacity. Remote Docker contexts
must identify the daemon endpoint and never combine remote application metrics
with the CLI machine's CPU or RAM denominator.

## Measurements and interpretation

Use kernel cgroup accounting for totals and Docker Engine raw stats where direct
cgroup access is unavailable. Cgroups provide hierarchical CPU, memory, and I/O
accounting; [kernel reference](https://docs.kernel.org/admin-guide/cgroup-v2.html).

| Measurement | Display contract |
|---|---|
| CPU | Cores consumed = CPU-time delta / elapsed monotonic time; 1.00 is one busy logical CPU. Show percent of visible CPU capacity separately. |
| Memory | Charged memory including cache; expose file cache separately when available. Never substitute summed process RSS for the total. |
| Swap | Charged swap separately from memory, or unavailable. |
| Disk I/O | Accounted block read/write bytes per second; not file size or logical application writes. |
| Network | Receive/transmit rates at the measured service or network-namespace boundary; include loopback/internal traffic where the source counts it. |
| Tasks | Label threads/tasks distinctly from process count. |
| Constraints | Installed CPU quotas, memory high/max, throttling, OOM events, and pressure where supported. |

Docker's CLI subtracts cache from its Linux memory display. Normalize raw memory
data for consistent semantics instead of parsing formatted `docker stats` output.
See [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/).

Always label a limit's scope. The existing 3 GiB slice limit does not cap
PostgreSQL outside it. Do not sum child limits into an invented whole-app limit.
Ancestor constraints and CPU affinity/cpuset restrictions also matter; if enclosing
limits are hidden by a namespace, effective capacity is unknown. A shared ancestor
limit is a shared ceiling, not guaranteed capacity available to this app.

Native network accounting may be absent. Read existing systemd IP accounting when
available; otherwise show unavailable. Never assign host-interface traffic to the
app. Host-networked Docker containers have the same attribution problem. Network
totals count unique measurement boundaries and remain labeled traffic observed,
not external bandwidth: app-to-app traffic can be counted at both endpoints.

Optional `--storage` scans only registered data/log/upload/backup locations, once
at startup even in watch mode. Report scan time, errors, allocated-byte semantics,
and exclusions; avoid following symlinks or counting overlapping roots twice.
Shared Docker image layers and shared host journals are separate/unattributed.

## Collector and output contract

Keep dispatch in canonical `cb`, mirrored to `deploy/cli/cb`. Put collection,
normalization, and rendering in a shipped Python standard-library helper, separate
from backend initialization. Include the helper in native, package, and mono
artifacts. Verify a usable interpreter in every channel before shipping; a missing
interpreter produces actionable installation guidance. No runtime pip installs.

Use bounded subprocess/API timeouts and one persistent sampler in watch mode.
Prefer cgroup v2 files on native Linux and raw Docker Engine stats for containers,
honoring the user's Docker context/transport. Capability-detect older systems;
use available systemd counters and mark unsupported metrics instead of guessing.
Docker stats integration must not require giving the app a Docker socket mount.

Take two observations before displaying rates. Re-resolve membership periodically
and after restarts. Reset baselines on cgroup/container replacement, PID start-time
change, counter rollback, and unavailable samples. Newly discovered components
show warming up until a valid delta exists. Short-lived children are included in
their surviving parent cgroup's counters.

JSON schema version 1 should contain sample timestamps and interval, installation
mode, measurement host, scope, components, totals, limit scopes, and warnings.
Each metric has a value/unit, source, and availability reason. Missing values are
`null`, never zero; partial sums are labeled observed subtotals. Preserve cumulative
counters alongside rates for automation. Exclude environment values, credentials,
and full process command lines.

Exit 0 when a usable report is produced, including explicitly partial reports;
exit 1 when no trustworthy scope/report can be collected; exit 2 for invalid
arguments. A stopped component is distinct from an unreadable one. Do not report
zero memory merely because a process stopped: residual cgroup charges may remain.

## Delivery and acceptance

First release: snapshot, watch, JSON, owned-service totals, native component rows,
mono container total, coverage notices, and observed limits/events. Add mono
process detail and optional storage scanning next. Process detail must label PSS
or RSS explicitly and never pretend it reconciles to charged container memory.

Verify with fixtures and isolated runtime checks:

1. Busy unrelated processes do not change the app's accounting membership.
2. Native totals include PostgreSQL/helper outside the slice and count each worker
   once; shared nginx stays separate. Missing identity members are surfaced.
3. CPU and I/O deltas, restarts, short-lived children, counter resets, missing
   controllers, and permission errors produce correct values or explicit gaps.
4. Mono totals agree with raw Engine/cgroup counters under the documented memory
   definition; host networking and external dependencies expose coverage limits.
5. Hierarchical memory/CPU limits are shown at their actual boundaries; partial
   guest visibility never becomes a physical-host claim.
6. JSON stays parseable, watch handles resize/signals, and collection works with
   the backend stopped. Measure collector overhead on idle and busy installations.
7. CLI parity, installer manifests, packaging inclusion, command documentation,
   and the install compatibility matrix remain consistent.

Do not move PostgreSQL/helper into the existing capped slice as part of this
feature: that changes their resource constraints. Any future consolidation needs
its own capacity decision and rollout.
