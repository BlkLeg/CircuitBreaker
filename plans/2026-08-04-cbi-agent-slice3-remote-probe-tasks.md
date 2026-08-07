# cbi-agent Slice 3 — Remote Probe: Executable Task Breakdown

**Date:** 2026-08-07

**Derived from:**
- `plans/2026-08-04-cbi-agent-slice3-remote-probe.md` — **authoritative** for product and
  architecture requirements. No task body may contradict it; deviations are listed in
  **Deviations** below with justification.
- `plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md` (format model, release gate,
  and the `pendingCorpusTypes` contract this slice is required to discharge)
- `plans/2026-08-04-cbi-agent-slice2-host-telemetry-tasks.md`
- `plans/2026-08-04-cbi-agent-slice4-local-discovery.md` (the scope evaluator built here is
  consumed there — do not build a slice-3-private one)
- `specs/2026-07-26-cb-agent-design.md`

**Codebase layout:**
- Go agent: `apps/agent/` (`cmd/cb-agent/main.go`,
  `internal/{frame,link,capability,spool,collect,collect/host,status,hostinfo,tlsdial}`)
- Backend: `apps/backend/src/app/` (`services/monitoring/{scheduler,state,writer,proxmox_override}.py`,
  `services/monitoring/collectors/{__init__,net,web,dns_check}.py`,
  `workers/{monitor_scheduler,monitor_poll_worker,rollup_worker,main}.py`,
  `services/{monitor_service,agent_link,agent_registry,agent_capabilities,agent_telemetry}.py`,
  `api/{monitor,agents,ws_agents,ws_monitors}.py`, `schemas/{monitor,agent_frame,agents}.py`,
  `core/{subjects,nats_client,network_acl,url_validation}.py`, `db/models.py`)
- Frontend: `apps/frontend/src/` (`components/monitors/{MonitorForm,MonitorCard,MonitorCardDetail}.jsx`,
  `pages/{MonitorsPage,MonitorDetailPage,AgentDetailPage,AgentsPage}.jsx`,
  `hooks/useMonitorStream.js`, `api/{monitor.js,agents.js}`)
- Cross-language wire corpus: `fixtures/agent_frame_corpus.json`, consumed by
  `apps/agent/internal/frame/conformance_test.go` and
  `apps/backend/tests/test_agent_frame_conformance.py`
- Migrations: `apps/backend/migrations/versions/` — head is **`0097_agent_spool_state`**
  (verified: no migration declares it as `down_revision`)
- Docker E2E: `apps/agent/e2e/`

---

## Summary

