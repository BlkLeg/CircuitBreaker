# cbi-agent Slice 4 — Local Discovery: Executable Task Breakdown

**Date:** 2026-08-08

**Derived from:**
- `plans/2026-08-04-cbi-agent-slice4-local-discovery.md` — **authoritative** for product and
  architecture requirements. No task body may contradict it; every deviation is listed under
  **Decisions** below with its justification.
- `plans/2026-08-04-cbi-agent-slice3-remote-probe-tasks.md` (format model, and the source of every
  reusable dispatch/lease/ingest pattern this slice mirrors)
- `plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md` (release gate, `pendingCorpusTypes`
  contract this slice is required to discharge for `discovery.request` / `discovery.finding`)
- `specs/2026-07-26-cb-agent-design.md`

**Codebase layout:**
- Go agent: `apps/agent/` (`cmd/cb-agent/main.go`,
  `internal/{frame,link,capability,spool,netscope,hostinfo,status,tlsdial,update}`,
  `internal/collect/{collect.go,payload.go,host/,probe/}`)
- Backend: `apps/backend/src/app/`
  (`services/{discovery_service,discovery_profiles_service,discovery_scheduler,discovery_import_service,discovery_merge}.py`,
  `services/{agent_link,agent_registry,agent_capabilities,agent_probe,agent_telemetry}.py`,
  `services/monitoring/{probe_eligibility,probe_reconcile}.py`,
  `workers/monitor_probe_dispatch.py`,
  `api/{discovery,agents,ws_discovery,ws_agents}.py`,
  `schemas/{discovery,agents,agent_frame}.py`,
  `core/{agent_scope,network_acl,scheduler,job_lock}.py`, `db/models.py`)
- Frontend: `apps/frontend/src/`
  (`pages/{AgentDetailPage,AgentsPage,DiscoveryPage,DiscoveryHistoryPage}.jsx`,
  `components/agents/*`, `components/discovery/{ScanProfileForm,ScanDetailPanel,NewScanPage}.jsx`,
  `components/monitors/RunFromSelect.jsx`, `hooks/useDiscoveryStream.js`,
  `api/{agents.js,discovery.js}`)
- Cross-language wire corpus: `fixtures/agent_frame_corpus.json`,
  `fixtures/agent_scope_corpus.json`
- Migrations: `apps/backend/migrations/versions/` — head is **`0099_monitor_probe_runs`**
- Docker E2E: `apps/agent/e2e/`

---

## Summary

Slice 4 adds agent-executed local-network discovery while the backend stays authoritative for
scope, scheduling, job state, result matching, review, and import. An agent is an additional
**execution location** for the existing discovery pipeline — not a second discovery system.

Slice 3 left this slice in unusually good shape. `core/agent_scope.py` + `internal/netscope` +
`fixtures/agent_scope_corpus.json` are the one scope evaluator, `agent_networks` already persists
directly-connected facts with a generation, `agent_link.CAPABILITY_FOR_TYPE` already maps
`discovery.finding` → `local_discovery`, and `frame.go` already declares
`TypeDiscoveryRequest`/`TypeDiscoveryFinding` with the correct control/data classification.
`MonitorProbeRun` + `monitor_probe_dispatch` + `probe_reconcile` + `probe_eligibility` are a
complete, working dispatch-lease-reconcile lifecycle to mirror.

What does **not** exist, and is therefore this slice's work rather than an assumption:

1. **No discovery table knows an agent exists.** `grep -rn 'scan_agent_id\|dispatch_id\|discovery_agent_id\|finding_id'` over the
   repo returns zero hits. `scan_results` carries **no unique constraint of any kind**
   (`db/models.py:1684-1736`), so there is no idempotent replay key at all.
2. **`local_discovery` config is hard-rejected.** `agent_capabilities.py:190-195` still carries
   `default_config=MappingProxyType({})` / `normalize=_reject_unknown_keys("local_discovery")`,
   whose own docstring says Slice 4 replaces it. Every key in the plan's grant is a 422 today.
3. **There is no scan-type vocabulary anywhere in the product's history.** `scan_types` is
   unvalidated `list[str]` on all three schemas (`schemas/discovery.py:25,46,214`) and execution
   does bare membership tests. Plan §3's `agent_connect` has nothing to hook into.
4. **There is no reconciliation loop for discovery *scan jobs*.** `services/discovery_reconciler.py`
   exists but heals discovery *readiness* (nmap capability) and touches no `ScanJob` row
   (`discovery_reconciler.py:1-15`). The only caller of
   `_schedule_queued_scan_jobs` is `_scan_finalize` (`discovery_service.py:812`), so a job that
   fails to claim a slot is abandoned until some other job finishes. Plan §3's dispatch deadline,
   expiry, and retry-on-reconnect have no owner.
5. **No `internal/collect/discover` package**, no netlink dependency, no reverse-DNS helper, and
   `probe.Runtime` emits exactly one result per unit of work (`runtime.go:582-604`) — the
   many-findings-plus-terminal-summary contract is a genuine structural divergence, not a copy.

**33 ordered, test-first tasks**, one focused commit each, each ending with the affected Go,
backend, or frontend suites green.

---

## Known-red baseline

Establish this **before** starting. None of it is Slice 4's fault and none of it may be "fixed"
inside a Slice 4 commit.

| Command | Status | Why |
|---|---|---|
| `cd apps/backend && PYTHONPATH=src pytest --maxfail=60 -q` | **exits 1** | 1581 passed / 21 skipped / **0 failed**. The failure is `--cov-fail-under=60` in `pyproject.toml:200-208`; total coverage is 52.08%. **Always run `--no-cov` for a real signal.** |
| Any *subset* pytest run | **fails the coverage gate** | `pytest tests/unit/x.py -q` reports 0.52% coverage and exits 1. `--no-cov` is mandatory for targeted runs; judge coverage only on a full run. |
| `-x` in addopts | stops at first failure | override with `--maxfail=N`. Per-test timeout is 30s. |
| `apps/agent/e2e` `test_agent_update_success_and_forced_rollback` | **red on `dev`** | Follow-up F-8: `docker network disconnect` races the re-exec'd container's sandbox creation. Undiagnosed. |
| `apps/agent/e2e` `test_agent_uninstall` | **xfail** | marked at `test_agent_e2e.py:775-792`. |
| `cd apps/backend && ruff check src/app` | PASS | repo-wide `ruff check .` still has pre-existing errors outside the CI scope. Do **not** run `make format`. |
| `mypy src/app`, `go vet ./...`, `go test -race ./...`, `npm run lint`, `npm test` | PASS | these are the CI gates. |
| CI backend pytest | **does not exist** | `grep -rn "pytest" .github/workflows/` → nothing. |
| CI docker e2e | **does not exist** | Slice 4's Python and E2E tests are **locally enforced only**. |

`cmd/cb-agent` `TestStartDaemonState_CachedGrantFaultIsReportedAtStartup` is flaky ~1 in 3 on a
`t.TempDir` cleanup error, not an assertion. Re-run before blaming a change.

---

## Decisions

Every open question from investigation is resolved here. **No task body may reopen one.**

### D-1. FK behavior splits: RESTRICT on the live assignment, CASCADE on finished history.

**Decision:**
- `discovery_profiles.scan_agent_id` → `ON DELETE RESTRICT`, named
  `fk_discovery_profiles_scan_agent_id_agents`.
- `scan_jobs.scan_agent_id` → `ON DELETE CASCADE`, named `fk_scan_jobs_scan_agent_id_agents`.
- `scan_results.discovery_agent_id` → `ON DELETE CASCADE`, named
  `fk_scan_results_discovery_agent_id_agents`.
- `DELETE /api/v1/agents/{id}` (`api/agents.py:892-917`, 409 branch at `:910-914`) gains a
  pre-check returning **409** with dependent profile names/counts before the DB can raise.

