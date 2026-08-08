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
  (`pages/{AgentDetailPage,AgentsPage,DiscoveryPage,DiscoveryHistoryPage,NewScanPage}.jsx`,
  `components/agents/*`, `components/discovery/{ScanProfileForm,ScanDetailPanel}.jsx`,
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
4. **There is no discovery reconciliation loop.** The only caller of
   `_schedule_queued_scan_jobs` is `_scan_finalize` (`discovery_service.py:812`), so a job that
   fails to claim a slot is abandoned until some other job finishes. Plan §3's dispatch deadline,
   expiry, and retry-on-reconnect have no owner.
5. **No `internal/collect/discover` package**, no netlink dependency, no reverse-DNS helper, and
   `probe.Runtime` emits exactly one result per unit of work (`runtime.go:582-604`) — the
   many-findings-plus-terminal-summary contract is a genuine structural divergence, not a copy.

**31 ordered, test-first tasks**, one focused commit each, each ending with the affected Go,
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
- `DELETE /api/v1/agents/{id}` gains a pre-check returning **409** with
  `{"detail": {"reason": "agent_has_discovery_profiles", "profiles": [...], "profile_count": N}}`
  before the DB can raise, mirroring `api/agents.py:869-893`.

**Rationale:** Plan §2 asks for RESTRICT on "an agent selected by a profile **or retained job/result
history**". Taken literally that makes an agent row permanently undeletable, because
`discovery_scheduler._purge_old_scan_results_impl` is disabled outright when
`discovery_retention_days <= 0` (`discovery_scheduler.py:124-125`). Slice 3 resolved the identical
tension explicitly: `MonitorItem.probe_agent_id` is RESTRICT because it is a *live assignment*
(`models.py:262-272`) while `MonitorProbeRun.agent_id` is CASCADE because "anything reachable there
is finished history" (`:326-333`). The plan's actual invariant — "**Revocation** does not erase
provenance" — is fully satisfied: revocation sets `agents.status='revoked'` and deletes no row, so
provenance survives. Only an explicit, 409-guarded operator deletion cascades.

### D-2. The migration is `0100_discovery_agent_execution`, and `0001_init` must be taught about every new column and index.

**Decision:** `_EXCLUDED_COLUMNS["discovery_profiles"|"scan_jobs"|"scan_results"]`
(`0001_init.py:91,115,116`) gains every column this slice adds, and `0100` creates them itself for
fresh installs and upgrades alike. A `tests/test_discovery_agent_schema.py` modeled on
`tests/test_monitor_probe_schema.py:53-105` asserts bootstrap fidelity plus a real
downgrade/upgrade round-trip that the FK survives with `("scan_agent_id",), "agents", "RESTRICT"`
and that the partial unique indexes keep their `WHERE` clause.

**Rationale:** Fresh installs do not replay revisions — `0001_init` rebuilds `Base.metadata` minus
its exclusion lists. `agents` is in `_EXCLUDED_TABLES` and `_should_copy_fk` drops any FK whose
*target* is excluded (`0001_init.py:149-155`), so a naively-added FK would ship on every new
deployment as a bare INTEGER with no constraint — the 409 in D-1 would be silently void. Worse, the
index-copy loop rebuilds indexes as `sa.Index(name, *cols, unique=…)` and **discards
`postgresql_where`** (`:213-217`), which would turn `(scan_job_id, finding_id) WHERE finding_id IS
NOT NULL` into a **full** unique index and break every result row after the first with a NULL
`finding_id`. `0099_monitor_probe_runs.py:19-25` documents exactly this failure.

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
`agent_rejected`, `dispatch_failed`, `scope_changed`, `capability_disabled`.

**Rationale:** This is plan §3's own stated v1 recommendation ("avoiding a broad status-model
change"). `status` is a bare string on `ScanJob` read by the frontend status filter
(`DiscoveryHistoryPage.jsx:594-599`), the history query, and the review badge; a sixth value is a
cross-cutting change with no product requirement behind it.

### D-5. `waiting_for_agent` keeps the job `queued` and does not consume a concurrency slot.

**Decision:** When an agent job is claimed but its agent is not connected, the claim is **released**:
`status='queued'`, `progress_phase='waiting_for_agent'`, `dispatch_status='queued'`,
`dispatch_deadline_at = now + CB_DISCOVERY_DISPATCH_DEADLINE_S` (default 900). A new
`services/discovery_reconcile.py` (Task 21), registered on the existing APScheduler under the
existing advisory-lock idiom, is what re-drains it, expires it, and retries it on reconnect.

**Rationale:** `discovery_scheduler._running_scan_count` counts `status == "running"`
(`:30-32`). A `waiting_for_agent` job in `running` would hold a scarce slot for the whole deadline
while doing no work. Leaving it `queued` is correct but requires an owner, because today the *only*
caller of `_schedule_queued_scan_jobs` is `_scan_finalize` (`discovery_service.py:812`) — a queued
job with no other job running is abandoned forever. Plan §3 requires the deadline/expiry/retry
behavior and names no owner; `monitoring/probe_reconcile.py` is the working precedent, including
deriving its grace from the ingest module's own constant.

### D-6. `agent_connect` is introduced together with the product's first scan-type vocabulary, validated on write only.

**Decision:** New `core/discovery_scan_types.py` declaring
`SERVER_SCAN_TYPES = {"nmap","arp","snmp","http","docker","opnsense","deep_dive","proxmox","lldp"}`,
`AGENT_SCAN_TYPES = {"agent_connect"}`, `ALL_SCAN_TYPES`, and
`validate_scan_types(types, *, scan_agent_id) -> list[str]`. Wired into
`DiscoveryProfileCreate`/`DiscoveryProfileUpdate`/`AdHocScanRequest` and into
`discovery_service.create_scan_job`. **Validation runs on write only, never on read** — existing
rows may hold arbitrary strings and must keep loading.

**Rationale:** Plan §3 treats "expose a focused scan type such as `agent_connect`" as a one-liner,
but nothing validates scan types anywhere today. Without a vocabulary there is no way to express
"do not send server-only scan types to an agent", which §3 also requires. Write-only validation is
what makes the introduction backward-compatible.

### D-7. System-managed profiles are keyed by `(scan_agent_id, normalized_cidr)` under a partial unique index, with a derived per-agent cron.

**Decision:** `discovery_profiles` gains `scan_agent_id`, `normalized_cidr` (`String`, the
`ipaddress.ip_network(...)` canonical form), and `managed_by` (`String(16)`, NULL for user
profiles, `'system'` for auto). Partial unique index
`uq_discovery_profiles_system_agent_cidr` on `(scan_agent_id, normalized_cidr)`
`WHERE managed_by = 'system'`. Cadence is `schedule_cron = f"{agent_id % 60} */6 * * *"`. A subnet
that disappears sets `enabled = 0` (an `Integer` column, not a bool) and is never deleted. Every
system-profile write goes through `discovery_profiles_service.create_profile`/`update_profile`.

**Rationale:** `DiscoveryProfile` has no `__table_args__`, no unique constraint, no canonical CIDR
column, and no managed marker. A plain `UNIQUE(scan_agent_id, normalized_cidr)` would collide with a
user-created profile targeting the same CIDR, which plan §3 forbids ("User-created profiles remain
separate and are never overwritten"). Cron is the only cadence field and has no jitter primitive, so
a derived per-agent minute offset is the mechanism; APScheduler's `misfire_grace_time=300` is not
jitter. Going through the service layer is required or the discovery-category audit rows and
`reload_discovery_jobs` never fire and `DiscoveryStatusOut.next_scheduled` silently omits system
profiles (`api/discovery.py:98-112`).

### D-8. Candidate subnets keep riding `agent_networks`; `capability.readiness` gains an optional `networks` field to refresh them mid-session.

**Decision:** Do **not** add structured discovery data to `agent_capability_readiness` (it has no
column for it). Collector state travels as ordinary readiness rows named
`discovery.neighbor`, `discovery.icmp`, `discovery.tcp`, `discovery.dns`. Candidate CIDRs continue to
come from `agent_networks.facts` via `core/agent_scope.derive_scope`. `CapabilityReadinessPayload`
(backend) and `frame.CapabilityReadinessPayload` (Go) gain **one** optional field, `networks`,
identical in shape to `HelloPayload.networks`; `agent_link._handle_readiness` forwards it to the
existing `agent_registry.record_network_facts`, which already bumps `generation` only on real change.

**Rationale:** Plan §6 asks for "active interface names, addresses, and directly connected candidate
CIDRs" in readiness, and there is no field for any of it. Slice 3 already built the persistence
(`agent_networks`, generation, `record_network_facts`) and the derivation (`derive_scope`) — a second
copy in a readiness column would be the duplication the "one scope evaluator" constraint forbids.
But `HelloPayload.networks` is sent only at connect, so plan §3's "when a subnet appears, create and
scan its system profile" would otherwise wait for a reconnect. One optional field on an existing
periodic frame is the minimum change that closes it, and `record_network_facts`'s
change-gated write means it costs no extra row writes in steady state.

### D-9. Row-building and Hardware matching are extracted to `services/discovery_result_service.py`, taking `db` as a parameter.

**Decision:** Extract `discovery_service.py:557-642` (the `ScanResult(...)` construction, override
fields, MAC-then-IP Hardware match, and two-field conflict classification) into
`discovery_result_service.build_and_classify_result(db, job_id, raw, *, discovery_agent_id=None, finding_id=None) -> tuple[ScanResult, str]`
where the returned `str` is `"new" | "matched" | "conflict"`. `_scan_import` calls it in its loop;
the agent finding handler calls it once per finding. MAC and IP are normalized **before** the call
on the agent path, and the matcher's MAC comparison becomes case-insensitive.

**Rationale:** Plan §5 requires this refactor but under-specifies it. The rest of `_scan_import`
(`:479-687`) is batch-shaped and actively wrong for a single incremental finding: it opens its own
`SessionLocal`, requires the `setup` dict from `_scan_setup`, de-dupes IPs across the whole batch
(`:495-505`), suppresses prober rows (`:521-555`), and **overwrites** `job.hosts_*` rather than
incrementing (`:670-675`). The matcher does exact-equality MAC lookups with no normalization
(`:591-598`), so untrusted agent-supplied MACs in arbitrary case would systematically fail to match
existing Hardware — plan §4's "normalize IP and MAC values server-side" is what prevents that, and
it has to happen before the matcher, not after.

### D-10. Job counters are incremental on the agent path and absolute on the server path.

**Decision:** `_scan_finalize` keeps its current absolute-write semantics for server jobs. The agent
path increments `job.hosts_found/new/updated/conflict` and `job.finding_count` per accepted finding
inside the ingest transaction, and its terminal summary calls a new
`discovery_service.finalize_agent_job(db, job, status, *, error_reason=None)` that writes terminal
status/timestamps and emits the existing events **without** touching the counters.

**Rationale:** Sharing `_scan_finalize` unchanged would clobber accumulated agent counts with a
stats dict the agent path never assembles.

### D-11. The neighbor cache is read via `RTM_GETNEIGH` over `golang.org/x/sys/unix`. No new module.

**Decision:** `internal/collect/discover/neigh_linux.go` implements a netlink dump directly against
`golang.org/x/sys/unix`, promoted from indirect to direct in `go.mod` at its existing pinned
`v0.28.0`. Parsing is table-tested against captured `[]byte` fixtures; a `neigh_stub.go` with
`//go:build !linux` returns "unsupported" so the package still builds and vets everywhere.

**Rationale:** Plan §1 requires "netlink, not shell parsing". `vishvananda/netlink` is a new module
whose recent releases declare Go ≥1.23 while CI pins 1.22 (`go.mod:9-14` documents this exact hazard
for two other dependencies). `/proc/net/arp` is IPv4-only. `x/sys` is already in the module graph, so
the socket + message parsing is ~150 lines with zero dependency risk.

### D-12. The E2E gate asserts one system profile **per directly connected subnet**, not exactly one overall.

**Decision:** `apps/agent/e2e/docker-compose.yml` pins `agent-net` to `10.88.0.0/24`. The gate
asserts (a) exactly one enabled system-managed profile per directly-connected private subnet the
agent reports, (b) exactly one of them targets the `probe-net` fixture subnet `10.77.0.0/24`, and
(c) the fixture is discovered through it — with **no** CIDR entry or agent-side configuration.

**Rationale:** Plan §8 step 3 says "exactly one system-managed profile", which cannot hold: the agent
container is attached to two networks. Today `agent-net` is an unpinned bridge
(`docker-compose.yml:44-53`) so Docker allocates a **/16** — 65534 addresses, which alone blows past
`max_addresses_per_job: 1024`. Pinning it to a /24 makes the topology honest and the assertion
meaningful. The zero-configuration property the step actually protects is preserved in full.

### D-13. `discovery.cancel` is a new server→agent control frame and lands with its corpus fixtures in one commit.

**Decision:** `TYPE_DISCOVERY_CANCEL = "discovery.cancel"` / `TypeDiscoveryCancel`. Task 5 lands, in
**one** commit: both constants, the Go `allFrameTypes` **and** `controlFrameTypes` entries, all three
pydantic payload models, all three Go payload structs, the `fixtures/agent_frame_corpus.json`
fixtures, the `_PAYLOAD_MODEL_FOR_TYPE` entries, the Go `TestCorpus_TypedPayloadsDecode` switch
arms, a by-name field assertion modeled on
`test_probe_payloads_survive_the_typed_models_by_name`, and the deletion of `TYPE_DISCOVERY_REQUEST`
/ `TYPE_DISCOVERY_FINDING` from **both** pending lists.

**Rationale:** `test_corpus_covers_every_declared_frame_type` asserts a set **equality**
(`test_agent_frame_conformance.py:148`), so declaring a constant without a fixture fails the suite
immediately, and a stale pending entry fails just as loudly. Without the by-name assertion a model
that misspells `open_ports` or `evidence` silently drops the field and the round-trip still passes.
Corpus content follows the existing precedent: a fully-populated variant, a minimal variant, every
value of each closed vocabulary (`kind` ∈ {`host`,`summary`}), and at least one explicit `false`.

### D-14. Disabling `local_discovery` or revoking the agent cancels in-flight dispatches explicitly.

**Decision:** `PUT /agents/{id}/capabilities` disabling `local_discovery`, and agent revocation, both
call `agent_discovery.cancel_agent_dispatches(db, agent_id, reason=...)` — which closes open jobs in
the DB inside the transaction, builds inert cancellation value objects, and publishes
`discovery.cancel` only **after** commit, never raising on delivery failure.

**Rationale:** Mirrors `monitor_service.ProbeCancellation` / `publish_probe_cancels` and
`api/agents.py:830-848`. It is not optional: once the grant is off, `dispatch_frame`'s gate
(`agent_link.py:411-420`) drops the agent's own terminal summary as a `capability_violation`, so
without an explicit cancel the job never closes.

### D-15. Scope-limit helpers are added to the one evaluator, in both languages, with corpus coverage.

**Decision:** `core/agent_scope.py` gains `network_in_scope(scope, cidr) -> Decision` (whole-prefix
containment, special-use denial first, exclusion, then allow-list), `address_count(cidrs) -> int`,
and `MIN_SCOPE_PREFIX_V4 = 16` / `MIN_SCOPE_PREFIX_V6 = 48` hard ceilings. `internal/netscope` gains
`NetworkInScope` / `AddressCount` with identical semantics, and `fixtures/agent_scope_corpus.json`
grows a `network_cases` section both suites consume.

**Rationale:** The evaluator answers only per-address allow/deny today. Plan §3 requires "every target
CIDR contained in the versioned effective scope" and §7 requires the agent to re-check the same rule
before connecting. Two implementations of "is this prefix in scope" is exactly the divergence the
shared corpus exists to forbid.

---

## Task list

Each task is one commit. Each begins with a failing test and ends with the named suites green.
`--no-cov` on every targeted backend run.

### Phase A — Contracts and schema (Tasks 1–6)

**Task 1 — Add whole-CIDR scope helpers to the backend evaluator.**
Tests first in `tests/unit/test_agent_scope.py` + `tests/unit/test_agent_scope_corpus.py`:
a `/24` fully inside a derived direct network is in scope; a `/24` straddling the boundary is not;
a prefix containing any `_BLOCKED_NETWORKS` address is `special_use` **before** any allow rule; a
prefix overlapping `excluded_cidrs` is `excluded_cidr`; an empty scope is `empty_scope`; `/8` is
rejected against `MIN_SCOPE_PREFIX_V4`; `address_count` sums `/24 + /25` correctly and treats a
`/32` as 1. Then implement `network_in_scope`, `address_count`, `MIN_SCOPE_PREFIX_V4/V6` in
`core/agent_scope.py`, and add a `network_cases` array to `fixtures/agent_scope_corpus.json`.
Green: `pytest tests/unit/test_agent_scope.py tests/unit/test_agent_scope_corpus.py --no-cov`.

**Task 2 — Mirror the helpers in Go against the same corpus.**
Test first: `internal/netscope/corpus_test.go` grows a `network_cases` loop that fails until
`NetworkInScope`/`AddressCount` exist and agree with every backend expectation, including the
ordering rule (special-use before allow). Implement in `internal/netscope/netscope.go`.
Green: `cd apps/agent && go test -race ./internal/netscope/...`.

**Task 3 — Give `local_discovery` a real structured config on both sides.**
Tests first: `tests/services/test_agent_capabilities.py` (defaults exactly match plan §1; every
bound rejected with a specific message: `max_addresses_per_job` 1–4096, `max_concurrent_hosts`
1–256, `host_timeout_ms` 100–10000, `job_timeout_seconds` 30–1800, `tcp_ports` 1–65535 with ≤32
entries, `scope_mode` ∈ `SCOPE_MODES`, CIDR lists through `normalize_scope_cidrs`);
`tests/api/test_agents_api.py` (a structured config round-trips through
`PUT /agents/{id}/capabilities` and is echoed in `capabilities.set`);
`internal/capability/capability_test.go` (the Go normalizer clamps identically and an unknown key
is dropped, not passed through). Replace `agent_capabilities.py:190-195` with
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
Columns, per plan §2 and D-1/D-7:
- `discovery_profiles`: `scan_agent_id` (FK RESTRICT, indexed), `normalized_cidr`, `managed_by`.
- `scan_jobs`: `scan_agent_id` (FK CASCADE), `dispatch_id` (`String(32)`, unique),
  `dispatch_status`, `dispatch_deadline_at`, `last_finding_at`, `finding_count` (default 0);
  index `(scan_agent_id, status, created_at)`; **also** the missing index on `profile_id`.
- `scan_results`: `discovery_agent_id` (FK CASCADE, indexed), `finding_id` (`String(64)`);
  partial unique index `(scan_job_id, finding_id) WHERE finding_id IS NOT NULL`.
- Documented `source_type` vocabularies at `models.py:1668` and `:1726` both gain `agent`.
**Same commit:** every new column and index name is added to
`0001_init._EXCLUDED_COLUMNS["discovery_profiles"|"scan_jobs"|"scan_results"]`.
Green: `pytest tests/unit/test_migration_0100_discovery_agent_execution.py tests/test_discovery_agent_schema.py --no-cov`
plus the CI single-head check.

**Task 5 — The three discovery frame contracts and their corpus fixtures.**
Everything in D-13, in one commit. Payload shapes are plan §4 verbatim.
`DiscoveryRequestPayload`, `DiscoveryFindingPayload` (with `OpenPort` sub-model), and
`DiscoveryCancelPayload`; bounded — `targets` ≤ 16, `tcp_ports` ≤ 32, `evidence` ≤ 16 entries of
≤ 32 chars, `hostname` ≤ 253, `open_ports` ≤ 64, `dispatch_id` exactly 32 lowercase hex.
Green: `pytest tests/test_agent_frame_conformance.py --no-cov` and
`go test -race ./internal/frame/...`.

**Task 6 — Introduce the scan-type vocabulary (D-6).**
Tests first in `tests/api/test_discovery_api.py`: a profile with `scan_types=["nmap"]` and a
`scan_agent_id` is 422; `["agent_connect"]` without a `scan_agent_id` is 422; `["bogus"]` is 422;
an **existing** row holding an unknown string still loads through `GET`. Add
`core/discovery_scan_types.py` and wire `validate_scan_types` into the three schemas and into
`create_scan_job`; the `_NMAP_OVERRIDE_PREFIX` label encoding (`discovery_service.py:330-334`) is
skipped on the agent path.
Green: `pytest tests/api/test_discovery_api.py --no-cov`.

### Phase B — The Go collector (Tasks 7–13)

**Task 7 — `internal/collect/discover`: request validation, no network I/O.**
Test first: a table over rejection causes — unknown method, target not in the effective scope,
target not directly connected, prefix wider than `MIN_SCOPE_PREFIX_*`, address count over
`max_addresses_per_job`, a port outside the grant, a `deadline_at` already past, a malformed
`dispatch_id`. Each returns a distinct machine-readable reason and performs **zero** network
activity (assert via an injected dialer that fails the test if called). Implement `Request`,
`Finding`, `Validate(req, grant, scope)`.
Green: `go test -race ./internal/collect/discover/...`.

**Task 8 — Neighbor cache over netlink (D-11).**
Test first: parse captured `RTM_GETNEIGH` response bytes into `{ip, mac, state}`, including a
truncated message, an unknown address family, an `NUD_FAILED` entry that must be dropped, and a
zero MAC. Implement `neigh_linux.go` + `neigh_stub.go`; promote `golang.org/x/sys` to a direct
require.
Green: `go test -race ./internal/collect/discover/...` and `go vet ./...`.

**Task 9 — Bounded host liveness: ICMP datagram + TCP connect.**
Test first: `max_concurrent_hosts` is never exceeded (counting semaphore probe); `host_timeout_ms`
is honored; context cancellation returns within one timeout and leaks no goroutines
(`runtime.NumGoroutine()` before/after, as `probe/runtime_test.go` does); an unprivileged ICMP
socket failure degrades to TCP-connect rather than failing the job. Reuse the ICMP construction
already in `internal/collect/probe/icmp.go` — do not fork it.
Green: `go test -race ./internal/collect/discover/...`.

**Task 10 — Reverse DNS and bounded banner capture.**
Test first: PTR lookup is bounded and a failure yields no hostname rather than an error; a banner
read stops at 512 bytes and 2 seconds; non-UTF8 and control bytes are stripped; nothing is captured
for a port whose grant does not list it.
Green: `go test -race ./internal/collect/discover/...`.

**Task 11 — The discovery runtime: dispatch, incremental findings, terminal summary, cancellation.**
Test first: one `discovery.request` produces N `kind="host"` findings plus exactly one
`kind="summary"` terminal finding; `finding_id` is **replay-stable** (same dispatch + same address
⇒ same id — this is what makes spool replay idempotent, so it must be a digest of
`dispatch_id|kind|address`, not `collect.SampleID()`); a second request for a live `dispatch_id` is
refused; `discovery.cancel` stops work within one host timeout and still emits a terminal summary
with `outcome="cancelled"`; a rejected request emits **only** a summary with the Task 7 reason.
Model the structure on `probe/runtime.go` (`Assign:279`, `Cancel:331`, slot gate `:411-456`, pump
`:461-474`) but note the many-findings shape is new.
Green: `go test -race ./internal/collect/discover/... ./internal/collect/...`.

**Task 12 — Discovery readiness, and `networks` on the readiness frame (D-8).**
Test first (Go): `DiscoverNames` reports `discovery.neighbor|icmp|tcp|dns` with
`ready|degraded|unavailable` and a remediation string when the ICMP socket is unavailable; the
readiness frame carries current `networks`. Test first (backend): `_handle_readiness` forwards
`networks` to `record_network_facts`, an absent key leaves the last report standing, and an explicit
`[]` replaces it. Add the optional field to both `CapabilityReadinessPayload`s and a corpus fixture
exercising it.
Green: `go test -race ./internal/collect/discover/... ./internal/frame/...`,
`pytest tests/services/test_agent_link.py tests/test_agent_frame_conformance.py --no-cov`.

**Task 13 — Wire the runtime into `main.go` and the link.**
Test first: `cmd/cb-agent` asserts the runtime starts only when `local_discovery` is granted, that
`capabilities.set` disabling it cancels in-flight work and stops future work, that a config change
re-applies bounds, and that `discovery.request`/`discovery.cancel` reach the runtime.
Follow `main.go:381-387` (link callbacks), `:689-696` (construct+Start), `:697-727`
(`applyProbeConfig`), `:729-747` (`onCapabilitiesSet`).
Green: `cd apps/agent && make test`.

### Phase C — Backend dispatch and ingest (Tasks 14–21)

**Task 14 — Extract `discovery_result_service.build_and_classify_result` (D-9).**
Test first: characterization tests pinning today's behavior for `_scan_import` (a new host, a MAC
match, a hostname conflict, the docker override fields) pass **unchanged** after extraction; plus
new tests that a lowercase agent MAC matches an uppercase stored MAC and that `finding_id` /
`discovery_agent_id` are persisted when supplied. No behavior change on the server path.
Green: `pytest tests/services/test_discovery_service.py tests/services/test_discovery_result_service.py --no-cov`.

**Task 15 — `services/agent_discovery.py`: finding ingest.**
Test first, mirroring `tests/services/test_agent_probe_ingest.py` one-for-one: raw-size limits
enforced **before** pydantic; the `(dispatch_id, job, agent)` triple must agree or it is a
`capability_violation`; a finding whose address is outside the job target or the current scope is
rejected and audited; a finding after cancellation or a terminal summary is rejected; a duplicate
`(scan_job_id, finding_id)` inserts exactly one `ScanResult` and emits no second `result_added`;
tenant is derived from the job, never from the payload; counters increment (D-10); MAC/IP are
normalized before matching. Dispositions and `InvalidDiscoveryFinding` follow `agent_probe.py`'s
shapes.
Green: `pytest tests/services/test_agent_discovery_ingest.py --no-cov`.

**Task 16 — Register the handler, and give `capability.violation` a home.**
Test first: a granted agent's `discovery.finding` reaches the ingest service; an ungranted one is a
`capability_violation` and is dropped; a malformed one is a `protocol_violation`; both are rate
limited through `agent_telemetry.recordable_violation`. Add exactly one `_HANDLERS` line
(`agent_link.py:300-309`) — `CAPABILITY_FOR_TYPE` is already correct. **Same commit:** add a
`TYPE_CAPABILITY_VIOLATION` handler recording the agent's own outbound scope-disagreement reports
as `agent_events`; today they are declared (`agent_frame.py:21`) and silently dropped, so plan §7's
`capability_violation` requirement produces no row.
Green: `pytest tests/services/test_agent_link.py --no-cov`.

**Task 17 — Agent eligibility for a discovery job.**
Test first: an agent that is pending / rejected / revoked / offline / ungranted / readiness-degraded
/ has no directly-connected scope covering the target is denied with a distinct machine-readable
reason; an eligible one is allowed. Add `services/discovery_eligibility.py`, mirroring
`monitoring/probe_eligibility.py` (`Eligibility:103`, `_denied:116`, `_readiness_denial:223`) — its
`CAPABILITY` is hardcoded to `remote_probe` at `:55`, so parameterize or mirror; reuse
`probe_eligibility.derive_agent_scope:204` for the DB→scope bridge rather than re-querying
`agent_networks`.
Green: `pytest tests/services/test_discovery_eligibility.py --no-cov`.

**Task 18 — Dispatch an agent job.**
Test first: claiming an agent job mints a 32-hex `dispatch_id`, sets `dispatch_status='dispatched'`
and a deadline, and publishes exactly one `discovery.request` with `.isoformat()` datetimes (a
space separator is rejected by Go); an offline agent releases the claim to `queued` +
`waiting_for_agent` + deadline per D-5 and publishes nothing; a second worker cannot double-dispatch
the same job (row lock + compare-and-set on `dispatch_status`); the request's targets and ports are
re-validated against the live scope at dispatch time, not at creation time.
Green: `pytest tests/services/test_agent_discovery_dispatch.py --no-cov`.

**Task 19 — Terminal summary finalization, events, and audit.**
Test first: a `kind="summary"` finding writes terminal status/timestamps via
`finalize_agent_job` without clobbering incremental counters (D-10), emits the existing
`job_update` / `job_progress` / badge events through `_emit_ws_event` **after** commit, writes the
ordinary `scan_completed`/`scan_failed` audit row, and is idempotent under two concurrent summaries
(exactly one finalization). `outcome` maps to the D-4 `error_reason` constants.
Green: `pytest tests/services/test_agent_discovery_ingest.py tests/services/test_discovery_service.py --no-cov`.

**Task 20 — Cancellation on every path (D-14).**
Test first: `DELETE /discovery/jobs/{id}` on an agent job publishes `discovery.cancel`; disabling
`local_discovery` cancels in-flight dispatches and closes their jobs; revoking the agent does the
same; a scope change that no longer contains a live job's target cancels it with
`error_reason="scope_changed"`; a late finding after any of these is rejected independently of
whether the cancel was delivered; delivery failure never raises.
Green: `pytest tests/api/test_discovery_api.py tests/api/test_agents_api.py --no-cov`.

**Task 21 — `services/discovery_reconcile.py` (D-5).**
Test first: a `waiting_for_agent` job whose agent reconnects is retried **once** through the normal
dispatcher; past its deadline it fails with `error_reason="agent_unavailable"`; a `dispatched` job
whose deadline passed with findings received fails with `agent_disconnected` and **retains** its
findings; a completed or cancelled job is never replayed; the pass is idempotent under concurrent
workers (advisory lock) and drains the `queued` backlog that `_schedule_queued_scan_jobs` otherwise
strands. Register on the existing APScheduler beside `discovery_purge` (`core/scheduler.py:99-105`)
and derive its grace from `agent_discovery`'s own constant, as `probe_reconcile` does.
Green: `pytest tests/services/test_discovery_reconcile.py --no-cov`.

### Phase D — Zero-configuration bootstrap (Tasks 22–23)

**Task 22 — `services/discovery_bootstrap.py`: derive scope, upsert system profiles, first scan.**
Test first: the first readiness/network report after approval creates exactly one enabled
system-managed profile per safe directly-connected subnet and **none** for loopback, link-local,
default-route, tunnel/point-to-point, public, or over-wide prefixes; repeated reports create no
duplicate profile and no duplicate scan (idempotent upsert on the D-7 partial unique index); an
initial scan is queued after a bounded jitter; a subnet that disappears sets `enabled = 0` and
retains history; a user profile targeting the same CIDR is never touched. Writes go through
`discovery_profiles_service`.
Green: `pytest tests/services/test_discovery_bootstrap.py --no-cov`.

**Task 23 — Recurring cadence and central pause controls.**
Test first: the system profile's `schedule_cron` is `f"{agent_id % 60} */6 * * *"` and is registered
with APScheduler so `DiscoveryStatusOut.next_scheduled` reports it; pausing globally, per agent, or
per subnet stops scheduling without deleting anything; a recurring scan auto-updates unchanged
Hardware `last_seen` via the existing `_auto_merge_known_devices` (`discovery_service.py:690`) and
leaves only genuinely new or conflicting devices pending.
Green: `pytest tests/services/test_discovery_bootstrap.py tests/services/test_discovery_scheduler.py --no-cov`.

### Phase E — API and frontend (Tasks 24–28)

**Task 24 — Expose execution location on the API.**
Test first: `scan_agent_id` round-trips on `DiscoveryProfileCreate/Update/Out`, `AdHocScanRequest`,
and `ScanJobOut` (which today carries neither `source_type` nor any agent field,
`schemas/discovery.py:114-135`); `GET /discovery/eligible-agents` lists active granted agents with a
per-agent ineligibility reason; `DELETE /agents/{id}` returns 409 with dependent profile counts
(D-1) instead of a 500.
Green: `pytest tests/api/test_discovery_api.py tests/api/test_agents_api.py --no-cov`.

**Task 25 — `DiscoveryScopeSection` + `LocalDiscoveryConfigEditor` on Agent Detail.**
Test first (`__tests__/agent-discovery-scope.test.jsx`, cloned from
`agent-assigned-probes.test.jsx:333-382`): automatic subnets, central exclusions, and explicit
routed overrides render with **visibly different provenance**; effective CIDRs show the difference
between the allow list and what the evaluator will actually permit; excluding an automatic subnet
and adding a routed CIDR both persist; a scope wider than the hard-safe range requires the existing
`ConfirmDialog` (`AgentDetailPage.jsx:356-367,750-759`); disabling explains that active work is
cancelled but history retained. Extract as its own component — `AgentDetailPage` is past budget.
Clone `RemoteProbeConfigEditor.jsx`'s LIST_FIELDS / commit-on-blur / exported-bounds idiom.
Green: `npm test -- agent-discovery-scope`.

**Task 26 — "Scan from" on the profile and new-scan forms.**
Test first (`__tests__/discovery-scan-from.test.jsx`, cloned from `monitor-run-from.test.jsx:9-52`):
the default option is the Circuit Breaker server with `value=""`; selecting an agent filters the
scan-type checkboxes to `agent_connect` and disables the rest (`NewScanPage.jsx:320-323` is the
disable precedent); an ineligible agent shows its reason; `ScanProfileForm.CIDR_RE:17` accepts IPv6
ULA (it is IPv4-only today and would reject the agent's own scope).
Green: `npm test -- discovery-scan-from`.

**Task 27 — Execution location in job history, and the badge fix.**
Test first: job cards and `DiscoveryHistoryPage` (`:611-641`) show the execution location and link
the agent name to its detail page; `ScanDetailPanel.SOURCE_COLORS` (`:24-31`) gains `agent`; the
status filter (`:594-599`) and `error_reason` render the D-4 vocabulary including the
partial-findings message; the review queue handles agent findings with **no** separate UI path.
**Same commit:** add the missing `pending_count` to `discovery_merge._emit_result_processed_event`
(`:96-101`) — `useDiscoveryStream.js:271-277` already reads it, and many incremental agent findings
make the existing badge drift materially worse.
Green: `npm test`, `pytest tests/services/test_discovery_merge.py --no-cov`.

**Task 28 — CSS for the new BEM classes.**
No new test. Add styles for the `agent-discovery-*` classes this slice introduces **and** for
Slice 3's `agent-probes-*` classes, which ship unstyled today
(`grep -rn 'agent-probes' apps/frontend/src --include=*.css` → nothing).
Green: `npm run lint`, `npm test`.

### Phase F — End-to-end gate (Tasks 29–31)

**Task 29 — Prepare the E2E harness (D-12).**
Pin `agent-net` to `10.88.0.0/24`; relax and parameterize `_agent_network_name`'s exact-set
assertion (`test_agent_e2e.py:462-466`); add a second `probe-net` fixture container brought up
mid-test and a second `cb-agent` service on its own isolated network. All existing e2e tests must
still pass (except the two already red per the baseline).
Green: `cd apps/agent/e2e && pytest -m e2e -k "not update_success"`.

**Task 30 — E2E: zero-configuration discovery, plan §8 steps 1–7.**
One install command, normal approval, no CIDR entry: the agent reports its directly connected test
subnet, the backend creates the system profiles per D-12, an initial scan starts automatically with
observable incremental progress, the fixture lands in the ordinary review queue, importing it
creates exactly one Hardware row, and replaying the findings creates no duplicate result or
Hardware row. Reuse `_backend_sh:1852` and the isolation loop `:1987-2007` to prove the backend
could not have scanned the fixture itself.

**Task 31 — E2E: cancellation, restart, second agent, recurrence — plan §8 steps 8–11.**
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