Slice 3 adds agent-executed ICMP/TCP/HTTP/DNS monitor checks while the backend remains the
authoritative scheduler and state machine. A monitor picks exactly one vantage — the server
(`probe_agent_id IS NULL`, today's behavior) or one named agent — with **no automatic fallback**.

Two things the design treats as pre-existing **do not exist anywhere in the repo** and therefore
become Slice 3's first four tasks rather than assumptions:

1. **The agent reports no IP addresses, prefixes, or routes.** `apps/agent/internal/hostinfo/mac.go`
   calls `net.Interfaces()` and keeps only `HardwareAddr.String()`; it never calls `iface.Addrs()`.
   `apps/agent/internal/collect/host/host.go`'s `network()` reads `/proc/net/dev` counters and
   `/sys/class/net/<n>/{operstate,speed}` only. `apps/backend/src/app/db/models.py`'s `Agent`
   (line 285) stores `primary_macs` JSONB and `reported_ip` — nothing prefix-shaped. Without this,
   §3's derived scope has no input and acceptance test 11 ("provision with only the Slice 1 install
   command and select the agent without editing scope") is unachievable.
2. **There is no shared network-scope evaluator, in either language.**
   `apps/backend/src/app/services/agent_capabilities.py:111-116` still carries the placeholder
   `default_config=MappingProxyType({})` / `normalize=_reject_unknown_keys("remote_probe")`, whose
   own docstring says slices 3 and 4 replace it. Nothing in `apps/agent/**/*.go` parses a CIDR.

Everything else in Slice 3 is additive on top of a working four-stage monitor pipeline
(`services/monitoring/scheduler.py` → NATS `mon.poll.item` → `workers/monitor_poll_worker.py` →
`services/monitoring/{collectors,proxmox_override,writer,state}.py`) whose invariants — one
authoritative `next_due_at`, no wedged items, `source="monitor"` availability, one alert shape —
must survive unchanged.

**23 ordered, test-first tasks**, one focused commit each, each ending with the affected Go,
backend, or frontend suites green.

---

## Known-red baseline

Establish this **before** starting. None of it is Slice 3's fault and none of it may be "fixed"
inside a Slice 3 commit.

| Command | Status | Why |
|---|---|---|
| `(cd apps/backend && pytest)` | **exits 1** | All tests pass (1357 passed / 18 skipped). The failure is `--cov-fail-under=60` in `apps/backend/pyproject.toml` `addopts`; total coverage is ~50%. **Always run `--no-cov` for a real signal.** |
| `ruff check .` (repo-wide) | **6 errors** | Pre-existing E501/I001/F401/F841 in `apps/backend/tests/services/test_agent_install.py` and `apps/backend/tests/unit/test_migration_0091_hardware_machine_id_hash.py`. Only `ruff check src/app` (the CI scope) is green. |
| `ruff format --check src/app` | **1 file** | `apps/backend/src/app/services/agent_update.py`. Do **not** run `make format` — it runs `ruff format src/` (wider than lint) and will pollute the diff. |
| `make test` | **cannot run** | Targets repo-root `tests/integration`, which needs a `circuitbreaker_test` database that does not exist locally. Not the Slice 3 gate. |
| `apps/agent/e2e/test_agent_e2e.py::test_agent_update_success_and_forced_rollback` | **red** | Follow-up F-8: `docker network disconnect` races the re-exec'd container's sandbox creation. Recorded in `apps/agent/e2e/.pytest_cache/v/cache/lastfailed`. |
| `cmd/cb-agent` `TestStartDaemonState_CachedGrantFaultIsReportedAtStartup` | **flaky ~1 in 3** | `t.TempDir` `RemoveAll` cleanup error, not an assertion. Re-run before blaming a change. |
| F-2 (`tests/unit/test_startup_schema_guard.py`) | **STALE — now green** | The follow-ups file says red; all 30 tests in `tests/unit` pass today. Do not inherit that assumption. |

Also note: **backend pytest runs in no CI workflow.** `.github/workflows/ci.yml` and `dev-ci.yml`
run only ruff, mypy, `npm run lint`, `npm test`, `go test -race ./...` and `go vet ./...`. The
cross-language conformance gate and every backend test in this plan are **locally enforced only**.

---

## Prerequisites

Slice 3 owns all of these. Nothing below may be treated as already-landed.

| Prerequisite | Status today | Owner |
|---|---|---|
| Agent-reported directly-connected network facts (interface addresses + prefixes) | **absent** | **Task 1** |
| Backend persistence of those facts with a generation/scope version | **absent** | **Task 2** |
| Shared network-scope evaluator (`direct_private` policy) — backend | **absent** | **Task 3** |
| Same evaluator, Go, corpus-verified identical | **absent** | **Task 4** |
| `remote_probe` structured capability config | placeholder rejects every key | **Task 5** |
| `monitor_probe_runs` + `monitor_items.probe_*` columns | **absent** | **Task 6** |
| `probe.cancel` frame constant; `probe.assign`/`probe.result` payload models + corpus fixtures | constants for assign/result exist; cancel absent; all three payloads and fixtures absent | **Task 7** |
| `mon.probe.remote` subject and a stream that carries it | **absent** | **Task 8** |
| `internal/collect/probe` Go package | **absent** (`internal/collect` has only `collect.go`, `payload.go`, `host/`) | **Tasks 16-20** |

Already present and reusable (do not rebuild):
- `CAPABILITY_FOR_TYPE[TYPE_PROBE_RESULT] = "remote_probe"` — `services/agent_link.py:65`.
- `TypeProbeAssign` is already in `controlFrameTypes` (`apps/agent/internal/frame/frame.go`), so
  assignments already cannot spool; `probe.result` is already classified as a data frame by
  `IsDataFrame`, so results already spool. **Do not change either classification.**
- The generic server→agent control path: `agent_registry.publish_agent_control_frame` →
  Redis `cb:agents:control:{id}` → `ws_agents._run_control_frame_listener` →
  `ws_agents._control_frame_bytes`. It is generic over `type`; `probe.assign`/`probe.cancel` need
  **zero** changes in `api/ws_agents.py`.
- `agent_capability_readiness.collector` is a free-form `String(64)` with a composite
  `(agent_id, collector)` PK, and `agent_telemetry._READINESS_STATES` already accepts
  `ready|degraded|unavailable|disabled`. `probe.icmp|tcp|http|dns` need **no** backend change and
  already render on Agent Detail.
- `agent_registry.py:765` renders `default_config_for(cap) | dict(grant.config or {})`, so giving
  `remote_probe` real defaults needs **no data migration**.

---

## Decisions

Every open question from investigation is resolved here. No task body may reopen one.

### D-1. Network facts ride `hello` as a `networks` field and land in a new `agent_networks` table.

**Decision:** Add `networks` to `HelloPayload` on both sides: one entry per non-loopback, up
interface, `{name, flags, addrs: ["10.0.0.5/24", "fd00::1/64"]}`, derived from `iface.Addrs()`
(which already yields `*net.IPNet`, i.e. the prefix, with no `/proc/net/route` parsing). Persist to
a new `agent_networks` table (`agent_id` FK CASCADE, `generation` int, `observed_at`, `facts` JSONB)
written from `agent_registry.update_hello_metadata`, bumping `generation` only when the normalized
facts differ.

**Rationale:** `iface.Addrs()` prefixes are sufficient for the "directly connected" test §3 requires
and are trivially testable behind an injected enumerator; `/proc/net/route` parsing is not, and
netlink would add a dependency. `hello` is the right carrier because §3's rule is evaluated at
assignment and dispatch time, both of which already read agent state, and because
`update_hello_metadata` is already the single ingest point for agent-reported metadata
(`api/ws_agents.py:557`). A generation counter is what Slice 4 asks for
(`plans/2026-08-04-cbi-agent-slice4-local-discovery.md`, "persist the latest normalized
interface/subnet report with a generation and timestamp"), so building it here avoids a rewrite.

### D-2. Fair sharing uses an oversampled lock CTE; the literal design wording is not implementable.

**Decision:** `_CLAIM_SQL` becomes a three-stage CTE: `locked` (the `FOR UPDATE SKIP LOCKED` claim,
`LIMIT :oversample`), `ranked` (`row_number() OVER (PARTITION BY coalesce(probe_agent_id, 0) ORDER
BY next_due_at)`), then the `UPDATE ... WHERE id IN (SELECT id FROM ranked WHERE rn <= :per_vantage
LIMIT :batch)`. Defaults: `:oversample = 1000`, `:per_vantage = 50`, `:batch = 200`.

**Rationale:** PostgreSQL rejects `FOR UPDATE is not allowed with window functions`, so the ranking
cannot sit at the same query level as the claim (verified against the running
`circuitbreaker-postgres-1`). Locking first and ranking second is the only working shape, but it
means the global limit applies *before* the per-vantage rank — so an inner `LIMIT 200` would let one
agent with 400 due monitors consume the whole locked set and starve every other vantage, which is
exactly what §2's rule exists to prevent. Oversampling the lock restores fairness; rows locked but
not claimed are released at commit and cost nothing. `:oversample` is the documented fairness knob.
This requires the new `(probe_agent_id, enabled, next_due_at)` index from §1 or the oversampled
`ORDER BY` degrades to a full sort over all due rows.

### D-3. `mon.probe.remote` gets its own stream, `MONITOR_PROBE`. Do not extend `MONITOR_POLL`.

**Decision:** New `ensure_monitor_probe_stream()` in `core/nats_client.py` creating
`MONITOR_PROBE`, `subjects=["mon.probe.remote"]`, `RetentionPolicy.WORK_QUEUE`,
`max_age = int(os.getenv("CB_MONITOR_PROBE_MAX_AGE_S", "60"))`.

**Rationale:** `ensure_monitor_poll_stream()` swallows "already in use" at **debug** level, so
adding a subject to `MONITOR_POLL`'s list silently never applies to any existing deployment —
every `js_publish("mon.probe.remote", …)` then returns `False` with a warning and dispatch simply
never happens. JetStream additionally forbids two consumers with overlapping subject filters on a
`WORK_QUEUE` stream, so a second durable on `MONITOR_POLL` would need an explicit non-overlapping
filter anyway. A separate stream sidesteps both and gives §2's "blocked agents cannot delay server
checks" by construction. 60 s (vs `MONITOR_POLL`'s 300 s default) because an assignment older than
that is past its deadline and must not surface minutes late.

### D-4. `probe_execution_status = "stale"` has an explicit definition.

**Decision:** `stale` means: agent active **and** online **and** `remote_probe` granted **and**
probe readiness fresh, but no `completed` result has been accepted within `2 × interval_secs`
(`probe_last_result_at < now() - 2 * interval_secs`). Set in the reconciliation pass (D-5).
`unavailable` means we know *why* (offline / revoked / ungranted / out-of-scope / dispatch failed /
result timeout); `stale` means the agent looks healthy but results are not arriving.

**Rationale:** §1 declares the enum value and §7 renders it, but §2/§6/§8 never say when it is
entered. Without a rule an implementer either omits it (breaking the §7 UI contract) or invents an
unreasonable threshold.

### D-5. Run expiry and restart reconciliation live in the existing `monitor_scheduler` tick.

**Decision:** At the top of `workers/monitor_scheduler.py::tick`, before claiming: expire runs whose
`deadline_at < now() - interval '30 seconds'` and are still `queued|dispatched`, set the owning
monitor's `probe_execution_status='unavailable'` / `reason='result_timeout'`, and apply the D-4
staleness rule. No new worker process, no new `supervisord` entry.

**Rationale:** §8 requires expiry and restart reconciliation but names no owner. `monitor_scheduler`
is already the single-active clock under the `monitor_scheduler` advisory lock, already runs every
1.0 s, and already opens a session per tick. Without an owner, the §1 partial unique index turns a
silent agent into a permanent wedge for that monitor — the exact property
`tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items` exists to
protect. Expiry is also what makes best-effort `probe.cancel` (§4) safe.

### D-6. A monitor that becomes due with an active run **skips the interval**.

**Decision:** Pre-check for an active run before inserting; on collision (or on the partial-unique
`IntegrityError`) create **no** second run, do **not** pull `next_due_at` back, and set
`probe_execution_status='running'`, `reason='previous_run_in_flight'`.

**Rationale:** §2 requires "no active run already exists" but `claim_due_items` advances and commits
`next_due_at` before anything knows about runs. Skipping costs one interval; queuing would build a
backlog behind exactly the agent that is already slow. The design states existing interval semantics
remain authoritative, and D-5's expiry bounds how long a skip can persist.

### D-7. Remote results **do** go through `apply_proxmox_overrides`.

**Decision:** The shared result service (Task 11) calls
`services/monitoring/proxmox_override.py::apply_proxmox_overrides` for remote results exactly as the
poll worker does for local ones. This constrains the service's input type: it must carry
`check_type`, `target_type`, `target_id` per result, not just samples.

**Rationale:** `apply_proxmox_overrides` rewrites the `avail` sample for `icmp`/`tcp` monitors on
Proxmox-linked hardware/compute_unit targets. Skipping it would invert UP/DOWN for agent-executed
ICMP/TCP on Proxmox targets relative to the byte-identical server-executed check — a direct
violation of §6's "server and agent checks must produce the same status, event, history, and alert
semantics" that no test in §9's list would catch.

### D-8. `details` is persisted only in `monitor_probe_runs.result_metadata`. This asymmetry is deliberate.

**Decision:** Remote results persist `details` (and per-sample `error_reason`) in
`monitor_probe_runs.result_metadata`. Server-executed checks continue to discard both. Do **not** add
a details column to `telemetry_timeseries`.

**Rationale:** `CheckResult.details` and `Sample.error_reason` are silently dropped today —
`services/monitoring/writer.py::write_samples` maps only metric/value/source/ts, and
`monitor_poll_worker.poll_one` returns a 3-tuple with no slot for details. `telemetry_timeseries` is
a compressed Timescale hypertable with a 90-day retention policy (migration `0041`); altering it
requires the disable/restore-compression dance from `0095` for zero product benefit. §6's parity
requirement is about *monitor state*, not about audit metadata. Record the asymmetry in the shared
service's docstring so it is a decision, not a bug.

### D-9. Tenant compatibility: reject only when **both** sides carry a tenant and they differ.

**Decision:** Derive the monitor's tenant from its linked target entity (hardware / compute_unit /
service / external_node all carry `tenant_id`). If the monitor has a tenant and the agent has a
tenant and they differ, refuse assignment (422) and refuse dispatch. A tenant-less standalone
monitor (`target_type IS NULL`) **may** be assigned to a tenant-scoped agent.

**Rationale:** `monitor_items` has no `tenant_id` and is not in `0040_rls_policies`, so nothing at
the DB layer will enforce this — it is application code only. Refusing tenant-less monitors outright
would block the legitimate "admin monitors an arbitrary IP from the branch office" workflow, and the
target is still bounded by the agent's derived scope, which is derived from the tenant's own
directly connected networks. **Flagged for product confirmation** (see Open Decisions).

### D-10. HTTP monitor credentials are shipped inside `probe.assign`, in memory only.

**Decision:** `probe.assign.config` carries the monitor's full validated config including
`password`/`token`. The agent holds it in memory for the life of the run only — never in
`status.json`, never in `grants.json`, never in a log line, never echoed in `probe.result`.

**Rationale:** §2 explicitly says "credentials and complete monitor configuration are loaded
immediately before encrypted delivery"; there is no alternative that supports authenticated HTTP
checks from a remote vantage. `HttpConfig` already stores `password`/`token` in plaintext in
`monitor_items.params` JSONB, so this widens *distribution*, not *storage*. The three enforcing
properties are testable and are pinned in Tasks 16 and 18. **Flagged for security confirmation**
(see Open Decisions).

### D-11. Two new Go dependencies, pinned below the Go 1.22 CI ceiling.

**Decision:** `golang.org/x/net v0.33.0` (for `icmp` + `ipv4`/`ipv6` message construction) and
`github.com/miekg/dns v1.1.63` (for SOA/CAA/SRV and custom resolver+port), with a comment in
`apps/agent/go.mod` naming the CI pin as the reason.

**Rationale:** `.github/workflows/ci.yml` and `dev-ci.yml` pin `setup-go` to `1.22` while the local
toolchain is newer, so a too-new dependency compiles locally and breaks CI. Verified against
proxy.golang.org: `x/net v0.33.0` declares `go 1.18` (safe) but `v0.36.0` declares `go 1.23.0`
(breaks CI); `miekg/dns v1.1.63` declares `go 1.19` (safe) but `v1.1.66` declares `go 1.23.0`.
Go's stdlib `net.Resolver` cannot query SOA or CAA at all, which §5 requires.

### D-12. Agent unavailability writes no `avail` sample; uptime responses gain observed coverage.

**Decision:** Keep §2's rule (no `avail=0` on unavailability) and additionally expose observed
coverage alongside uptime so a gap is visible rather than invisible.

**Rationale:** `workers/rollup_worker.py::calculate_daily_rollups` counts observed minutes from
`metric='avail'` rows and **deletes** the `MonitorDailyStats` row when `observed_minutes == 0`;
`monitor_service._uptime_pct_map` averages only the rows that exist. Neither filters on `source`. So
a day-long agent outage neither shows as downtime nor as a gap — it silently shrinks the denominator
and a monitor unobserved for 20 hours reports 100% for the day. The no-sample rule is right (agent
unavailability is not target downtime); the reporting-integrity fix is coverage, not a fake sample.
**Flagged for product confirmation** (see Open Decisions).

### D-13. Execution-condition live pushes omit `status`.

**Decision:** Execution refreshes publish `{monitor_id, probe_execution_status,
probe_execution_reason, ts}` to Redis channel `monitor:{item_id}` with **no** `status` key, and the
frontend fold only overwrites `status` when the message carries one.

**Rationale:** `workers/monitor_poll_worker.py::_publish_live_status` currently emits
`{monitor_id, status, msg, ts}` for every outcome and `api/ws_monitors.py::_redis_listener` splats
the whole payload into the outbound frame, so any `status` key would be folded straight into the
card by `MonitorsPage.jsx` and clobber the pill — violating §7's "the main UP/DOWN status pill
retains the last target state when execution is unavailable". Corollary: **do not** fold
`probe_execution_status` into `MonitorCard.jsx`'s exported `groupStatusOf` or `headlineOf`;
`MonitorsPage.jsx` imports `groupStatusOf` for the summary counts, the group buckets **and** the
status filter.

### D-14. "Check now" 409 comes from a result object, computed synchronously.

**Decision:** `monitor_service.run_immediate_check` and `run_target_check` return a result object
(`ok: bool`, `reason: str | None`) from a synchronous eligibility precheck, then create the run and
schedule the publish. `api/monitor.py`'s `/{monitor_id}/check` raises `HTTPException(409,
detail=reason)` for the agent path. Server monitors (`probe_agent_id IS NULL`) keep today's 200
behavior byte-for-byte.

**Rationale:** Both service functions are fire-and-forget `loop.create_task` returning `bool`, and
both routes discard the result and always return 200 with the monitor body. §2 requires 409 with the
availability reason, which needs the precheck before the async hop.

### D-15. `require_write_auth` already **is** editor-level. Add no new RBAC dependency to the monitor router.

**Decision:** `probe_agent_id` writes stay behind the existing
`Depends(require_write_auth)`. `remote_probe` grant/scope writes stay behind the existing
`require_role("admin")` on `api/agents.py`. Monitor read routes keep today's (unauthenticated)
convention.

**Rationale:** `core/security.py::require_write_auth` already requires role in `{admin, editor}` or a
`write:*` scope, which satisfies §7's "assignment writes require editor-level monitor permission".
Adding RBAC to the monitor read routes is unbudgeted scope creep that would break the frontend and
existing tests; the read-route inconsistency is pre-existing and is recorded as a follow-up.

### D-16. Reconnect makes assigned monitors due **with jitter**, not at exactly `now()`.

**Decision:** On connect, `UPDATE monitor_items SET next_due_at = now() + make_interval(secs =>
random() * least(interval_secs, 30)) WHERE probe_agent_id = :id AND enabled`, executed inside the
`with SessionLocal() as db:` block in `api/ws_agents.py` that already commits alongside
`record_event(db, agent_id, "connected")`.

**Rationale:** An agent with 300 assignments reconnecting at exactly `now()` gets 50 claimed on the
very next tick and dispatched into a 20-slot queue, producing an immediate burst of
capacity-exhausted execution errors — turning a healthy reconnect into an alert-adjacent event.
`services/monitoring/scheduler.py` already uses exactly this jitter idiom.

---

## Global Constraints

Apply to every task; the task reviewer holds implementers to these.

**Backend authority is not negotiable.** All scheduling state stays in `monitor_items.next_due_at`.
Agents never hold a schedule. A worker or agent crash must never wedge an item — the property proven
by `tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items` must hold
for remote runs too, which is what D-5's expiry pass buys.

**One result path.** After Task 11 there is exactly **one** function that turns a normalized check
outcome into samples + state + events + alerts + live status. `workers/monitor_poll_worker.py` and
the `probe.result` handler both call it. Do not grow a second copy — that is the mistake the slice
1/2 hardening plan spent Task 5 undoing for telemetry.

**Commit ownership stays at the top-level caller.** `services/monitoring/state.py::apply_result` and
`services/monitoring/writer.py::write_samples` both document "the caller owns the transaction". The
shared result service commits **once**, covering samples + state + events + run completion (§6).

**NATS subjects are declared only in `apps/backend/src/app/core/subjects.py`** and imported. Never
hardcode `"mon.probe.remote"`.

**One capability registry.** `remote_probe` config is defined in exactly two places:
`apps/backend/src/app/services/agent_capabilities.py`'s `CAPABILITY_DEFINITIONS` and
`apps/agent/internal/capability/capability.go`'s `configNormalizers`. Bounds constants must be
byte-identical in both.

**One scope evaluator.** After Task 4 there is exactly one backend evaluator and one Go evaluator,
verified against one shared corpus. Slice 4 imports them. Any second CIDR/special-use rule set is a
review rejection.

**Never backfill grant rows in a migration.** Registry defaults merge over persisted config at read
time (`agent_registry.py:765`), so already-approved agents keep `config = {}` in the database and
still read the full defaults. Every code path reading `remote_probe` config must go through
`structured_grants_dict` / `default_config_for`, never bare `grant.config`.

---

## Parity contract

The Go probe checkers are a **byte-level behavioral mirror** of three backend modules. Parity is the
acceptance bar, not an aspiration. Named functions being mirrored:

| Go checker | Mirrors | Contract that must match exactly |
|---|---|---|
| ICMP | `apps/backend/src/app/services/monitoring/collectors/net.py::collect_icmp` (and `_jitter`) | Defaults `packet_count=5`, `timeout=1.5`. Samples **always** start `avail`, `packet_loss_pct`; when any reply arrives, append in this order `latency_ms` (mean, 3dp), `latency_min_ms` (raw min), `latency_max_ms` (raw max), `jitter_ms` (mean absolute successive delta, 3dp, `0.0` for <2 samples). `loss_pct = round(lost/count*100, 2)`. `up = bool(latencies)`. msg up = `"{mean}ms avg, {loss_pct}% loss"`; msg down = `"100% packet loss ({count} probes)"`. `details` always absent. **The `icmp_unavailable` branch becomes `outcome="execution_error"`, not target DOWN** (§5). |
| TCP | `net.py::collect_tcp` | Defaults `timeout=1.0`, `port=80`. `ports` list tried **in order**, first success wins. Success: `avail=1`, `latency_ms` (`round(ms, 2)`), msg `"port {port} open in {latency}ms"`. Failure: `avail=0` **only** — no latency sample, no error_reason — msg `"no reachable port in {ports}"`. |
| HTTP | `apps/backend/src/app/services/monitoring/collectors/web.py::collect_http` (with `_request`, `_status_accepted`, `_json_path`, `_tls_details`) | URL default `f"http://{host}/"`. Sample order is `latency_ms`, `http_status`, then optional `cert_days_remaining`, with `avail` **inserted at index 0** last. TLS details come from a **separate** TLS connection (`_tls_details`) and never fail the check; shape `{"tls": {subject_cn, issuer_cn, expires_at, days_remaining}}`. Checks run in order: accepted-status (`"lo-hi"` inclusive ranges or bare digit strings; empty list falls back to `["200-299"]`) → keyword (+`keyword_invert`) → dotted `json_path` with `[idx]` segments compared as `str(value) != str(expected)`. msgs: `"unexpected status {code}"`, `"keyword {found|not found}: {kw!r}"`, `"json {path} = {value!r}, expected {expected!r}"`, success `"{code} in {latency}ms"`. Transport exception → `avail=0` with `error_reason="http_error"`, msg `"request failed: {ExcType}"`, no latency sample. |
| DNS | `apps/backend/src/app/services/monitoring/collectors/dns_check.py::collect_dns` | Defaults `record_type="A"` (uppercased), `port=53`, `timeout=5.0`. Success samples `avail`, `latency_ms` (2dp); `details = {"records": [str(r) …]}`; msg `"{RT}: {n} record(s) in {latency}ms"`. `expected_values` matching is **substring, any-of-any**: `any(any(e in r for r in records) for e in expected)`; mismatch rewrites `samples[0]` to `avail=0`, keeps `details`, msg `"{RT} records {records} did not match expected {expected}"`. Lookup failure → `avail=0`, `error_reason="dns_error"`, msg `"{RT} lookup failed: {exc}"`. |

**Defaults come from the collectors, not from pydantic.** `schemas/monitor.py`'s
`_MonitorBase._validate_config` persists `model_dump(exclude_unset=True)`, so a stored config is
usually **sparse** and the collector-side `params.get(key, default)` values are the real defaults.
They agree today; the Go side must replicate the collector defaults.

---

## Security invariants (testable assertions, not prose)

Each is owned by a named task and pinned by a named test.

| Invariant | Owner | Pinned by |
|---|---|---|
| Scope is enforced **independently** on both ends — a backend-approved assignment whose target is outside the agent's own derived scope is still rejected by the agent | Tasks 3, 4, 16 | `TestProbeRuntime_OutOfScopeAssignmentIsRejectedWithoutDialing` (Go), `test_dispatch_refuses_target_outside_effective_scope` (backend) |
| Every HTTP redirect hop is re-validated against scope before connecting | Task 18 | `TestHTTPChecker_RedirectToOutOfScopeHostIsRejected`, `TestHTTPChecker_RedirectToPublicIPIsRejected` |
| DNS rebinding: every resolved A/AAAA of a hostname target must be in scope; a resolver returning one in-scope and one out-of-scope address rejects | Tasks 4, 16, 18 | `TestScope_HostnameWithAnyOutOfScopeAddressIsRejected` |
| `0.0.0.0/0` and `::/0` are rejected as scope entries | Task 3 | `test_normalize_remote_probe_config_rejects_default_routes` |
| Loopback, link-local, multicast, broadcast, unspecified, IPv4-mapped-IPv6 and cloud-metadata destinations are blocked and **cannot** be re-enabled by `additional_cidrs` | Tasks 3, 4 | `test_scope_permanently_blocks_special_use_even_when_explicitly_added` + its Go corpus twin |
| Only `http`/`https` URL schemes; scheme is rejected **before** any DNS resolution | Task 18 | `TestHTTPChecker_RejectsNonHTTPSchemeBeforeResolving` |
| `probe.result` `details` ≤ 64 KiB and `msg` ≤ 2000 chars, enforced as the **first** thing the handler does | Task 12 | `test_probe_result_oversized_details_is_rejected_without_touching_monitor_state` |
| A `run_id` that does not match the authenticated agent **and** monitor is rejected and recorded as a capability violation | Task 12 | `test_probe_result_with_foreign_run_id_records_capability_violation` |
| A result arriving after `deadline_at + 30s` updates run audit state only — never monitor state or uptime | Task 12 | `test_late_result_updates_run_audit_but_not_monitor_state` |
| Duplicate `run_id` result is an idempotent no-op | Task 12 | `test_duplicate_probe_result_is_idempotent` |
| Secrets never leave memory: no `password`/`token`/`Authorization` value in `status.json`, `grants.json`, agent logs, `probe.result`, or `monitor_probe_runs.result_metadata` | Tasks 16, 18 | `TestProbeRuntime_AssignmentSecretsAreNeverPersistedOrLogged`, `TestHTTPChecker_ResultCarriesNoRequestHeadersOrBody` |
| HTTP response inspection is bounded at 1 MiB | Task 18 | `TestHTTPChecker_ResponseBodyIsBoundedAtOneMiB` |
| Scope and grant config are never host-editable (agent stores the server's normalized config and re-reads it from the server on connect) | Task 5 | `TestRemoteProbeConfig_LocalEditsAreOverwrittenByServerGrant` |

---

## Ordered Implementation Tasks

Ordering rationale: the two missing prerequisites first (network facts → scope evaluator), then the
contracts everything else binds to (capability config → schema → frame protocol → NATS), then the
backend dispatch/result pipeline, then the Go probe runtime and checkers (which can proceed in
parallel with backend work from Task 7 onward, since the protocol contract has landed), then the
frontend, then E2E and the gate.

---

### Task 1: Agent-reported directly-connected network facts on `hello`

**Prerequisite work — §3's derived scope has no input without this.**

**Scope:** Enumerate the agent's non-loopback, up interfaces with their IPv4/IPv6 addresses and
prefix lengths, and carry them on `hello`. No scope logic yet — this task only produces facts.

**Files touched:**
- **new** `apps/agent/internal/hostinfo/netfacts.go`, `apps/agent/internal/hostinfo/netfacts_test.go`
- `apps/agent/internal/hostinfo/hostinfo.go` (`Collect` populates the new field)
- `apps/agent/internal/frame/frame.go` (`HelloPayload` gains `Networks`)
- `apps/backend/src/app/schemas/agent_frame.py` (`HelloPayload` gains `networks`)
- `fixtures/agent_frame_corpus.json` (one `hello` entry carrying `networks`, one without)
- `apps/agent/internal/frame/conformance_test.go` (`roundTripHelloPayload` covers the new field)

**Tests first:**
- `apps/agent/internal/hostinfo/netfacts_test.go` (new):
  `TestNetFacts_SkipsLoopbackAndDownInterfaces`,
  `TestNetFacts_EmitsIPv4AndIPv6PrefixesFromInjectedEnumerator`,
  `TestNetFacts_OmitsLinkLocalAndUnroutableAddresses`,
  `TestNetFacts_IsDeterministicallyOrdered` (sorted by interface name, then address, so the
  backend's generation comparison in Task 2 does not churn),
  `TestNetFacts_EnumeratorErrorYieldsEmptySliceNotPanic`.
  The enumerator is an injected `func() ([]net.Interface, error)` + `func(net.Interface)
  ([]net.Addr, error)` pair with real-`net` fallbacks, mirroring the `Now`/`Usage` seam style on
  `apps/agent/internal/collect/host/host.go`'s `Collector`. **No test may touch the real host's
  interfaces.**
- `apps/backend/tests/test_agent_frame_conformance.py` — the existing
  `test_corpus_covers_every_declared_frame_type` and typed round-trip already cover this once the
  fixtures land; add nothing new.

**Implementation:** `netfacts.Collect()` returns `[]frame.NetworkFacts{Name, Flags, Addrs}` where
`Addrs` are `"10.0.0.5/24"`-style CIDR strings taken from `iface.Addrs()`'s `*net.IPNet` (which
already carries the prefix — do **not** parse `/proc/net/route`). `HelloPayload.Networks` is
`omitempty` on the Go side and optional-with-default on the Python side, per the existing
"every field optional-with-default for backward compat" convention in `schemas/agent_frame.py`.

**Verify:**
```
(cd apps/agent && go test -race ./internal/hostinfo/... ./internal/frame/...)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/test_agent_frame_conformance.py --no-cov -q)
```
Green = new `netfacts` tests pass; the corpus coverage test still asserts set equality.

**Depends on:** none.

---

### Task 2: Persist normalized network facts with a generation

**Scope:** Store what Task 1 reports, versioned, so assignment-time and dispatch-time scope
evaluation have a stable input and Slice 4 has the report it expects.

**Files touched:**
- `apps/backend/src/app/db/models.py` (**new** `AgentNetwork` model, table `agent_networks`)
- **new** `apps/backend/migrations/versions/0098_agent_networks.py`
  (`revision = "0098_agent_networks"`, `down_revision = "0097_agent_spool_state"`)
- `apps/backend/migrations/versions/0001_init.py` — add `"agent_networks"` to `_EXCLUDED_TABLES`
- `apps/backend/src/app/services/agent_registry.py` (`update_hello_metadata` persists + bumps
  `generation` only on change)
- `apps/backend/tests/factories.py` (`agent_network()` factory)

**Tests first:**
- **new** `apps/backend/tests/unit/test_migration_0098_agent_networks.py`, mirroring
  `tests/unit/test_migration_0093_agent_pending_device_key.py`:
  `test_migration_file_exists`, `test_revision_chains_onto_0097`,
  `test_migration_0098_is_the_only_child_of_0097` (AST-parse every file in
  `apps/backend/migrations/versions/` and assert exactly one declares that `down_revision` — the
  guard against a second alembic head, copied from `tests/test_agent_spool_schema.py`),
  `test_agent_networks_table_and_indexes_exist`.
- **new** `apps/backend/tests/services/test_agent_network_facts.py`:
  `test_hello_with_networks_creates_a_generation_one_row`,
  `test_identical_facts_do_not_bump_generation`,
  `test_changed_facts_bump_generation_and_observed_at`,
  `test_hello_without_networks_leaves_the_previous_report_intact` (presence-not-truthiness, matching
  `update_hello_metadata`'s documented rule).

**Implementation:** `agent_networks` = `agent_id` FK `ondelete="CASCADE"`, `generation` Integer,
`observed_at` `DateTime(timezone=True)`, `facts` JSONB, unique on `agent_id` (one current report per
agent). Migration uses the `0089_agents.py` `if_not_exists=True` style, since the table is excluded
from the bootstrap.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/unit/test_migration_0098_agent_networks.py tests/services/test_agent_network_facts.py --no-cov -q)
(cd apps/backend && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic upgrade head && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic downgrade -1 && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic upgrade head)
```
Green = both suites pass **and** the migration round-trips against a plain Postgres.