**Rationale:** Plan §2 asks for RESTRICT on "an agent selected by a profile **or retained job/result
history**". Taken literally that makes an agent row permanently undeletable, because
`discovery_scheduler._purge_old_scan_results_impl` is disabled outright when
`discovery_retention_days <= 0` (`discovery_scheduler.py:124-125`). Slice 3 resolved the identical
tension explicitly: `MonitorItem.probe_agent_id` is RESTRICT because it is a *live assignment*
(`models.py:262-272`) while `MonitorProbeRun.agent_id` is CASCADE because "anything reachable there
is finished history" (`models.py:341-346`). The plan's actual invariant — "**Revocation** does not
erase provenance" — is fully satisfied: revocation sets `agents.status='revoked'` and deletes no
row. Only an explicit, 409-guarded operator deletion cascades.

### D-2. The migration is `0100_discovery_agent_execution`, and `0001_init` must be taught about every new column.

**Decision:** `_EXCLUDED_COLUMNS["discovery_profiles"|"scan_jobs"|"scan_results"]`
(`0001_init.py:63`, entries at `:91,115,116`) gains every **column** this slice adds, and `0100`
creates them itself for fresh installs and upgrades alike. The new **indexes** need no entry: each
references an excluded column and is skipped automatically by the index-copy loop's own filter
(`0001_init.py:218-222`) — `_EXCLUDED_COLUMNS` is a `dict[str, set[str]]` of *column* names, so an
index name written there does nothing, or collides with a real column. A
`tests/test_discovery_agent_schema.py` modeled on `tests/test_monitor_probe_schema.py:53-105`
asserts bootstrap fidelity plus a real downgrade/upgrade round-trip that the FK survives with
`("scan_agent_id",), "agents", "RESTRICT"` and that the partial unique indexes keep their `WHERE`.

**Rationale:** Fresh installs do not replay revisions — `0001_init` rebuilds `Base.metadata` minus
its exclusion lists. `agents` is in `_EXCLUDED_TABLES` and `_should_copy_fk` drops any FK whose
*target* is excluded (`0001_init.py:149-155`), so a naively-added FK would ship on every new
deployment as a bare INTEGER with no constraint — the 409 in D-1 would be silently void. Worse, the
index-copy loop rebuilds indexes as `sa.Index(index.name, *(...), unique=index.unique)` and
**discards `postgresql_where`** (`0001_init.py:218-222`), which would turn
`(scan_job_id, finding_id) WHERE finding_id IS NOT NULL` into a **full** unique index and break
every result row after the first with a NULL `finding_id`. `0099_monitor_probe_runs.py:19-25`
documents exactly this failure.

### D-3. SQLite migration verification is struck from the plan.

**Decision:** Plan §9 step 8's "Run migration checks on SQLite" is not executed. Verification is
PostgreSQL fresh-bootstrap + upgrade + downgrade only.

**Rationale:** `db/session.py:23-28` raises unless `CB_DB_URL` starts with `postgresql`. There is no
SQLite runtime path to check.

### D-4. Job status gains no `partial`. An interrupted agent scan is `failed` with findings retained.

**Decision:** Terminal vocabulary stays `queued|running|completed|failed|cancelled`. A dispatch that
dies mid-scan finalizes as `failed` with `error_reason="agent_disconnected"`, accepted findings kept
and reviewable. New `error_reason` values, all machine-readable constants in
`services/agent_discovery.py`: `agent_unavailable`, `agent_disconnected`, `agent_execution_error`,
`agent_rejected`, `dispatch_failed`, `scope_changed`, `capability_disabled`, `profile_disabled`.

**Rationale:** This is plan §3's own stated v1 recommendation ("avoiding a broad status-model
change"). `status` is a bare string read by the frontend status filter
(`DiscoveryHistoryPage.jsx:594-599`), the history query, and the review badge; a sixth value is a
cross-cutting change with no product requirement behind it.

### D-5. `waiting_for_agent` keeps the job `queued` and does not consume a concurrency slot.

**Decision:** When an agent job is claimed but its agent is not connected, the claim is **released**:
`status='queued'`, `progress_phase='waiting_for_agent'`, `dispatch_status='queued'`,
`dispatch_deadline_at = now + CB_DISCOVERY_DISPATCH_DEADLINE_S` (default 900). A new
`services/agent_discovery_reconcile.py` (Task 23) drains it, expires it, and retries it on
reconnect. It registers with `IntervalTrigger` in `main.py`'s lifespan alongside
`discovery_reconciler` (`main.py:945-952`), under its **own** `run_with_advisory_lock` named
`agent_discovery_reconcile`.

**Rationale:** `discovery_scheduler._running_scan_count` counts `status == "running"`
(`:30-32`). A `waiting_for_agent` job in `running` would hold a scarce slot for the whole deadline
while doing no work. Leaving it `queued` is correct but needs an owner, because today the *only*
caller of `_schedule_queued_scan_jobs` is `_scan_finalize` (`discovery_service.py:812`) — a queued
job with no other job running is abandoned forever. It must **not** go inside
`core/scheduler.reload_discovery_jobs`, which is re-invoked on every profile write and first removes
every job it registered (`core/scheduler.py:66-68`). `monitoring/probe_reconcile.py` is the
precedent for *deriving the grace period from the ingest module's own constant* and nothing more:
it runs inside `monitor_scheduler.tick` and deliberately holds no lock of its own
(`probe_reconcile.py:12-16`).

**`services/discovery_reconciler.py` is untouched by this slice** and no finding path may import it
— it heals discovery *readiness* (nmap capability) and touches no `ScanJob` row
(`discovery_reconciler.py:1-15`), which is exactly what plan §5 means by "do not route agent
findings into the reconciler".

### D-6. `agent_connect` is introduced together with the product's first scan-type vocabulary, validated on write only.

**Decision:** New `core/discovery_scan_types.py` declaring
`SERVER_SCAN_TYPES = {"nmap","arp","snmp","http","docker","opnsense","deep_dive","proxmox","lldp"}`,
`AGENT_SCAN_TYPES = {"agent_connect"}`, `ALL_SCAN_TYPES`, and
`validate_scan_types(types, *, scan_agent_id) -> list[str]`. Wired into
`DiscoveryProfileCreate`/`DiscoveryProfileUpdate`/`AdHocScanRequest` and into
`discovery_service.create_scan_job`. **Validation runs on write only, never on read** — existing
rows may hold arbitrary strings and must keep loading.

**Rationale:** Plan §3 treats "expose a focused scan type such as `agent_connect`" as a one-liner,
but nothing validates scan types anywhere today (`schemas/discovery.py:25,46,214` are unvalidated
`list[str]`). Without a vocabulary there is no way to express "do not send server-only scan types to
an agent", which §3 also requires. Write-only validation is what makes the introduction
backward-compatible.

### D-7. System-managed profiles are keyed by `(scan_agent_id, normalized_cidr)` under a partial unique index, with a derived per-agent cron that an admin edit outlives.

**Decision:** `discovery_profiles` gains `scan_agent_id`, `normalized_cidr` (the
`ipaddress.ip_network(...)` canonical form), `managed_by` (`String(16)`, NULL for user profiles,
`'system'` for auto), and `paused_at`. Partial unique index
`uq_discovery_profiles_system_agent_cidr` on `(scan_agent_id, normalized_cidr)`
`WHERE managed_by = 'system'`. A brand-new system profile gets
`schedule_cron = f"{agent_id % 60} */6 * * *"`; the idempotent upsert **preserves** an
administrator-edited `schedule_cron` or `scan_types` on an existing one rather than re-deriving it.
A subnet that disappears sets `enabled = 0` (an `Integer` column, not a bool) and is never deleted.
`managed_by` is **server-set only** and is ignored if it appears in an API request body.

**Rationale:** `DiscoveryProfile` has no `__table_args__`, no unique constraint, no canonical CIDR
column, and no managed marker. A plain `UNIQUE(scan_agent_id, normalized_cidr)` would collide with a
user-created profile targeting the same CIDR, which plan §3 forbids. Cron is the only cadence field
(`models.py:1633`) and has no jitter primitive, so a derived per-agent minute offset is the
mechanism; APScheduler's `misfire_grace_time=300` is not jitter. Re-deriving on every bootstrap pass
would silently revert plan §6's "edit cadence and scan depth" the moment a readiness frame arrived.

### D-8. Candidate subnets keep riding `agent_networks`; `capability.readiness` gains an optional `networks` field to refresh them mid-session.

**Decision:** Do **not** add structured discovery data to `agent_capability_readiness` (it has no
column for it). Collector state travels as ordinary readiness rows named
`discovery.neighbor`, `discovery.icmp`, `discovery.tcp`, `discovery.dns`. Candidate CIDRs continue to
come from `agent_networks.facts` via `core/agent_scope.derive_scope`. `CapabilityReadinessPayload`
(backend) and `frame.CapabilityReadinessPayload` (Go) gain **one** optional field, `networks`,
identical in shape to `HelloPayload.networks`. `agent_telemetry.ingest_readiness`
(`agent_telemetry.py:237`) is what forwards it to the existing `agent_registry.record_network_facts`,
gated on presence in `model_fields_set`, with the write landing **before** its existing `db.commit()`
at `:256`; `agent_link._handle_readiness` (`:188-193`) stays a pass-through and gains no domain
logic.

The Go `CapabilityReadinessPayload.Networks` is tagged `json:"networks"` **without** `omitempty`.
That is load-bearing, for the reason `HeartbeatPayload` already documents at `frame.go:226-244`: an
agent that has lost every interface must be able to send `[]`, or a stale wider-than-reality scope
stands forever. (`HelloPayload.Networks` carries `omitempty` today — `frame.go:202` — which
`record_network_facts` already flags at `agent_registry.py:349-351`.)

Plan §6's "effective concurrency and address ceilings" are read from the **server-normalized grant**,
not agent-reported: Task 3 makes the Go normalizer clamp identically, so the server's copy is
authoritative and a second reported copy could only disagree.

**Rationale:** Plan §6 asks for candidate CIDRs in readiness and there is no field for any of it.
Slice 3 already built the persistence (`agent_networks`, generation, `record_network_facts`) and the
derivation (`derive_scope`) — a second copy in a readiness column would be the duplication the "one
scope evaluator" constraint forbids. But `HelloPayload.networks` is sent only at connect, so plan
§3's "when a subnet appears, create and scan its system profile" would otherwise wait for a
reconnect. One optional field on an existing periodic frame is the minimum change that closes it,
and `record_network_facts`'s change-gated write costs no extra row writes in steady state.

### D-9. Row-building and Hardware matching are extracted to `services/discovery_result_service.py`, taking `db` as a parameter.

**Decision:** Extract `discovery_service.py:509-642` into
`discovery_result_service.build_and_classify_result(db, job, raw, *, discovery_agent_id=None, finding_id=None) -> tuple[ScanResult, str]`
where the returned `str` is `"new" | "matched" | "conflict"`. The helper re-derives `snmp_data` and
`source` from `raw` and performs the docker-only `_match_ip_to_network` resolution (`:518-519`)
internally. `_scan_import` calls it in its loop; the agent finding handler calls it once per finding.

MAC and IP are normalized **on the agent path only**, before the call. The shared lookup at
`discovery_service.py:593-596` stays byte-identical, so the server path is untouched — an agent
finding's `matched` result depends on the caller normalizing, not on the matcher relaxing.

On the agent path the helper additionally filters both `Hardware` lookups by the job's tenant
(`Hardware.tenant_id == job.tenant_id`, with the both-sides-NULL case explicitly allowed), mirroring
`probe_eligibility.py:180-186`.

**Rationale:** Plan §5 requires this refactor but under-specifies it. The rest of `_scan_import`
(`:479-687`) is batch-shaped and actively wrong for a single incremental finding: it opens its own
`SessionLocal`, requires the `setup` dict from `_scan_setup`, de-dupes IPs across the whole batch
(`:495-505`), suppresses prober rows (`:521-555`), and **overwrites** `job.hosts_*` rather than
incrementing (`:670-675`). The 557-642 range alone is not extractable — `snmp_data`, `source`,
`network_id` and `vlan_id` are defined at `:512-519` and read inside it. And the matcher's `Hardware`
lookups carry no tenant predicate (`:593-596`, `Hardware.tenant_id` at `models.py:148`), so without
the tenant filter a tenant-A agent's finding could match and, via auto-merge, mutate a tenant-B row.

### D-10. Job counters are incremental on the agent path and absolute on the server path.

**Decision:** `_scan_finalize` keeps its current absolute-write semantics for server jobs. The agent
path increments `job.hosts_found/new/updated/conflict` and `job.finding_count` per accepted finding
inside the ingest transaction, and its terminal summary calls a new
`discovery_service.finalize_agent_job(db, job, status, *, error_reason=None)` that writes terminal
status/timestamps and emits the existing events **without** touching the counters.

**Rationale:** Sharing `_scan_finalize` unchanged would clobber accumulated agent counts with a
stats dict the agent path never assembles.

### D-11. The neighbor cache is read via `RTM_GETNEIGH` over `golang.org/x/sys/unix`. No new module.

**Decision:** `internal/collect/discover/neigh_linux.go` implements a netlink dump using
`x/sys/unix` for the constants and socket calls; **message framing and rtattr walking are
hand-written**, since `x/sys/unix` provides no `NetlinkRIB`/`ParseNetlinkMessage`/
`ParseNetlinkRouteAttr` (those exist only in stdlib `syscall`). `x/sys` is promoted from indirect to
direct in `go.mod` at its existing pinned `v0.28.0`. Parsing is table-tested against captured
`[]byte` fixtures; a `neigh_stub.go` with `//go:build !linux` returns "unsupported".

**Rationale:** Plan §1 requires "netlink, not shell parsing". `vishvananda/netlink` is a new module
whose recent releases declare Go ≥1.23 while CI pins 1.22 (`go.mod:9-12` and `:16-20` document this
exact hazard for two other dependencies). `/proc/net/arp` is IPv4-only. `x/sys` is already in the
module graph, so the socket plus message parsing is ~150 lines with zero dependency risk.

### D-12. The E2E gate asserts one system profile **per directly connected subnet**, not exactly one overall.

**Decision:** `apps/agent/e2e/docker-compose.yml` pins `agent-net` to `10.88.0.0/24`. The gate
asserts (a) exactly one enabled system-managed profile per directly-connected private subnet the
agent reports, (b) exactly one of them targets the `probe-net` fixture subnet `10.77.0.0/24`, and
(c) the fixture is discovered through it — with **no** CIDR entry or agent-side configuration.

**Rationale:** Plan §8 step 3 says "exactly one system-managed profile", which cannot hold: the agent
container is attached to two networks. Today `agent-net` is an unpinned bridge
(`docker-compose.yml:44-53`) so Docker allocates a **/16** — 65 534 addresses, which alone blows past
`max_addresses_per_job: 1024`. Pinning it to a /24 makes the topology honest and the assertion
meaningful. The zero-configuration property the step protects is preserved in full.

### D-13. `discovery.cancel` is a new server→agent control frame and lands with its corpus fixtures in one commit.

**Decision:** `TYPE_DISCOVERY_CANCEL = "discovery.cancel"` / `TypeDiscoveryCancel`. Task 5 lands, in
**one** commit: both constants, the Go `allFrameTypes` **and** `controlFrameTypes` entries, the
`internal/frame/frame_test.go:159-163` `controlTypes` literal (its `dataTypes` literal at `:179`
already covers `TypeDiscoveryFinding`), all three pydantic payload models, all three Go payload
structs, the `fixtures/agent_frame_corpus.json` fixtures, the `_PAYLOAD_MODEL_FOR_TYPE` entries, the
Go `TestCorpus_TypedPayloadsDecode` switch arms, a by-name field assertion modeled on
`test_probe_payloads_survive_the_typed_models_by_name`, and the deletion of `TYPE_DISCOVERY_REQUEST`
/ `TYPE_DISCOVERY_FINDING` from **both** pending lists.