**Depends on:** Task 1.

---

### Task 3: The shared network-scope evaluator (backend) and its cross-language corpus

**Prerequisite work — nothing like this exists in either language.**

**Scope:** One backend module that turns `(network facts, remote_probe config)` into a versioned
effective scope and answers "is this destination permitted?". Slice 4 imports it unchanged.

**Files touched:**
- **new** `apps/backend/src/app/core/agent_scope.py`
- **new** `fixtures/agent_scope_corpus.json` — the shared backend/Go conformance corpus
- **new** `apps/backend/tests/unit/test_agent_scope.py`
- **new** `apps/backend/tests/unit/test_agent_scope_corpus.py`

**Reuses (do not re-derive):** `apps/backend/src/app/core/network_acl.py`'s `is_cidr_allowed`
(`subnet_of` with explicit version matching) and `_RFC1918_NETWORKS`;
`apps/backend/src/app/services/discovery_network.py`'s `_validate_cidr` `/0`-rejection and
size-limit precedent; `apps/backend/src/app/core/url_validation.py`'s `_ALLOWED_SCHEMES`.

**Must NOT reuse:** `url_validation._is_forbidden_ip` — it blocks `is_private`, which is exactly
what remote probing must **allow**. And `network_acl.is_ip_in_cidrs` fail-opens on an empty list
(`if not cidrs: return True`); an empty effective scope must **deny everything**.

**Tests first (`tests/unit/test_agent_scope.py`):**
- `test_derived_scope_contains_only_private_ipv4_and_ipv6_ula`
- `test_derived_scope_excludes_loopback_link_local_multicast_and_public`
- `test_excluded_cidrs_narrow_the_derived_scope`
- `test_additional_cidrs_widen_it`
- `test_scope_permanently_blocks_special_use_even_when_explicitly_added` — loopback, link-local,
  multicast, broadcast, unspecified, `169.254.169.254`, `fd00:ec2::254`, and IPv4-mapped IPv6
  (`::ffff:10.0.0.1` must be evaluated as `10.0.0.1`, not silently pass a v6-only path)
- `test_empty_effective_scope_denies_every_destination` (the fail-open guard)
- `test_normalize_remote_probe_config_rejects_default_routes` — `0.0.0.0/0` and `::/0`
- `test_hostname_target_requires_every_resolved_address_in_scope`
- `test_scope_version_changes_only_when_effective_scope_changes`
- `tests/unit/test_agent_scope_corpus.py::test_every_corpus_case_matches_the_evaluator` — drives
  `fixtures/agent_scope_corpus.json`, whose entry shape is
  `{"description", "facts", "config", "destination", "expected": "allow"|"deny", "reason"}`.