**Rationale:** `test_corpus_covers_every_declared_frame_type` asserts a set **equality**
(`test_agent_frame_conformance.py:148`), so declaring a constant without a fixture fails the suite
immediately, and a stale pending entry fails just as loudly. Without the by-name assertion a model
that misspells `open_ports` or `evidence` silently drops the field and the round-trip still passes.
Without the `controlTypes` literal entry the new control frame's spool-ineligibility — plan §8's
"requests and cancellation do not spool" — is untested, and unlike the corpus gate that one fails
silently by omission.

### D-14. Disabling `local_discovery`, disabling a profile, or revoking the agent cancels in-flight dispatches explicitly.

**Decision:** `PUT /agents/{id}/capabilities` disabling `local_discovery`, agent revocation,
`discovery_profiles_service.update_profile` disabling a profile, and Task 24's
subnet-disappearance path all call
`agent_discovery.cancel_agent_dispatches(db, agent_id, reason=...)` — which closes open jobs in the
DB inside the transaction, builds inert cancellation value objects, and publishes `discovery.cancel`
only **after** commit, never raising on delivery failure.

**Rationale:** Mirrors `monitor_service.ProbeCancellation` / `publish_probe_cancels` and
`api/agents.py:830-848`. It is not optional: once the grant is off, `dispatch_frame`'s gate
(`agent_link.py:411-420`) drops the agent's own terminal summary as a `capability_violation`, so
without an explicit cancel the job never closes. Plan §4 names five triggers; profile-disable is the
one an implementation naturally forgets, and it is exactly the moment D-7's subnet-disappearance
path fires.

### D-15. The whole-CIDR scope helpers ship in Tasks 1–2 as ordinary entries in the existing flat corpus.

**Decision:** `core/agent_scope.py` gains `network_in_scope(scope, cidr) -> Decision`,
`address_count(cidrs) -> int`, and `MIN_SCOPE_PREFIX_V4 = 16` / `MIN_SCOPE_PREFIX_V6 = 48`.
`internal/netscope` gains `NetworkInScope`, `AddressCount`, and — with no backend counterpart —
`NetworkIsDirectlyConnected`, which answers §7's "still attached to it right now".

`fixtures/agent_scope_corpus.json` is a **flat array** whose entries name either `destination.host`
or `destination.cidr`. New prefix cases are appended as ordinary entries; **no `network_cases`
section is created**, because a top-level object would break both loaders
(`corpus_test.go:33-34` unmarshals into `[]corpusEntry`; `test_agent_scope_corpus.py:21-25`
parametrizes over a list).

**Rationale:** The evaluator answered only per-address allow/deny. Plan §3 requires "every target
CIDR contained in the versioned effective scope" and §7 requires the agent to re-check the same rule
before connecting. Two implementations of "is this prefix in scope" is exactly the divergence the
shared corpus exists to forbid. `NetworkIsDirectlyConnected` stays separate deliberately: folding
§7's agent-only rule into the shared one would make the two evaluators disagree by design and the
corpus meaningless.

### D-16. Scope is versioned on the dispatch, end to end.

**Decision:** `scan_jobs` gains `scope_version` (`String(64)`, nullable). `DiscoveryRequestPayload`
carries a required `scope_version` in both languages. At claim time the dispatcher writes
`derive_scope(...).version` to the job and sends the same value. The agent rejects a request whose
`scope_version` disagrees with its own freshly-derived `netscope.Derive(...).Version`. Ingest
validates a finding against the scope **snapshotted on the job**, not one the sender could move
between dispatch and ingest. When `record_network_facts` returns `True` (`agent_registry.py:331`),
or a grant's `scope_mode`/`excluded_cidrs`/`additional_cidrs` change, every live dispatch whose
`job.scope_version` no longer matches is cancelled with `reason="scope_changed"`.

**Rationale:** Plan §2 requires "active requests carry the version and are cancelled if it changes
incompatibly". `EffectiveScope.version` exists precisely for this — its own docstring says it "is
what lets a scheduler decide whether in-flight work is still authorized without diffing CIDR lists"
(`agent_scope.py:96-102`) — but Slice 3 only ever *surfaced* it (`api/agents.py:425`,
`schemas/monitor.py:334`) and never persisted it on a run (`MonitorProbeRun`, `models.py:314-360`,
has no version column). There is no precedent to inherit, so this slice builds it.

### D-17. `scan_results` gains a `tenant_id`.

**Decision:** `scan_results.tenant_id` (FK `tenants.id` `ON DELETE SET NULL`, indexed), added to
`0040_rls_policies._RLS_TABLES` and to `_EXCLUDED_COLUMNS`. Every agent-created job is created with
`tenant_id = agent.tenant_id`, and ingest asserts the written result's tenant equals the agent's and
is **non-NULL**.

**Rationale:** Plan §8 requires "tenant context is derived from the job/agent, never accepted from a
finding", and there is nothing to derive it onto: `ScanResult` has no tenant column
(`models.py:1684-1735`) and `scan_jobs` is in `_RLS_TABLES` while `scan_results` is not
(`0040_rls_policies.py:23-39`). Worse, `discovery_service.py:336-346` never sets `ScanJob.tenant_id`
at all, so every job is NULL today — a test asserting only that a payload-supplied tenant was
ignored would pass against a NULL and prove nothing.

---

## Task list

Each task is one commit. Each begins with a failing test and ends with the named suites green.
`--no-cov` on every targeted backend run.

### Phase A — Contracts and schema (Tasks 1–7)

**Task 1 — Add whole-CIDR scope helpers to the backend evaluator.** ✅ *landed*
Tests in `tests/unit/test_agent_scope.py` + `tests/unit/test_agent_scope_corpus.py`; implementation
in `core/agent_scope.py`; 16 `destination.cidr` entries appended to the flat corpus.
Green: `pytest tests/unit/test_agent_scope.py tests/unit/test_agent_scope_corpus.py --no-cov`.

**Task 2 — Mirror the helpers in Go against the same corpus.** ✅ *landed*
`corpus_test.go` branches on `destination.cidr`; `NetworkInScope`, `NetworkIsDirectlyConnected` and
`AddressCount` in `netscope.go`, with unit tests for the two the corpus cannot express.
Green: `cd apps/agent && go test -race ./internal/netscope/...`.

**Task 3 — Give `local_discovery` a real structured config on both sides.**
Tests first: `tests/services/test_agent_capabilities_local_discovery.py` (new file, mirroring
`test_agent_capabilities_remote_probe.py`): defaults exactly match plan §1; every bound rejected
with a specific message — `max_addresses_per_job` 1–4096, `max_concurrent_hosts` 1–256,
`host_timeout_ms` 100–10000, `job_timeout_seconds` 30–1800, `tcp_ports` 1–65535 with ≤32 entries,
`scope_mode` ∈ `SCOPE_MODES`, CIDR lists through `normalize_scope_cidrs`, booleans not accepted as
ints. Plus `auto_discovery_paused` (bool, default `false`) for M14's per-agent pause.
`tests/api/test_agents_api.py`: a structured config round-trips through
`PUT /agents/{id}/capabilities` and is echoed in `capabilities.set`.
`internal/capability/capability_test.go`: the Go normalizer clamps identically and an unknown key is
dropped, not passed through. Replace `agent_capabilities.py:190-195` with
`_LOCAL_DISCOVERY_DEFAULT_CONFIG` + `_normalize_local_discovery_config` delegating every CIDR to
`core.agent_scope`; register `local_discovery` in Go `configNormalizers`
(`internal/capability/capability.go:86-97`). **Same commit:** update
`apps/agent/e2e/test_agent_e2e.py:420`'s exact-dict assertion, or all eight e2e tests fail at
enroll.
Green: those three suites + `pytest tests/services/test_agent_registry.py --no-cov`.

**Task 4 — Migration `0100_discovery_agent_execution` and the ORM columns.**
Tests first: `tests/unit/test_migration_0100_discovery_agent_execution.py` (revision chain, single
head, `down_revision == "0099_monitor_probe_runs"`, AST guard) and
`tests/test_discovery_agent_schema.py` (bootstrap fidelity per D-2: a fresh `0001_init` install and
a real `0099 → 0100 → 0099 → 0100` round-trip both yield the same columns, the same named FKs with
the same `ondelete`, and partial unique indexes that still carry their `WHERE` clause).
Columns:
- `discovery_profiles`: `scan_agent_id` (FK RESTRICT, indexed), `normalized_cidr`, `managed_by`
  (`String(16)`), `paused_at` (`DateTime`, nullable).
- `scan_jobs`: `scan_agent_id` (FK CASCADE), `dispatch_id` (`String(32)`, unique),
  `dispatch_status`, `dispatch_deadline_at`, `last_finding_at`, `finding_count` (default 0),
  `scope_version` (`String(64)`, nullable — D-16).
- `scan_results`: `discovery_agent_id` (FK CASCADE, indexed), `finding_id` (`String(64)`),
  `tenant_id` (FK `tenants.id` SET NULL, indexed — D-17).
Indexes:
- `(scan_agent_id, status, created_at)` on `scan_jobs`; **also** the missing index on `profile_id`.
- Partial unique `uq_scan_results_job_finding` on `(scan_job_id, finding_id)`
  `WHERE finding_id IS NOT NULL`.
- Partial unique `uq_scan_jobs_active_dispatch` on `(scan_agent_id, id)`
  `WHERE dispatch_status IN ('queued','dispatched')` — the DB backstop behind Task 20's
  compare-and-set, mirroring `uq_monitor_probe_runs_active` (`models.py:374`).
- Partial unique `uq_discovery_profiles_system_agent_cidr` on `(scan_agent_id, normalized_cidr)`
  `WHERE managed_by = 'system'`.
Documented `source_type` vocabularies at `models.py:1668` and `:1726` both gain `agent`;
`scan_jobs.source_type` keeps its `manual` default and the agent path sets `agent` explicitly.
**Same commit:** every new **column** is added to `0001_init._EXCLUDED_COLUMNS` (`0001_init.py:63`)
and `scan_results` is added to `0040_rls_policies._RLS_TABLES`. Indexes need no entry (D-2).
Green: `pytest tests/unit/test_migration_0100_discovery_agent_execution.py tests/test_discovery_agent_schema.py --no-cov`
plus the CI single-head check.

**Task 5 — The three discovery frame contracts and their corpus fixtures.**
Everything in D-13, in one commit. Payload shapes are plan §4 verbatim, plus:
- `DiscoveryRequestPayload`: required `scope_version` (≤64 chars, D-16); `targets` ≤ 16;
  `tcp_ports` ≤ 32; `dispatch_id` exactly 32 lowercase hex.
- `DiscoveryFindingPayload`: `finding_id` ≤ 64 chars of `[0-9a-f]` (matching Task 4's `String(64)`
  column — an over-length value would become a psycopg `DataError` inside the `/link` read loop);
  `evidence` ≤ 16 entries of ≤ 32 chars; `hostname` ≤ 253; `open_ports` ≤ 64; `banner` ≤ 512 bytes
  after control/non-UTF8 stripping, matching Task 12's collector limit.
- The `kind="summary"` variant carries a closed `outcome` ∈
  `completed|execution_error|cancelled|rejected` (mirroring `ProbeResultPayload.outcome`,
  `schemas/agent_frame.py:271-297`), non-negative `hosts_found`/`addresses_scanned` counts,
  `msg` ≤ 2000 chars, `error_code` ≤ 64 chars.
Corpus: a fully-populated and a minimal variant, one fixture per `outcome` value, both `kind`
values, at least one explicit `false`, and a `banner`-bearing entry.
Green: `pytest tests/test_agent_frame_conformance.py --no-cov` and
`go test -race ./internal/frame/...`.

**Task 6 — Introduce the scan-type vocabulary and the `scan_agent_id` request field.**
Tests first in `tests/test_discovery.py`: a profile with `scan_types=["nmap"]` and a `scan_agent_id`
is 422; `["agent_connect"]` without a `scan_agent_id` is 422; `["bogus"]` is 422; an **existing** row
holding an unknown string still loads through `GET`.
Add `scan_agent_id: int | None = None` to `DiscoveryProfileCreate` (`schemas/discovery.py:21`),
`DiscoveryProfileUpdate` (`:42`) and `AdHocScanRequest` (`:210`) **in this commit** — the
validator's whole contract is conditioned on it, so it cannot be deferred. Add
`core/discovery_scan_types.py` and wire `validate_scan_types` into the three schemas and into
`create_scan_job`; the `_NMAP_OVERRIDE_PREFIX` label encoding (`discovery_service.py:330-334`) is
skipped on the agent path.
Green: `pytest tests/test_discovery.py --no-cov`.

**Task 7 — Extend the profile service with the execution-location columns.**
Test first: `create_profile`/`update_profile` persist `scan_agent_id`, a server-derived
`normalized_cidr`, and `managed_by`; a request body carrying `managed_by` is **ignored** (server-set
only); `reload_discovery_jobs` still fires so `DiscoveryStatusOut.next_scheduled` reports the
profile. `discovery_profiles_service.create_profile` (`:43`) builds `DiscoveryProfile(...)` from a
closed field list (`:56-72`) that Task 22's bootstrap cannot otherwise write through.
Green: `pytest tests/test_discovery.py tests/services/test_discovery_profiles_service.py --no-cov`.

### Phase B — The Go collector (Tasks 8–14)

**Task 8 — `internal/collect/discover`: request validation, no network I/O.**
Test first: a table over rejection causes — unknown method; target failing
`netscope.NetworkInScope`; target neither directly connected (`netscope.NetworkIsDirectlyConnected`)
**nor** covered by an `additional_cidrs` override; address count over `max_addresses_per_job`; a
port outside the grant; a `deadline_at` already past; a malformed `dispatch_id`; a `scope_version`
disagreeing with the agent's own freshly-derived `netscope.Derive(...).Version` (D-16). Each returns
a distinct machine-readable reason and performs **zero** network activity (assert via an injected
dialer that fails the test if called). **Positive case:** a routed CIDR present in
`additional_cidrs` but absent from `DirectNetworks` is **accepted** — plan §2 lets admins explicitly
add a routed subnet, and §3 scopes the direct-connect requirement to *automatic* targets only. Add
the matching entry to `fixtures/agent_scope_corpus.json` so both languages agree.
Green: `go test -race ./internal/collect/discover/...`.

**Task 9 — Neighbor cache over netlink (D-11).**
Test first: parse captured `RTM_GETNEIGH` response bytes into `{ip, mac, state}`, including a
truncated message, an unknown address family, an `NUD_FAILED` entry that must be dropped, and a
zero MAC. Implement `neigh_linux.go` + `neigh_stub.go`; promote `golang.org/x/sys` to a direct
require.
Green: `go test -race ./internal/collect/discover/...`, `go vet ./...`, and
`GOOS=darwin go build ./...` — otherwise the `//go:build !linux` stub is compiled by nothing
(`Makefile:6-11` is `GOOS=linux` only, CI is `ubuntu-22.04` only) and "builds everywhere" is
unverified.