**Implementation:** `derive_scope(facts, config) -> EffectiveScope` (networks + version) and
`evaluate(scope, destination) -> Decision`. Special-use denial is applied **after** every widening
rule so no override can re-enable it. IPv6 ULA is `fc00::/7` — note `network_acl.is_rfc1918` returns
`False` for every v6 network and has no ULA equivalent, so this is new code here.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/unit/test_agent_scope.py tests/unit/test_agent_scope_corpus.py --no-cov -q)
(cd apps/backend && ../../.venv/bin/ruff check src/app && PYTHONPATH=src ../../.venv/bin/mypy src/app)
```
Green = both suites pass; ruff and mypy stay clean on `src/app`.

**Depends on:** Task 2.

---

### Task 4: The Go mirror of the scope evaluator, verified against the same corpus

**Scope:** An independent Go evaluator producing identical decisions, proven by the Task 3 corpus.
This is what makes §3's "enforce scope independently" real rather than a comment.

**Files touched:**
- **new** `apps/agent/internal/netscope/netscope.go`, `netscope_test.go`, `corpus_test.go`
- `fixtures/agent_scope_corpus.json` (read-only from Go, at `../../../../fixtures/…` exactly as
  `apps/agent/internal/frame/conformance_test.go` reads the frame corpus)

**Tests first:**
- `apps/agent/internal/netscope/corpus_test.go::TestScopeCorpus_MatchesEveryCase` — iterates the
  shared corpus and asserts allow/deny parity with the backend. **This is the gate**: a rule that
  exists on one side only fails here.
- `netscope_test.go`: `TestDerive_OnlyPrivateAndULA`, `TestEvaluate_SpecialUseAlwaysDenied`,
  `TestEvaluate_EmptyScopeDeniesEverything`,
  `TestScope_HostnameWithAnyOutOfScopeAddressIsRejected` (the DNS-rebinding invariant),
  `TestEvaluate_IPv4MappedIPv6IsEvaluatedAsIPv4`,
  `TestEvaluate_DirectlyConnectedRequirementRejectsRoutedTargetWithoutOverride` — §3's
  agent-side extra rule, so a hostile route advertisement cannot widen the default grant.

**Implementation:** Package `netscope`, no dependency on `internal/link` or `internal/collect`, so
Slice 4's discovery can import it too. Every decision returns a machine-readable reason string that
matches the corpus `reason` field.

**Verify:**
```
(cd apps/agent && go test -race ./internal/netscope/...)
(cd apps/agent && go vet ./...)
```
Green = every corpus case matches; `go vet` clean.

**Depends on:** Task 3.

---

### Task 5: Give `remote_probe` a real configuration schema on both sides

**Scope:** Replace the placeholder registry entry with §3's config, add the Go normalizer, and repair
every assertion that currently hard-codes `config: {}`.

**Files touched:**
- `apps/backend/src/app/services/agent_capabilities.py` — replace
  `_reject_unknown_keys("remote_probe")` with `_normalize_remote_probe_config` and a real
  `default_config`
- `apps/agent/internal/capability/capability.go` — new `RemoteProbeConfig`,
  `DefaultRemoteProbeConfig()`, `normalizeRemoteProbeConfigRaw` registered in `configNormalizers`,
  `Gate.RemoteProbeConfig()` accessor, and `Min/MaxProbeConcurrent` consts beside
  `MinHostInterval`/`MaxHostInterval`
- **Assertion repairs (same commit or the suites go red):**
  `apps/agent/e2e/test_agent_e2e.py:396`;
  `apps/backend/tests/api/test_agents_api.py`; `apps/backend/tests/services/test_agent_registry.py`;
  `apps/frontend/src/__tests__/{agent-approval-modal,agents-page,agent-detail-page}.test.jsx`

**Tests first:**
- **new** `apps/backend/tests/services/test_agent_capabilities_remote_probe.py`:
  `test_defaults_match_the_design_document` (`max_concurrent=20`, `scope_mode="direct_private"`,
  three empty lists), `test_max_concurrent_out_of_range_raises`,
  `test_unknown_key_raises`, `test_normalize_remote_probe_config_rejects_default_routes`,
  `test_bare_boolean_grant_acquires_the_default_config`,
  `test_existing_grant_with_empty_config_reads_back_the_defaults` (proves no data migration is
  needed — `agent_registry.py:765` merges at read time),
  `test_new_registry_config_is_not_backfilled_onto_already_approved_agents`
- `apps/agent/internal/capability/capability_test.go`:
  `TestNormalizeRemoteProbeConfig_DefaultsAndBounds`,
  `TestNormalizeRemoteProbeConfig_InvalidConfigKeepsEnabledAndPreviousConfig` (the existing
  per-capability `GrantFault` isolation contract),
  `TestRemoteProbeConfig_LocalEditsAreOverwrittenByServerGrant` (§3: scope is never host-editable)

**Implementation:** Normalizer style copies `_normalize_host_telemetry_config`: reject unknown keys
via `set(config) - set(DEFAULTS)`, merge `dict(DEFAULTS) | config`, then per-field checks with
explicit `isinstance(x, bool)` guards before int checks, raising `ValueError` (which
`schemas/agents.py::_validate_capability_map` already turns into a 422 at both approve and
capabilities-update). CIDR validation delegates to Task 3's module.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_agent_capabilities_remote_probe.py tests/services/test_agent_registry.py tests/api/test_agents_api.py --no-cov -q)
(cd apps/agent && go test -race ./internal/capability/...)
(cd apps/frontend && npx vitest run src/__tests__/agent-approval-modal.test.jsx src/__tests__/agents-page.test.jsx src/__tests__/agent-detail-page.test.jsx)
```
Green = all three estates pass. **The e2e `_enroll_agent` assertion is repaired in this commit** —
all seven e2e tests call it, so a stale literal kills the whole e2e suite at enrollment.

**Depends on:** Task 3.

---

### Task 6: Probe schema — `monitor_items.probe_*`, `monitor_probe_runs`, migration `0099`

**Scope:** §1's data model, plus the two `0001_init.py` bootstrap edits without which fresh installs
are silently and permanently broken.

**Files touched:**
- `apps/backend/src/app/db/models.py` — five columns on `MonitorItem` (line 228) plus
  `Index("ix_monitor_items_probe_due", "probe_agent_id", "enabled", "next_due_at")` in its
  `__table_args__`; **new** `MonitorProbeRun` model
- **new** `apps/backend/migrations/versions/0099_monitor_probe_runs.py`
  (`revision = "0099_monitor_probe_runs"`, `down_revision = "0098_agent_networks"`)
- `apps/backend/migrations/versions/0001_init.py` — **two required edits**
- `apps/backend/tests/factories.py` — add `monitor_item()` and `monitor_probe_run()` (there is **no**
  monitor factory today; every monitor test builds `MonitorItem(...)` inline)

**The two bootstrap edits (both verified fatal if skipped):**
1. Add the five `probe_*` column names to `_EXCLUDED_COLUMNS["monitor_items"]` (today exactly
   `{"name", "max_retries", "retry_interval_secs", "last_status_change_at"}` — the four columns
   `0086_native_monitors` added, which is the house rule). `_should_copy_fk` returns `False` when the
   FK target is in `_EXCLUDED_TABLES`, and `agents` **is** excluded — so leaving `probe_agent_id` in
   the bootstrap emits `probe_agent_id INTEGER,` with **no FOREIGN KEY clause**, voiding the
   RESTRICT/409 behavior §1 requires on every fresh install.
2. Add `"monitor_probe_runs"` to `_EXCLUDED_TABLES`. The bootstrap's index-copy loop rebuilds indexes
   as `sa.Index(name, *cols, unique=index.unique)`, **dropping `postgresql_where`** — turning §1's
   partial unique index into a full unique index on `monitor_id`, so a fresh install would allow
   exactly one probe run per monitor, forever. (`privacy_finding_ignores`, the only existing
   partial-index table, is already excluded for precisely this reason.) The loop also copies only
   **multi**-column `UniqueConstraint`s and **no** `CheckConstraint`s — so do not express the
   `status`/`outcome` vocabularies as model-level CHECKs.

**Tests first:**
- **new** `apps/backend/tests/unit/test_migration_0099_monitor_probe_runs.py`:
  `test_revision_chains_onto_0098`, `test_migration_0099_is_the_only_child_of_0098` (AST guard),
  `test_monitor_items_has_probe_columns_and_composite_index`,
  `test_monitor_probe_runs_partial_unique_index_exists_with_its_predicate`
- **new** `apps/backend/tests/test_monitor_probe_schema.py` — the **bootstrap fidelity** tests,
  patterned on `tests/test_agent_telemetry_schema.py::test_bootstrap_metadata_preserves_autoincrement`
  (which loads a migration by file path via `importlib.util.spec_from_file_location` because
  `migrations/versions` is not a package):
  `test_bootstrap_does_not_create_monitor_items_probe_columns`,
  `test_bootstrap_does_not_create_monitor_probe_runs`,
  `test_probe_agent_id_foreign_key_survives_a_real_alembic_upgrade`
- **new** `apps/backend/tests/services/test_monitor_probe_runs_model.py`:
  `test_two_active_runs_for_one_monitor_violate_the_partial_unique_index`,
  `test_a_completed_run_does_not_block_a_new_active_run`,
  `test_deleting_an_agent_with_assignments_raises_integrity_error` (proves RESTRICT at the DB layer;
  the 409 wrapper is Task 14)

**Implementation:** `MonitorProbeRun` — single-column `id BigInteger primary_key=True
autoincrement=True` (**not** a hypertable; a composite `(id, created_at)` PK would reintroduce the
F-7 autoincrement trap), `run_id` String(32) unique-indexed, `monitor_id` + `agent_id` indexed FKs,
`status`, scheduled/dispatched/deadline/started/completed timestamps, `outcome`, bounded `msg`,
`error_code`, `result_metadata` JSONB, `attempt_count`, `created_at`. Indexes per §1:
`(agent_id, status, scheduled_at)`, `(monitor_id, created_at)`, and the partial unique
`(monitor_id) WHERE status IN ('queued','dispatched')` declared with `postgresql_where=sa.text(...)`
in **both** the model and the migration, exactly as
`migrations/versions/ec2fa30c05d1_add_privacy_finding_ignores.py` does. `monitor_items.probe_agent_id`
FK is `ondelete="RESTRICT"` — **the opposite of every other agent FK in `models.py`**, all of which
are CASCADE; add an inline comment naming §1 so it does not read as a mistake.

**Note:** `services/discovery_merge.py` calls `monitor_service._build_target_monitor` inside its own
transaction with a flush and no commit, so every new `monitor_items` column must be nullable or carry
a server default, or discovery auto-monitoring breaks
(`tests/services/test_discovery_auto_monitor.py`).

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/unit/test_migration_0099_monitor_probe_runs.py tests/test_monitor_probe_schema.py tests/services/test_monitor_probe_runs_model.py tests/services/test_discovery_auto_monitor.py --no-cov -q)
(cd apps/backend && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic upgrade head && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic downgrade -1 && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic upgrade head)
(cd apps/backend && CB_DB_URL="$TIMESCALE_URL" ../../.venv/bin/alembic upgrade head)
```
Green = suites pass **and** both migration lines succeed. The pytest suite builds schema with
`Base.metadata.create_all`, **not** Alembic, so it cannot catch a bootstrap or migration defect —
the alembic lines are the real check.

**Depends on:** Task 2 (revision chain).

---

### Task 7: `probe.assign` / `probe.cancel` / `probe.result` protocol + corpus

**Scope:** The wire contract, in both languages, with fixtures — the one-commit atomic gate.

**Files touched (all six must move together):**
- `apps/agent/internal/frame/frame.go` — `TypeProbeCancel = "probe.cancel"` in the server→agent const
  block, **plus** entries in `allFrameTypes` **and** `controlFrameTypes`; three payload structs
- `apps/backend/src/app/schemas/agent_frame.py` — `TYPE_PROBE_CANCEL` + three payload models
- `fixtures/agent_frame_corpus.json` — multiple fixtures per type (minimal, full, one per `outcome`)
- `apps/agent/internal/frame/conformance_test.go` — three `roundTrip*Payload` helpers wired into
  `TestCorpus_TypedPayloadsDecode`'s switch; **delete** `TypeProbeAssign` and `TypeProbeResult` from
  `pendingCorpusTypes`
- `apps/backend/tests/test_agent_frame_conformance.py` — three entries in `_PAYLOAD_MODEL_FOR_TYPE`;
  **delete** `TYPE_PROBE_ASSIGN` and `TYPE_PROBE_RESULT` from `PENDING_CORPUS_TYPES`

**The gate is bidirectional.** `test_corpus_covers_every_declared_frame_type` asserts
`corpus_types | PENDING_CORPUS_TYPES == declared` **and** `not (corpus_types & PENDING_CORPUS_TYPES)`
— adding a fixture without deleting the exemption fails exactly as loudly as the reverse.
`probe.cancel` is **deliberately not pre-exempted**, so declaring the constant without a fixture
fails immediately in both languages.

**Classification rules — do not "fix" either:** `TypeProbeAssign` is already in `controlFrameTypes`
(assignments must never spool, §4); `TypeProbeCancel` must be **added** there; `TypeProbeResult` must
**stay out** of it, or results stop surviving outages (§4).

**Payload shapes (§4):** `ProbeAssignPayload{run_id, monitor_id, check_type, host, config,
scheduled_at, deadline_at}`; `ProbeCancelPayload{run_id, reason}`;
`ProbeResultPayload{run_id, monitor_id, outcome, up, started_at, finished_at, samples[{metric,
value}], msg, details}`. `up` carries **no** `omitempty` on the Go side — `false` is semantically
load-bearing and must survive re-encode, exactly as `HeartbeatPayload`'s spool fields do.

**Timestamps:** always `.isoformat()` strings, tz-aware. `agent_registry.publish_agent_control_frame`
serializes with `json.dumps(frame, default=str)`, so a raw `datetime` becomes
`"2026-08-04 18:00:00+00:00"` (space separator) which Go's `time.Time` **rejects** — it requires
RFC3339 with a `T`. Mirror `agent_link._handle_key_rotate`'s `.isoformat()` call site.

**Tests first:**
- `apps/agent/internal/frame/conformance_test.go` — `TestCorpus_TypedPayloadsDecode` gains the three
  arms; `TestCorpus_CoversEveryDeclaredFrameType` must go green with the two deletions
- `apps/backend/tests/test_agent_frame_conformance.py` — same, driven by the shared corpus
- **new** `apps/agent/internal/frame/frame_test.go` case
  `TestProbeResultPayload_FalseUpSurvivesRoundTrip`

**Verify:**
```
(cd apps/agent && go test -race ./internal/frame/...)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/test_agent_frame_conformance.py --no-cov -q)
```
Green = both conformance suites pass with `probe.assign`/`probe.result` **removed** from both pending
lists and `probe.cancel` present in the corpus.

**Depends on:** none (parallel with Tasks 1-6). **Everything from Task 9 onward depends on this.**

---

### Task 8: `mon.probe.remote` subject and the `MONITOR_PROBE` stream

**Scope:** D-3. A dedicated work-queue stream so a blocked agent cannot delay server checks and so
the subject actually exists on upgraded deployments.

**Files touched:**
- `apps/backend/src/app/core/subjects.py` — `MONITOR_PROBE_REMOTE = "mon.probe.remote"` beside
  `MONITOR_POLL_ITEM`, under the same `mon.` root comment
- `apps/backend/src/app/core/nats_client.py` — new `ensure_monitor_probe_stream()`, called from the
  same connect and reconnect sites that call `ensure_monitor_poll_stream()`
- `apps/backend/src/app/workers/monitor_scheduler.py` — `await nats_client.ensure_monitor_probe_stream()`
  beside the existing `ensure_monitor_poll_stream()` call

**Tests first:**
- **new** `apps/backend/tests/services/test_monitor_probe_stream.py`:
  `test_ensure_monitor_probe_stream_declares_a_separate_work_queue_stream` (asserts name
  `MONITOR_PROBE`, subjects `["mon.probe.remote"]`, `WORK_QUEUE`),
  `test_monitor_probe_remote_is_not_added_to_the_monitor_poll_subject_list` — the regression guard
  for the swallowed-conflict trap,
  `test_subject_constant_is_not_hardcoded_at_any_call_site` (grep-style assertion over
  `src/app` that the literal appears only in `core/subjects.py`)

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_monitor_probe_stream.py --no-cov -q)
```
Green = the new stream is declared separately and `MONITOR_POLL`'s subject list is untouched.