**Task 10 — Bounded host liveness: ICMP datagram + TCP connect.**
Test first: `max_concurrent_hosts` is never exceeded (counting semaphore probe); `host_timeout_ms`
is honored; context cancellation returns within one timeout and leaks no goroutines
(`runtime.NumGoroutine()` before/after — there is no existing precedent in this repo; this
assertion is new); an unprivileged ICMP socket failure degrades to TCP-connect rather than failing
the job. Reuse the ICMP construction in `internal/collect/probe/icmp.go` — **and only that**;
`probe/http.go` is out of bounds for this package.
Green: `go test -race ./internal/collect/discover/...`.

**Task 11 — Reverse DNS and bounded banner capture.**
Test first: PTR lookup is bounded and a failure yields no hostname rather than an error; a banner
read stops at 512 bytes and 2 seconds; non-UTF8 and control bytes are stripped; nothing is captured
for a port whose grant does not list it. **Plan §7's redirect prohibition:** banner capture is a raw
`net.Conn` read only — assert against a test HTTP server returning a 302 that the collector issues
**no** second request and sends no `Authorization` or `Cookie` header, and add a package-level guard
test that `internal/collect/discover` imports neither `net/http` nor `internal/collect/probe`'s HTTP
checker (`probe/http.go:103,297-303` follows redirects by default and accepts credentials).
Green: `go test -race ./internal/collect/discover/...`.

**Task 12 — The discovery runtime: dispatch, incremental findings, terminal summary, cancellation.**
Test first: one `discovery.request` produces N `kind="host"` findings plus exactly one
`kind="summary"` terminal finding; `finding_id` is **replay-stable** (a digest of
`dispatch_id|kind|address`, not `collect.SampleID()` — that is what makes spool replay idempotent);
a second request for a live `dispatch_id` is refused; `discovery.cancel` stops work within one host
timeout and still emits a terminal summary with `outcome="cancelled"`; a rejected request emits
**only** a summary with the Task 8 reason. Structure follows `probe/runtime.go` (`Assign:279`,
`Cancel:331`, slot gate `:411-456`, pump `:461-474`), but the many-findings shape is new —
`probe.Runtime` emits exactly one result per unit of work (`runtime.go:582-604`).
Green: `go test -race ./internal/collect/discover/... ./internal/collect/...`.

**Task 13 — Discovery readiness, and `networks` on the readiness frame (D-8).**
Test first (Go): `DiscoverNames` reports `discovery.neighbor|icmp|tcp|dns` with
`ready|degraded|unavailable` and a remediation string when the ICMP socket is unavailable; the
readiness frame carries current `networks`, tagged **without** `omitempty`; a by-name assertion that
the `networks` payload marshals exactly `name`/`flags`/`addrs` and nothing else — plan §6 forbids
routing-table secrets, SSIDs, DNS search domains and interface counters, and without this the next
contributor extending the field has no guard. Test first (backend):
`agent_telemetry.ingest_readiness` forwards `networks` to `record_network_facts` before its
`db.commit()`, an absent key leaves the last report standing, and an explicit `[]` replaces it. Add
the optional field to both payload models and a corpus fixture exercising it.
Green: `go test -race ./internal/collect/discover/... ./internal/frame/...`,
`pytest tests/services/test_agent_telemetry_readiness.py tests/test_agent_frame_conformance.py --no-cov`.

**Task 14 — Wire the runtime into `main.go` and the link.**
Test first: `cmd/cb-agent` asserts the runtime starts only when `local_discovery` is granted, that
`capabilities.set` disabling it cancels in-flight work and stops future work, that a config change
re-applies bounds, and that `discovery.request`/`discovery.cancel` reach the runtime.
Follow `main.go:381-387` (link callbacks), `:689-696` (construct+Start), `:697-727`
(`applyProbeConfig`), `:729-747` (`onCapabilitiesSet`).
Green: `cd apps/agent && make test`.

### Phase C — Backend dispatch and ingest (Tasks 15–23)

**Task 15 — Extract `discovery_result_service.build_and_classify_result` (D-9).**
Test first: characterization tests pinning today's behavior for `_scan_import` — a new host, a MAC
match, a hostname conflict, the docker override fields, and **a docker-sourced row whose
`network_id` is resolved rather than supplied** — pass unchanged after extraction. New tests: a
lowercase agent MAC matches an uppercase stored MAC *on the agent path*; the same MAC against an
**other-tenant** stored row classifies `new`, not `matched`; `finding_id` / `discovery_agent_id` /
`tenant_id` are persisted when supplied; an agent-provenance `ScanResult` accepted through the
review queue imports idempotently via `discovery_import_service` — one Hardware row, replay-safe.
No behavior change on the server path.
Green: `pytest tests/services/test_discovery_service.py tests/services/test_discovery_result_service.py --no-cov`.

**Task 16 — `services/agent_discovery.py`: finding ingest.**
Test first, mirroring `tests/services/test_agent_probe_ingest.py`: a named `MAX_FINDING_BYTES`
(16 KiB) enforced on the raw mapping **before** `model_validate`, exactly as
`agent_probe.validate_probe_payload` does at `:194` (nothing upstream bounds an inbound frame —
`api/ws_agents.py:732` is a bare `receive_bytes()`); the `(dispatch_id, job, agent)` triple must
agree or it is a `capability_violation`; a finding whose address is outside the job target or
outside the scope **snapshotted on the job** (`job.scope_version`, D-16) is rejected and audited; a
finding after cancellation or a terminal summary is rejected; a duplicate `(scan_job_id,
finding_id)` inserts exactly one `ScanResult` and emits no second `result_added`; the written
`ScanResult.tenant_id` equals `agent.tenant_id` and is **non-NULL**, and a payload-supplied
`tenant_id` is discarded; counters increment (D-10); MAC/IP are normalized before matching;
`banner` is passed through as untrusted text and lands in `ScanResult.banner` (`models.py:1711`,
`Text` and unbounded at the DB layer — the pydantic cap is the only bound).
**A `MAX_FINDINGS_PER_DISPATCH` ceiling**, derived from the job's `max_addresses_per_job` grant plus
a small summary allowance, enforced with a compare-and-set on `scan_jobs.finding_count`: the N+1th
finding is rejected, inserts no `ScanResult`, emits no `result_added`, closes the job with
`error_reason="agent_execution_error"` and records a `capability_violation`. Without it a
2048-address /21 target admits unbounded distinct agent-chosen `finding_id`s, each fanning out
through `_emit_ws_event` (`discovery_service.py:128-143`) to every connected client.
**Log hygiene:** every rejection reason and every `agent_events.detail` value derived from a finding
passes through `core.log_sanitize.safe_log_fragment` (`:17`); `banner`, `hostname` and `evidence`
never appear in a reason string or an event detail — address and machine-readable code only. Test
that a hostname containing `\r\n` produces a single-line log record.
Green: `pytest tests/services/test_agent_discovery_ingest.py --no-cov`.

**Task 17 — Register the handler, and give `capability.violation` a home.**
Test first: a granted agent's `discovery.finding` reaches the ingest service; an ungranted one is a
`capability_violation` and is dropped; a malformed one is a `protocol_violation`; both are rate
limited through `agent_telemetry.recordable_violation`. Add exactly one `_HANDLERS` line
(`agent_link.py:300-309`) — `CAPABILITY_FOR_TYPE` is already correct.
**Same commit:** a `TYPE_CAPABILITY_VIOLATION` handler recording the agent's own outbound
scope-disagreement reports. Today they are declared (`agent_frame.py:21`) and silently dropped, so
plan §7 produces no row. It validates against a bounded pydantic payload (closed `reason`
vocabulary, `detail` free text ≤ 200 chars) and passes through `recordable_violation`
(`agent_telemetry.py:49`) **before** any write — `capability.violation` is deliberately absent from
`CAPABILITY_FOR_TYPE` (`agent_link.py:61-67`), so `dispatch_frame`'s grant gate does not apply and
an agent with `local_discovery` off can still send it, into an unbounded JSONB column
(`models.py:528`) with no retention job. Test: 100 frames in one minute write at most one
`agent_events` row, and the row records the reason code and address and **never** the banner bytes
or evidence values.
Green: `pytest tests/services/test_agent_link.py --no-cov`.