**Depends on:** none.

---

### Task 9: Fair-share due-claiming, server/agent routing, and run creation

**Scope:** §2's scheduling half. `claim_due_items` learns about vantages; `enqueue_due` learns to
route.

**Files touched:**
- `apps/backend/src/app/services/monitoring/scheduler.py` — `_CLAIM_SQL` rewrite per D-2,
  `probe_agent_id` added to the `RETURNING` list **and** the dict mapping in `claim_due_items`,
  routing + run creation + dispatch-failure compensation in `enqueue_due`
- `apps/backend/src/app/workers/monitor_scheduler.py` — pass the new knobs

**Tests first (`apps/backend/tests/services/test_monitor_scheduler.py`, which has only two tests
today):**
- `test_claim_returns_probe_agent_id` — the silent-failure guard: without it in `RETURNING`, every
  monitor routes to the server path and nothing else in this task can be observed
- `test_per_vantage_cap_limits_one_agent_to_fifty_per_tick`
- `test_one_busy_vantage_does_not_starve_another` — the fairness property D-2 exists to provide;
  seed 400 due monitors on agent A and 10 on agent B and assert B's are claimed
- `test_global_batch_limit_is_still_two_hundred`
- `test_server_monitors_publish_to_mon_poll_item_and_agent_monitors_to_mon_probe_remote`
- `test_agent_route_creates_a_queued_run_and_publishes_only_the_run_id` — §2: NATS carries `run_id`
  only, never credentials
- `test_second_claim_while_a_run_is_active_skips_the_interval_without_a_second_run` (D-6)
- `test_publish_failure_pulls_next_due_at_back_and_records_dispatch_failed` (§8) — note
  `nats_client.js_publish` never raises; it returns `False` and logs a warning
- `test_claim_still_never_wedges_an_item_after_a_publish_crash` — preserves the property in
  `tests/integration/test_monitor_engine_e2e.py::test_restart_self_heals_no_wedged_items`

**Implementation:** Do **not** restructure `claim_due_items`' commit-before-publish ordering — that
ordering is exactly why a crashed worker never wedges an item. §8's "retry scheduling soon" is
implemented as a **compensating** `UPDATE` that pulls `next_due_at` back (with jitter) and sets
`probe_execution_status='unavailable'` / `reason='dispatch_failed'`.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_monitor_scheduler.py tests/integration/test_monitor_engine_e2e.py --no-cov -q)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/ --no-cov -q)
```
Green = the new fairness/routing tests pass **and** the existing engine e2e is untouched.

**Depends on:** Tasks 6, 8.

---

### Task 10: Remote-dispatch worker and the eligibility helper

**Scope:** §2's dispatch half — consume `mon.probe.remote`, check eligibility, load full config, send
`probe.assign`.

**Files touched:**
- **new** `apps/backend/src/app/workers/monitor_probe_dispatch.py` — pattern-copy
  `workers/monitor_poll_worker.py::run_worker` (pull_subscribe, `fetch`, healthy-file, ack/nak
  discipline) with its own durable on `MONITOR_PROBE`
- **new** `apps/backend/src/app/services/monitoring/probe_eligibility.py`
- `apps/backend/src/app/workers/main.py` — `_TYPE_MAP` alias + `_dispatch` branch
- `docker/supervisord.mono.conf` — new `[program:worker-monitor-probe-dispatch]` beside the existing
  `[program:worker-monitor-scheduler]` / `[program:worker-monitor-poll]` blocks
- `apps/agent/e2e/supervisord-e2e.conf` — the same block, or the e2e stack silently never dispatches

**Tests first:**
- `apps/backend/tests/services/test_worker_dispatch.py` — extend for the new type alias (this file
  already pins `_TYPE_MAP`)
- **new** `apps/backend/tests/services/test_probe_eligibility.py`:
  `test_offline_agent_is_ineligible_with_reason_offline`,
  `test_revoked_agent_is_ineligible`, `test_missing_remote_probe_grant_is_ineligible`,
  `test_stale_readiness_is_treated_as_unknown_not_ready` — readiness rows have **no TTL** and
  `hello.readiness` is parsed but never persisted, so immediately after reconnect the rows are stale;
  gate on `updated_at` freshness, not just `state`,
  `test_target_outside_effective_scope_is_ineligible`,
  `test_mismatched_tenant_is_ineligible` (D-9),
  `test_active_run_makes_the_monitor_ineligible_this_tick` (D-6)
- **new** `apps/backend/tests/services/test_monitor_probe_dispatch.py`:
  `test_dispatch_loads_full_config_and_publishes_probe_assign`,
  `test_dispatch_assign_timestamps_are_rfc3339_with_a_T_separator` — the
  `json.dumps(default=str)` trap; a space-separated datetime is rejected by Go's `time.Time`,
  `test_dispatch_refuses_target_outside_effective_scope`,
  `test_undelivered_control_frame_marks_the_run_dispatch_failed` —
  `publish_agent_control_frame` returns `False` on Redis-down and `True` even with zero subscribers,
  so a `True` return is "not guaranteed", not "delivered"

**Implementation:** Eligibility composes `agent_registry.get_agent` / `is_agent_online` /
`get_agent_connection_owner` / `structured_grants_dict` + a fresh-readiness query over
`agent_capability_readiness` for `probe.icmp|tcp|http|dns` + Task 3's scope evaluator + D-9's tenant
rule + the active-run check, and returns a machine-readable reason on every denial. Dispatch sends
via `agent_registry.publish_agent_control_frame` — never by touching the socket, which only
`link_stream`'s main loop may write to.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_probe_eligibility.py tests/services/test_monitor_probe_dispatch.py tests/services/test_worker_dispatch.py --no-cov -q)
```
Green = all three pass, with the worker registered in `_TYPE_MAP` **and** both supervisord configs.

**Depends on:** Tasks 3, 6, 7, 8, 9.

---

### Task 11: Extract the shared monitor-result service (server path only)

**Scope:** §6's refactor, proven on the **existing** server path before any remote caller exists. If
the remote branch lands in the same change, a local regression and a remote regression become
indistinguishable.

**Files touched:**
- **new** `apps/backend/src/app/services/monitoring/result_service.py`
- `apps/backend/src/app/workers/monitor_poll_worker.py` — `process_batch` becomes a thin caller;
  `_publish_transitions` and `_publish_live_status` move **verbatim** into the new module;
  `poll_one`'s `(SampleRow, up, msg)` tuple widens to carry `outcome` and `details`
- `apps/backend/tests/services/test_monitor_poll_worker.py` and
  `apps/backend/tests/integration/test_monitor_engine_e2e.py` — both construct/destructure that
  tuple directly and must be updated

**Tests first:**
- **new** `apps/backend/tests/services/test_monitor_result_service.py`:
  `test_completed_result_writes_samples_state_events_in_one_commit`,
  `test_proxmox_override_is_applied_to_remote_results_too` (D-7),
  `test_source_is_always_monitor` — `write_samples` hardcodes `"source": "monitor"` and neither
  `_uptime_pct_map` nor `rollup_worker` filters on `source`, so a second avail-writing path would
  silently double-count uptime,
  `test_details_are_never_written_to_telemetry_timeseries` (D-8),
  `test_transitions_and_live_status_are_published_after_the_commit_not_inside_it`
- `apps/backend/tests/integration/test_monitor_engine_e2e.py` — add
  `test_server_and_agent_paths_produce_identical_status_events_and_alerts`, driving the **same**
  normalized result through both callers and diffing `monitor_items.last_status`,
  `monitor_events` rows, `telemetry_timeseries` rows and the published alert subject. This is §6's
  acceptance bar.

**Implementation:** One batch entrypoint taking per-result records carrying `item_id`, `target_type`,
`target_id`, `check_type`, `samples`, `outcome`, `up`, `msg`, `details`, `checked_at`, `source`,
`agent_id`, `run_id` — the `check_type`/`target_type`/`target_id` fields are required because
`apply_proxmox_overrides` needs the item dicts (D-7). Internally:
`apply_proxmox_overrides` → `write_samples` → `apply_result` → run completion → **one** `db.commit()`
→ return transitions + live-status payloads for the caller to publish **outside** the transaction.
Reuse the `_noop_close_factory` helper pattern from
`tests/services/test_monitor_poll_worker.py` for any test that must hand the service the
SAVEPOINT-isolated `db_session`.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_monitor_result_service.py tests/services/test_monitor_poll_worker.py tests/services/test_monitor_state.py tests/services/test_monitor_writer.py tests/integration/test_monitor_engine_e2e.py --no-cov -q)
```
Green = the server path behaves identically to before the extraction, plus the new parity test.

**Depends on:** Task 6.

---

### Task 12: `probe.result` ingest — authentication, idempotency, deadline, size limits

**Scope:** §4's acceptance rules. This is the one place a hostile or buggy agent can touch monitor
state, so every rule here is a security invariant.

**Files touched:**
- **new** `apps/backend/src/app/services/agent_probe.py` — patterned on
  `apps/backend/src/app/services/agent_telemetry.py`'s `validate_host_payload` /
  `ingest_host_sample`, with its own `InvalidProbeResult(ValueError)` and reusing
  `agent_telemetry.recordable_violation` for the 60 s per-agent violation rate limit
- `apps/backend/src/app/services/agent_link.py` — `_handle_probe_result` + one entry in `_HANDLERS`.
  `CAPABILITY_FOR_TYPE[TYPE_PROBE_RESULT] = "remote_probe"` **already exists**; only the handler is
  missing, and today an unhandled `probe.result` is a completely silent no-op — no event, no log, no
  commit

**Tests first:**
- **new** `apps/backend/tests/services/test_agent_probe_ingest.py`:
  `test_probe_result_oversized_details_is_rejected_without_touching_monitor_state` (64 KiB, enforced
  **first** — nothing upstream caps inbound frame size; the WebSocket read is unbounded and
  `receive_frame` only parses JSON),
  `test_message_is_truncated_to_two_thousand_characters`,
  `test_probe_result_with_foreign_run_id_records_capability_violation`,
  `test_probe_result_for_another_agents_run_is_rejected`,
  `test_late_result_updates_run_audit_but_not_monitor_state` (`deadline_at + 30s`),
  `test_deadline_is_evaluated_against_server_receipt_time_not_frame_ts` — a **spooled** result keeps
  its original producer `TS` (the agent only stamps `TS` when zero) while arriving much later, so
  `frame.ts` is agent-clock provenance, never arrival time,
  `test_duplicate_probe_result_is_idempotent`,
  `test_completed_result_feeds_the_shared_result_service`,
  `test_execution_error_result_does_not_write_avail_or_touch_retries`,
  `test_result_metadata_never_contains_config_secrets`
- `apps/backend/tests/services/test_agent_link.py` — `test_probe_result_without_the_grant_records_a_capability_violation`
  (already true via `CAPABILITY_FOR_TYPE`; pin it) and
  `test_probe_result_dispatch_commits_exactly_once`
- **new** `apps/backend/tests/api/test_ws_agents_probe.py` — end-to-end over the real Noise
  WebSocket, patterned on `tests/api/test_ws_agents_link.py` (module-level
  `pytestmark = pytest.mark.usefixtures("agent_redis_default")`, `_active_agent_with_key`
  committing through a real `SessionLocal()` because `link_stream` cannot see `db_session`'s
  SAVEPOINT, `TestNoiseInitiator` from `tests/helpers/agent_noise_client.py`):
  `test_link_delivers_probe_assign_published_by_another_worker`,
  `test_link_accepts_a_probe_result_and_completes_the_run`

**Implementation:** Validate size → parse → match run/monitor/agent → deadline → idempotency, then
hand the normalized record to Task 11's service. Keep it **fast**: the handler runs on the
`/link` socket read loop, and that loop is what advances `last_heartbeat_at` against the server's
60 s dead-link deadline. Follow `_handle_host_telemetry`'s exact shape for violations — catch the
domain error, gate on `recordable_violation(agent.id)`, `record_event(..., "protocol_violation",
detail={...})`, `db.commit()`.

**Cleanup note:** any row this path commits through its own `SessionLocal()` will survive
`db_session`'s rollback. `conftest.py::_reap_agents_committed_outside_the_test` reaps **only** the
`agents` table, so these tests must clean up their own `monitor_items` / `monitor_probe_runs` rows.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_agent_probe_ingest.py tests/services/test_agent_link.py tests/api/test_ws_agents_probe.py tests/api/test_ws_agents_link.py --no-cov -q)
```
Green = every §4 acceptance rule is a passing assertion and the existing link suite is unaffected.

**Depends on:** Tasks 6, 7, 11.

---

### Task 13: Execution errors, reconciliation, staleness, and probe-run retention

**Scope:** §6's execution-error branch, §8's expiry/restart reconciliation, D-4's `stale`, and §1's
seven-day retention.

**Files touched:**
- `apps/backend/src/app/services/monitoring/result_service.py` — the execution-error branch
- **new** `apps/backend/src/app/services/monitoring/probe_reconcile.py`
- `apps/backend/src/app/workers/monitor_scheduler.py` — call it at the top of `tick` (D-5)
- `apps/backend/src/app/main.py` — a seven-day purge APScheduler job in the lifespan, following the
  `purge_old_scan_results` / audit-log-purge precedents

**Tests first:**
- **new** `apps/backend/tests/services/test_monitor_probe_reconcile.py`:
  `test_overdue_run_is_expired_and_monitor_marked_unavailable`,
  `test_expired_run_releases_the_partial_unique_index_so_the_monitor_dispatches_again` — the
  anti-wedge property,
  `test_reconciliation_runs_under_the_existing_scheduler_advisory_lock`,
  `test_ready_agent_with_no_recent_result_is_marked_stale` (D-4: `2 × interval_secs`),
  `test_stale_clears_on_the_next_completed_result`,
  `test_runs_older_than_seven_days_are_purged`
- `apps/backend/tests/services/test_monitor_result_service.py` (extend):
  `test_execution_error_writes_no_avail_sample`,
  `test_execution_error_does_not_touch_consecutive_failures_or_last_status` — must **not** call
  `state.apply_result`, which unconditionally sets `last_polled_at` and `consecutive_failures`; use a
  separate probe-columns-only function rather than adding a mode to `apply_result` and risking
  `tests/services/test_monitor_state.py`,
  `test_execution_error_publishes_a_live_refresh_without_a_status_key` (D-13),
  `test_repeated_identical_execution_reason_records_only_one_event` (§6)

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_monitor_probe_reconcile.py tests/services/test_monitor_result_service.py tests/services/test_monitor_state.py --no-cov -q)
```
Green = execution errors are inert with respect to target state, and a silent agent self-heals.

**Depends on:** Tasks 11, 12.

---

### Task 14: Cancellation, reconnect, revoke, capability disable, and delete-409

**Scope:** §4's `probe.cancel` triggers and §8's lifecycle table.

**Files touched:**
- `apps/backend/src/app/services/monitor_service.py` — `set_paused`, `delete_monitor`,
  `update_monitor` (reassign), `set_target_paused`
- `apps/backend/src/app/api/agents.py` — `post_revoke`, `put_capabilities`, `delete_agent`
- `apps/backend/src/app/services/agent_link.py` — `_handle_uninstall` (the agent-initiated revoke
  path must not diverge from the REST one)
- `apps/backend/src/app/api/ws_agents.py` — the reconnect immediate-due `UPDATE` (D-16), inside the
  `with SessionLocal() as db:` block that already commits alongside `record_event(..., "connected")`

**Tests first:**
- **new** `apps/backend/tests/services/test_monitor_probe_cancellation.py`:
  `test_pausing_a_monitor_cancels_its_active_run_and_publishes_probe_cancel`,
  `test_deleting_a_monitor_cancels_its_active_run`,
  `test_reassigning_a_monitor_cancels_the_old_agents_run_and_rejects_its_late_result` (§9 case 9),
  `test_disabling_remote_probe_cancels_runs_and_marks_assignments_unavailable_without_deleting_them`
  — must run inside `put_capabilities`, because `dispatch_frame`'s gate uses `grants_dict` (the
  enabled flag only), so a result returning after the disable is dropped as a `capability_violation`
  rather than as a run result and the run would hang until expiry,
  `test_revoking_an_agent_cancels_runs_and_preserves_assignments`,
  `test_cancellation_is_best_effort_and_a_failed_publish_still_expires_the_run`
- `apps/backend/tests/api/test_agents_api.py`:
  `test_deleting_an_agent_with_assigned_monitors_returns_409`,
  `test_delete_succeeds_after_the_monitors_are_reassigned`
- `apps/backend/tests/api/test_ws_agents_probe.py`:
  `test_reconnect_makes_assigned_monitors_due_with_jitter_not_all_at_once` (D-16)

**Implementation:** Every one of these call sites is a **synchronous** `def`. The only precedent for
publishing from there is `monitor_service.run_immediate_check`'s
`asyncio.get_running_loop()` + `create_task` idiom, which returns `False` when no loop is running —
extract it into one helper so all five triggers behave identically. `delete_agent` today is a bare
`db.delete(agent)` with no guard; with the RESTRICT FK from Task 6 it would otherwise surface as an
unhandled `IntegrityError`/500, so the count-and-409 pre-check is required, not cosmetic.

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/services/test_monitor_probe_cancellation.py tests/api/test_agents_api.py tests/api/test_ws_agents_probe.py tests/services/test_monitor_service.py --no-cov -q)
```
Green = every §8 lifecycle row has a passing test and the existing agents API suite is unaffected.

**Depends on:** Tasks 12, 13.

---

### Task 15: API surface — schemas, endpoints, and the check-now 409

**Scope:** §7's API changes.

**Files touched:**
- `apps/backend/src/app/schemas/monitor.py` — `probe_agent_id` on `_MonitorBase` / `MonitorUpdate`;
  the read-only `probe_*` block on `MonitorRead` / `MonitorOverview` / `TargetMonitorSummary`
- `apps/backend/src/app/services/monitor_service.py` — `_to_dict` (the **single** serializer feeding
  list/overview/get/create/update/target-create) and the settable-field whitelist in
  `update_monitor` (which today lists exactly `name, host, interval_secs, max_retries,
  retry_interval_secs, enabled, target_type, target_id` — a missing `probe_agent_id` makes PATCH a
  silent no-op)
- `apps/backend/src/app/api/monitor.py` — `GET /{monitor_id}/probe-runs`; 409 on `/{monitor_id}/check`
- `apps/backend/src/app/api/agents.py` — `GET /{agent_id}/probes` and the eligible-agent listing.
  **Any literal collection path must be declared above the `/{agent_id}` route**, as `/pending`,
  `/capability-defaults` and `/presence` already are

**Tests first:**
- `apps/backend/tests/api/test_monitor_api.py` (has a `_create(client, auth_headers, **overrides)`
  helper):
  `test_create_with_probe_agent_id_persists_and_reads_back`,
  `test_patch_probe_agent_id_reassigns`,
  `test_patch_with_echoed_readonly_probe_fields_does_not_change_the_assignment` — the frontend sends
  the form verbatim and `MonitorUpdate` is **not** `extra="forbid"`, so a stale echoed
  `probe_agent_id` from an unrelated rename could silently reassign a monitor,
  `test_probe_mode_is_server_when_unassigned_and_agent_when_assigned`,
  `test_check_now_returns_409_with_the_reason_when_the_agent_is_offline` (D-14),
  `test_check_now_on_a_server_monitor_still_returns_200`,
  `test_probe_runs_endpoint_is_bounded_and_newest_first`,
  `test_assignment_write_requires_editor_level_auth` (D-15),
  `test_cross_tenant_assignment_is_rejected` (D-9)
- `apps/backend/tests/api/test_agents_api.py`:
  `test_agent_probes_lists_assigned_monitors_with_execution_state`,
  `test_eligible_agents_listing_reports_online_grant_readiness_concurrency_and_scope`

**Verify:**
```
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/api/test_monitor_api.py tests/api/test_agents_api.py tests/services/test_monitor_service.py tests/services/test_monitor_targets.py --no-cov -q)
(cd apps/backend && ../../.venv/bin/ruff check src/app && PYTHONPATH=src ../../.venv/bin/mypy src/app)
```
Green = the API contract in §7 is fully asserted; lint and types clean.

**Depends on:** Tasks 10, 13, 14.

---

### Task 16: Go probe runtime — queue, concurrency, cancellation, deadlines

**Scope:** `internal/collect/probe`'s scheduler half. **No checkers yet** — a stub checker keeps this
task independently testable.

**Files touched:**
- **new** `apps/agent/internal/collect/probe/{runtime.go,runtime_test.go,checker.go}`
- `apps/agent/internal/link/link.go` — `Options.OnProbeAssign` / `Options.OnProbeCancel`
  (`func(json.RawMessage) error`), defaulted to no-ops in `Run`, plus
  `case frame.TypeProbeAssign:` / `case frame.TypeProbeCancel:` arms in `runOnce`'s inbound switch
  next to the existing `capabilities.set` arm
- `apps/agent/internal/link/link_test.go` — delivery test

**The hard constraint:** that inbound switch runs on the **same goroutine** as the websocket writer,
the heartbeat ticker, the rekey ticker and the spool-drain ticker, and `incoming` is unbuffered. A
handler that probes inline stalls heartbeats (20 s interval) and crosses the server's 60 s dead-link
deadline, tearing down the link. **The handler must validate and enqueue only.**

**Tests first:**
- `runtime_test.go`:
  `TestProbeRuntime_HandlerReturnsImmediatelyAndDoesNotBlockTheCaller`,
  `TestProbeRuntime_RespectsMaxConcurrentFromTheGrant` (atomic max-concurrency counter),
  `TestProbeRuntime_QueueOfOneHundredIsBoundedAndOverflowReturnsRejected` — §2: capacity exhaustion
  returns an execution error, never a silent drop,
  `TestProbeRuntime_CancelBeforeExecutionEmitsCancelledOutcome`,
  `TestProbeRuntime_CancelDuringExecutionStopsTheCheckerAndEmitsCancelled`,
  `TestProbeRuntime_DeadlineExceededEmitsExecutionErrorNotTargetDown`,
  `TestProbeRuntime_OutOfScopeAssignmentIsRejectedWithoutDialing` — asserts the stub checker was
  never invoked; the agent-side half of the independent-enforcement invariant,
  `TestProbeRuntime_OutOfScopeAssignmentEmitsCapabilityViolation`
  (`frame.TypeCapabilityViolation` already exists and is already a data frame),
  `TestProbeRuntime_ResultsAreEmittedOnTheDataFrameChannel` — never `ControlFrames`;
  `outbound.go`'s `assertDataFrame` **panics** on a control frame sent through `DataFrames`,
  `TestProbeRuntime_AssignmentSecretsAreNeverPersistedOrLogged` (D-10),
  `TestProbeRuntime_RunIDIsEchoedVerbatim`
- `link_test.go`: `TestRun_DeliversProbeAssignToTheCallback`,
  `TestRun_ProbeAssignHandlerDoesNotDelayHeartbeats`