**Task 18 — Agent eligibility for a discovery job.**
Test first: an agent that is pending / rejected / revoked / offline / ungranted /
readiness-degraded / whose tenant and the job's tenant both exist and differ
(`REASON_TENANT_MISMATCH`, `probe_eligibility.py:66,180-186` semantics verbatim) / has no
directly-connected scope covering the target is denied with a distinct machine-readable reason; an
eligible one is allowed. Add `services/discovery_eligibility.py`, mirroring
`monitoring/probe_eligibility.py` (`Eligibility:103`, `_denied:116`, `_readiness_denial:223`) — its
`CAPABILITY` is hardcoded to `remote_probe` at `:55`, so parameterize or mirror; reuse
`probe_eligibility.derive_agent_scope:204` for the DB→scope bridge rather than re-querying
`agent_networks`.
Green: `pytest tests/services/test_discovery_eligibility.py --no-cov`.

**Task 19 — Creation-time validation of an agent-targeted profile or scan.**
Test first, in `tests/test_discovery.py`: `POST`/`PUT /discovery/profiles` and `POST /discovery/scan`
carrying a `scan_agent_id` return **422** with a machine-readable reason for each of — inactive /
pending / revoked agent, `local_discovery` ungranted, degraded collector readiness, a target CIDR
failing `agent_scope.network_in_scope`, `address_count(targets) > grant["max_addresses_per_job"]`,
and a port outside `tcp_ports`. Wire `discovery_eligibility` + `network_in_scope` + `address_count`
into `discovery_profiles_service.create_profile`/`update_profile` and
`discovery_service.create_scan_job`. Plan §3 requires this at **profile save and job creation** and
plan §7 names four checkpoints; the address-count gap is concretely reachable, since
`MIN_SCOPE_PREFIX_V4 = 16` admits a /16 (65 536 addresses) while `max_addresses_per_job` caps at
4096.
Green: `pytest tests/test_discovery.py tests/services/test_discovery_eligibility.py --no-cov`.

**Task 20 — Route an agent job to the agent executor, and dispatch it.**
Test first: `create_scan_job(..., scan_agent_id=N)` persists `scan_agent_id`,
`source_type="agent"`, and `tenant_id = agent.tenant_id`;
`discovery_scheduler._run_profile_job_async` (`:89-96`) copies `profile.scan_agent_id` onto the job
it creates; `schedule_discovery_scan_job` branches on `job.scan_agent_id is not None` to
`agent_discovery.dispatch(...)` and **never** enters `run_scan_job`/`_scan_setup` (assert with a
spy); a scheduled agent profile firing its cron produces an agent job with zero server-scanner
activity. Then: claiming mints a 32-hex `dispatch_id`, sets `dispatch_status='dispatched'`, a
deadline, and `job.scope_version = derive_scope(...).version`, and publishes exactly one
`discovery.request` carrying that same version with `.isoformat()` datetimes (a space separator is
rejected by Go); an offline agent releases the claim to `queued` + `waiting_for_agent` + deadline
per D-5 and publishes nothing; targets and ports are re-validated against the live scope at
dispatch time **in addition to** Task 19's creation-time validation, never instead of it; two real
sessions against Postgres cannot double-dispatch — the second attempt fails on
`uq_scan_jobs_active_dispatch`, not merely on the CAS.
Without this task nothing routes an agent-targeted job away from the server executor:
`create_scan_job` (`discovery_service.py:278-287,336-346`) takes no `scan_agent_id` and never sets
`source_type`, and `_run_profile_job_async` calls `run_scan_job` directly (`:97`).
Green: `pytest tests/services/test_discovery_service.py tests/services/test_agent_discovery_dispatch.py --no-cov`.

**Task 21 — Terminal summary finalization, events, and audit.**
Test first: a `kind="summary"` finding writes terminal status/timestamps via `finalize_agent_job`
without clobbering incremental counters (D-10), emits the existing `job_update` / `job_progress` /
badge events through `_emit_ws_event` **after** commit, writes the ordinary
`scan_completed`/`scan_failed` audit row, and is idempotent under two concurrent summaries (exactly
one finalization). `outcome` maps to the D-4 `error_reason` constants. **`finalize_agent_job` never
invokes `discovery_merge._auto_merge_result` (`discovery_merge.py:165`), regardless of the
`discovery_auto_merge` setting** — that path *creates* `Hardware(name=result.hostname or ...)` with
no review (`discovery_merge.py:196-213`), and plan §5 says rows reach `discovery_import_service`
only when a user accepts them. Assert it with a patched spy.
Green: `pytest tests/services/test_agent_discovery_ingest.py tests/services/test_discovery_service.py --no-cov`.

**Task 22 — Cancellation on every path (D-14, D-16).**
Test first: `DELETE /discovery/jobs/{id}` on an agent job publishes `discovery.cancel`; disabling
`local_discovery` cancels in-flight dispatches and closes their jobs; revoking the agent does the
same; **disabling a discovery profile** — through `update_profile` and through Task 24's
subnet-disappearance path — cancels that profile's in-flight jobs with `reason='profile_disabled'`;
a scope change that either drops a live job's target **or** moves `job.scope_version` cancels it
with `reason='scope_changed'`, fired both from `record_network_facts` returning `True`
(`agent_registry.py:331`) and from a grant scope edit; a late finding after any of these is rejected
independently of whether the cancel was delivered; delivery failure never raises.
Green: `pytest tests/test_discovery.py tests/api/test_agents_api.py --no-cov`.

**Task 23 — `services/agent_discovery_reconcile.py` (D-5).**
Test first: a `waiting_for_agent` job whose agent reconnects is retried **once** through the normal
dispatcher; past its deadline it fails with `error_reason="agent_unavailable"`; a `dispatched` job
whose deadline passed with findings received fails with `agent_disconnected` and **retains** its
findings; a completed or cancelled job is never replayed; the pass is idempotent under concurrent
workers and drains the `queued` backlog that `_schedule_queued_scan_jobs` otherwise strands.
Register with `IntervalTrigger` in `main.py`'s lifespan alongside `discovery_reconciler`
(`main.py:945-952`), holding its own `run_with_advisory_lock` named `agent_discovery_reconcile` —
**not** inside `core/scheduler.reload_discovery_jobs`, which is re-invoked on every profile write
and strips every job it registered (`core/scheduler.py:66-68`). Derive its grace from
`agent_discovery`'s own constant, as `probe_reconcile` derives its from the ingest module's.
Green: `pytest tests/services/test_agent_discovery_reconcile.py --no-cov`.

### Phase D — Zero-configuration bootstrap (Tasks 24–25)

**Task 24 — `services/discovery_bootstrap.py`: derive scope, upsert system profiles, first scan.**
Test first: the first readiness/network report after approval creates exactly one enabled
system-managed profile per safe directly-connected subnet and **none** for loopback, link-local,
default-route, tunnel/point-to-point, public, over-wide prefixes, **or a subnet whose
`address_count` exceeds the agent's `max_addresses_per_job`** (test with a reported /16); repeated
reports create no duplicate profile and no duplicate scan (idempotent upsert on the D-7 partial
unique index); an initial scan is queued after a bounded jitter; a subnet that disappears sets
`enabled = 0`, cancels its in-flight job (`reason='profile_disabled'`, Task 22) and retains history;
a user profile targeting the same CIDR is never touched; the upsert **preserves** an admin-edited
`schedule_cron`/`scan_types` on an existing system profile and only derives `f"{agent_id % 60} */6
* * *"` for a brand-new one. Writes go through `discovery_profiles_service` (Task 7).
Green: `pytest tests/services/test_discovery_bootstrap.py --no-cov`.