**Implementation:** `Checker` is a **local** interface — `Check(ctx, host string, cfg
json.RawMessage) (Outcome, error)` — because `collect.Collector`/`collect.Result` are hard-wired to
`frame.HostTelemetryPayload` and `collect.EncodeBounded` asserts `Schema == 1`. Reuse
`collect.SampleID()` (crypto/rand 16-byte lowercase hex — exactly §4's 32-hex `run_id` shape) for
any agent-generated id. Scope checks call Task 4's `internal/netscope`.

**Verify:**
```
(cd apps/agent && go test -race ./internal/collect/probe/... ./internal/link/...)
```
Green = concurrency, queue, cancellation and deadline behavior all pinned, with no checker written.

**Depends on:** Tasks 4, 5, 7.

---

### Task 17: Go ICMP and TCP checkers (parity)

**Scope:** Mirror `collectors/net.py::collect_icmp` and `collect_tcp` exactly. See the **Parity
contract** table.

**Files touched:**
- **new** `apps/agent/internal/collect/probe/{icmp.go,icmp_test.go,tcp.go,tcp_test.go}`
- `apps/agent/go.mod` / `go.sum` — `golang.org/x/net v0.33.0` (D-11)

**Tests first:**
- `icmp_test.go`: `TestICMP_SampleOrderMatchesBackendCollector` (`avail`, `packet_loss_pct`, then
  `latency_ms`, `latency_min_ms`, `latency_max_ms`, `jitter_ms`),
  `TestICMP_JitterIsMeanAbsoluteSuccessiveDeltaRoundedToThreePlaces`,
  `TestICMP_LossPercentRoundingMatchesBackend`,
  `TestICMP_MessageStringsMatchBackendExactly` (both up and 100%-loss forms),
  `TestICMP_SingleReplyYieldsZeroJitter`,
  `TestICMP_NoUnprivilegedPingSupportIsAnExecutionErrorNotTargetDown` — §5, and the inverse of the
  backend's `icmp_unavailable` `up=False`; getting this wrong inverts monitor state on every
  misconfigured host,
  `TestICMP_IPv6TargetUsesICMPv6`,
  `TestICMP_DefaultsAreCountFiveTimeoutOnePointFive` (collector defaults, not pydantic)
- `tcp_test.go`: `TestTCP_PortsAreTriedInOrderAndFirstSuccessWins`,
  `TestTCP_SuccessSamplesAreAvailAndLatencyOnly`,
  `TestTCP_FailureEmitsAvailZeroWithNoLatencySampleAndNoErrorReason`,
  `TestTCP_MessageStringsMatchBackendExactly`,
  `TestTCP_ConnectionRefusedIsTargetDownNotExecutionError` (§5),
  `TestTCP_EveryCandidateAddressIsScopeCheckedBeforeDialing`

**Implementation:** Unprivileged datagram ICMP via
`icmp.ListenPacket("udp4"|"udp6", ...)`. A listen failure (the kernel's
`net.ipv4.ping_group_range` not covering the agent's GID) is an **execution error** plus
`probe.icmp = unavailable` readiness — the agent ships with no `CAP_NET_RAW` and that must not
change. Both checkers take an injected dialer/pinger so no test touches the real network.

**Verify:**
```
(cd apps/agent && go test -race ./internal/collect/probe/...)
(cd apps/agent && go vet ./... && go build ./...)
```
Green = parity tests pass and the module still builds under the Go 1.22 CI pin.

**Depends on:** Task 16.

---

### Task 18: Go HTTP(S) checker (parity, redirect scope, bounded body, redaction)

**Scope:** Mirror `collectors/web.py::collect_http` (`_request`, `_status_accepted`, `_json_path`,
`_tls_details`) and add the three things §5 requires that the backend does not do: per-hop redirect
validation, a 1 MiB inspection bound, and secret redaction.

**Files touched:**
- **new** `apps/agent/internal/collect/probe/{http.go,http_test.go}`

**Tests first:**
- Parity: `TestHTTPChecker_SampleOrderIsAvailLatencyStatusThenCertDays`,
  `TestHTTPChecker_AcceptedStatusRangesAndBareCodes` (including the empty-list fallback to
  `["200-299"]`),
  `TestHTTPChecker_KeywordAndInvertedKeyword`,
  `TestHTTPChecker_DottedJSONPathWithIndexSegmentsComparedAsStrings`,
  `TestHTTPChecker_MessageStringsMatchBackendExactly` (all four forms),
  `TestHTTPChecker_TLSDetailsComeFromASeparateConnectionAndNeverFailTheCheck`,
  `TestHTTPChecker_TransportErrorEmitsAvailZeroWithHTTPErrorReasonAndNoLatencySample`
- Security: `TestHTTPChecker_RejectsNonHTTPSchemeBeforeResolving`,
  `TestHTTPChecker_RedirectToOutOfScopeHostIsRejected`,
  `TestHTTPChecker_RedirectToPublicIPIsRejected`,
  `TestHTTPChecker_EveryResolvedAddressIsCheckedNotJustTheFirst`,
  `TestHTTPChecker_ResponseBodyIsBoundedAtOneMiB`,
  `TestHTTPChecker_ResultCarriesNoRequestHeadersOrBody`,
  `TestHTTPChecker_BasicAndBearerCredentialsNeverAppearInResultOrLogs` (D-10)

**Implementation:** Custom `http.Transport` with a `DialContext` that scope-checks the **resolved**
address on every hop — the same override pattern `apps/agent/internal/collect/host/docker.go`
already uses for its unix socket. `CheckRedirect` re-validates each hop against `internal/netscope`.
Body reading is `io.LimitReader` at 1 MiB. **Do not** reuse `internal/tlsdial.NewTransport` — that
implements SPKI pinning for the Circuit Breaker server only; monitored targets have unrelated certs
and their own `verify_tls` setting.

**Verify:**
```
(cd apps/agent && go test -race ./internal/collect/probe/...)
```
Green = every parity and security assertion passes against `httptest` servers; no test reaches the
real network.

**Depends on:** Task 17.

---

### Task 19: Go DNS checker (parity)

**Scope:** Mirror `collectors/dns_check.py::collect_dns` for all ten record types §5 lists.

**Files touched:**
- **new** `apps/agent/internal/collect/probe/{dns.go,dns_test.go}`
- `apps/agent/go.mod` / `go.sum` — `github.com/miekg/dns v1.1.63` (D-11)

**Tests first:**
- `TestDNS_AllTenRecordTypesResolve` (A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, CAA — the stdlib
  `net.Resolver` cannot do SOA or CAA at all, which is why the dependency exists)
- `TestDNS_ExpectedValueMatchingIsSubstringAnyOfAny` — the exact
  `any(any(e in r for r in records) for e in expected)` semantics
- `TestDNS_MismatchRewritesAvailToZeroAndKeepsDetails`
- `TestDNS_MessageStringsMatchBackendExactly` (success, mismatch and lookup-failure forms)
- `TestDNS_DetailsCarryStringifiedRecords`
- `TestDNS_CustomResolverDestinationIsScopeChecked` — §3: "DNS resolver destinations are validated
  like other network targets"
- `TestDNS_DefaultsAreRecordTypeAPortFiftyThreeTimeoutFive`
- `TestDNS_LookupFailureEmitsDNSErrorReason`

**Verify:**
```
(cd apps/agent && go test -race ./internal/collect/probe/...)
(cd apps/agent && make build-all && make manifest)
```
Green = parity tests pass and both architectures still cross-compile with the new dependencies.

**Depends on:** Task 17.

---

### Task 20: Probe readiness and daemon wiring

**Scope:** §5's readiness block plus the runtime's lifecycle in `cmd/cb-agent/main.go`.

**Files touched:**
- `apps/agent/internal/collect/probe/` — exported `ProbeNames = []string{"probe.icmp", "probe.tcp",
  "probe.http", "probe.dns"}`, mirroring `apps/agent/internal/collect/host/host.go`'s
  `CollectorNames`, plus a readiness evaluator
- `apps/agent/cmd/cb-agent/main.go` — new `daemonRuntime` fields, an `applyProbeConfig()` closure
  modeled on `applyHostConfig`, called from `onCapabilitiesSet`, and the two probe callbacks passed
  into `link.Options` in `runDaemon`; update `startDaemonState`'s ordering doc comment
- `apps/agent/cmd/cb-agent/main_test.go`

**Tests first:**
- `TestProbeReadiness_TCPAndHTTPAreReadyByDefault`
- `TestProbeReadiness_ICMPIsUnavailableWhenPingGroupRangeIsUnusable` (§5)
- `TestProbeReadiness_DNSIsDegradedWhenNoUsableResolverIsConfigured` (§5)
- `TestApplyProbeConfig_DisablePublishesDisabledForEveryProbeName` — readiness rows are **never
  deleted** server-side (`ingest_readiness` only upserts), so a missing disable path leaves the UI
  permanently showing "ready"
- `TestApplyProbeConfig_DisableCancelsInFlightRuns`
- `TestApplyProbeConfig_ConcurrencyChangeTakesEffectWithoutRestart`
- `TestStartDaemonState_ProbeRuntimeIsWiredAfterTheGate` (runs under `-race`)

**Implementation:** Reconfigure from the `onCapabilitiesSet` closure directly, **not** by subscribing
to `capability.Gate.Changes()` — that channel exists but nothing consumes it, it delivers at most one
coalesced signal, and it would race the direct call `applyHostConfig` already makes.

**Verify:**
```
(cd apps/agent && make test)
(cd apps/agent && go vet ./...)
```
Green = `go test -race ./...` across the whole module. Re-run once if
`TestStartDaemonState_CachedGrantFaultIsReportedAtStartup` trips its known `TempDir` cleanup flake.

**Depends on:** Tasks 16, 17, 18, 19.

---

### Task 21: Frontend — vantage selection, execution condition, and Agent Detail probes

**Scope:** All of §7's UI in one task. It was originally split three ways; the split bought nothing
because the three halves share `MonitorsPage.jsx`'s live fold and the same API client module, and
splitting them meant landing a "Run from" selector that nothing yet renders.

The load-bearing rule for the whole task: **the UP/DOWN pill shows target state only.** Execution
condition is always a secondary indicator. D-13 is why — the live push for an execution change
carries no `status` key, and the fold must not invent one.

**Files touched:**
- `apps/frontend/src/api/monitor.js` — `getMonitorProbeRuns`
- `apps/frontend/src/api/agents.js` — `getAgentProbes` + the eligible-agent listing call
- `apps/frontend/src/components/monitors/MonitorForm.jsx` — `probe_agent_id: null` in `DEFAULTS`
  plus a "Run from" `<select id="mf-probe-agent">` following the existing `mf-type` field shape
- **new** `apps/frontend/src/components/monitors/RunFromSelect.jsx`
- `apps/frontend/src/components/monitors/MonitorCard.jsx` — "via Server" / "via <agent>" in the
  `mon-target` span. **Do not touch the exported `groupStatusOf` or `headlineOf`** —
  `MonitorsPage.jsx` imports `groupStatusOf` for the summary counts, the group buckets and the
  status filter, so folding execution state into it would silently rewrite the dashboard
- `apps/frontend/src/components/monitors/MonitorCardDetail.jsx` — a fifth `mon-stats` tile for last
  result; an agent link in `mon-actions`
- `apps/frontend/src/pages/MonitorDetailPage.jsx` — "Run from" and "Execution status" rows in the
  `<dl>`; a **separate** probe-runs table cloning the events `<table className="data-table">`, per
  §7's "separately from target state transitions"
- `apps/frontend/src/pages/MonitorsPage.jsx` — the live fold merges execution fields without
  overwriting `status` (D-13)
- **new** `apps/frontend/src/components/agents/AssignedProbesSection.jsx` and
  **new** `apps/frontend/src/components/agents/RemoteProbeConfigEditor.jsx` — extracted, because
  `AgentDetailPage.jsx` is already ~647 lines against a 150-line cap
- `apps/frontend/src/pages/AgentDetailPage.jsx` — mount both as
  `<section aria-label="Assigned probes">` (tests select by aria-label) and hook the
  disable-confirmation into `handleToggleCapability` using the already-imported `ConfirmDialog`
- `apps/frontend/src/styles/monitors.css`

**Tests first.**

New `apps/frontend/src/__tests__/monitor-run-from.test.jsx`:
- `renders Circuit Breaker server as the default option`
- `lists only eligible agents with online, readiness and scope indicators`
- `warns when the selected agent is offline`
- `warns when the agent network vantage has changed`
- `surfaces a server-side scope rejection through the existing role=alert element`
- `the Run from select stays enabled when editing an existing monitor` — the check-type select is
  `disabled={!!initial}`; copying that here would make reassignment impossible from the edit form,
  contradicting §7/§8's explicit reassign action
- `strips read-only probe_* fields before submitting` — `MonitorsPage.jsx` sends the form verbatim
  and seeds edit state with `{...DEFAULTS, ...initial}`

Extend `apps/frontend/src/__tests__/monitor-card.test.jsx`:
- `shows via Server for an unassigned monitor`
- `shows via <agent name> for an assigned monitor`
- `renders probe unavailable as a secondary condition without changing the status pill`
- `groupStatusOf is unchanged by probe_execution_status`

Extend `apps/frontend/src/__tests__/monitor-detail-page.test.jsx`:
- `renders probe runs in a table separate from target events`
- `execution errors do not appear in the target event list`

New `apps/frontend/src/__tests__/monitor-live-execution.test.jsx`:
- `a push carrying only probe_execution_status leaves the status pill untouched`
- `a push carrying status still updates the pill`

New `apps/frontend/src/__tests__/agent-assigned-probes.test.jsx`:
- `lists assigned monitors with type, target, interval, target state and execution condition`
- `shows concurrency used against the configured limit`
- `offers open, check now, reassign and return-to-server actions`
- `disabling remote probing with assignments asks for confirmation and explains state retention`
- `disabling with no assignments does not prompt`
- `remote probe config editor rejects max_concurrent outside 1-100 before calling the API`
- `an invalid config rolls back to the previous value` — the optimistic-update-with-rollback pattern
  `handleToggleCapability` already uses

**Note:** `probe.icmp|tcp|http|dns` readiness rows render in the existing readiness block with **no**
change — the block already filters `degraded`/`unavailable` and its comment says Slice 3/4 collectors
land there unchanged.

**Verify:**
```
(cd apps/frontend && npx vitest run)
(cd apps/frontend && npm run lint)
```
Green = the whole frontend suite passes, 0 lint errors. Two traps: any newly mocked API function
must be added to the `vi.hoisted` `apiDefaults` object **and re-applied in `beforeEach`**, because
`vi.clearAllMocks` does not restore implementations; and dynamic object indexing needs the file-top
`/* eslint-disable security/detect-object-injection -- <reason> */` used elsewhere.

**Depends on:** Task 15.

---


### Task 22: Docker E2E — remote probe acceptance

**Scope:** §9's end-to-end list, against a target the backend genuinely cannot reach.

**Files touched:**
- `apps/agent/e2e/docker-compose.yml` — a **new** isolated network (the backend must **not** be
  attached) plus a small target service on it. Today `circuitbreaker` is on **both** `default` and
  `agent-net`, so anything cb-agent can reach the backend can reach too — §9 step 1 is not
  expressible without this change
- `apps/agent/e2e/test_agent_e2e.py` — a new `@pytest.mark.e2e` test
- `apps/agent/e2e/supervisord-e2e.conf` — already updated in Task 10

**Test:** `test_remote_probe_assignment_execution_and_unavailability`, covering §9 steps 1-6 and 9-11
in one stack lifetime (the suite is already ~25-45 min; do not add seven more stacks):
1. Bring up the stack, enroll and approve via `_enroll_agent`.
2. Assert the agent's reported networks made it eligible **without any scope edit** (step 11).
3. Create ICMP, TCP, HTTP and DNS monitors against the isolated target, assigned to the agent.
4. Assert `monitor_events` / `telemetry_timeseries` / alert behavior matches server-executed checks
   (steps 3-4).
5. `_cut_agent_network()` → assert the target state is **retained** and `probe_execution_status`
   becomes `unavailable`; assert **no** `avail=0` sample was written (step 5). Budget the full ~60 s
   read-deadline detection — this helper produces a black hole, not a closed socket.
6. Restore → assert an immediate check clears the warning (step 6).
7. Reassign and assert the old agent's late result is rejected (step 9).
8. Return the monitor to server execution explicitly and assert it runs from the server (step 10).

**Verify:**
```
(cd apps/agent/e2e && pytest test_agent_e2e.py -m e2e -k remote_probe -v)
(cd apps/agent/e2e && pytest test_agent_e2e.py -v -m e2e)
```
Green = the new test passes and the other six are unaffected.
`test_agent_update_success_and_forced_rollback` is **expected red** (F-8).

**Depends on:** Tasks 1-21.

---

### Task 23: Release gate verification

**Scope:** Verification only. Run every command in the Release Gate below.

**Required changes:** none expected. If a gate line fails, **do not fix it inline** — report the
specific failure; it routes back to the task whose area regressed, as a small dedicated follow-up.
Check every failure against **Known-red baseline** first.

**Depends on:** Tasks 1-22.

---

## Release Gate

Run each line from the repo root; every `cd` is wrapped in a subshell.

```
# Go agent — -race is mandatory
(cd apps/agent && make test)                       # go test -race ./...
(cd apps/agent && go vet ./...)
(cd apps/agent && make build-all && make manifest) # amd64 + arm64 match the manifest

# Backend — same scope CI lints
(cd apps/backend && ../../.venv/bin/ruff check src/app)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/mypy src/app)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest --no-cov)   # see Known-red baseline

# Cross-language conformance — the gate that forces probe.* fixtures
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/test_agent_frame_conformance.py --no-cov -q)
(cd apps/agent && go test ./internal/frame/... -run TestCorpus)
(cd apps/backend && PYTHONPATH=src ../../.venv/bin/pytest tests/unit/test_agent_scope_corpus.py --no-cov -q)
(cd apps/agent && go test ./internal/netscope/... -run TestScopeCorpus)

# Migrations — both dialect configurations
(cd apps/backend && CB_DB_URL="$TIMESCALE_URL" ../../.venv/bin/alembic upgrade head \
   && CB_DB_URL="$TIMESCALE_URL" ../../.venv/bin/alembic downgrade -1 \
   && CB_DB_URL="$TIMESCALE_URL" ../../.venv/bin/alembic upgrade head)
(cd apps/backend && CB_DB_URL="$PLAIN_PG_URL" ../../.venv/bin/alembic upgrade head)

# Frontend
(cd apps/frontend && npm run lint && npx vitest run)

# Docker E2E (linux/amd64)
(cd apps/agent/e2e && pytest -m e2e)
```

### Behaviors demonstrated before Slice 3 is called done

1. An agent approved with **only** the Slice 1 install command is immediately selectable as a
   vantage for a monitor targeting a directly connected subnet, with no scope editing. (§9.11)
2. ICMP, TCP, HTTP and DNS monitors assigned to that agent enter the existing monitor history, state
   machine, retry and alert pipeline with byte-identical semantics to server-executed checks. (§6, §9.3-4)
3. Disconnecting the agent retains the target's last UP/DOWN state, surfaces a separate
   probe-unavailable condition, writes **no** `avail` sample and does not increment
   `consecutive_failures`. Reconnecting clears it. (§2, §9.5-6)
4. A target outside the agent's effective scope is refused at assignment **and** refused again by the
   agent at execution, with a capability-violation event. (§3, §9.7)
5. Per-agent fairness holds: one vantage with hundreds of due monitors does not starve another. (§2, §9.8)
6. Reassigning a monitor cancels the old agent's run and rejects its late result; returning to server
   execution happens only through an explicit user action. (§8, §9.9-10)
7. `fixtures/agent_frame_corpus.json` covers `probe.assign`, `probe.cancel` and `probe.result`, both
   `pendingCorpusTypes` lists have shrunk by two, and neither language suite can be made green by
   half the change.

---

## Deviations

Recorded where this plan does not follow the design document literally.

1. **§2's fair-sharing wording is not implementable as written.** "Rank due monitors within each
   `probe_agent_id` … claim no more than 50 per vantage … preserve the global batch limit of 200"
   requires a window function at the same query level as `FOR UPDATE SKIP LOCKED`, which PostgreSQL
   rejects. D-2 implements the intent with an oversampled lock CTE. The 50-per-vantage and
   200-global numbers are preserved exactly; only the oversample factor is added.
2. **§6's "preserve maintenance behavior" refers to nothing that exists.** `MAINTENANCE` is declared
   in `services/monitoring/state.py` and appears in model comments, but `decide()` has no
   maintenance branch and nothing anywhere sets that status. This plan does **not** build maintenance
   windows; it only guarantees the constant and its export are not regressed.
3. **`details` and `error_reason` are persisted for remote runs only** (D-8). §6 asks for identical
   semantics; both fields are discarded on the server path today and adding a column to a compressed
   Timescale hypertable is unbudgeted. The asymmetry is documented in the shared service's docstring.
4. **§3's shared scope evaluator is built here, not consumed.** The Assumptions section says Slice 3
   "consumes the same … normalized network facts and scope version established by Slices 1, 2, and 4"
   — circular, since Slice 4 is unwritten and Slices 1-2 produce nothing of the kind. Tasks 1-4
   build it to Slice 4's stated shape so Slice 4 imports rather than rewrites.
5. **§7's "editor-level monitor permission" is satisfied by the existing dependency** (D-15).
   `require_write_auth` already requires `{admin, editor}` or a `write:*` scope. Monitor **read**
   routes remain unauthenticated, as they are today; tightening them is a separate change.
6. **Task 1's `networks` report is not an exhaustive interface inventory.** D-1 says "one entry per
   non-loopback, up interface"; `hostinfo.netFactsCollector.collect` additionally drops an up,
   non-loopback interface whose addresses all filter out, so a flags-only interface never appears.
   Such an entry names no directly connected network and so cannot change §3's derived scope, but
   it would give Task 2's generation comparison something to churn on. **Slice 4 must not read the
   report as a complete list of up interfaces** — if it needs interface-type facts for
   address-less interfaces, that is a new field, not an assumption about this one. The Go field is
   also tagged `json:"networks,omitempty"`, so a host with nothing directly connected omits the key
   rather than sending `[]`: Task 2's backend rule accepts an explicit empty report and clears the
   stored one, but no shipping agent build produces that frame today.
7. **`agent_networks.observed_at` is not a freshness timestamp.** Slice 4's storage note asks for
   "the latest normalized report with a generation and timestamp"; Task 2 moves `observed_at` only
   when `generation` moves, so it answers "since when have these been the agent's networks", not
   "when did the agent last say so". Liveness is `agents.last_seen_at`, and refreshing the row on
   every reconnect would be a write carrying no new information — the same reasoning
   `record_spool_stats` already documents for `spool_reported_at`.
8. **Task 3's `test_normalize_remote_probe_config_rejects_default_routes` drives the CIDR
   validator, not a config normalizer.** The named test appears in both Task 3 and Task 5; the
   `remote_probe` normalizer itself belongs to Task 5 by the "one capability registry" constraint
   (bounds live in `CAPABILITY_DEFINITIONS`), and Task 5 says CIDR validation delegates to Task 3's
   module. `core/agent_scope.normalize_scope_cidr`/`normalize_scope_cidrs` are that delegate and are
   what the Task 3 copy of the test pins.
9. **The scope corpus's `destination` is an object, not a bare string.** The declared entry shape
   names `"destination"` without a type. Hostname cases need the resolved answer set, and the
   evaluator deliberately resolves nothing itself (the same address list is checked at dispatch and
   re-checked at the agent), so entries carry `{"host", "resolved"?}`. Task 4's Go mirror reads the
   same shape.
10. **`EffectiveScope` also carries `additional_hostnames` and the directly-connected subset.**
   Task 3's named tests cover neither, but the `remote_probe` config carries `additional_hostnames`
   and §3 gives the agent an extra directly-connected requirement "unless covered by an explicit
   centrally approved override" — Tasks 4 and 16 need both, and the "one scope evaluator" constraint
   forbids them from inventing wildcard-matching or a second notion of "directly connected". Hostname
   approval never bypasses the per-address check; that is pinned by a test here.

## Open decisions requiring confirmation

**All four were confirmed by the product owner on 2026-08-07, as written.** No task may reopen them.

- **D-9 (tenant boundary): CONFIRMED — allow tenant-less monitors.** Reject only when both sides
  carry a tenant and they differ. A standalone monitor may be assigned to a tenant-scoped agent;
  the target is still bounded by the agent's derived scope.
- **D-10 (credential distribution): CONFIRMED — ship them, in memory only.** HTTP `password`/`token`
  ride `probe.assign`. The three enforcing properties (never in `status.json`, never in
  `grants.json`, never logged, never echoed in `probe.result`) are hard requirements pinned by
  Tasks 16 and 18, not best-effort.
- **D-11 (Go dependencies): CONFIRMED — add both, pinned under the Go 1.22 CI ceiling.**
  `golang.org/x/net v0.33.0` and `github.com/miekg/dns v1.1.63`. Do **not** bump `setup-go`.
- **D-12 (uptime coverage): CONFIRMED — expose observed coverage.** The uptime response gains
  observed/window minutes and the UI renders the shortfall. The no-`avail`-sample rule stands.

---

## Deferred / follow-ups

Intentionally out of scope for Slice 3.

- **Maintenance windows.** No implementation exists; §6's "preserve maintenance behavior" is a
  no-op here (Deviation 2).
- **`details`/`error_reason` for server-executed checks.** D-8. Revisit only with a storage plan for
  `telemetry_timeseries` or an equivalent runs table for local checks.
- **Monitor read-route authentication.** `api/monitor.py`'s GET routes have no auth dependency; this
  predates Slice 3 and tightening it would break the frontend and existing tests (D-15).
- **`ruff check .` repo-wide and `ruff format --check src/app`.** Both red at baseline on unrelated
  files. A separate cleanup commit, never inside a Slice 3 task.
- **F-8** (`test_agent_update_success_and_forced_rollback`) and the
  `TestStartDaemonState_CachedGrantFaultIsReportedAtStartup` `TempDir` flake. Both pre-existing.
- **Bumping CI to Go 1.23+.** Would remove the dependency pins in D-11, but is an unrelated change
  riding on Slice 3.
- **§7's "Create monitor from this agent" action for Slice 4 discoveries.** The design places it in
  Slice 3's UI section, but it depends on Slice 4's device findings, which do not exist. Deferred to
  Slice 4.
- **Query-plan verification at fleet scale** (§9 backend test list). The
  `(probe_agent_id, enabled, next_due_at)` index is created and unit-tested in Task 6; an `EXPLAIN`
  assertion at fleet cardinality needs a seeded performance fixture and belongs with the broader
  scheduler performance work.
- **A second reconciliation worker process.** D-5 folds expiry into `monitor_scheduler`'s tick. If
  fleet growth makes that tick expensive, split it out then — not preemptively.