**Task 25 — Recurring cadence and central pause controls.**
Test first: the system profile's cron is registered with APScheduler so
`DiscoveryStatusOut.next_scheduled` reports it; pausing globally (an `app_settings` flag), per agent
(`local_discovery.auto_discovery_paused`, Task 3) or per subnet (`discovery_profiles.paused_at`,
Task 4) stops scheduling without deleting anything; a recurring scan auto-updates unchanged
Hardware `last_seen` via `_auto_merge_known_devices` (`discovery_service.py:690`) **with
agent-supplied `hostname` explicitly not propagated** — a hostname difference leaves `hw.hostname`
unchanged and the result `pending`, exactly as an `ip_changed`/`mac_changed` already does
(`:717-719`), because `:722-723` writes it unconditionally today and plan §4 calls hostname an
untrusted observation. Only genuinely new or conflicting devices stay pending.
Green: `pytest tests/services/test_discovery_bootstrap.py tests/services/test_discovery_service.py --no-cov`.

### Phase E — API and frontend (Tasks 26–30)

**Task 26 — Expose execution location on the API.**
Test first: `scan_agent_id` (added to the three request schemas in Task 6) is now surfaced on
`DiscoveryProfileOut` (`schemas/discovery.py:63`) and `ScanJobOut` (`:114`), which today carry
neither it nor `source_type`; `GET /discovery/eligible-agents` lists active granted agents with a
per-agent ineligibility reason; `GET /agents/{id}/discovery` returns effective scope with
provenance, port set and limits, collector readiness rows, the active job, and recent job history —
mirroring `GET /agents/{id}/probes`, which is what `AgentDetailPage.jsx:227-235` already loads for
`AssignedProbesSection`; pause/resume endpoints for all three scopes (M14); `DELETE /agents/{id}`
returns 409 with dependent profile counts (D-1) instead of a 500; the retention purge
(`discovery_scheduler._purge_old_scan_results_impl`, `:119`) deletes agent-sourced results without
violating the new FKs and without touching the `agents` row.
Green: `pytest tests/test_discovery.py tests/api/test_agents_api.py --no-cov`.

**Task 27 — `DiscoveryScopeSection` + `LocalDiscoveryConfigEditor` on Agent Detail.**
Test first (`__tests__/agent-discovery-scope.test.jsx`, cloned from
`agent-assigned-probes.test.jsx:333-382`): automatic subnets, central exclusions, and explicit
routed overrides render with **visibly different provenance**; a tunnel/point-to-point,
default-route, or public candidate must **not** appear as automatically included; effective CIDRs
show the difference between the allow list and what the evaluator will actually permit; a
degraded-readiness collector renders a warning; readiness state, the active job, and the job-history
list all render, with the agent name linking into discovery history; the pause toggle and
cadence/scan-depth editing persist; excluding an automatic subnet and adding a routed CIDR both
persist; a scope wider than the hard-safe range requires the existing `ConfirmDialog`
(`AgentDetailPage.jsx:356-367,750-759`); disabling explains that active work is cancelled but
history retained. Extract as its own component — `AgentDetailPage` is past budget. Clone
`RemoteProbeConfigEditor.jsx`'s LIST_FIELDS / commit-on-blur / exported-bounds idiom.
Green: `npm test -- agent-discovery-scope`.

**Task 28 — "Scan from" on the profile and new-scan forms.**
Test first (`__tests__/discovery-scan-from.test.jsx`, cloned from `monitor-run-from.test.jsx:9-52`):
the default option is the Circuit Breaker server with `value=""`; selecting an agent filters the
scan-type checkboxes to `agent_connect` and disables the rest
(`components/discovery/NewScanPage.jsx:320-323` is the disable precedent); an ineligible agent shows
its reason; `ScanProfileForm.CIDR_RE:17` accepts IPv6 ULA (it is IPv4-only today and would reject
the agent's own scope).
Green: `npm test -- discovery-scan-from`.

**Task 29 — Execution location in job history, and the badge fix.**
Test first: job cards and `DiscoveryHistoryPage` (`:611-641`) show the execution location and link
the agent name to its detail page; `ScanDetailPanel.SOURCE_COLORS` (`:24-31`) gains `agent`; the
status filter (`:594-599`) and `error_reason` render the D-4 vocabulary including the
partial-findings message; the review queue handles agent findings with **no** separate UI path.
**Same commit:** add the missing `pending_count` to `discovery_merge._emit_result_processed_event`
(`:96-101`) — `useDiscoveryStream.js:271-277` already reads it, and many incremental agent findings
make the existing badge drift materially worse.
Green: `npm test`, `pytest tests/services/test_discovery_merge.py --no-cov`.

**Task 30 — CSS for the new BEM classes.**
No new test. Add styles for the `agent-discovery-*` classes this slice introduces **and** for
Slice 3's `agent-probes-*` classes, which ship unstyled today
(`grep -rn 'agent-probes' apps/frontend/src --include=*.css` → nothing).
Green: `npm run lint`, `npm test`.

### Phase F — End-to-end gate (Tasks 31–33)

**Task 31 — Prepare the E2E harness (D-12).**
Pin `agent-net` to `10.88.0.0/24`; relax and parameterize `_agent_network_name`'s exact-set
assertion (`test_agent_e2e.py:462-466`); add a second `probe-net` fixture container brought up
mid-test and a second `cb-agent` service on its own isolated network. All existing e2e tests must
still pass (except the two already red per the baseline).
Green: `cd apps/agent/e2e && pytest -m e2e -k "not update_success"`.

**Task 32 — E2E: zero-configuration discovery, plan §8 steps 1–7.**
One install command, normal approval, no CIDR entry: the agent reports its directly connected test
subnet, the backend creates the system profiles per D-12, an initial scan starts automatically with
observable incremental progress, the fixture lands in the ordinary review queue, importing it
creates exactly one Hardware row, and replaying the findings creates no duplicate result or
Hardware row. Reuse `_backend_sh:1852` and the isolation loop `:1987-2007` to prove the backend
could not have scanned the fixture itself.

**Task 33 — E2E: cancellation, restart, second agent, recurrence — plan §8 steps 8–11.**
Disabling the capability mid-scan cancels it and late findings are rejected; restarting both sides
and changing the agent's address reconnects and resumes recurring discovery with no re-enrollment
and no profile duplication; a second isolated agent's findings and provenance stay distinct; the
recurring scan auto-updates unchanged Hardware `last_seen` and re-queues only genuinely new or
conflicting devices.

---

## Definition of done

Plan §10 verbatim, plus:

- `pytest --maxfail=60 -q` shows **no new failures** against the 1581-passing baseline.
- `go test -race ./...`, `go vet ./...`, `ruff check src/app`, `mypy src/app`, `npm run lint`,
  `npm test` all green.
- `fixtures/agent_frame_corpus.json` covers all three `discovery.*` types and **both**
  `PENDING_CORPUS_TYPES` / `pendingCorpusTypes` lists have had `discovery.request` and
  `discovery.finding` removed.
- The `0100` migration survives a real fresh-bootstrap, upgrade, and downgrade with its FKs and
  partial indexes intact.
- No `CAP_NET_RAW`, no root, no bundled scanner, no network relay, no autonomous scanning.

## Follow-ups (explicitly out of scope)

- **F-9.** `.github/workflows/*.yml` runs no backend pytest and no docker e2e job, so every Python
  and E2E test in this plan is locally enforced only. Adding a pytest job requires first resolving
  the 52% vs 60% coverage gate, which is not Slice 4's to fix.
- **F-8.** The pre-existing `test_agent_update_success_and_forced_rollback` docker-network race.
- SNMP and mDNS/SSDP discovery, deferred by plan §11 to a second milestone.
- A managed rendezvous/relay for a Circuit Breaker installation that is itself behind NAT, which
  plan §11 correctly calls a separate architectural slice.
