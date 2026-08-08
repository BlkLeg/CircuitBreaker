# cbi-agent Slices 1-2 Cohesion Hardening — Task Breakdown

**Date:** 2026-08-06

**Derived from:**
- `plans/2026-08-04-cbi-agent-slice1-gap-closure.md` and
  `plans/2026-08-04-cbi-agent-slice1-gap-closure-tasks.md` (slice 1 architecture + format model)
- `plans/2026-08-04-cbi-agent-slice2-host-telemetry.md` (authoritative slice 2 requirements) and
  `plans/2026-08-04-cbi-agent-slice2-host-telemetry-tasks.md`
- `plans/2026-08-04-cbi-agent-e2e-cohesion-review.md` (cross-slice contracts + release gate)
- `plans/2026-08-04-cbi-agent-slice3-remote-probe.md` and
  `plans/2026-08-04-cbi-agent-slice4-local-discovery.md` (forward-compatibility targets)
- `specs/2026-07-26-cb-agent-design.md`
- the 2026-08-06 slice 1/2 cohesion review (11 numbered issues + 5 minor items)

**Codebase layout:**
- Go agent daemon: `apps/agent/` (`cmd/cb-agent/main.go`,
  `internal/{config,enroll,frame,noiseconn,link,capability,spool,collect,collect/host,status,hostinfo,update,tlsdial}`)
- Backend: `apps/backend/src/app/` (`api/agents.py`, `api/ws_agents.py`, `api/telemetry.py`,
  `services/agent_{registry,link,telemetry,install,update}.py`, `services/telemetry_service.py`,
  `services/intelligence/retention.py`, `workers/telemetry_ingest_worker.py`,
  `schemas/agent_frame.py`, `schemas/agents.py`, `db/models.py`)
- Frontend: `apps/frontend/src/` (`pages/AgentsPage.jsx`, `pages/AgentDetailPage.jsx`,
  `components/agents/AgentApprovalModal.jsx`, `components/map/{CustomNode,TelemetrySidebar}.jsx`,
  `hooks/{useAgentLive,useTelemetryStream}.js`, `api/agents.js`)
- Cross-language wire corpus: `fixtures/agent_frame_corpus.json`, consumed by
  `apps/agent/internal/frame/conformance_test.go` and
  `apps/backend/tests/test_agent_frame_conformance.py`
- Migrations: `apps/backend/migrations/versions/` (alembic; head is `0095_agent_host_telemetry`)
- Docker E2E: `apps/agent/e2e/`

---

## Summary

Slices 1 and 2 are implemented on `dev`, but slice 2 landed as a single 2,443-line commit
(`26372836`) with no collector tests, no backend ingestion tests, no conformance-corpus extension,
and a Hardware projection that duplicates rather than reuses the platform telemetry normalizer.
This plan closes all 11 cohesion-review issues plus 5 minor items in **21 ordered, test-first
tasks** (one commit each, except Task 13 which may split into two as documented there), and must land **before slice 3 begins** because every defect it fixes is a load-bearing
contract slice 3 (`probe.result`) and slice 4 (`discovery.finding`) inherit:

- **The normalizer** (issue 1) becomes the one function `probe.result` projections call, instead of
  a fourth hand-rolled copy.
- **The conformance corpus harness** (issue 3) becomes the gate that makes shipping `probe.result`
  without cross-language fixtures impossible.
- **The collector test seams** (issue 2) are the pattern the probe collector must ship with in its
  first commit — retro-fitting injected clocks/dialers is exactly the debt being paid off here.
- **Readiness semantics** (issue 4) and **per-capability grant isolation** (issue 11) define how a
  new capability reports its own health and survives a sibling's bad config.
- **Bounded spool catch-up** (issue 6) is the release-gate requirement, and probe results are more
  latency-sensitive than telemetry.
- **One capability wire shape** (issues 7, 8) means slice 3/4 grants with real config are a
  non-event for the fleet UI instead of rendering every capability as granted.
- **Bounded history** (issue 10), **spool visibility** (issue 9), and the Agent Detail gaps make
  the slice-2 data actually observable, which is the only way the slice-3 e2e journey can be
  asserted.

Nothing here adds a new capability, frame type beyond an additive heartbeat payload, or slice-3
surface. It is correctness, coverage, and contract consolidation.

---

## Decisions

Every open question from investigation is resolved here. No task body may reopen one.

### D-1. Agent samples keep the direct write path; the normalizer is extracted and shared. (Task 5)

**Decision:** Do **not** publish agent samples to NATS `telemetry.ingest.{hardware_id}`. Extract
`app/services/telemetry_normalize.py` as the single home for platform-metric normalization and
route `write_telemetry`, `telemetry_ingest_worker._build_metric_row`, and the agent projection
through it.

**Rationale:** The slice-2 plan asked for a NATS envelope, but that envelope is unfit without a
rewrite: `telemetry_ingest_worker._process_batch` reads only `{hardware_id, source, payload}`
(`workers/telemetry_ingest_worker.py:112-114`) and stamps `ts = utcnow()` at `:120`, discarding the
supplied collection timestamp; it `bulk_insert_mappings` at `:138` with no upsert, so it cannot
honor `uq_hardware_live_metrics_agent_sample` (`migrations/versions/0095_agent_host_telemetry.py:107-111`).
A NATS hop also cannot replace the direct path — `ingest_host_sample` must persist
`AgentHostSample` synchronously inside the `/link` handler's session (`services/agent_link.py:98`)
to get replay idempotency from `uq_agent_host_sample` (`db/models.py:444`), so publishing the
projection separately splits one transaction into two and opens a duplicate window. NATS is
optional by design anyway (`workers/telemetry_collector.py:165-201` already falls back to
`write_telemetry`), so a correct direct path is mandatory regardless; making it the only path
removes a failure mode. The actual defect in issue 1 is duplicated normalization, not transport.
Slices 3 and 4 reference `telemetry.ingest.*` nowhere.

### D-2. History honors the plan's per-range bucket widths with per-range caps, not a universal 120. (Task 7)

**Decision:** `_HISTORY_BUCKET_SECONDS = {1h: 30, 6h: 60, 24h: 300, 7d: 1800, 30d: 3600}` and
`_HISTORY_MAX_POINTS = {1h: 120, 6h: 360, 24h: 288, 7d: 336, 30d: 720}` (each = duration / width),
enforced by a SQL `LIMIT`.

**Rationale:** The slice-2 plan (`plans/2026-08-04-cbi-agent-slice2-host-telemetry.md:183-188`) is
internally inconsistent — its stated widths yield 360/288/336/720 points, all above 120. The
current code resolves that by applying a universal 120 cap on top
(`api/agents.py:364-368`), which decimates via `points[round(i * last / 119)]` and throws away most
of what it computed. Reading "1 hour: raw, at most 120 points" as a 30 s grain makes it literally
raw at the default `interval_s: 30` cadence and averaging (not dropping) at faster cadences.
Largest response is 720 points × 8 floats ≈ 60 KB, and every range is hard-bounded by `LIMIT`.

### D-3. `projection_attempts` and `ix_agent_host_samples_projection` are dropped, not implemented. (Task 8)

**Decision:** Drop the column (`db/models.py:441`) and the index (`db/models.py:446`). Keep
`projected_at` — it is read at `api/agents.py:66`.

**Rationale:** The column supports an asynchronous projection retry worker that was never built and
is not needed: projection happens in the *same transaction* as the sample insert
(`services/agent_telemetry.py:117-119` inserts, `:129-161` projects, `:162` is the single commit),
so a persisted-but-unprojected row cannot exist and there is nothing to count. No query anywhere
filters on `projected_at`, so its index is write amplification on a hypertable for zero read
benefit. Reintroduction is trivial and belongs in the same migration as the worker that reads it —
never ahead of it. Slice 3 routes probe results into the existing monitor state pipeline
(`plans/2026-08-04-cbi-agent-slice3-remote-probe.md:332,478`), not a deferred projection.

### D-4. Revoked/disabled host telemetry reports `disabled` readiness rows; rows are never deleted. (Task 11)

**Decision:** On capability disable, publish one `frame.Readiness{State: "disabled"}` per name in
`host.CollectorNames`.

**Rationale:** `ingest_readiness` only ever upserts (`services/agent_telemetry.py:209-217`); there
is no delete path and adding one needs a new backend contract and frame semantic. `disabled` is
already in the accepted set (`services/agent_telemetry.py:207`) and is already what the collector
emits for an individually-disabled probe (`internal/collect/host/host.go:64,84,94`), so the UI
needs no new case. This fixes issue 4's stale-"Live" symptom with zero backend change. Note
`TYPE_CAPABILITY_READINESS` is deliberately absent from `CAPABILITY_FOR_TYPE`
(`services/agent_link.py:62-66`), so an agent whose grant was just revoked can still report its own
shutdown.

### D-5. Spool catch-up is a paced per-connection burst over a peek/commit spool. (Task 13)

**Decision:** Delete `spool.DrainInterleaveRatio`. Add a `drainTicker` arm to `runOnce`'s select
loop at 100 ms, budgeted `drainFramesPerTick = 4` / `drainBytesPerTick = 256 KiB`
(≤40 frames/s, ≤2.5 MiB/s), reading from a `Peek`/`Commit` spool with a head pointer.

**Rationale:** Numbers: a 1-hour 30 s-cadence outage (120 frames) catches up in ~3 s; 24 hours
(2,880 frames) in ~72 s; a completely full 64 MiB spool in under 3 minutes — bounded, which is what
the release gate requires. Rejected: (a) drain-until-empty on connect — unbounded; a fleet
reconnecting after a backend outage delivers up to 64 MiB per agent at once; (b) a larger fixed
interleave ratio — still gated on live-send frequency, so a disabled or failing collector never
drains at all, and probe results are bursty rather than periodic; (c) an adaptive ratio — same
gating flaw plus a tuning surface with no stopping rule; (d) a dedicated drain goroutine — not
possible, gorilla/websocket forbids concurrent writers and `seq` (`internal/link/link.go:473`) is
owned by the select loop. Commit-after-send makes delivery at-least-once, which is safe: the
backend dedupes on `(agent_id, sample_id, collected_at)` (`services/agent_telemetry.py:120-128`)
and guards the live projection with `collected_at >= hardware.telemetry_last_polled` (`:153-160`).

### D-6. An invalid capability config honors the server's `enabled` flag and reports `degraded`. (Task 12)

**Decision:** Per-capability isolation. A bare bool is always applied. A config that fails
normalization records a `GrantFault`, **keeps the server's `enabled` flag**, and carries over the
previous valid config for that capability (falling back to the package default if there is none).
A structurally broken grant object is installed fail-closed as `Grant{Enabled: false}`. Faults are
reported as `capability.<name>` = `degraded` via `capability.readiness`.

**Rationale:** `degraded` not `unavailable` because the capability *is* running, just not with the
requested configuration. Rejected: treating an invalid config as a disable — that takes a monitored
host dark over a typo in a cadence field and is indistinguishable in the UI from a deliberate
revocation. Also rejected: a `capability.violation` frame — the type exists (`internal/frame/frame.go:47`,
`schemas/agent_frame.py:21`) but has no handler in `_HANDLERS` (`services/agent_link.py:220-228`),
so it would require a backend change for no gain over readiness.

### D-7. Filesystem usage is injected as an exported func field, not an interface. (Task 1)

**Decision:** `Usage func(path string) (FSUsage, error)` on `host.Collector`, with a nil-fallback
accessor, mirroring the existing `Now func() time.Time` field (`internal/collect/host/host.go:31`).

**Rationale:** Smallest diff, no new abstraction in the package, and it mirrors the injection style
slice 3's probe collector needs for its dialer/resolver/HTTP client. A full `fs.FS` + statfs
interface would also let the `/proc` readers move to `fstest.MapFS`, but `Collector.Root` already
solves that and the churn would touch every probe.

### D-8. Corpus type coverage is enforced with a shrinking allow-list. (Task 3)

**Decision:** Both suites fail on any declared frame type that is neither in the corpus nor in an
explicit `pendingCorpusTypes` allow-list, seeded with exactly **six** entries: `probe.assign`,
`probe.result`, `discovery.request`, `discovery.finding`, `update`, `uninstall`. Both suites also
assert that **every** `pendingCorpusTypes` entry *is* a currently declared type, so a typo or a
stale entry fails loudly instead of silently disabling enforcement.

Python is the authoritative exhaustiveness check: it enumerates the module's `TYPE_*` attributes at
runtime, so a new constant cannot escape it. Go cannot enumerate untyped string constants at
runtime, so the Go half iterates a package-level `allFrameTypes` slice declared **next to** the
constants in `internal/frame/frame.go`, and asserts every element is non-empty. Treat the Go half as
a fast local signal and the Python half as the gate.

**Rationale:** Strict coverage would red the suite immediately for types that legitimately have no
wire fixture yet, and a red baseline gets suppressed rather than fixed. An allow-list makes every
future uncovered type a visible, reviewable edit and gives slice 3 a concrete definition of done:
**delete `probe.assign` and `probe.result`**. `probe.cancel` is deliberately **not** seeded — it is
not a declared constant in either language today (`internal/frame/frame.go:43-76` declares
`TypeProbeAssign` and no `TypeProbeCancel`; `schemas/agent_frame.py:16-45` likewise), and slice 3
introduces it (`plans/2026-08-04-cbi-agent-slice3-remote-probe.md:203`). Pre-exempting the one new
type slice 3 adds is exactly the failure mode this decision exists to prevent, so slice 3 must ship
`probe.cancel` with a fixture in the same commit as its constant.

### D-9. `ingest_readiness` is **made** all-or-nothing by a pre-validation pass. (Task 4)

**Decision:** A `capability.readiness` payload containing any invalid state must persist nothing.
This property **does not exist today; this plan creates it.** Task 4 adds a first pass over
`report.readiness` validating every `item.state` against `{ready, degraded, unavailable, disabled}`
**before** any `db.get` / `db.add` / attribute write, so the raise happens ahead of every mutation.
Document it in the function docstring and pin it with two tests — one calling `ingest_readiness`
directly, one driving it through `dispatch_frame` so the caller's commit is covered.

**Rationale:** Today a payload whose *second* entry is invalid **does** persist the first.
`ingest_readiness` (`services/agent_telemetry.py:206-217`) mutates and `db.add`s each row as it
iterates and raises on the bad item with no rollback; the caller `_handle_readiness`
(`services/agent_link.py:108-113`) catches `InvalidHostTelemetry`, calls `record_event`, and then
`db.commit()` at `:113` — committing the partially applied rows. Even a direct-call unit test would
observe them: `tests/conftest.py:130` builds `Session(bind=connection, ...)` with SQLAlchemy's
default `autoflush=True`, so the follow-up SELECT flushes the pending rows. A pre-validation pass is
chosen over `db.rollback()` in the caller's `except` block because it also holds for direct callers
and does not discard the caller's other pending work. This becomes load-bearing in slice 3, where
probe collectors add entries to the same payload: a partial write would leave stale rows for
collectors the agent *did* report, which is strictly worse than no write.

### D-10. Approving with `capabilities` omitted grants all three capabilities. (Task 14)

**Decision:** `CAPABILITY_DEFINITIONS` sets `default_enabled = True` for `host_telemetry`,
`remote_probe`, and `local_discovery`. The frontend preset is deleted and fetched from
`GET /api/v1/agents/capability-defaults`.

**Rationale:** This resolves issue 8 in favor of the plan documents
(`plans/2026-08-04-cbi-agent-slice1-gap-closure.md:102-108`,
`plans/2026-08-04-cbi-agent-e2e-cohesion-review.md:54-58`), which make the all-three preset
authoritative — so `services/agent_registry.py:31-35` is the side that is wrong, not
`AgentApprovalModal.jsx:14`. Granted-but-idle is the design: `remote_probe` executes nothing until
a monitor is explicitly assigned, `local_discovery` is bounded by the `direct_private` derived
scope, and the approver retains a per-capability opt-out. If security posture is later judged to
override the plan, the correct expression is to change the *plan* and flip `default_enabled` in the
registry — one line, one place — never to reintroduce a divergent frontend constant.

### D-11. `GET /agents/presence` emits the structured grant shape unconditionally — no compatibility flag. (Task 15)

**Decision:** `AgentPresenceRead.capabilities` becomes `dict[str, CapabilityGrant]`. No
`?capability_shape=bool` escape hatch.

**Rationale:** The endpoint has exactly two in-repo consumers (`AgentsPage.jsx:159`,
`AgentDetailPage.jsx:143-148`), but only `AgentsPage.jsx` reads `presence.capabilities`, so only it
is migrated; the detail page uses presence solely for `online`, `connected_since` and `hardware`,
and every capability read there already routes through `normalizeCapability` on
`agent.capabilities` from `getAgent` (`AgentDetailPage.jsx:211,233,320,326,336,349`).
`AgentPresenceRead.capabilities`
was already typed as the `bool | CapabilityGrant` union, so clients were already told to expect
either shape. A flag would have to be threaded through the bulk query and would give slice 3/4 a
live boolean code path to accidentally depend on — precisely the defect. The compatibility
obligation that genuinely exists is on **input** (`ApproveRequest`, `CapabilitiesUpdateRequest`
keep the union) and is preserved unchanged, as is the agent-facing downgrade in
`api/ws_agents.py:291-297` for `capability_schema < 2`.

### D-12. Live spool depth rides the existing `heartbeat` payload; `hello` carries the at-connect value. (Task 16)

**Decision:** Add `HeartbeatPayload{spool_depth, spool_bytes}` (both optional-with-default on the
Python side) rather than a new frame type. `hello.spool_depth` is stamped from `Options.Spool` in
`internal/link`, not in `hostinfo`.

**The Go heartbeat fields carry no `omitempty`.** A current agent always emits
`{"spool_depth":N,"spool_bytes":M}` — including `{"spool_depth":0,"spool_bytes":0}` once the backlog
clears — so an empty `{}` payload unambiguously means "this agent predates the change". Both
`_handle_heartbeat` and `update_hello_metadata` gate `record_spool_stats` on
`"spool_depth" in payload.model_fields_set`, honoring `update_hello_metadata`'s documented
presence-not-truthiness rule (`services/agent_registry.py:248-257`). `HelloPayload.SpoolDepth`
**keeps** its `omitempty` (`internal/frame/frame.go:148`) — hello is the at-connect snapshot; the
heartbeat is what clears the indicator. Without this split the two required behaviors are mutually
exclusive: with `omitempty` on the heartbeat, "old agent sends `{}`" and "current agent with an
empty spool sends `{}`" are byte-identical, so either the columns can never return to 0 (the
indicator never clears) or the old-agent path writes 0 into columns that must stay NULL.

**Rationale:** Hello-only is insufficient by construction — the backlog exists precisely *while
connected and draining*, and a stable link may not reconnect for days, so a hello-only value would
pin a stale depth on screen for the whole catch-up window and never clear. The heartbeat already
runs at a fixed 20 s (`internal/link/link.go:29`, `api/ws_agents.py:61`), already has a server
handler with the `Agent` row in scope (`services/agent_link.py:71-85`), already commits
(`:344`), and currently carries a wasted empty payload. A new frame type would need a
`CAPABILITY_FOR_TYPE` decision, a corpus entry, a handler, and its own timer for a strictly smaller
payload. `hostinfo` stays spool-agnostic because the spool is owned by the link, not by host
collection.

### D-13. The telemetry E2E drives the daemon at `interval_s: 10` and restores 30 at the end. (Task 20)

**Decision:** PUT `interval_s: 10` at the start of the new e2e test; restore `30` before it exits.

**Rationale:** 10 s is the real production minimum (`internal/capability/capability.go:15`), so the
test still exercises a supported configuration. Leaving it at 30 s would push the outage-catch-up
step alone past four minutes and make it the slowest test in the suite. The default-cadence path
stays covered by the Go and backend suites; cadence is pure configuration.

### D-14. The capability registry lives in a new dependency-free `app/services/agent_capabilities.py`. (Task 14)

**Decision:** `CapabilityDefinition`, `CAPABILITY_DEFINITIONS`, and `normalize_grant` live in a new
module `apps/backend/src/app/services/agent_capabilities.py` that imports nothing from `app` beyond
typing/stdlib. `services/agent_registry.py` and `schemas/agents.py` both import it **at module
scope**. There is no conditional fallback and no second copy.

**Rationale:** No import cycle exists to avoid: `agent_registry` imports only
`app.schemas.agent_frame` (`services/agent_registry.py:27`), never `app.schemas.agents`, and
`schemas/agents.py` imports no service module at all (`:1-7`). Putting the registry behind a
function-local import inside a pydantic validator would hide the dependency and leave the registry's
home ambiguous, and Task 15, the "One capability registry" Global Constraint, and slices 3/4 all
reference it by name. A dedicated dependency-free module also keeps the schema layer from importing
a service that touches the DB. `agent_registry` keeps re-exporting `DEFAULT_CAPABILITY_GRANTS` and
`HOST_TELEMETRY_DEFAULT_CONFIG` as derived read-only views so existing importers are unaffected.

---

## Global Constraints

Apply to every task; the task reviewer holds implementers to these.

**Database portability.** The backend is **PostgreSQL-only but TimescaleDB-optional**. There is no
SQLite main database anywhere — `db/session.py:17` states "CB_DB_URL must be set to a
postgresql:// URL; there is no SQLite fallback" and `:23-27` raise on any other prefix;
`db/models.py:20` imports `INET, JSONB` unconditionally. (The cohesion review's release-gate line
"SQLite development/migration tests and PostgreSQL production/E2E tests both pass" is wrong and is
corrected in this plan's Release Gate.) The binding constraint is that `docker-compose.deps.yml:3`
is `postgres:16-alpine` **without** the timescaledb extension while `Dockerfile.mono:140` installs
it, and migrations `0041_telemetry_hypertable.py:70` / `0050_timescaledb_hypertables.py:149`
explicitly bail out via `_has_timescaledb(bind)`. Therefore:
- **Never** use `time_bucket()` in new code (`workers/rollup_worker.py:32` uses it unguarded — do
  not extend that precedent). Use `to_timestamp(floor(extract(epoch from <ts>) / :width) * :width)`,
  which is version-independent. `date_bin()` (PG14+) is acceptable but buys nothing.
- Every new `create_hypertable` call must be guarded by a `_has_timescaledb` helper.
- Every new **per-agent read** against `agent_host_samples` must filter on **both** `agent_id` and a
  `collected_at` range so hypertable chunk exclusion works
  (PK `(id, collected_at)`, `db/models.py:443`; index `ix_agent_host_samples_agent_time`, `:445`).
  **Fleet-wide maintenance passes are exempt from the `agent_id` half**: Task 6's retention
  aggregate groups *by* `agent_id` across all agents and both `DELETE ... WHERE collected_at <
  cutoff` statements are fleet-wide by design. They still carry a `collected_at` predicate, so chunk
  exclusion applies.

**One normalizer.** After Task 5 there is exactly **one** function mapping a normalized platform
telemetry dict onto `HardwareLiveMetric` columns. Today that logic is triplicated:
`services/telemetry_service.py:241-248`, `workers/telemetry_ingest_worker.py:83-96`,
`services/agent_telemetry.py:131-150`. Slice 3's `probe.result` and slice 4's `discovery.finding`
projections **must** import it, never add a fourth copy.

**Canonical capability wire shape.** Every REST *response* carrying grants emits
`{name: {enabled: bool, config: object}}` with server-normalized config — never a bare boolean.
Every REST *request* keeps accepting `bool | CapabilityGrant` per capability, indefinitely. The
agent wire protocol is unaffected: `api/ws_agents.py:291-297` keeps downgrading to booleans for
`capability_schema < 2`. `agent_registry.grants_dict` (bool-valued) stays — it is an internal
enforcement lookup used only by `services/agent_link.py:331`, not a wire shape.

**One capability registry.** A single `CAPABILITY_DEFINITIONS` table in
`app/services/agent_capabilities.py` (Task 14, **D-14**) replaces `DEFAULT_CAPABILITY_GRANTS`,
`HOST_TELEMETRY_DEFAULT_CONFIG`, the three `if capability == "host_telemetry"` special cases,
`schemas/agents.py`'s `HOST_TELEMETRY_DEFAULTS`, and **both** frontend copies —
`AgentApprovalModal.jsx`'s `NORMAL_PRESET` **and** `AgentDetailPage.jsx`'s `HOST_DEFAULTS`, both of
which Task 14 deletes in favour of `GET /api/v1/agents/capability-defaults`. Its Go mirror is the
`configNormalizers` registry (Task 12). **Slices 3 and 4 add exactly one entry to each and touch
nothing else.**

**Upgrades never silently enable a new capability on an already-approved agent**
(`plans/2026-08-04-cbi-agent-slice1-gap-closure.md:107-108`;
`plans/2026-08-04-cbi-agent-e2e-cohesion-review.md:56-58`). `default_enabled` is consulted **only**
by `approve_agent`. A capability with no `agent_capability_grants` row is denied everywhere. No
migration may backfill grant rows; no read path may fall back to `default_enabled`. Pinned by a
regression test in Task 14 that must never be deleted.

**Readiness vocabulary is exactly `{ready, degraded, unavailable, disabled}`.**
`services/agent_telemetry.py:207` is the authority; anything else raises `InvalidHostTelemetry` and
is recorded as a `protocol_violation` (`services/agent_link.py:108-113`). Slice 3 probe collectors
and slice 4 discovery collectors reuse these four and nothing else. `capability.readiness` is the
**only** ingest path — `hello.readiness` is parsed but never persisted — and it only upserts, so a
row the UI should stop showing must be actively overwritten.

**Collector contract.** `collect.Collector.Collect` must populate `Result.Readiness` for every
collector it owns **even when it returns a non-nil error**. An empty `Readiness` alongside an error
means "no information" (context cancellation) and must not be reported. Documented on the interface
(`internal/collect/collect.go:16-18`), inherited by slice 3/4 collectors.

**One websocket writer.** gorilla/websocket forbids concurrent writers and the `seq` counter
(`internal/link/link.go:473`) is owned by `runOnce`'s select loop. Anything slices 3/4 add to the
outbound path — including any catch-up or retry pump — must be an arm of that select, never a side
goroutine.

**The spool is payload-agnostic.** `frame.IsDataFrame` is a deny-list
(`internal/frame/frame.go:104-110`), so `telemetry.host`, `probe.result`, and `discovery.finding`
share it with no code change. The catch-up scheduler must stay payload-agnostic — no
telemetry-specific special-casing.

**Test hygiene.**
- The Go suite runs under `go test -race ./...`. `apps/agent/Makefile` has no `test` target today;
  Task 10 adds one and wires it into CI. Issue 5's race is only provable under `-race`.
- No test may read the real `/proc`, `/sys`, host filesystem, Docker daemon, or network.
  `Collector.Root`, `Collector.Now`, and the new `Collector.Usage` are the injection pattern.
- Backend telemetry tests must monkeypatch `app.services.agent_telemetry.get_redis`,
  `.cache_telemetry`, and `.publish_telemetry` — these are module-level imports
  (`services/agent_telemetry.py:16,26`), so patching `app.core.redis.get_redis` will **not**
  intercept them.
- `apps/backend/tests/factories.py` gains `agent_host_sample`, `agent_capability_readiness`,
  `agent_host_sample_hourly`, and `hardware_live_metric` in Task 4; every later backend task builds
  on those rather than hand-rolling ORM rows.
- `fixtures/agent_frame_corpus.json` is append-only — reordering or editing an existing entry
  changes parametrized test ids used in CI history.

**Repo conventions.** Go follows `apps/agent`'s existing package/error/table-driven test style;
Python follows the existing service/router/schema layering and alembic conventions; frontend
follows existing component/hook/RTL patterns. Each task is one focused commit; do not bundle.

---

## Ordered Implementation Tasks

Ordering rationale: shared foundations first (collector test seams → conformance corpus → backend
test factories/matrix), then the backend data-path fixes that the normalizer unlocks, then the Go
runtime fixes that the collector seams unlock, then the API/UI contract work, then E2E, then the
gate.

---

### Task 1: Add a filesystem-usage seam to the host collector and cover every `/proc` and `/sys` probe with deterministic fixtures

**Closes:** issue 2 (collector half)

**Current state:** `apps/agent/internal/collect/host/` contains `host.go` (371 lines) and
`docker.go` (129 lines) and **zero** `_test.go` files. (The review's "the slice-2 core has no
tests" is imprecise: `internal/collect/payload_test.go` does exist, 48 lines, covering `Rate`,
`EncodeBounded` truncation, and `SampleID`. What has no tests is `collect/host/` and the `Runner`
in `collect.go:22-81`.) `Collector` already exposes `Root`, `Config`, and `Now`
(`host.go:28-34`) and every read is rooted through `c.path` (`host.go:39-41`): `/proc/stat`
(`:115`), `/proc/loadavg` (`:161`), `/proc/meminfo` (`:169`), `/proc/uptime` (`:197`),
`/proc/self/mounts` (`:207`), `/proc/diskstats` (`:241`), `/proc/net/dev` (`:277`),
`/sys/class/net/<n>/{operstate,speed}` (`:295,:308`), and the thermal globs (`:334-336`). The one
non-injectable dependency is `host.go:218-221`, which calls `syscall.Statfs(c.path(mountpoint))` —
the path is rooted but `Blocks/Bavail/Bfree/Bsize` come from the real filesystem backing the temp
dir, making `total_bytes/used_bytes/available_bytes/used_pct` and `Summary.RootDiskPct`
(`:222-231`) host-dependent and untestable. `New(config)` (`:36-38`) sets `Root` and `Now`, but a
struct literal leaves `Now` nil, which panics at `:52`.

**Required changes:**
- Add `type FSUsage struct { TotalBytes, FreeBytes, AvailBytes uint64 }` and a
  `Usage func(path string) (FSUsage, error)` field on `Collector`; add package-level
  `statfsUsage(path)` wrapping `syscall.Statfs` and set `Usage: statfsUsage` in `New`.
- Add unexported `c.usage(path)` and `c.now()` accessors with nil-fallbacks to `statfsUsage` /
  `time.Now`. Rewrite `filesystems` (`host.go:206-235`) to call `c.usage(c.path(x[1]))` computing
  `total = u.TotalBytes`, `avail = u.AvailBytes`, `used = u.TotalBytes - u.FreeBytes` — **arithmetic
  must stay byte-identical** or `root_disk_pct` shifts under Task 5. Rewrite `Collect` (`:52`) to
  call `c.now()`.
- Add `apps/agent/internal/collect/host/host_test.go` with
  `writeTree(t, root, map[string]string)` (MkdirAll parents, 0644 files under `t.TempDir()`) and
  `newTestCollector(t, cfg, files)` returning a `Collector` with `Root` set, a settable clock in
  `Now`, and `Usage` stubbed from a `map[string]FSUsage`. **No committed `testdata/` tree** —
  permission-denied and socket cases cannot be represented in git.
- Baseline fixture content (reused across cases): `/proc/stat` = `cpu  100 20 30 400 50 0 0 0 0 0`
  plus `cpu0`/`cpu1` lines plus `intr 1`/`ctxt 1`/`btime 1750000000`; `/proc/loadavg` =
  `0.50 1.25 2.00 1/234 5678`; `/proc/meminfo` MemTotal 16000000 kB / MemFree 2000000 kB /
  MemAvailable 8000000 kB / SwapTotal 4000000 kB / SwapFree 3000000 kB; `/proc/uptime` =
  `123456.78 987654.32`; `/proc/self/mounts` with **four fields on every line** —
  `/dev/sda1 / ext4 rw,relatime`, `proc /proc proc rw,nosuid`, `tmpfs /run tmpfs rw,nosuid`,
  `overlay /var/lib/docker/o overlay rw,relatime`, `/dev/sdb1 /mnt/data ext4 ro,relatime` — plus one
  deliberately short line `badline / ext4`. `filesystems` (`host.go:206-235`) evaluates
  `len(x) < 4` **before** consulting `pseudoFS[x[2]]` (`:215`), so three-field pseudo-FS rows would
  be dropped by the arity guard and the `pseudoFS` map (`:204`) would never be exercised — the
  exclusion test would pass against a build with `pseudoFS` deleted entirely. The short line covers
  the arity guard separately;
  `/proc/diskstats` 14-field rows for sda, sdb, loop0, ram0, dm-0; `/proc/net/dev` two header lines
  plus eth0, lo, veth1234, docker0, br-abc, wlan0; `/sys/class/net/{eth0,veth1234,docker0,br-abc}/operstate`
  = `up`, `wlan0/operstate` = `down`, `eth0/speed` = `1000`;
  `/sys/class/thermal/thermal_zone0/temp` = `45000`;
  `/sys/class/hwmon/hwmon0/{temp1_input,temp1_max,temp1_crit}` = `61000`/`85000`/`100000`.

**Tests** (all new; the package has none today):
- `TestFilesystems_UsesInjectedUsageForByteMath` — asserts `/`'s byte fields derive solely from the
  stubbed `FSUsage`. **Fails to compile against today's code**, which is the point: before the seam
  the only writable version asserts whatever the CI host's `/tmp` reports.
- `TestFilesystems_StatfsErrorSkipsOnlyThatMount` — stub `Usage` to error for `/mnt/data`; assert
  `/` survives. Unwritable today, proving the seam is required not cosmetic.
- `TestCore_*`: first sample omits `Summary.CPUPct` while setting `MemTotalBytes=16000000*1024`,
  `MemAvailableBytes=8000000*1024`, `MemUsedBytes=8000000*1024`, `MemPct=50`, `SwapPct=25`,
  `Load1/5/15=0.5/1.25/2.0`, `UptimeS=123456.78`, `BootTimeUnixS=1750000000`, `LogicalCPUs=2`;
  second sample at totals 1600 / idle 950 yields `CPUPct == 50`; **decreasing** totals leave
  `CPUPct` nil with no error (`host.go:154`); missing/unreadable (`chmod 0000`, `t.Skip` when
  `os.Geteuid()==0`)/malformed `/proc/stat` and missing `/proc/meminfo` return an error wrapping
  `"host core"`; missing `/proc/loadavg` and `/proc/uptime` are **not** errors.
- `TestFilesystems_*`: proc/sysfs/tmpfs/overlay excluded **via `pseudoFS`, not via the arity
  guard** (all four fixture lines carry four fields); the 3-field `badline / ext4` row is skipped by
  the arity guard, asserted as its own case; sda1/sdb1 included; `/`'s `used_pct`
  copied to `Summary.RootDiskPct`; `ro,relatime` → `read_only true`; `TotalBytes 0` omits
  `used_pct` and leaves `RootDiskPct` nil; two `/` rows — last wins (pin current behavior);
  missing `/proc/self/mounts` → `{host.filesystems, unavailable}` + `Payload.Status "degraded"`
  while `host.core` stays `ready`; `IncludeFilesystems=false` → `disabled` + empty slice.
- `TestDisks_*`: first sample emits `read_bytes = sectors*512` with no `*_bps`; second sample 10 s
  later emits exact rates; loop0/ram0/dm-0 gated by `IncludeVirtual`; device disappearing/appearing
  between samples; decreasing counters omit both rate keys; <14-field rows skipped; missing
  `/proc/diskstats` → unavailable + degraded; `IncludeDisks=false` → disabled.
- `TestNetwork_*`: `lo` always excluded even with `IncludeVirtual=true` (`host.go:292`);
  veth/docker0/br-abc gated by `IncludeVirtual`; `wlan0` (operstate `down`) excluded entirely; an
  interface whose operstate file is **absent is included with `"state": ""`** (`host.go:295-299`
  ignores the read error and skips only on exactly `"down"` — pin this, the review's "down
  interfaces" shorthand understates the matrix); `speed` absent or `-1` omits the key; first sample
  emits no per-interface or `Summary.Net*BPS`; second sample emits both, summed over **included**
  interfaces only; full counter reset drops per-interface rates but still emits `Summary.Net*BPS`
  as 0 (pin); `rx_errors`/`tx_errors` from post-colon fields 2 and 10.
- `TestThermal_*`: both sensors yield exactly `thermal_zone0/temp` (45.0) and `hwmon0/temp1` (61.0,
  warning 85.0, critical 100.0) with `Summary.MaxTempC = 61.0`; **no sensors → `{host.thermal,
  unavailable, "no temperature sensors found"}` with `Payload.Status` still `"healthy"`** —
  `host.go:77-85` deliberately sets no `p.Status`, unlike `optional()` (`:68`) and the Docker branch
  (`:89`), matching slice-2 Task 7; this is pinned, not "fixed"; unreadable/non-numeric temp files
  are skipped while siblings collect; `IncludeTemperatures=false` → disabled + nil `MaxTempC`.
- `TestCollect_ReadinessCoversEveryCollector` — a single `Collect` always returns exactly six
  entries in order `host.core, host.filesystems, host.disks, host.network, host.thermal,
  host.docker` (`host.go:61-95`), every state in the allowed set. **This is the invariant slice 3
  extends rather than replaces.**

**Depends on:** none. Lands first — Task 9 needs `TestCore_*` fixtures to write its failing test
against, and Task 5 needs a trustworthy collector to reason about.

---

### Task 2: Cover the Docker collector against a fake socket and the `collect.Runner` scheduling loop

**Closes:** issue 2 (Docker + Runner half)

**Current state:** `docker.go` has no tests. `docker()` (`:80-128`) resolves the socket through
`c.path("/var/run/docker.sock")` (`:81`) — it does **not** bypass `Collector.Root`, so a
`net.Listen("unix", <root>/var/run/docker.sock)` fixture is sufficient and no new seam is needed.
It builds a 5 s-timeout client over a unix `DialContext` (`:82-85`), derives an 8 s `statsCtx`
(`:86`) but issues the container-list request with the parent ctx (`:88`), maps dial failure to
`"open Docker socket: %w"` (`:94`), non-200 to `"Docker API returned %s"` (`:98`), decode failure to
`"decode Docker response: %w"` (`:102`), truncates above 100 containers and sets `Payload.Status
"degraded"` (`:104-107,124-127`), and calls `dockerStatsSummary` only for `State=="running"`
(`:117-120`). `dockerStatsSummary` (`:47-78`) swallows every error to nil and emits `cpu_pct` only
when `total >= pre-total`, `system > pre-system`, and `online_cpus > 0` (`:68-70`).
`apps/agent/internal/collect/` has **no** `collect_test.go`: the `Runner` (`collect.go:22-81`) —
immediate first tick via `NewTimer(0)` (`:53`), `collectedAt` captured *before* `Collect` (`:60`),
the `host.payload/degraded` append (`:66-68`), `OnReadiness` only on success (`:69-71`), frame
emitted with `TS = collectedAt` (`:73`) — is entirely uncovered.

**Required changes:**
- Add `apps/agent/internal/collect/host/docker_test.go` with
  `startFakeDocker(t, root, http.Handler)` that MkdirAll's `<root>/var/run`,
  `net.Listen("unix", <root>/var/run/docker.sock)`, serves in a goroutine, and `t.Cleanup`s a
  `Shutdown`. Route `/v1.41/containers/json` and `/v1.41/containers/{id}/stats` through an
  `http.ServeMux` so canned bodies are explicit.
- Add `apps/agent/internal/collect/collect_test.go` with a `fakeCollector` implementing
  `collect.Collector`, configurable to return a canned `Result`, an error, to block on `ctx.Done`,
  or to record concurrency via atomic counters. **Task 9 consumes this type** — build it here.

**Tests:**
- `TestDocker_SocketAbsentReportsUnavailableWithRemediation` — asserts state `unavailable`, reason
  containing `"open Docker socket"`, and the exact remediation string `"rerun the installer and
  verify membership in the docker group"` plus `Payload.Status "degraded"` (`host.go:87-89`). This
  is the only user-facing instruction for the most common Docker failure and is unpinned today.
- `TestDocker_SocketUnreadable` (`chmod 0000`, `t.Skip` when euid==0) takes the same branch;
  `IncludeDocker=false` → `{host.docker, disabled}` and nil `Payload.Docker` (`host.go:93-95`).
- `TestDocker_ApiErrorBranches` — 500 → `"Docker API returned 500 Internal Server Error"`;
  `{not json` → reason containing `"decode Docker response"`.
- `TestDocker_MoreThanOneHundredContainersTruncatesAndDegrades` — 150 containers → `len(containers)
  == 100`, `total 100`, `truncated true`, status `degraded`. Nothing today stops a refactor
  dropping the degraded flag, which is the only signal the list is incomplete.
- `TestDocker_StatsFailureLeavesContainerWithoutStatsAndDoesNotDegrade` — stats 500 or malformed
  leaves id/name/image/state/status present, no `memory_used_bytes`, readiness unchanged
  (`docker.go:52-63`).
- `TestDocker_CPUPercentMatchesDockerFormula` — canned body (total 200000000, precpu 100000000,
  system 2000000000, presystem 1000000000, online_cpus 4, mem 512MiB/1024MiB, two networks) →
  `cpu_pct 40`, `memory_pct 50`, exact `memory_used_bytes`/limit, `network_rx_bytes`/`tx_bytes`
  summed; `online_cpus 0` omits `cpu_pct`; `"Names": []` → name `""` (`docker.go:111-114`).
- Context cases: ctx cancelled before `Collect` returns `ctx.Err()` from `host.go:45-47` with **no**
  readiness; ctx cancelled mid-response takes the `open Docker socket` branch without hanging.
- `TestRunner_EmittedFrameCarriesCollectionTimestamp` — `frame.TS` equals the clock at collection
  start, not send time. **This is the contract the backend's `collected_at` window check
  (`services/agent_telemetry.py:75-81`) and the whole spool catch-up story depend on**, proven
  nowhere today.
- `TestRunner_FirstCollectionIsImmediate`, `TestRunner_ResetWithNewIntervalStopsPriorGoroutine`,
  `TestRunner_DoesNotOverlapCollections` (atomic max-concurrency == 1 with a collector slower than
  the interval — slice-2 Task 4 requires skipping, not queueing, and slice 3's probe runner is
  built on this same Runner), `TestRunner_StopCancelsInFlightCollect`,
  `TestRunner_NilOnReadinessDoesNotPanic`, `TestRunner_TruncationAppendsDegradedPayloadReadiness`
  (`collect.go:64-68`), `TestRunner_SchemaZeroEncodeFailureEmitsNoFrame` (`payload.go:38-40`) —
  **scoped to the frame channel only**: assert nothing reaches `out`, and do **not** assert anything
  about `OnReadiness`, which Task 9 changes to fire on this path.
- **Explicitly out of scope, owned by Task 9:** any assertion about the `OnReadiness` callback on
  either failure path — a `Collect` *error* **or** an `EncodeBounded` failure. Both currently emit
  nothing (`collect.go:62,65`) and Task 9 makes both emit `unavailable`. Add a comment in
  `collect_test.go` naming Task 9 on each so the two tasks do not race to write the same test and
  Task 9 does not silently break a test it never listed.

**Depends on:** Task 1 (reuses `writeTree`/`newTestCollector`).

---

### Task 3: Extend the cross-language frame corpus and make type coverage self-enforcing

**Closes:** issue 3

**Current state:** `fixtures/agent_frame_corpus.json` holds 21 entries covering hello, heartbeat,
hello.ack, capabilities.set, capability.violation, ping, log, disconnect, update.status,
transport.rekey, key.rotate. It has **no** `telemetry.host` entry, **no** `capability.readiness`
entry, **no** hello carrying `capability_schema`, and **no** `{enabled, config}` grant — both the
hello.ack grants (corpus line 58) and the capabilities.set payload (line 74) are bare booleans.
`apps/agent/internal/frame/conformance_test.go:69-90` switches on hello, hello.ack,
transport.rekey, key.rotate, update.status only; `apps/backend/tests/test_agent_frame_conformance.py:25-31`
mirrors exactly that set. Both typed models exist and are unexercised: `internal/frame/frame.go:166-201`
(`CapabilityReadinessPayload`, `HostSummary`, `HostTelemetryPayload`), `:129-132` (`CapabilityGrant`,
referenced nowhere), `schemas/agent_frame.py:111-124`. The agent advertises `capability_schema: 2`
(`internal/hostinfo/hostinfo.go:43`) and the server branches on it at `api/ws_agents.py:291-297`,
reading it from the hello at `:556` — none of that negotiation is in the corpus. Python's
`HelloPayload.capability_schema` defaults to 1 (`schemas/agent_frame.py:92`) while Go's zero value
is 0 (`frame.go:149`) — an asymmetry nothing pins.

**Required changes:**
- Add corpus entries (append-only): (1) `telemetry.host — full sample, schema 1, healthy` with a
  32-lowercase-hex `sample_id`, all 18 `HostSummary` keys numeric, one `filesystems` entry
  (`device, mountpoint, fs_type, total_bytes, used_bytes, available_bytes, read_only, used_pct`),
  one `disks` entry, one `interfaces` entry, one `temperatures` entry, and a `docker` object
  (`containers, total, running, truncated`) — field names copied verbatim from `host.go:225,262,307,350`
  and `docker.go:115,124` so the corpus is the schema of record; (2) `telemetry.host — core-only
  degraded sample` (status `degraded`, summary limited to `cpu_pct`/`mem_pct`, empty lists, null
  docker); (3) `telemetry.host — truncated docker list`; (4) `capability.readiness — all four
  states` with the `unavailable` entry carrying `reason`, `remediation`, and a non-empty `missing`
  array; (5) `capability.readiness — empty readiness list`; (6) `hello — schema-2 negotiation`
  (`capability_schema: 2`, non-zero `spool_depth`, readiness array); (7) `hello.ack — structured
  {enabled, config} grants for a schema-2 agent`; (8) `capabilities.set — structured grants with
  host_telemetry config`; (9) `capabilities.set — mixed legacy boolean and structured grants`
  (host_telemetry as object, remote_probe as bare `false`) to pin `capability.go:60-78`'s per-key
  fallback.
- Go: extend the typed-decode switch with `TypeTelemetryHost` → `roundTripHostTelemetryPayload` and
  `TypeCapabilityReadiness` → `roundTripCapabilityReadinessPayload`, in the style of
  `roundTripHelloPayload` (`conformance_test.go:92-121`): unmarshal → re-marshal → re-unmarshal →
  compare `Schema`/`SampleID`/`Status`, every `HostSummary` pointer field for **both nilness and
  value**, each list length, and `reflect.DeepEqual` on each list and on `Docker`.
- Go: `TestCorpus_HostTelemetrySampleIDMatchesServerRegex` (`^[0-9a-f]{32}$`, the same expression
  enforced at `services/agent_telemetry.py:28`) and `TestCorpus_HostTelemetrySummaryHasNoNulls`
  (`schemas/agent_frame.py:119` types summary as `dict[str, int | float]` and would reject one).
- Go: `TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate` — for every `capabilities.set` entry
  and every `hello.ack` `capabilities` sub-object, `capability.New(t.TempDir())` +
  `ApplyGrants(payload)`; assert no error, expected `Allowed()` per capability, and for
  host_telemetry the exact `Gate.HostConfig()`. `internal/capability` imports only stdlib, so
  package `frame`'s test file can import it with no cycle. **This makes the corpus exercise the
  real decoder rather than a test-local copy.**
- Python: add `TYPE_TELEMETRY_HOST` → `HostTelemetryPayload` and `TYPE_CAPABILITY_READINESS` →
  `CapabilityReadinessPayload` to `_PAYLOAD_MODEL_FOR_TYPE`. **Leave the harness dumping with plain
  `first.model_dump_json()`** (`tests/test_agent_frame_conformance.py:68`) — switching it to
  `by_alias=True` would make the round-trip pass without the production fix below, so the test would
  no longer prove the defect it exists to catch.
- **Production fix surfaced by the above:** add `model_config = ConfigDict(populate_by_name=True)`
  to `HostTelemetryPayload` (`schemas/agent_frame.py:115-124`). `:116` declares
  `schema_version: int = Field(alias="schema")` with no `populate_by_name`, so
  `model_dump_json()` emits `"schema_version"` and the round-trip re-validation
  (`test_agent_frame_conformance.py:68-69`) raises missing-field for `"schema"` —
  **`HostTelemetryPayload` cannot round-trip at all today.**
- Python: `test_corpus_grant_payloads_are_accepted_in_both_wire_forms` — for every
  `capabilities.set` entry, `ws_agents._wire_grants(structured, capability_schema=1)` collapses to
  booleans and `capability_schema=2` passes through unchanged (`api/ws_agents.py:291-297`); plus
  `test_hello_absent_capability_schema_defaults_to_legacy` asserting
  `HelloPayload.model_validate({}).capability_schema == 1`, with a matching Go assertion that an
  absent field decodes to the zero value and must be **treated as 1** by any consumer — documented
  in both files so the 0-vs-1 asymmetry is deliberate.
- Both sides: `TestCorpus_CoversEveryDeclaredFrameType` /
  `test_corpus_covers_every_declared_frame_type`, failing on any declared type neither in the corpus
  nor in `pendingCorpusTypes`. Seed that list with the **six** entries in **D-8** (**not**
  `probe.cancel`, which is not a declared constant in either language today), with a comment naming
  slice 3 and slice 4 as the tasks that must remove entries.
  - **Python is the authoritative half**: enumerate the module's `TYPE_*` attributes via
    `vars(agent_frame)` so a new constant cannot escape the gate, and assert
    `set(corpus_types) | set(pendingCorpusTypes) == set(TYPE_* values)` — an equality, so a stale
    allow-list entry that is no longer a declared type also fails.
  - **Go cannot enumerate untyped string constants at runtime**, so declare a package-level
    `allFrameTypes []string` **next to the constants in `frame.go`** and iterate that; assert every
    element is non-empty and that every `pendingCorpusTypes` entry appears in `allFrameTypes`. State
    in the test's comment that the Go half is a fast local signal and the Python half is the gate.
- **Do not** add the invalid-`interval_s` grant entry here — it belongs with Task 12, or the shared
  suite lands red.

**Tests:** the above are the tests. The two that fail before their fix:
`test_corpus_typed_payloads_decode_and_round_trip[telemetry.host — full sample]` (pydantic
missing-field for `"schema"`, proving the model defect before the `ConfigDict` fix) and
`TestCorpus_CoversEveryDeclaredFrameType` (red for `telemetry.host` and `capability.readiness`
before the fixtures exist — this is the mechanism that makes slice 3 unable to ship `probe.result`
without fixtures).

**Depends on:** none (independent of Tasks 1-2).

---

### Task 4: Backend agent-telemetry test factories and the ingest/readiness/endpoint test matrix

**Closes:** issue 2 (backend half)

**Current state:** There is no `test_agent_telemetry.py` anywhere under `apps/backend/tests/`.
`services/agent_telemetry.py` (233 lines) is exercised only indirectly:
`tests/services/test_agent_link.py:98-135` dispatches `telemetry.host` frames with payload
`{"cpu": 0.5}`, which fails `validate_host_payload` before reaching any logic, so both tests only
prove the capability gate at `services/agent_link.py:329-338`. `tests/api/test_agents_api.py` (957
lines) never calls `/telemetry` or `/telemetry/history`. `tests/intelligence/test_retention.py` (60
lines) exercises `HardwareLiveMetric` only. `tests/factories.py` has `agent` (146-166),
`agent_capability_grant` (168-181), `agent_event` (183-188) and **no** telemetry factories.
`AgentHostSample` enforces `uq_agent_host_sample` on `(agent_id, sample_id, collected_at)`
(`db/models.py:444`); `HardwareLiveMetric` enforces a unique index on
`(agent_id, agent_sample_id, collected_at)` (`:1845-1851`).

**Required changes:**
- Add to `tests/factories.py`: `agent_host_sample(agent, hardware=None, **kw)` (defaults
  `sample_id=secrets.token_hex(16)`, `collected_at=utcnow()`, `status="healthy"`, minimal valid
  `raw`), `agent_capability_readiness(agent, collector="host.core", state="ready", **kw)`,
  `agent_host_sample_hourly(agent, bucket_at, sample_count, summary)`,
  `hardware_live_metric(hardware, **kw)`.
- Add `tests/services/test_agent_telemetry.py` with a module-level `_payload(**overrides)` helper
  **built from the `fixtures/agent_frame_corpus.json` "telemetry.host — full sample" entry** (not
  hand-rolled), and an autouse fixture monkeypatching
  `app.services.agent_telemetry.{get_redis,cache_telemetry,publish_telemetry}`.
- Add `tests/api/test_agent_telemetry_api.py` for the two viewer endpoints.
- **Production fix required by D-9 — `ingest_readiness` is not all-or-nothing today.** Add a first
  pass over `report.readiness` in `services/agent_telemetry.py:199-217` validating every
  `item.state` against `{ready, degraded, unavailable, disabled}` and raising
  `InvalidHostTelemetry("invalid readiness state")` **before** the mutation loop performs any
  `db.get` / `db.add` / attribute write. Without this the D-9 test below cannot pass: the current
  loop mutates rows and raises on the *second* bad item, and `_handle_readiness`
  (`services/agent_link.py:108-113`) catches the exception, calls `record_event`, then `db.commit()`
  at `:113` — committing the partial write. A direct-call test sees the same rows because
  `tests/conftest.py:130` uses SQLAlchemy's default `autoflush=True`. Record the guarantee in the
  function docstring.

**Tests:**
- `validate_host_payload` branch matrix (`services/agent_telemetry.py:54-82`), one case per
  rejection with the exact `InvalidHostTelemetry` message: >256 KiB compact JSON; missing
  `sample_id`/`status`/`summary`; `schema 2` and `status "unknown"`; `sample_id` of 31/33 chars,
  uppercase hex, non-hex; 129 filesystems / 129 disks / 129 interfaces / 257 temperatures
  (`_LIST_LIMITS`, `:31`); `cpu_pct` 100.1 and -0.1 and each percent field out of 0..100;
  `uptime_s -1`; boundary 0 and 100 **accepted**.
- Summary value types, split because the three cases do **not** behave alike (verified against the
  installed pydantic 2.13):
  - a **string or `null`** summary value fails `HostTelemetryPayload.model_validate` at
    `services/agent_telemetry.py:57-60` and raises `"payload schema is invalid"` — **not**
    `"summary.{name} is not numeric"`. Assert the schema message.
  - a **boolean** summary value is *coerced to `int` 1* by `summary: dict[str, int | float]`
    (`schemas/agent_frame.py:119`) before the loop at `:68-74` ever runs, so
    `isinstance(value, bool)` at `:69` is **unreachable dead code** and `True` is currently
    **accepted as 1**. Pin that as the current behavior with a test named
    `test_boolean_summary_value_is_coerced_to_one_and_accepted`, and add a comment at `:69` stating
    the guard cannot fire. **Do not** "fix" it here — changing it would need a `field_validator` on
    `summary` and is out of scope for a coverage task; the comment plus the pinned test make the
    dead branch visible rather than mistaken for coverage.
- Timestamp window (`:75-81`): +61 s rejected, +59 s accepted, 30 d + 1 min rejected, 29 d accepted,
  naive datetime treated as UTC.
- Agent state and grants: pending/revoked/rejected agent raises `"agent is not active"` and writes
  no row; **`test_ungranted_valid_telemetry_persists_nothing`** — dispatch a *valid* payload with
  `host_telemetry` disabled and assert zero `AgentHostSample` rows **and** one `capability_violation`
  `AgentEvent`; the same frame with the grant enabled persists exactly one row; a missing grant row
  behaves as denied.
- Violation rate limiting (`:41-51`, `services/agent_link.py:96-105`): 5 invalid payloads inside one
  minute produce exactly one `protocol_violation` event whose detail carries the cumulative
  "repeated" count; monkeypatch `time.monotonic` past 60 s → a second event.
- Idempotent replay: identical `(agent_id, sample_id, collected_at)` twice returns the same row id,
  leaves exactly one `AgentHostSample` **and** one `HardwareLiveMetric` (the early return at `:98-99`
  precedes projection) and does not re-stamp `telemetry_last_polled`;
  `test_flush_integrity_error_returns_existing_row` monkeypatches `Session.flush` to raise
  `IntegrityError` once, exercising the rollback-and-reselect path at `:118-128` (the concurrent-writer
  path, never executed today) — restore `flush` in a `finally` or the session is poisoned for
  teardown; a different `sample_id` at the same `collected_at` persists as a second row.
- Unlinked vs linked: `hardware_id None` persists the sample, creates no `HardwareLiveMetric`, leaves
  `projected_at` None, still publishes to `telemetry:agent:{id}` (`:163-176`); a pre-link sample is
  never back-filled after linking.
- `test_older_sample_from_second_agent_does_not_move_hardware_last_polled` — agents A and B on
  hardware H, ingest A at T+10 then B at T+5; `telemetry_last_polled` stays T+10 and B does not
  re-project (`:154-156`), while both `AgentHostSample` and both `HardwareLiveMetric` rows exist with
  correct attribution. Without this, spool catch-up from one agent can rewind a co-located agent.
- `test_uptime_float_persists_into_bigint_column` — `summary.uptime_s = 123456.78` persists into
  `AgentHostSample.uptime_s` and `HardwareLiveMetric.uptime_s` (both BigInteger) rounded. The Go
  collector genuinely emits a float (`host.go:197-199`).
- Readiness (`:199-233`): first report inserts one row per collector and returns `changed True`; an
  identical replay returns `False` and publishes nothing; a changed `reason` alone returns `True`;
  `updated_at` advances on every accepted report; a malformed payload raises
  `"invalid readiness payload"` and records a `protocol_violation` through
  `services/agent_link.py:108-113`.
- **D-9, two tests, both red before the pre-validation pass above:**
  `test_invalid_readiness_state_persists_nothing` calls `ingest_readiness` directly with a payload
  whose **second** entry is invalid and asserts zero `AgentCapabilityReadiness` rows for the first
  collector; `test_invalid_readiness_state_through_dispatch_frame_persists_nothing` drives the same
  payload through `agent_link.dispatch_frame` so the caller's `db.commit()` at
  `services/agent_link.py:113` is covered, asserting zero readiness rows **and** exactly one
  `protocol_violation` `AgentEvent`.
- `test_ingest_readiness_accepts_disabled_state_without_grant` — post `capability.readiness` naming
  `disabled` for an agent whose `host_telemetry` grant is `false`; assert rows update rather than
  reject. **Pins the contract Task 11 depends on** (`services/agent_link.py:62-66` omits
  `TYPE_CAPABILITY_READINESS` from `CAPABILITY_FOR_TYPE`).
- `GET /agents/{id}/telemetry`: 404 unknown agent; 200 with `latest None`/`readiness []` for an agent
  with no samples; newest-by-`collected_at` with the eight `_sample_json` summary keys
  (`api/agents.py:50-67`); readiness sorted by collector; `capability` defaulting to
  `{"enabled": False, "config": {}}` (`:286-288`); `hardware_id` present; viewer → 200, unauthenticated
  → 401.
- `GET /agents/{id}/telemetry/history`: invalid range → 422; **`test_history_is_bounded_for_every_range`
  asserts `len(points) <= 120` for the current code and is rewritten by Task 7 to the per-range caps
  — do NOT write "exactly 120 preserving endpoints", which Task 7 deliberately changes**; a bucket
  where every row is null yields `None` not 0 (`:105`); no data → `{"range": ..., "points": []}`.
- `projection_attempts`: write a **module-level comment only**, naming Task 8 as the task that drops
  `AgentHostSample.projection_attempts` (`db/models.py:441`) and the index
  `ix_agent_host_samples_projection`, so the dead column is not silently re-introduced as "covered".
  **Do NOT write an assertion against the column** — Task 8 removes it two tasks later and any such
  test would raise `AttributeError`/`KeyError`; `test_agent_host_sample_has_no_projection_attempts_column`
  in Task 8 is the assertion that replaces it.
- **Reserved for other tasks — do not write here or the file lands red:**
  `test_linked_projection_uses_platform_summary_keys` (Task 5) and
  `test_history_does_not_load_all_raw_rows` (Task 7).

**Depends on:** Task 3 (the payload helper loads the corpus entry, so backend and collector cannot
drift).

---

### Task 5: Extract one shared Hardware-metric normalizer and route the agent projection through it

**Closes:** issue 1

**Current state:** `services/agent_telemetry.py:129-161` inlines a parallel copy of the projection.
It builds `HardwareLiveMetric` directly (`:131-150`) from agent key names —
`summary["mem_used_bytes"] / (1024*1024)` (`:138-140`), `summary["mem_total_bytes"] / (1024*1024)`
(`:141-143`), `row.root_disk_pct` → `disk_pct` (`:144`), `row.max_temp_c` → `temp_c` (`:145`) — and
never calls `_normalise_payload`, `_derive_mem_pct`, `_derive_disk_pct`, `_as_float`, `_as_int`, or
`_bytes_to_mb`. It then writes `hardware.telemetry_data = dict(summary)` (`:158`), sets
`HardwareLiveMetric.raw = payload` — the **full agent frame payload** (`:149`) — sets
`hardware.last_seen` unconditionally (`:161`), and publishes `{"data": dict(summary), ...}` to the
Redis cache and telemetry WebSocket (`:180-193`).

The consumers that go blank: `telemetry_service.py:62-70` `_derive_disk_pct` looks for `disk_pct`,
`rootfs_used`/`rootfs_total`, or `disk_used_bytes`/`disk_total_bytes` — never `root_disk_pct`;
`:246` looks for `temp_c`/`cpu_temp` — never `max_temp_c`; `:243-244` looks for
`mem_used_mb`/`mem_used` — never `mem_used_bytes`. `api/telemetry.py:159-167` spreads
`hw.telemetry_data` into the entity response. `components/map/CustomNode.jsx:533,535,543` reads
`tData.cpu_temp`; `:557,566,569` reads `cpu_pct`, `mem_used_gb`, `mem_total_gb` **with no
fallback**. `components/map/TelemetrySidebar.jsx:253-264` reads `cpu_pct`, `mem_used_gb`/`mem_used`,
`mem_total_gb`/`mem_total`, `disk_used_gb`/`rootfs_used`, `disk_total_gb`/`rootfs_total` — so byte
fallbacks exist there but **not** in `CustomNode`, and `mem_used_gb`/`mem_total_gb` must be emitted
explicitly.

Two leak paths the review under-counts: `HardwareLiveMetric.raw = payload` (`:149`) is served
verbatim by `_row_to_payload` (`telemetry_service.py:121-124`) on
`GET /api/v1/hardware/{id}/telemetry`'s DB-fallback branch (`:177-189`); and the Redis cache
envelope (`:180-193`) is returned unchanged by `get_telemetry_for_hardware` (`:163`).

Two corrections to the review's root-cause text: (a) the `last_seen` divergence is real
(`agent_telemetry.py:161` vs `telemetry_ingest_worker.py:147`'s `_NON_LIVE_STATUSES` gate) but has
**no observable effect today** — `agent_telemetry.py:61` admits only `"healthy"`/`"degraded"` and
`_NON_LIVE_STATUSES = {"unknown","unreachable","error","unconfigured"}` (`telemetry_service.py:17`)
contains neither; it is a latent divergence to lock shut before the agent's status vocabulary grows,
not the cause of the blank UI, which is **purely key naming**. (b) Root-disk **bytes are not in the
agent summary**: `internal/frame/frame.go:170-189` (`HostSummary`) carries `root_disk_pct` only;
the bytes live per filesystem at `internal/collect/host/host.go:224`
(`total_bytes`/`used_bytes`/`available_bytes`/`used_pct`), with the `/` entry identified at
`:227-229`. Any `disk_used_gb`/`rootfs_used` projection must read the `mountpoint == "/"` entry from
`payload["filesystems"]`.

**Required changes:**
- Create `apps/backend/src/app/services/telemetry_normalize.py`. **Move** (not copy)
  `_as_float`, `_as_int`, `_bytes_to_mb`, `_derive_mem_pct`, `_derive_disk_pct`
  (`telemetry_service.py:26-70`), `_NON_LIVE_STATUSES` (`:17`), and `_normalise_payload` (`:100-118`),
  and **re-export them from `telemetry_service`** so `workers/telemetry_ingest_worker.py:27-35`'s
  import block keeps working unchanged. Spell the re-export explicitly as a single
  `from app.services.telemetry_normalize import (_NON_LIVE_STATUSES, _as_float, _as_int,
  _bytes_to_mb, _derive_disk_pct, _derive_mem_pct, _normalise_payload)  # noqa: F401` — the names are
  unused inside `telemetry_service` itself, so without the `noqa` (or an equivalent `__all__`)
  `ruff check src/app` fails F401 and the Release Gate goes red.
- Add `live_metric_fields(data) -> dict` returning exactly the `HardwareLiveMetric` column mapping
  that `telemetry_service.py:241-248` and `telemetry_ingest_worker.py:83-96` implement today
  (`cpu_pct, mem_pct, mem_used_mb, mem_total_mb, disk_pct, temp_c, power_w, uptime_s`). Rewrite both
  to call it — a pure refactor, no behavior change on the poller paths.
- Add `agent_summary_to_platform(summary, filesystems) -> dict` emitting, with these exact names and
  units: `cpu_pct` (0-100), `mem_pct`, `mem_used`/`mem_total` (**bytes**, feeding `_derive_mem_pct`
  and the `TelemetrySidebar.jsx:255,258` fallbacks), `mem_used_mb`/`mem_total_mb` (**MiB**, via
  `_bytes_to_mb` for 2-dp parity with `telemetry_service.py:44-48`), `mem_used_gb`/`mem_total_gb`
  (**GiB**, 1 dp — required with no fallback by `CustomNode.jsx:557,569`), `disk_pct` (from
  `root_disk_pct`), `rootfs_used`/`rootfs_total` (**bytes**, from the `mountpoint == "/"` filesystems
  entry), `disk_used_gb`/`disk_total_gb` (**GiB**, same entry), **both** `temp_c` and `cpu_temp`
  (Celsius, from `max_temp_c`), and `uptime_s`. Pass through unchanged for Agent-Detail parity:
  `load_1, load_5, load_15, logical_cpus, mem_available_bytes, swap_pct, swap_used_bytes,
  swap_total_bytes, net_rx_bps, net_tx_bps, boot_time_unix_s`. Emit **no** `power_w`/`system_power_w`
  — the Linux collector has no power probe, so `HardwareLiveMetric.power_w` (`db/models.py:1871`)
  stays NULL and `CustomNode.jsx:546-552`'s wattage badge correctly renders nothing; **do not fake
  it.** Every key is **omitted, not `None`**, when its source is absent, so the `_derive_*` fallbacks
  behave.
- Keep `agent_summary_to_platform` and `live_metric_fields` **separate** functions so slice 3/4 can
  reuse `live_metric_fields` without inheriting host-specific `filesystems` handling.
- Rewrite `agent_telemetry.py:129-161`: compute `platform = agent_summary_to_platform(...)` once;
  build `HardwareLiveMetric` from `live_metric_fields(platform)` plus the attribution columns
  (`agent_id`, `agent_sample_id`, `collected_at`, `status`, `source="agent"`); set `raw=platform`
  (not the frame payload); set `hardware.telemetry_data = platform`; gate `hardware.last_seen` on
  `sample.status not in _NON_LIVE_STATUSES`, matching `telemetry_ingest_worker.py:147` and
  `telemetry_service.py:259`. Keep the `telemetry_last_polled` monotonicity guard (`:154-156`) and
  the `projected_at` stamp (`:152`).
- Publish `"data": platform` in the Redis cache/WebSocket envelope (`:180-193`), keeping
  `source="agent"`, `agent_id`, `sample_id` — slice 3/4 want the same attribution fields.
- **Leave Agent-Detail surfaces untouched:** `api/agents.py:50-67` `_sample_json` and the
  `telemetry:agent:{id}` broadcast (`agent_telemetry.py:166-176`) keep **agent** key names, because
  `AgentDetailPage.jsx:36-45,381` is keyed on them. The wire shape of
  `GET /agents/{id}/telemetry/history` (`{range, points: [{collected_at, summary, sample_count}]}`
  with agent-named summary keys) does not change.
- File a follow-up (do not fix here): `components/Map/Sidebar.jsx:241` multiplies `cpu_pct` by 100
  (Proxmox fraction convention) and renders only when `integration_config_id != null`
  (`:174,178`), so an agent linked to Proxmox-managed Hardware would render `cpu_pct: 12.3` as
  `1230%`. The normalizer keeps `cpu_pct` on the 0-100 platform convention.

**Tests (failing first):**
- `tests/services/test_agent_telemetry_projection.py::test_linked_agent_hardware_telemetry_data_uses_platform_keys`
  — ingest with a `/` filesystems entry; assert `hw.telemetry_data` contains `disk_pct`, `temp_c`,
  `cpu_temp`, `mem_used_mb`, `mem_total_mb`, `mem_used_gb`, `mem_total_gb`, `disk_used_gb`,
  `disk_total_gb`, `rootfs_used`, `rootfs_total`, `mem_used`, `mem_total`. Fails at `:158`.
- `test_agent_live_metric_raw_round_trips_through_row_to_payload` — `_row_to_payload(row)` has
  `disk_pct` and `temp_c`. Fails because `:149` stores the frame payload.
- `test_agent_projection_matches_ingest_worker_normalization` — feed the same `platform` through
  `_build_metric_row` and the agent path; every shared column equal. Fails today: `mem_used_mb` is
  unrounded at `:138-140` while `_bytes_to_mb` rounds to 2 dp (`telemetry_service.py:48`).
- `test_agent_cache_and_publish_envelope_uses_platform_keys` — captured `data` has
  `disk_pct`/`temp_c`/`mem_used_gb` and not `root_disk_pct`/`max_temp_c`/`mem_used_bytes`.
- `test_non_live_status_withholds_hardware_last_seen` (regression guard for the latent divergence)
  and `test_agent_detail_sample_json_still_uses_agent_keys`.
- Refactor safety: `tests/services/test_telemetry_normalize.py` parity test asserting
  `live_metric_fields` produces byte-identical column values for a poller-shaped payload
  (`cpu`, `mem_used`, `mem_total`, `cpu_temp`, `system_power_w`, `uptime`).
- Frontend: extend `apps/frontend/src/__tests__/telemetry-sidebar.test.jsx` with an agent-projected
  `telemetry_data` fixture (platform keys only) and assert the memory and disk GB rows render.

**Depends on:** Task 4 (factories + the ingest matrix this refactor must not break).

---

### Task 6: Make agent retention bounded, complete, and self-reporting

**Closes:** minor item — `retention.py` return dict omits agent rows

**Current state:** `services/intelligence/retention.py:136-176`. `:138-147` selects every
`AgentHostSample` between `warm_cutoff` and `hot_cutoff` across **all** agents and materializes it
into Python — on a table whose `raw` JSONB column is `nullable=False` (`db/models.py:439`).
`:148-151` groups in Python by `(agent_id, hour)`. `:152-170` averages seven fields — `cpu_pct,
mem_pct, root_disk_pct, net_rx_bps, net_tx_bps, max_temp_c, load_1` — and upserts
`AgentHostSampleHourly` one `db.get`/`db.add` at a time. `:171-173` deletes raw rows older than
`hot_cutoff` and **discards the rowcount**; `:174-176` deletes expired hourly rows and likewise.
`:178` returns `{"downsampled": downsampled, "deleted": deleted}` where both were computed
exclusively in the `HardwareLiveMetric` branch (`:61,:125,:130-134`). The aggregate omits `uptime_s`
even though `AgentHostSample.uptime_s` exists (`db/models.py:438`) and both `api/agents.py:63` and
`:94` include it — so every 30 d history point sourced from `AgentHostSampleHourly` has no uptime
series. There is no `db.commit()` here; the caller commits (`workers/analytics_worker.py:45-46`) and
existing tests call it directly. The return value is consumed nowhere, so adding keys is safe.

**Required changes:**
- Replace `:138-170` with a single set-based upsert: `postgresql.insert(AgentHostSampleHourly)` over
  a `SELECT` grouping `AgentHostSample` by `agent_id` and
  `func.to_timestamp(func.floor(func.extract("epoch", collected_at) / 3600) * 3600)` — **not**
  `time_bucket()`, **not** `date_trunc` on a naive column — filtered on
  `collected_at >= warm_cutoff AND collected_at < hot_cutoff`; project `func.count()` as
  `sample_count` and `func.jsonb_build_object(...)` of the per-field `func.avg(...)` as `summary`;
  `.on_conflict_do_update(index_elements=["agent_id", "bucket_at"], ...)` for idempotence against
  the `(agent_id, bucket_at)` PK (`db/models.py:452-455`).
- Add `uptime_s` to the aggregated field list, bringing the hourly summary to the same **eight** keys
  emitted by `api/agents.py:56-63` and `:86-95`.
- Capture the discarded rowcounts: `agent_deleted` from `:171-173` and `agent_hourly_deleted` from
  `:174-176`; capture hourly buckets written from the upsert's `rowcount`.
- Return `{"downsampled": hardware_downsampled + agent_downsampled, "deleted": hardware_deleted +
  agent_deleted + agent_hourly_deleted, "hardware_downsampled": ..., "hardware_deleted": ...,
  "agent_downsampled": ..., "agent_deleted": ..., "agent_hourly_deleted": ...}` — grand totals honor
  the docstring at `:39` while the breakdown makes agent work observable. Update the docstring
  (`:31-39`), which does not mention the agent branch at all.
- Preserve the ordering (aggregate before the raw delete) and add a comment noting that rows older
  than `warm_cutoff` are deleted **without** aggregation by design — they are already cold.
- Keep the portable bulk `DELETE ... WHERE collected_at < cutoff`; `drop_chunks()` is Timescale-only
  and cannot be relied on.
- **This task is the named exemption to the "filter on both `agent_id` and `collected_at`" Global
  Constraint.** The aggregate is fleet-wide by design — it groups *by* `agent_id` across all agents
  and filters on `collected_at` alone, as do both `DELETE` statements. Chunk exclusion still applies
  via the time predicate. Do **not** add a per-agent loop to satisfy the constraint; that would
  reintroduce the N-query pattern this task removes.

**Tests (failing first):**
- `tests/intelligence/test_retention_agent.py::test_retention_result_counts_agent_rows` — 48 h of
  1-minute samples 10-12 days old; `result["agent_downsampled"] == 48`,
  `result["agent_deleted"] == 2880`, and the grand totals include them. Fails today with
  `KeyError: 'agent_downsampled'` and `downsampled == 0`.
- `test_agent_hourly_summary_includes_uptime_s` — bucket mean present. Fails at `:155-163`.
- `test_agent_downsample_runs_in_sql` — `after_cursor_execute` listener over 10,000 seeded rows;
  assert an `INSERT INTO agent_host_sample_hourly ... SELECT ... GROUP BY` and that **no** statement
  selects `agent_host_samples.raw`. Fails at `:139-147`. **Seed the 10,000 rows with a single Core
  `insert()` + executemany parameter list (or `Session.bulk_insert_mappings`), never the per-row
  factories** — `apps/backend/pyproject.toml:199` sets a 30 s per-test `timeout` and `addopts`
  includes `-x`, so a slow ORM seed aborts the whole suite for reasons unrelated to the code under
  test. The factories stay for the small-N behavioral cases. If the test still runs long, mark it
  `@pytest.mark.timeout(120)` explicitly rather than relying on the default.
- `test_agent_retention_is_idempotent` — two runs produce identical row counts,
  `sample_count`s, and `summary` values; the second reports `agent_downsampled == 0` for
  already-purged raw rows.
- `test_agent_retention_uses_no_timescale_functions` — captured SQL contains neither `time_bucket`
  nor `date_bin`.
- `test_agent_samples_older_than_warm_cutoff_are_deleted_not_aggregated` (40 days old) — documents
  the intentional behavior of `:171-173`.
- Regression guard: extend `tests/intelligence/test_retention.py` with
  `test_hardware_counters_unchanged` asserting `result["hardware_downsampled"] == 48` for the
  existing `test_old_data_downsampled_not_deleted` scenario (`:42-60`).
- Backward compat: hourly rows already written lack `uptime_s`; the history endpoint must use
  `summary.get("uptime_s")`, never index. Existing rows age out within 30 days via `:174-176`.
- Transactionality: `run_retention_executor` does not commit. Verify
  `tests/intelligence/test_retention.py`'s direct-call pattern still sees the upserted rows before
  the caller commits.

**Depends on:** Task 4 (factories). Must land **before** Task 7, whose 7 d/30 d hourly merge reads
`AgentHostSampleHourly.summary` and would otherwise surface a `None` uptime series.

---

### Task 7: Aggregate agent telemetry history in SQL with per-range bucket widths and hard point caps

**Closes:** issue 10

**Current state:** `api/agents.py:307-369` `get_agent_telemetry_history`. **The review is wrong that
there is no 120-point cap** — `:364-368` does cap every range and deliberately preserves both
endpoints. The accurate defects are threefold. (a) `:324-333` executes
`select(AgentHostSample).where(agent_id, collected_at >= start).order_by(collected_at)` and
materializes **every** matching ORM row — including the `raw` JSONB column, the largest field in
the table (`db/models.py:439`) — with no aggregation and no limit; at a 10 s cadence a `7d` request
hydrates ~60k rows each carrying a full host payload. (b) The `1h` bucket width is
`timedelta(seconds=1)` (`:335`), a no-op at any real cadence, so each raw sample becomes its own
bucket, `_bucket_samples` (`:70-113`, whose eight-field tuple is `:86-95` and whose emitted point dict is
`:106-112`) averages nothing, and the cap at `:368` degenerates into
**decimation** — `points[round(i * last / 119)]` picks every Nth bucket and discards the rest rather
than averaging (at 10 s cadence it drops 2 of every 3 samples). (c) The plan's per-range widths at
`:334-340` are overridden by that universal cap, so 6h/24h/7d/30d never return the plan's grain.

Retention interaction: `services/intelligence/retention.py:171-173` deletes raw rows older than
`hot_days` (default 7) and `:174-176` deletes hourly rows older than `warm_days` (30) — so the `7d`
range sits exactly on the raw/hourly boundary yet **never consults `AgentHostSampleHourly`**; only
the `30d` branch does (`api/agents.py:342`). If `telemetry_hot_days` is set below 7
(`retention.py:45-49`), `7d` returns a truncated series with no fallback.
`raw_boundary = min(row.collected_at for row in rows)` (`:343`) is itself computed from the fully
materialized list.

Wire contract to preserve: `AgentDetailPage.jsx:169` reads `data.points`; `:86-87` reads
`point.summary?.[metric]`; `:398-402` requests `cpu_pct, mem_pct, root_disk_pct, net_rx_bps,
max_temp_c`; `api/agents.py:106-112` emits `{collected_at, summary, sample_count}`.

**Required changes:**
- Add `apps/backend/src/app/db/bucket.py::epoch_bucket(column, width_seconds)` returning
  `func.to_timestamp(func.floor(func.extract("epoch", column) / width) * width)`. **Slice 3's
  `GET /api/v1/monitors/{id}/probe-runs` (`plans/…slice3-remote-probe.md:373`) and slice 4's job
  history (`…slice4-local-discovery.md:323`) import this instead of re-deriving it.** Task 6 uses
  the same expression.
- Replace `:324-341` with a single aggregate query: module constants `_HISTORY_BUCKET_SECONDS` and
  `_HISTORY_MAX_POINTS` per **D-2**, replacing `bucket_widths` (`:334-340`) and the hardcoded 120
  (`:364-368`); select `epoch_bucket(...)`, `func.avg(...)` for each of the eight summary columns
  (same tuple as `:86-95`), and `func.count()`; `.where(agent_id, collected_at >= start)`;
  `.group_by(bucket)`; `.order_by(bucket.desc())`; `.limit(_HISTORY_MAX_POINTS[range_name])`;
  reverse in Python so the response stays ascending. **The `LIMIT` is the hard bound** — the endpoint
  can never return more rows than the cap regardless of cadence or retention settings.
- Replace `raw_boundary` (`:343`) with a scalar
  `select(func.min(AgentHostSample.collected_at)).where(...)` so no rows are materialized.
- Extend the `AgentHostSampleHourly` merge (`:342-362`) to cover **`7d` as well as `30d`**: query
  where `agent_id`, `bucket_at >= start`, `bucket_at < COALESCE(raw_boundary, now())`, ascending,
  limited to the range cap. For `7d` the hourly points are coarser (1 h) than the raw 30 min grain —
  emit them as-is with their true `sample_count` and let the chart interpolate; do **not** fabricate
  30 min points. Read the summary with `.get("uptime_s")` for pre-Task-6 rows.
- Apply the total cap after the merge by truncating to the newest `_HISTORY_MAX_POINTS[range]`
  points, then sort ascending. **Delete the decimation at `:364-368` entirely.**
- Delete `_bucket_samples` (`:70-113`) if it has no remaining caller, along with any now-unused
  imports, so no second bucketing implementation survives to drift.
- Preserve the response shape exactly (`{collected_at, summary, sample_count}`, emitted at
  `:106-112` today), with `summary` values `None` where the average is NULL — matching `:105`'s
  current `sum(values) / len(values) if values else None`.

**Tests (failing first):**
- `tests/api/test_agent_telemetry_history.py::test_1h_range_averages_into_30s_buckets` — 720 samples
  at 5 s cadence with a known ramp; `len(points) <= 120`, every `sample_count == 6`, first point's
  `cpu_pct` equals the mean of its six values. Fails today: 720 single-sample buckets decimated to
  120 points with `sample_count == 1`, 600 samples silently dropped.
- `test_history_aggregates_in_sql_not_python` — `after_cursor_execute` capture over 5,000 rows;
  assert a statement containing both `avg(` and `GROUP BY`, and that **no** statement selects
  `agent_host_samples.raw`. Fails at `:326`. **Seed the 5,000 rows with a single Core `insert()` +
  executemany parameter list (or `Session.bulk_insert_mappings`)**, for the same 30 s
  `pyproject.toml:199` timeout reason as Task 6; use `@pytest.mark.timeout(120)` if it still runs
  long.
- `test_history_point_count_bounded_for_every_range` — parametrized over all five ranges;
  `len(points) <= _HISTORY_MAX_POINTS[range]` and consecutive `collected_at` deltas are exact
  multiples of `_HISTORY_BUCKET_SECONDS[range]` (proving alignment to the epoch grid, not to the
  first sample). Fails for `1h` (unaligned 1 s buckets) and for the rest (decimation breaks uniform
  spacing).
- `test_7d_range_merges_hourly_rows_when_raw_purged` — hourly rows for days 3-7 back, raw rows for
  the last 2 days only (what `retention.py:171-173` leaves behind); assert the points span 7 days.
  Fails today: `7d` returns a 2-day series.
- `test_history_response_shape_unchanged` — each point has exactly `collected_at`, `summary`,
  `sample_count`; `summary` has exactly the eight agent-named keys. Locks
  `AgentDetailPage.jsx:86-87,398-402`.
- `test_history_sql_uses_no_timescale_functions` — neither `time_bucket` nor `date_bin`. Prevents
  regression onto a Timescale-only construct that would break `postgres:16-alpine`.
- `test_history_returns_empty_points_for_agent_with_no_samples` — covers the `func.min(...) -> None`
  path replacing `min(..., default=utcnow())`.
- Update Task 4's `test_history_is_bounded_for_every_range` to the per-range caps.
- Verify `HistoryChart` (`AgentDetailPage.jsx:86-134`) renders acceptably at 720 points before
  merging — `6h`/`24h`/`7d`/`30d` grow from 120 to 360/288/336/720. Confirm the serialized
  `collected_at` stays UTC-offset-aware (`to_timestamp` returns `timestamptz`; the old code built
  `datetime.fromtimestamp(key, tz=UTC)` at `:108`) so the chart x-axis does not shift.

**Depends on:** Task 6 (hourly `uptime_s`), Task 4 (endpoint tests).

---

### Task 8: Drop the dead `projection_attempts` column and its index; guard **every** TimescaleDB-only statement in migration 0095

**Closes:** minor item — dead `projection_attempts` column; plus the plain-PostgreSQL migration
break that blocks the Release Gate's second `alembic upgrade head`

**Current state:** `db/models.py:441` declares
`projection_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)`;
`migrations/versions/0095_agent_host_telemetry.py:58` creates it with `server_default="0"`. A
repo-wide grep across `apps/backend/{src,tests,migrations}` and `apps/frontend/src` returns exactly
three hits: the model declaration, the migration column, and nothing else. The sibling `projected_at`
**is** live (written at `services/agent_telemetry.py:152`, read at `api/agents.py:66`), but the index
`ix_agent_host_samples_projection` on `(projected_at, collected_at)` (`db/models.py:446`,
`0095:67-69`) supports a "find unprojected samples" scan that no query performs — pure write
overhead on a hypertable. Projection is **not** deferrable today: `ingest_host_sample` inserts
(`:117-119`), projects (`:129-161`), and commits **once** (`:162`), so a persisted-but-unprojected
sample cannot exist.

Separately, 0095 issues **six** TimescaleDB-only statements gated only on
`conn.dialect.name == "postgresql"`, with **no availability check**, unlike
`0041_telemetry_hypertable.py:23-27,70` and `0050_timescaledb_hypertables.py:40-42,149`:
`SELECT create_hypertable('agent_host_samples', ...)` at `:33-37` (the fresh-install early-return
branch) and `:118-121`; `ALTER TABLE hardware_live_metrics SET (timescaledb.compress = false)` at
`:99`; `ALTER TABLE ... SET (timescaledb.compress, timescaledb.compress_segmentby=...,
compress_orderby=...)` at `:112-117`; and the same disable/re-enable pair in `downgrade` at `:137`
and `:146-150`. On the `postgres:16-alpine` stack in `docker-compose.deps.yml:3` there is no
timescaledb, so PostgreSQL rejects the `SET (timescaledb.*)` statements with
`unrecognized parameter namespace "timescaledb"` and **0095 aborts the upgrade**. Note the ordering:
an existing plain-PG database does **not** take the early-return at `:28-38` (this migration is what
creates the three agent tables), so it reaches `:99` long before `:118` — gating only the two
`create_hypertable` calls would not make the upgrade succeed.

Release status: `git branch -a --contains 26372836` returns only `dev`/`origin/dev`
and `git tag --contains 26372836` is empty — 0095 has never shipped, so it may be corrected in
place. `apps/backend/tests/conftest.py:72-76` builds schema from `Base.metadata.create_all`, not
alembic, so model and migration must be kept consistent by hand.

**Required changes:**
- Delete `projection_attempts` (`db/models.py:441`) and
  `Index("ix_agent_host_samples_projection", ...)` (`:446`). **Keep `projected_at`** (`:440`).
- Delete the column from `0095:58`, the `op.create_index` at `:67-69`, and its `op.drop_index` in
  `downgrade` at `:154` — legitimate because 0095 is unreleased.
- Add `0096_drop_agent_projection_attempts.py` (`down_revision = "0095_agent_host_telemetry"`) that
  **idempotently** drops the column and index if present (inspect via `sa_inspect(conn)` first,
  following the defensive pattern at `0095:22-32`). Required because developers on `dev` have
  already applied 0095; on a fresh install both replay and the drop is a no-op.
- Copy **both** helpers from `0041_telemetry_hypertable.py` into 0095: `_has_timescaledb(bind)`
  (`0041:23-28`, `SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb' LIMIT 1`) and
  `_is_hypertable(bind, table)` (`0041:31-38`).
- Gate **every one of the six** Timescale-only statements, not just the `create_hypertable` pair:
  - `:33-37` and `:118-121` (`create_hypertable`) on `_has_timescaledb(bind)`, mirroring `0041:70`
    and `0050:149`.
  - `:99`, `:112-117` (upgrade's compress disable/re-enable) and `:137`, `:146-150` (downgrade's)
    on `_has_timescaledb(bind) and _is_hypertable(bind, "hardware_live_metrics")` —
    `ALTER TABLE ... SET (timescaledb.compress ...)` also fails on a **non-hypertable** even when
    the extension is installed, so the availability check alone is insufficient.
  Without all six, the plain-PostgreSQL deployment path cannot migrate at all.
- Leave `HardwareLiveMetric.agent_id`/`agent_sample_id` and
  `uq_hardware_live_metrics_agent_sample` (`db/models.py:1845-1851`, `0095:106-111`) untouched —
  they are live and used by Task 5's projection.
- Write 0096 defensively: `agent_host_samples` may be a hypertable and Timescale rejects some
  `ALTER TABLE` operations while native compression is enabled (`0095:99,:112-117` already show the
  disable/re-enable dance for `hardware_live_metrics`). 0095 sets no compression policy on
  `agent_host_samples`, so a plain `DROP COLUMN` should succeed — inspect first, tolerate failure.

**Tests (failing first):**
- `tests/test_agent_telemetry_schema.py::test_agent_host_sample_has_no_projection_attempts_column`
  — `"projection_attempts" not in AgentHostSample.__table__.c`.
- `test_agent_host_samples_has_no_dead_projection_index` — absent from
  `__table__.indexes` **and** from `sa.inspect(db_session.get_bind()).get_indexes("agent_host_samples")`.
- `test_projected_at_still_present_and_reported` — `projected_at` in the table and `_sample_json`
  still emits `"projected"`. Proves the drop did not overreach.
- `test_migration_0095_skips_hypertable_without_timescaledb` — call the new `_has_timescaledb` with a
  stub connection whose `execute(...).scalar()` returns `None`; assert `False`. Pair with
  `test_has_timescaledb_true_when_extension_available` and
  `test_is_hypertable_false_for_a_plain_table`.
- `test_migration_0095_emits_no_timescaledb_ddl_without_the_extension` — read
  `migrations/versions/0095_agent_host_telemetry.py` and assert that every `timescaledb.` and
  `create_hypertable` occurrence sits inside a block guarded by `_has_timescaledb` /
  `_is_hypertable`. Cheap structural lock; the real proof is the Release Gate's plain-PG
  `alembic upgrade head`.
- `test_migration_0096_is_idempotent` — run `upgrade` twice where the column is already absent.
- Extend Task 5's projection test file with `test_ingest_still_succeeds_after_column_drop`.
- Update the module-level `projection_attempts` comment Task 4 left in
  `tests/services/test_agent_telemetry.py` to say the column is now gone and to point at
  `test_agent_host_sample_has_no_projection_attempts_column`. (Task 4 deliberately wrote a comment
  and **not** an assertion, so there is no test here to delete.)

**Depends on:** Task 5 (avoids a merge conflict in `agent_telemetry.py`'s vicinity; no functional
coupling).

---

### Task 9: Make collector readiness survive collection and encode failures

**Closes:** issue 4 (collector layer)

**Current state:** `internal/collect/collect.go:61` calls `Collect`, then guards everything behind
**both** `if err == nil` (`:62`) **and** `if marshalErr == nil` (`:65`), with `OnReadiness` nested at
`:69-71`. The review names only the failed-`Collect` path; the `EncodeBounded` path is equally
broken and is reachable when core telemetry alone exceeds 256 KiB
(`internal/collect/payload.go:82`) or when `Schema != 1` (`:38-40`). **Both guards must be fixed.**
`host.Collector.Collect` returns `collect.Result{}, fmt.Errorf("host core: %w", err)` at
`internal/collect/host/host.go:58-60` when `/proc/stat` or `/proc/meminfo` is unreadable
(`:114-202`), discarding the readiness slice already being built at `:54`/`:61`; it also returns an
empty `Result` on `SampleID` failure (`:48-51`) and on context cancellation (`:45-47`). The
optional-probe helper (`:62-73`) and the thermal/docker blocks (`:77-95`) already emit correct
per-probe states, and `collect.go:66-68` already appends a `host.payload/degraded` entry on
truncation. `frame.Readiness`'s doc comment (`internal/frame/frame.go:120-122`) is stale — it
enumerates only `ready | degraded | unavailable` and omits `disabled`, which `host.go:64,84,94`
already emits and `services/agent_telemetry.py:207` already accepts.

**Required changes:**
- Document the readiness-survives-error contract on the `Collector` interface
  (`collect.go:16-18`) per Global Constraints.
- Restructure `Runner.run` (`collect.go:52-81`): call `Collect`; return immediately if
  `ctx.Err() != nil`; compute `payload, encErr := EncodeBounded(&result.Payload)` only when
  `err == nil`; append the existing `host.payload/degraded` entry on truncation and a new
  `{Collector: "host.payload", State: "unavailable", Reason: encErr.Error()}` when `EncodeBounded`
  fails; call `r.OnReadiness` **whenever `len(result.Readiness) > 0`, regardless of `err`/`encErr`**;
  write to `r.out` only when both are nil; always `timer.Reset(interval)`.
- In `host.Collector.Collect`, replace the early return at `:58-60` with: append
  `{Collector: "host.core", State: "unavailable", Reason: err.Error(), Remediation: "verify /proc is
  mounted and readable by the cb-agent user"}`; set `p.Status = "unavailable"`; **continue evaluating
  the optional probes** (they read independent files); **skip the `c.previous = next` assignment at
  `:96`** so a partial counter snapshot cannot poison the next run's rate math; return
  `collect.Result{Readiness: readiness}, fmt.Errorf("host core: %w", err)` with a deliberately zero
  `Payload`.
- Replace the `SampleID` early return (`:48-51`) with a
  `{host.core, unavailable, "could not generate sample id"}` readiness plus the error. **Leave
  `ctx.Err()` (`:45-47`) returning an empty `Result`** — a stop is not an outage and must not
  overwrite server-side rows.
- Export `var CollectorNames = []string{"host.core", "host.filesystems", "host.disks",
  "host.network", "host.thermal", "host.docker"}` and build every readiness slice from it, so
  Task 11's disable path and the collector agree by construction.
- Correct `frame.Readiness`'s doc comment (`frame.go:120-122`) to enumerate all four states, citing
  `services/agent_telemetry.py:207` as authoritative.

**Tests (failing first):**
- `collect_test.go::TestRunner_EmitsReadinessWhenCollectFails` — fake collector returns
  `(Result{Readiness: [{host.core, unavailable}]}, errors.New("boom"))`; assert `OnReadiness` fired
  and nothing reached `out`. Fails today at `:62` (the test times out waiting).
- `TestRunner_EmitsReadinessWhenEncodeFails` — valid readiness with `Payload.Schema = 0`; assert a
  `host.payload/unavailable` entry and no frame. Fails at `:65`.
- `TestRunner_ContextCancellationEmitsNoReadiness` — guards the fix against over-reporting a
  shutdown as an outage.
- `host_test.go::TestCollector_CoreFailureReportsUnavailableAndStillCoversEveryProbe` — fixture root
  with `/proc/self/mounts` and `/sys` present but `/proc/stat` absent; assert `err != nil`, zero
  `Payload`, `{host.core, unavailable}` with a non-empty reason, and **one entry per
  `host.CollectorNames`**. Fails today: `:58-60` returns no readiness at all.
- `TestCollector_ReadinessCoversAllSixCollectorsOnASuccessfulRun` and
  `TestCollector_DisabledProbesReportDisabledNotMissing` — the all-six assertion is what stops a
  future probe being added to `host.go` without being added to `CollectorNames` (which would leave
  its row never flipped to `disabled` by Task 11).

**Notes:** `host.filesystems` calls `Usage` on the Root-rewritten path, so fixture mount lists must
name directories that exist under the temp root or the entry is silently skipped (`host.go:220`).
`host.docker` dials `c.path("/var/run/docker.sock")`, so with a fixture Root and `IncludeDocker=true`
the dial fails fast and deterministically reports `unavailable` — usable as a positive test, not a
flake. Continuing optional probes after a core failure is a deliberate behavior change: a few extra
file reads on a broken host in exchange for honest per-probe rows.

**Depends on:** Tasks 1 and 2 (fixture helpers and `fakeCollector`).

---

### Task 10: Re-order daemon startup to remove the `statusWriter` race and make status readiness an upsert

**Closes:** issue 5

**Current state:** `cmd/cb-agent/main.go:204` declares `var statusWriter *status.Writer`;
`applyHostConfig` (`:220-251`) installs an `OnReadiness` closure that **reads** `statusWriter`
(`:235-239`); `:252` calls `applyHostConfig()`, reaching `hostRunner.Reset` (`:250`) which starts a
goroutine whose first collection fires immediately (`collect.go:53`); the main goroutine only
**assigns** `statusWriter` at `:260`. That read/write pair is unsynchronized — a data race.
Functionally the first readiness is swallowed by the `if statusWriter != nil` guard (`:235`), then
`:264` calls `statusWriter.SetReadiness(hostinfo.Collect(AgentVersion).Readiness)` — and
`status.Writer.SetReadiness` (`internal/status/status.go:157-163`) **replaces the whole slice**
rather than upserting by collector, so even with the ordering fixed, every later collector readiness
write would erase `agent.identity` and vice versa. **The merge semantics must change too.**
`auditStateDir` runs at `:275-278`, after `capGate.LoadCached` (`:197`), after the collector
goroutine, and after the first `statusWriter` writes; `openSpool` runs at `:286`; the update-rollback
watcher spawns at `:302-307`. The review's "the collector starts before `auditStateDir`, documented
as running before touching anything else in the state directory" needs qualification:
`enroll.LoadOrCreateDeviceKey` (`:185`) and `enroll.Run` (`:191`) already write `device.key` before
it. **The invariant actually violated is narrower: `auditStateDir` must precede every daemon-loop
state write** — `grants.json` (`internal/capability/capability.go:148-172`), `status.json`
(`internal/status/status.go:186-211`), and `spool/queue.jsonl` (`internal/spool/spool.go:31-41`).
`apps/agent/Makefile` has only `build-all`/`manifest`/`clean` — no test target, no `-race` anywhere.

**Required changes:**
- Replace `SetReadiness` (`status.go:157-163`) with
  `func (w *Writer) MergeReadiness(items []frame.Readiness) error` that upserts by
  `Readiness.Collector` and re-sorts by collector before persisting, so `status.json` and
  `printStatus`'s listing (`main.go:651-661`) stay deterministic. Keep the `readiness` JSON field
  name unchanged.
- Extract the startup wiring into
  `startDaemonState(cfg, key, agentVersion, ctx) (*daemonRuntime, error)`, where `daemonRuntime`
  carries `capGate`, `statusWriter`, `sp`, `dataFrames`, `controlFrames`, `queueReadiness`, and
  `applyHostConfig`. `runDaemon` becomes: load config/key → enroll → `startDaemonState` → build the
  `link.Options` closures → `link.Run`. **This is what makes the ordering testable without executing
  the full daemon.**
- Fix the order inside `startDaemonState` to exactly: (1) `auditStateDir(config.StateDir(),
  os.Geteuid(), os.Getegid())` — moved up from `:275-278`; (2) `capability.New(...)` +
  `LoadCached()`; (3) `status.NewWriter(...)` + `SetGrants(capGate.Grants())` +
  `MergeReadiness(hostinfo.Collect(agentVersion).Readiness)`; (4) `openSpool(...)`; (5) define
  `queueReadiness` and `applyHostConfig`; (6) call `applyHostConfig()` **last**.
- Change `var statusWriter *status.Writer` (`:204`) to a `:=` assignment at step (3) so the compiler
  enforces assignment-before-capture, and delete the now-dead nil guard at `:235`.
- Delete the readiness overwrite at `:264-266`; step (3)'s `MergeReadiness` replaces it and can no
  longer erase collector readiness.
- Keep the update-rollback watcher (`:302-307`) in `runDaemon`, spawned after `startDaemonState`
  returns, so it still runs after `auditStateDir` and after `openSpool` — an unclean-shutdown spool
  recovery (`spool.go:43-63`) must be reflected in `status.json` before the first connection
  attempt, exactly as today.
- State the narrowed invariant ("before every daemon-loop state write") in `auditStateDir`'s doc
  comment (`:504-529`) so the next reader does not re-order it back.
- Add a `test:` target to `apps/agent/Makefile` running `go test -race ./...`.
- **Wire it into CI explicitly — no Go job exists today.** `grep -rn "setup-go\|go test\|go vet"
  .github/workflows/` returns nothing: `dev-ci.yml`'s `test:` job (`:57-70`) runs only
  `cd apps/frontend && npm test`, and `ci.yml`'s `test:` job (`:84-97`) is the same. Add an
  `actions/setup-go` step plus `- run: cd apps/agent && make test` and
  `- run: cd apps/agent && go vet ./...` to the **existing `test:` job in both**
  `.github/workflows/dev-ci.yml` and `.github/workflows/ci.yml`. Issue 5's race is only provable
  under `-race`, and without this there is no automated guard once slice 3 lands.
- **Backend `pytest` is deliberately NOT added to CI in this plan** (it needs a TimescaleDB
  testcontainer and is a separate infrastructure change). The Release Gate marks it, the E2E block,
  and the migration block as **locally enforced**; only the Go, lint, and frontend blocks are
  CI-enforced after this task.

**Tests (failing first):**
- `main_test.go::TestStartDaemonState_NoRaceBetweenCollectorReadinessAndStatusWriter` — pre-seed
  `<tmp>/grants.json` with `{"host_telemetry":{"enabled":true,"config":{"interval_s":10}}}`, call
  `startDaemonState`, wait for `status.json` to contain a `host.*` entry, run under `-race`. **Fails
  today with a DATA RACE naming the read at `:235` and the write at `:260`.**
- `TestStartDaemonState_CollectorReadinessIsNotErasedByIdentityReadiness` — `status.json` contains
  **both** `agent.identity` and `host.core` after the first collection. Fails: `:264` replaces.
- `status_test.go::TestWriter_MergeReadinessUpsertsByCollectorAndKeepsOthers` — three successive
  merges leave exactly 3 entries sorted by collector with `host.core=unavailable` and
  `agent.identity` intact. **Replaces the existing `TestWriter_SetReadiness` (`status_test.go:148`).**
- `TestStartDaemonState_AuditRunsBeforeAnyStateWrite` — state dir owned by a foreign uid
  (`t.Skip` unless root, mirroring `TestAuditStateDir_OwnershipMismatchFailsLoudly` at
  `main_test.go:380`); assert an error **and** that neither `status.json` nor `queue.jsonl` was
  created.
- Re-run unmodified as the regression net for the reorder:
  `TestOpenSpool_RecoversAfterUncleanShutdownAndReportsStats` (`main_test.go:214`),
  `TestOpenSpool_DefaultsCapWhenConfigZero` (`:261`), all four `TestWatchForRollback_*`
  (`:465,527,613,685`).

**Depends on:** Task 9 (makes the collector emit readiness this task stops erasing).

---

### Task 11: Report readiness on capability disable, re-enable, and 15-minute reconciliation

**Closes:** issue 4 (daemon layer)

**Current state:** `applyHostConfig` (`main.go:220-251`) stops the runner (`:225-228`) then returns
**bare** at `:230-232` when `capGate.HostConfig()` reports not-enabled, emitting nothing — so the
server's `AgentCapabilityReadiness` rows keep whatever they last held and the UI shows a stale
"Live". The only producer of readiness frames is the `OnReadiness` closure (`:234-249`).
`queueReadiness` (`:208-219`) enforces a 15-minute floor at `:211` **but has no timer of its own**:
the slice-2 plan's "Every 15 minutes as reconciliation"
(`plans/…slice2-host-telemetry.md:121`) only happens as a side effect of a successful collection, so
when `host_telemetry` is disabled or the collector is erroring, **reconciliation stops entirely**.
`queueReadiness` also stamps `readinessSentAt` (`:216`) on a successful channel send even though
`runOnce` discards control frames until `connectedFired` (`internal/link/link.go:593-596`), so a
state change made while disconnected consumes the 15-minute budget without reaching the server;
`onConnected`'s `queueReadiness(true)` (`:333`) is the only rescue. Server-side,
`capability.readiness` is **not** capability-gated (`services/agent_link.py:62-66`) and
`ingest_readiness` only upserts (`services/agent_telemetry.py:209-217`). Also load-bearing and
unstated in the review: **`hello.readiness` is never persisted** — there is no `readiness` reference
in `api/ws_agents.py` or `services/agent_registry.py`, so `hostinfo.Collect`'s `agent.identity`
readiness (`internal/hostinfo/hostinfo.go:42,50-59`) never reaches the table.

**Required changes:**
- Introduce a daemon-level `readinessState map[string]frame.Readiness` guarded by `readinessMu`, and
  `publishReadiness(items []frame.Readiness)` that upserts into it, writes the merged sorted set
  through `statusWriter.MergeReadiness`, marshals it into `readinessPayload`, and calls
  `queueReadiness(changed)`. Move the body of the `OnReadiness` closure (`:234-249`) into it so the
  collector and the daemon share one sink.
- Seed `readinessState` at startup with `hostinfo.Collect(AgentVersion).Readiness` (Task 10 step 3)
  so every `capability.readiness` frame carries `agent.identity` — today that entry only travels in
  `hello`, which the backend never ingests.
- In `applyHostConfig`, **before** the `if !enabled { return }` at `:230-232`, call
  `publishReadiness` with one `{Collector: n, State: "disabled"}` for every `n` in
  `host.CollectorNames` (Task 9). **Only the disable path** — do *not* add a branch for
  "enabled but its stored config is unusable". Task 12 deletes that path by construction: after it,
  `decode` is the sole validation point, a stored config is valid by construction, and
  `Gate.HostConfig`'s silent `ok=false` at `internal/capability/capability.go:201-208` disappears.
  The enabled-but-unusable case is instead reported as `capability.<name>` = `degraded` from
  Task 12's `GrantFault` path, so a branch added here would be unreachable dead code with an
  unwritable test.
- Rely on Task 9's all-six-every-run guarantee to flip rows back from `disabled` to `ready` on
  re-enable — the runner's first collection fires immediately (`collect.go:53`), so no synthetic
  "enabling" report is needed. Add a comment at the enable branch (`:233-250`) making the coupling
  explicit.
- Add a reconciliation goroutine in `startDaemonState` driven by
  `time.NewTicker(reconcileTickInterval)` (a package var defaulting to 1 minute so tests can shrink
  it) calling `queueReadiness(false)` until `ctx.Done`. With the existing 15-minute floor this yields
  at least one readiness frame every 15-16 minutes and — critically — **keeps running when
  `host_telemetry` is disabled and no collection ever happens.**
- Make `queueReadiness` link-aware: an `atomic.Bool linked` set true in `onConnected` (`:310-334`)
  and false in `onDisconnected` (`:342-346`); return early **without stamping `readinessSentAt`**
  when unlinked. `onConnected`'s existing `queueReadiness(true)` re-arms the send. This removes the
  up-to-15-minute readiness blackout after a mid-outage state change. Verify the `onConnected` force
  path still fires exactly once per connection and does not double-send alongside the ticker.

**Tests (failing first):**
- `main_test.go::TestApplyHostConfig_DisableEmitsDisabledForEveryHostCollector` — drive
  `startDaemonState` with the grant on, wait for one collection, apply
  `{"host_telemetry":{"enabled":false}}`, drain `controlFrames`; assert the last payload has all six
  `host.CollectorNames` at `disabled` and still carries `agent.identity`. Fails today: `:231` returns
  and nothing is queued.
- `TestApplyHostConfig_ReEnableFlipsDisabledBackToReady` — proves Task 9's guarantee overwrites the
  disabled rows.
- `TestReadinessReconciliation_FiresWithoutAnyCollection` — capability disabled, shrunk tick/floor;
  a second frame is queued with no collection. Fails: no reconciliation path exists independent of a
  successful collection.
- `TestQueueReadiness_DoesNotConsumeBudgetWhileDisconnected` — with `linked=false` nothing is queued
  and `readinessSentAt` is unchanged; then `onConnected` queues exactly one frame with the newest
  payload.
- `TestPublishReadiness_MergesIdentityWithHostCollectors` — payload sorted by collector, containing
  `agent.identity` plus the six `host.*` entries.
- Backend contract already pinned by Task 4's
  `test_ingest_readiness_accepts_disabled_state_without_grant`.

**Depends on:** Tasks 9 (`CollectorNames`, readiness on every run) and 10 (`startDaemonState`,
`MergeReadiness`, `statusWriter` assigned before capture).

---

### Task 12: Isolate per-capability grant failures so one bad config cannot reject the whole snapshot

**Closes:** issue 11

**Current state:** `internal/capability/capability.go:54-80` `decode` returns `(nil, err)` for the
**whole snapshot** on any per-capability problem: an unparseable grant object (`:66-69`) or a
`host_telemetry` config failing `normalizeHostConfig` (`:70-76`), which rejects `interval_s` outside
10..900 (`:115-118`) and any wrong-typed field (`:96-105`). `ApplyGrants` (`:139-183`) returns at
`:141-143`, so nothing is persisted and `g.grants` is untouched — `remote_probe` and
`local_discovery` in the same payload are silently discarded. Two additional faces the review omits:
(a) `LoadCached` (`:121-137`) shares the all-or-nothing decode, so one invalid **cached** grant makes
a **restarted** agent lose every grant it had; (b) `Gate.HostConfig` (`:201-208`) re-runs
`normalizeHostConfig` and silently returns `ok=false` on error, so a stored-invalid config degrades
to "quietly off" with no signal anywhere. `main.go`'s `onCapabilitiesSet` (`:348-357`) propagates the
error, which `runOnce` logs at `internal/link/link.go:669` and otherwise ignores. The existing test
`TestGateStructuredHostConfigDefaultsAndRejectsInvalidWithoutReplacing`
(`capability_test.go:86-113`) passes today **only because the entire apply is rejected**. The
slice-2 plan requires per-capability semantics: "Invalid server configuration is rejected without
replacing the last valid configuration" (`plans/…slice2-host-telemetry.md:62-63`).

**Required changes:**
- Add `type GrantFault struct { Capability, Reason string }` and change `decode` to
  `decode(payload []byte, previous Snapshot) (Snapshot, []GrantFault, error)`, reserving the error
  **solely** for a payload that is not a JSON object at all (`:56-58`).
- Per-capability handling per **D-6**: a bare bool stays as-is (`:61-65`); a grant object that fails
  to unmarshal (`:66-69`) records a fault and installs `Grant{Enabled: false}` fail-closed (its
  enabled flag is unknowable); a capability whose config fails normalization (`:70-76`) records a
  fault, **keeps the server's enabled flag**, and carries over `previous[name].Config` if that still
  validates, else the package default (`DefaultHostConfig`, `:29-31`); an unrecognized capability
  name passes through untouched.
- Generalize the `host_telemetry` special case (`:70-76`) into
  `var configNormalizers = map[string]func(json.RawMessage) (json.RawMessage, error)` that `decode`
  consults by name. **Slice 3's `remote_probe` scope config and slice 4's `local_discovery` config
  register their own normalizers instead of editing `decode`** — without this, slice 3 re-creates
  this exact bug in a new place. This is the Go mirror of Task 14's `CAPABILITY_DEFINITIONS`.
- Change `ApplyGrants` to `([]GrantFault, error)`: pass the current snapshot as `previous`, persist
  and install the resulting snapshot **even when faults exist** (so the good capabilities land), and
  return the faults. Only a genuinely undecodable payload returns a non-nil error and leaves the
  snapshot untouched. `grants.json` carries the **effective** config (retained or defaulted), so a
  restart is consistent with what is actually running — state this explicitly, since a reader could
  otherwise expect `grants.json` to be a verbatim copy of the server's payload; the divergence is
  reconciled by the fault report, not by mirroring bad input.
- Apply the same isolation to `LoadCached` (`:121-137`): drop only the faulty entries, keep the rest,
  return the faults so the daemon re-reports them on its first connection.
- Simplify `Gate.HostConfig` (`:201-208`) to return the stored config directly, documenting that
  `decode` is now the sole validation point — after this change a stored config is valid by
  construction and the silent `ok=false` path disappears.
- Update `onCapabilitiesSet` (`main.go:348-357`): call the new signature, return `nil` when the only
  problem is faults (so `link.go:669` stops logging a fault-only outcome as a whole-frame failure),
  and for each fault call Task 11's `publishReadiness` with
  `{Collector: "capability." + fault.Capability, State: "degraded", Reason: fault.Reason,
  Remediation: "correct this capability's configuration in Agent Detail"}`; publish
  `{Collector: "capability."+name, State: "ready"}` for every capability that applied cleanly so a
  corrected config clears the row. Do the same for `LoadCached`'s faults at startup.
  `capability.readiness` is the right channel: not capability-gated
  (`services/agent_link.py:62-66`), has a handler (`:227`), and `ingest_readiness` accepts an
  arbitrary collector string (`services/agent_telemetry.py:209-217`) — **no new frame type, no
  backend change.**
- Add the corpus entry deferred from Task 3: `capabilities.set — invalid host_telemetry interval
  alongside a valid remote_probe grant`, asserted through
  `TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate` to show `remote_probe` still applies.

**Tests (failing first):**
- `capability_test.go::TestApplyGrants_InvalidHostConfigDoesNotBlockOtherCapabilities` —
  `{"host_telemetry":{"enabled":true,"config":{"interval_s":9}},"remote_probe":{"enabled":true},"local_discovery":true}`
  → nil error, `Allowed("remote_probe")` and `Allowed("local_discovery")` true, exactly one fault
  naming host_telemetry. Fails at `:73`/`:141-143` with nothing applied.
- `TestApplyGrants_InvalidHostConfigRetainsLastValidConfig` — apply 45, then 9 with `enabled:true`;
  `HostConfig()` still reports 45 and enabled. **Supersedes
  `TestGateStructuredHostConfigDefaultsAndRejectsInvalidWithoutReplacing` (`:86-113`).**
- `TestApplyGrants_InvalidHostConfigWithNoPriorValidFallsBackToDefault` — first-ever grant
  `interval_s: 1000` → `IntervalS == 30`, enabled true, one fault.
- `TestApplyGrants_StructurallyBrokenGrantIsFailClosedNotFatal` —
  `{"remote_probe":"nonsense","host_telemetry":true}` → host_telemetry allowed, remote_probe denied,
  one fault, nil error.
- `TestApplyGrants_NonObjectPayloadStillErrorsAndLeavesSnapshotIntact` — payload `[1,2,3]`.
- `TestLoadCached_OneCorruptGrantKeepsTheRest` — hand-written `grants.json` with a valid
  `remote_probe` and `host_telemetry` at `interval_s: 0`; `Allowed("remote_probe")` true after
  `LoadCached`. Fails today: `:129-132` returns and leaves `g.grants` empty, so a restart silently
  drops every capability.
- `TestApplyGrants_PersistsEffectiveNotRejectedConfig` — reopen a fresh Gate over the same dir and
  `LoadCached`; `IntervalS == 45`.
- `main_test.go::TestOnCapabilitiesSet_ReportsCapabilityFaultAsDegradedReadiness` — against
  `startDaemonState`, an invalid config queues `capability.host_telemetry = "degraded"` with a
  non-empty reason; a valid config then queues `"ready"`.

**Depends on:** Tasks 10 (`startDaemonState`) and 11 (`publishReadiness`), and Task 3 (whose
conformance test calls `ApplyGrants`). The `capability` package changes themselves are independent
and can be written first.

**`ApplyGrants`' signature change touches three call sites, all of which must be updated in this
same commit or the Go suite lands red:** `cmd/cb-agent/main.go:349`; every existing
`internal/capability/capability_test.go` call site; and
**`apps/agent/internal/frame/conformance_test.go`'s `TestCorpus_GrantPayloadsApplyThroughTheCapabilityGate`
(created by Task 3)** — update it to the two-return form, assert `len(faults) == 0` for the existing
corpus entries, and assert `len(faults) == 1` naming `host_telemetry` for the new
`capabilities.set — invalid host_telemetry interval alongside a valid remote_probe grant` entry this
task adds.

---

### Task 13: Replace the fixed 1:4 drain interleave with a bounded, paced catch-up pump over a peek/commit spool

**Closes:** issue 6; minor item — stale "no producer exists yet" comments

**Current state:** `spool.DrainInterleaveRatio` is a hardcoded 4 (`internal/spool/spool.go:16`),
consumed only at `internal/link/outbound.go:74` where `dataFrameSender.sendLive` drains one spooled
frame per four successful live sends. **Draining happens only as a side effect of live production**
(`outbound.go:73-77`): at the default 30 s cadence
(`internal/capability/capability.go:29-31`), a 1-hour outage's 120 spooled samples need 480 live
sends — about 4 hours — and if the capability is later disabled or the collector starts failing,
**the backlog never drains at all**; it sits until cap eviction discards it. Two defects make the
ratio fix impossible on its own, both omitted by the review: (a) **FIFO breaks on a resend failure**
— `drainOne` re-enqueues via `spool.Enqueue` (`outbound.go:93`), which appends to the **tail**
(`spool.go:110`) while cap eviction drops from the **head** (`:119`), so the oldest frame becomes the
newest and its neighbours are evicted before it; (b) **every mutation rewrites the entire queue
file** (`spool.persist`, `:65-89`, called from `Enqueue:121` and `Drain:133`) and `SizeBytes`
re-encodes every entry (`sizeBytesLocked`, `:91-101`) — at the 64 MiB cap
(`services/agent_install.py:59`) a fast drain would be O(n²) in I/O, hundreds of GB written to empty
one full spool. **Raising the drain rate without a storage change makes things worse.** The stale
"no producer exists yet / spool stays idle in heartbeat-only Slice 1 operation" claim appears at
`internal/link/link.go:145-147` (Options.Spool's doc), `:153-155` (Options.DataFrames' doc),
`:563-567` (runOnce's sender comment), `internal/link/outbound.go:11-23` (which documents the 1:4
ratio), `internal/status/status.go:70-73` and `:169-171`, and
`internal/hostinfo/hostinfo.go:26-28` — **all seven are now false.**

**Required changes.** Land this as **one commit**, or as a strictly-additive first commit followed
by a second that does the removals — the naive "spool storage, then link scheduling" split does
**not** compile at commit 1, because `internal/link/outbound.go` consumes both symbols the storage
commit would delete: `d.liveCount % spool.DrainInterleaveRatio` in `sendLive` (`outbound.go:74`) and
`d.spool.Drain()` in `drainOne` (`outbound.go:90`). Deleting them without rewriting `outbound.go` in
the same commit leaves `internal/link` non-compiling and `go test -race ./...` red, violating this
plan's "each task is a single commit that leaves the suites green" rule.

**If splitting:** commit 1 is purely additive — add `Peek`/`Commit`/`head`/`compactLocked`/the
incremental `bytes` counter while **keeping** `Drain()` and `DrainInterleaveRatio`; commit 2
rewrites `outbound.go`/`link.go` **and** deletes `Drain()` + `DrainInterleaveRatio` together. Review
as one behavioral change either way. The two sub-headings below describe the areas, not the commit
boundary.

*Spool storage:*
- Add a consumed-prefix `head int` plus a sibling marker file `queue.head` written atomically
  (temp + rename, 0600, the `status.persistLocked` pattern at `status.go:186-211`). `Len()`
  (`spool.go:139-143`) returns `len(entries) - head`.
- Replace `Drain()` (`:124-137`) — **in the same commit that rewrites `outbound.go`** — with a
  two-phase API: `Peek(maxFrames int, maxBytes int64) []frame.Frame` returns up to `maxFrames`
  unconsumed frames from the head, stopping at `maxBytes`
  of encoded size, mutating nothing; `Commit(n int) error` advances `head` and rewrites the marker.
  **Nothing is discarded until it has actually been sent**, so a crash mid-burst re-sends rather than
  loses — safe because `ingest_host_sample` dedupes on `(agent_id, sample_id, collected_at)`
  (`services/agent_telemetry.py:120-128`).
- Add `compactLocked()` rewriting `queue.jsonl` from `entries[head:]`, resetting `head` and removing
  `queue.head`; trigger from `Commit` when `head >= 512` or consumed bytes exceed `capBytes/4`, and
  from the eviction loop (`:111-120`).
- Change `Enqueue` (`:106-122`) to append one encoded line via
  `os.OpenFile(path, O_APPEND|O_CREATE|O_WRONLY, 0600)` + `Sync` instead of the whole-file persist at
  `:121`; fall back to a full rewrite only when eviction actually drops entries.
- Replace `sizeBytesLocked` (`:91-101`) with a running `bytes int64` maintained on
  load/enqueue/commit/compact, storing each entry's encoded length
  (`type entry struct { f frame.Frame; n int64 }`); `SizeBytes()` (`:145-149`) becomes O(1).
- Extend `load()` (`:43-63`) to read `queue.head` first, drop the consumed prefix, and compact
  immediately. A missing or garbage marker means `head=0` (re-send everything — safe and idempotent).
- Delete `DrainInterleaveRatio` (`:16`) — **in the same commit that rewrites `outbound.go`**, per
  the commit-split note above.

*Link scheduling:*
- Strip the ratio logic from `sendLive` (`outbound.go:59-78`): remove the `liveCount` field (`:28`)
  and the modulo trigger (`:73-77`). `sendLive` now only sends live and spools on failure.
- Replace `drainOne` (`:84-101`) with `drainBurst(maxFrames int, maxBytes int64) error`. **It must
  return `nil` immediately when `d.spool == nil`**, mirroring `reportStats`' existing guard
  (`outbound.go:104-106`), and add a nil-safe `hasBacklog() bool` (`d.spool != nil &&
  d.spool.Len() > 0`). A nil spool is the *normal* case for most callers: `link_spool_test.go:123`
  is the only `link.Options` construction in the repo that sets `Spool:`, so every other test in the
  package — and any future non-daemon caller — would otherwise panic dereferencing a nil
  `*spool.Spool` on the first drain tick. Otherwise: `Peek` the batch, send in order, `Commit` only
  the count that succeeded; on the first send error `Commit` the
  successes and return — the uncommitted remainder stays at the head in original order, which
  **eliminates the tail-requeue reordering at `:93`**. Call `reportStats` (`:105-115`) once per
  burst, not per frame.
- Add `drainTicker := time.NewTicker(drainTickInterval)` to `runOnce` and a `case <-drainTicker.C:`
  arm in the main select alongside the `DataFrames` case (`link.go:589-591`), whose body is
  `if connectedFired && sender.hasBacklog() { ... sender.drainBurst(drainFramesPerTick,
  drainBytesPerTick) ... }` — `connectedFired` per `link.go:478,638-639`, `hasBacklog()` nil-safe as
  above. A returned error ends the connection exactly as the `DataFrames` case does. **This MUST
  live in the select loop** — see Global Constraints.
- Declare the budget as package vars so tests can shrink them: `drainTickInterval = 100ms`,
  `drainFramesPerTick = 4`, `drainBytesPerTick = 256 << 10`.
- Rewrite all seven stale comments listed above: host telemetry is now a live data-frame producer,
  the spool is no longer idle, and the drain model is a paced per-connection catch-up burst.

**Tests (failing first):**
- `spool_test.go::TestSpool_PeekDoesNotConsumeUntilCommit` — enqueue 3, `Peek(3, big)`, reopen from
  the same dir, `Len()==3`; then `Commit(2)`, reopen, `Len()==1` and the survivor is the third frame.
  Fails today: `Drain` removes and persists before the caller has sent anything.
- `TestSpool_CommitPreservesFIFOAfterPartialFailure` — the direct regression for the tail-requeue
  bug: enqueue seq 1..5, `Peek(5)`, `Commit(2)`, `Peek(3)` → 3,4,5 in order. Today's
  Drain-then-Enqueue-on-failure (`outbound.go:92-95`) yields 4,5,3.
- `TestSpool_EnqueueIsSubQuadratic` — 2000 frames of ~4 KiB; `queue.jsonl` has exactly 2000 lines and
  the run completes inside a generous wall-clock budget. Fails under the whole-file rewrite at `:121`.
- `TestSpool_SizeBytesIsIncrementalAndMatchesFile`, `TestSpool_CompactsAfterHeadThreshold` (600
  enqueued, `Commit(600)` → zero-length `queue.jsonl`, marker removed),
  `TestSpool_LoadHonoursHeadMarker`.
- `outbound_test.go::TestDataFrameSender_LiveSendNoLongerDrains` — **replaces**
  `TestDataFrameSender_DrainRatio_OneDrainPerFourLiveSends` (`outbound_test.go:112-153`): 10-frame
  backlog, 8 successful live sends, backlog untouched.
- `TestDataFrameSender_DrainBurstRespectsFrameAndByteBudget` and
  `TestDataFrameSender_DrainBurstCommitsOnlySuccessesAndKeepsOrder` (failure on the 3rd of 5 → 2
  committed, failing frame still first, order preserved, error propagates).
- `link_spool_test.go::TestRun_CatchUpDrainsBacklogWithinBound` — extend the existing httptest +
  real-Noise harness (`link_spool_test.go:33`): preload 120 spooled frames, shrink
  `drainTickInterval`, start `Run` with **no live production at all**, assert all 120 arrive in FIFO
  order within a bounded time. **Fails today: with zero live sends `outbound.go:73-77` never triggers
  and the backlog sits forever.**
- `TestRun_DrainNeverStartsBeforeHelloAck` — fake server delays the ack; no data frame on the wire
  before it (guards the `connectedFired` condition on the new arm).
- `TestRunOnce_DrainTickerIsInertWithoutASpool` — run the existing harness with `Options.Spool` left
  nil (the shape of every `link.Options` in the package except `link_spool_test.go:123`) and a
  shrunk `drainTickInterval`; assert many ticks elapse with no panic and no data frame. **Without
  the nil guard this panics on the first tick** rather than proving bounded catch-up.

**Notes:** `queue.head` is a new on-disk artifact under `stateDir`; no secrets, 0600, covered by
uninstall's wholesale removal (`main.go:818-824`, `performUninstall` at `:938`). Version skew is safe
both ways: an older binary ignores the marker and re-sends committed frames (idempotent); a newer
binary over an older spool sees no marker and starts at `head=0`. Commit-after-send makes delivery
at-least-once — validated for telemetry here, and slice 3 must supply the equivalent guarantee for
`probe.result` before reusing the path (its acceptance window is `deadline_at + 30s`,
`plans/…slice3-remote-probe.md:250-258`, so a very old spooled result is dropped server-side rather
than mis-applied). Live frames may overtake older spooled frames — safe, because the backend keys
idempotency on `(agent_id, sample_id, collected_at)` and guards the live projection with
`collected_at >= hardware.telemetry_last_polled`, so a late spooled sample enriches history without
clobbering "latest".

**Depends on:** none (independent of Tasks 9-12). Must land before slice 3 begins.

---

### Task 14: Replace `DEFAULT_CAPABILITY_GRANTS` and `NORMAL_PRESET` with one server-side capability registry

**Closes:** issue 8

**Current state:** `services/agent_registry.py:31-35` defines
`DEFAULT_CAPABILITY_GRANTS = {"host_telemetry": True, "remote_probe": False, "local_discovery":
False}` (the review names it `DEFAULT_GRANTS` at `:32-34` — the real symbol and span are as cited
here). `components/agents/AgentApprovalModal.jsx:14` defines
`NORMAL_PRESET = {host_telemetry: true, local_discovery: true, remote_probe: true}`, with a comment
(`:7-13`) claiming `capabilities` is "always sent explicitly to the approve endpoint, never omitted"
— true of the modal (`:123`), false of every other caller.
`plans/2026-08-04-cbi-agent-slice1-gap-closure.md:102-108` and
`plans/2026-08-04-cbi-agent-e2e-cohesion-review.md:54-58` make the all-three preset authoritative,
so the **backend constant is the side that is wrong**.

Precision on the review's "API-driven approvals never get remote_probe/local_discovery":
`approve_agent` (`:297-344`) starts from `DEFAULT_CAPABILITY_GRANTS` and `.update()`s
`capability_overrides` (`:316-317`), so an approve with no `capabilities` body creates **rows for all
three** with `remote_probe`/`local_discovery` at `enabled=False`. The rows exist; they are disabled.
A second, sharper divergence: even when an override **is** sent, `approve_agent` passes a bare
boolean through `_grant_parts` (`:47-57`, `:318-321`) which yields `config={}`, and only
`host_telemetry` gets `_normalize_host_config` (`:320-321`). `set_capability_grants` repeats that
special case (`:679-681`) and `structured_grants_dict` a third time (`:727-729`). **The moment
slice 3 defines `remote_probe.config` defaults (`max_concurrent`, `scope_mode`, `excluded_cidrs`,
`additional_cidrs`, `additional_hostnames` — `plans/…slice3-remote-probe.md:136-146`), approving with
`{"remote_probe": true}` persists an empty config and the agent receives `{"enabled": true,
"config": {}}`.** `HOST_TELEMETRY_DEFAULT_CONFIG` (`:36-44`) is duplicated verbatim as
`HOST_TELEMETRY_DEFAULTS` (`schemas/agents.py:9-17`) and again as `HOST_DEFAULTS`
(`AgentDetailPage.jsx:26-34`). `ApproveRequest` (`schemas/agents.py:127-138`) has **no** config
validator unlike `CapabilitiesUpdateRequest` (`:145-166`), so an invalid `interval_s` in an approve
body reaches `_normalize_host_config`'s bare `ValueError` (`agent_registry.py:67`) and exits through
the generic handler at `main.py:1411-1413` as a **500, not 422** (`api/agents.py:471-490` has no
try/except). `tests/api/test_agents_api.py:274-295` pins the current wrong defaults.

**Required changes:**
- Create `apps/backend/src/app/services/agent_capabilities.py` per **D-14** — dependency-free (no
  `app` imports beyond typing/stdlib) so both `services/agent_registry.py` and `schemas/agents.py`
  import it at **module scope**. There is no import cycle to work around: `agent_registry` imports
  only `app.schemas.agent_frame` (`:27`), never `app.schemas.agents`, and `schemas/agents.py`
  imports no service module at all (`:1-7`).
- In that module add `@dataclass(frozen=True) class CapabilityDefinition(name, default_enabled,
  default_config, normalize)` and module-level
  `CAPABILITY_DEFINITIONS: dict[str, CapabilityDefinition]` with exactly the three names. `host_telemetry` carries today's `HOST_TELEMETRY_DEFAULT_CONFIG` and
  `_normalize_host_config`; `remote_probe` and `local_discovery` carry `default_enabled=True`
  (per **D-10**), `default_config={}`, and a passthrough normalizer that **rejects any unknown key**
  (empty allow-set today, so any config on those capabilities is rejected until slice 3/4 populates
  it).
- Keep `DEFAULT_CAPABILITY_GRANTS` and `HOST_TELEMETRY_DEFAULT_CONFIG` as derived read-only views of
  the registry so existing importers keep working; comment them as such.
- Add `normalize_grant(capability, value, *, current_config=None) -> tuple[bool, dict]` **to
  `agent_capabilities.py`**: resolves
  `_grant_parts`, raises `ValueError` for an unknown capability, merges
  `definition.default_config | (current_config or {}) | supplied_config`, applies
  `definition.normalize`. **This is the single place a bare-boolean grant acquires its default
  config.**
- Rewrite `approve_agent` (`:316-330`), `set_capability_grants` (`:677-691`, passing the existing
  config as `current_config`), and `structured_grants_dict` (`:721-735`, filling config from
  `CAPABILITY_DEFINITIONS.get(name)`'s `default_config` — **`.get`, never `[name]`**, see Task 15 —
  merged with `dict(g.config or {})`) to call it, **deleting all
  three `if capability == "host_telemetry"` branches.**
- Delete `HOST_TELEMETRY_DEFAULTS` (`schemas/agents.py:9-17`) and rewrite
  `CapabilitiesUpdateRequest.validate_host_config` (`:148-166`) as a generic `validate_capabilities`
  running `normalize_grant` per entry and re-raising `ValueError` as a pydantic error, importing
  `app.services.agent_capabilities` at **module scope** per **D-14**.
- Add the same validator to `ApproveRequest.capabilities` (`:127-138`) so an invalid approve body is
  a 422.
- Add `GET /api/v1/agents/capability-defaults` (`response_model=dict[str, CapabilityGrant]`,
  `require_role("viewer")`) returning `{n: {"enabled": d.default_enabled, "config": d.default_config}}`.
  Declare it **above `"/{agent_id}"`** alongside `/pending` and `/presence` so it is not parsed as an
  agent id (constraint documented at `api/agents.py:217-219`).
- Add `getCapabilityDefaults` to `apps/frontend/src/api/agents.js`.
- Delete `NORMAL_PRESET` (`AgentApprovalModal.jsx:14`); initialise `capabilities` state from
  `getCapabilityDefaults()` fetched alongside `getAgent` in the existing effect (`:55-74`), holding
  the modal in `loading` until both resolve; submit the full structured map at `:123` so an
  approver's opt-out preserves the server's default config for the capabilities left on. Update the
  doc comment (`:7-13`).
- **Rebind the two lines that consume that state**, or toggling replaces a structured grant with a
  bare boolean and the task's own goal is unmet for every capability the approver touches:
  `AgentApprovalModal.jsx:239` becomes `checked={capabilities[key]?.enabled ?? false}` and
  `:240-242` becomes
  `onChange={(e) => setCapabilities((prev) => ({ ...prev, [key]: { ...prev[key], enabled:
  e.target.checked } }))}`.
- **Delete `HOST_DEFAULTS` (`AgentDetailPage.jsx:26-34`)** — it is the fourth copy of the host
  defaults and is load-bearing at `:234` (the config merge sent to `setAgentCapabilities`), `:342`
  (which toggles are rendered) and `:350` (each toggle's fallback value). Fetch
  `getCapabilityDefaults()` alongside `getAgent` in the detail page's existing load effect, hold the
  capability editor in a loading state until it resolves, and drive `:234`'s merge, `:342`'s key
  list and `:350`'s fallbacks from `defaults.host_telemetry.config`. Without this the server
  registry and a hardcoded frontend copy can still drift, which is exactly the defect issue 8 is
  about.
- Add a module docstring on `CAPABILITY_DEFINITIONS` restating the never-backfill invariant from
  Global Constraints.

**Tests:**
- `test_agents_api.py::test_approve_with_omitted_capabilities_grants_the_full_normal_preset` —
  `json={}` → `remote_probe` and `local_discovery` are `{"enabled": True, "config": {}}`. **Fails
  today**; this is the direct rewrite of `test_approve_applies_default_grants_and_sets_active`
  (`:274-295`), whose assertion block must be updated in the same commit.
- `test_agent_registry.py::test_boolean_override_still_receives_the_capability_default_config` —
  `{"host_telemetry": True}` persists the full seven-key host default; then with a monkeypatched
  registry giving `remote_probe` a non-empty `default_config`, `{"remote_probe": True}` yields that
  config, not `{}`. **The second half fails today and is the exact defect slice 3 would inherit.**
- `test_approve_rejects_invalid_host_telemetry_config_with_422` — `interval_s: 5`. **Fails today with
  500.**
- `test_approve_rejects_unknown_capability_name` — 422. Fails today: `approve_agent` writes a grant
  row for any string.
- `test_new_registry_entry_is_not_backfilled_onto_already_approved_agents` — approve, monkeypatch a
  fourth `default_enabled=True` entry, assert `structured_grants_dict` still returns three keys and
  `grants_dict(...).get("fourth", False)` is `False`. Passes on the first run; **must never be
  deleted.**
- `test_capability_defaults_endpoint_matches_what_an_omitted_approve_grants` — the structural lock
  that prevents the frontend/backend preset drifting apart again.
- `agent-approval-modal.test.jsx` — rewrite `defaults to the normal preset with all three
  capabilities enabled` (`:55`) to mock `getCapabilityDefaults`; add `sends the server default config
  for capabilities left enabled` asserting the `approveAgent` body carries `{enabled, config}`
  objects. Fails today: no such export, and the modal sends bare booleans.
- `agent-approval-modal.test.jsx:151-164` — **rewrite the existing
  `lets the approver opt out of a capability before activation`**, which asserts the submitted body
  is `{host_telemetry: true, local_discovery: true, remote_probe: false}` and will fail after this
  change. New assertion: the opt-out submits
  `remote_probe: {enabled: false, config: <registry default>}` while the untouched capabilities keep
  `{enabled: true, config: <registry default>}`.
- `AgentDetailPage` regression: a config key that exists **only** in the server registry renders as a
  toggle with no frontend edit (proves `HOST_DEFAULTS` is really gone), and the interval/checkbox
  fallbacks come from the fetched defaults.
- **`apps/agent/e2e/test_agent_e2e.py:358-362` must be rewritten in this commit.** `_enroll_agent`
  asserts `approve.json()["capabilities"] == {"host_telemetry": True, "remote_probe": False,
  "local_discovery": False}` — bare booleans — but `POST /agents/{id}/approve` has
  `response_model=AgentRead` (`api/agents.py:471`) and `_to_read` (`:116-126`) fills `capabilities`
  from `structured_grants_dict`. **That assertion is already false on `dev`**, so all five e2e tests
  fail inside `_enroll_agent` before Task 20 adds anything; this task additionally flips
  `remote_probe`/`local_discovery` to enabled. Rewrite it to the structured all-three shape:
  `host_telemetry` → `{"enabled": True, "config": {...host defaults...}}`, `remote_probe` and
  `local_discovery` → `{"enabled": True, "config": {}}`.

**Depends on:** none within the API cluster. Note this flips the meaning of an omitted `capabilities`
field for existing API callers; it cannot affect already-approved agents (grants are written once at
approval).

---

### Task 15: Make `{enabled, config}` the canonical capability shape on every REST response, including presence

**Closes:** issue 7

**Current state:** `schemas/agents.py:52` types `AgentRead.capabilities` as
`dict[str, CapabilityGrant]`, populated by `_to_read` from `structured_grants_dict`
(`api/agents.py:116-126`). `schemas/agents.py:92` types `AgentPresenceRead.capabilities` as
`Mapping[str, CapabilityValue]` where `CapabilityValue = bool | CapabilityGrant` (`:25`), and
`api/agents.py:235` fills it from `agent_registry.bulk_grants_dict`, whose signature is
`-> dict[int, dict[str, bool]]` (`agent_registry.py:738`) and whose body assigns `g.enabled`
(`:753`). So `/agents/presence` emits bare booleans and `/agents/{id}` emits objects for the same
rows — and `tests/api/test_agents_api.py:837` **pins** the boolean shape, so that test must be
updated, not just the code. `bulk_grants_dict` has exactly one caller (`api/agents.py:235`);
`grants_dict` has exactly one production caller, the enforcement lookup at
`services/agent_link.py:331`. On the frontend, `AgentsPage.jsx:31-37` `formatCapabilities` filters on
raw truthiness (the filter is line **34**, not 33 as cited) and `:189` filters rows with
`!a.capabilities?.[capabilityFilter]`; both are fed from `presence.capabilities` (`:159`). **A
`{enabled: false, config: {}}` object is truthy, so both would report every capability as granted.**
`api/agents.js:22-25` already exports `normalizeCapability`, and `AgentDetailPage.jsx:211,233,320,326,336,349`
already routes every read through it — the detail page is already correct; only the fleet page is not.
`__tests__/agents-page.test.jsx:80` supplies a boolean presence fixture.

**Required changes:**
- Add `bulk_structured_grants_dict(db, agent_ids) -> dict[int, dict[str, dict[str, Any]]]` modelled
  on `bulk_grants_dict` (`:738-754`) for the single-query/every-id-present contract. Factor the
  per-row projection into a private `_structured_grant(g)` used by **both** it and
  `structured_grants_dict` so the two can never diverge, and write the registry lookup
  **defensively**:
  `definition = CAPABILITY_DEFINITIONS.get(g.capability); base = definition.default_config if
  definition else {}; config = base | dict(g.config or {})`. **Never index
  `CAPABILITY_DEFINITIONS[name]` directly here** — `approve_agent` writes an `AgentCapabilityGrant`
  row for any string key today (Task 14's 422 validator stops *new* ones but does not clean up
  existing rows, and no migration does), so a single legacy row with an unregistered capability name
  would turn `GET /agents/presence` and `GET /agents/{id}` into 500s for the whole fleet. Apply the
  same `.get` treatment wherever Task 14's `normalize_grant` read paths merge an existing row as
  `current_config`.
- Delete `bulk_grants_dict` and its tests (`tests/services/test_agent_registry.py:320-335`).
- Change `AgentPresenceRead.capabilities` (`schemas/agents.py:92`) to
  `dict[str, CapabilityGrant] = {}` and update the class docstring (`:84-86`).
- Change `api/agents.py:235` to call the new function and `:251` to pass the structured map.
- Leave `CapabilityValue` (`:25`) in place, referenced **only** by `ApproveRequest.capabilities`
  (`:138`) and `CapabilitiesUpdateRequest.capabilities` (`:146`); comment it as **input-only** —
  legacy booleans accepted on requests indefinitely, never emitted on responses. Leave
  `ws_agents._wire_grants` (`api/ws_agents.py:291-297`) untouched.
- `AgentsPage.jsx`: import `normalizeCapability` and rewrite `formatCapabilities` (`:31-37`) to
  `.filter(([, value]) => normalizeCapability(value).enabled)` and the capability filter (`:189`) to
  `!normalizeCapability(a.capabilities?.[capabilityFilter]).enabled`.
- `grep -rn "capabilities\[\|capabilities?.\[" apps/frontend/src` and route every remaining hit
  through `normalizeCapability`. **No component may index a capability value for truthiness.**

**Tests:**
- `test_presence_includes_capability_grants` (existing, `:827`) — change the assertion at `:837` to
  the structured shape. **Fails today.**
- `test_presence_and_agent_detail_report_identical_capability_grants` — non-default `interval_s`;
  `body["capabilities"] == row["capabilities"]`. Fails today (object vs boolean). **The contract lock
  preventing the two endpoints drifting when slice 3 adds probe scope config.**
- `test_presence_issues_single_query_regardless_of_fleet_size` — extend the existing
  `test_presence_issues_single_mget_regardless_of_fleet_size` (`:881`) pattern with a statement
  counter over a 20-agent fleet so the shape change does not reintroduce an N+1.
- `test_unknown_legacy_capability_row_is_returned_verbatim_not_500` — hand-insert an
  `AgentCapabilityGrant` with `capability="legacy_thing"`; `GET /agents/presence` and
  `GET /agents/{id}` both return 200 with `config == dict(g.config or {})` for that key. **Fails
  with a `KeyError`-driven 500 under a direct `CAPABILITY_DEFINITIONS[name]` lookup.**
- `test_approve_and_capabilities_put_still_accept_legacy_boolean_input` — 200 on both with the
  structured shape returned. Passes before and after; the explicit regression lock for the documented
  legacy-input requirement.
- `agents-page.test.jsx` — change the fixture at `:80` to the structured shape and add
  `expect(within(table).queryByText('Remote probe')).not.toBeInTheDocument()`; switch the
  `renderPage` presence fixtures (`~:271-360`) used by `narrows the table to the selected capability`
  (`:376`). **Both fail today** because every object is truthy.

**Depends on:** Task 14 (`CAPABILITY_DEFINITIONS` for per-capability config defaults).

---

### Task 16: Report live spool depth from the agent, persist it, and render a catch-up indicator

**Closes:** issue 9

**Current state:** The review says `hello.spool_depth` is "hardcoded 0
(`internal/hostinfo/hostinfo.go:26`)" — `:26` is a doc comment; the field is simply **omitted** from
the `frame.HelloPayload` literal at `:34-44`, and `frame.go:148` tags it
`json:"spool_depth,omitempty"`, so it is absent from the wire entirely rather than sent as `0`. The
backend then defaults it to 0 (`schemas/agent_frame.py:91`), and
`internal/hostinfo/hostinfo_test.go:69-70` asserts that zero — so that test is part of the change
surface. The daemon **does** track spool state accurately: `internal/status/status.go:74-75` holds
`SpoolDepth`/`SpoolBytes`, written by `SetSpoolStats` (`:172-178`) from `link.Options.OnSpoolStats`
(`link.go:161-165`, fired at `:239-242` and inside `dataFrameSender`) and at daemon start from
`openSpool` (`main.go:477-491`); `cb-agent status` prints it at `:663`. `link.Options.Spool`
(`link.go:148`) is already in scope inside `runOnce`, which builds hello at `:391-401` and heartbeats
at `:485-493` with a hardcoded `json.RawMessage("{}")`. Backend: `HelloPayload.spool_depth` is
validated at `api/ws_agents.py:547` and handed to `update_hello_metadata`, whose body
(`agent_registry.py:271-287`) only touches `os`, `os_version`, `arch`, `agent_version`,
`primary_macs`; `grep -rn spool` across `ws_agents.py`, `agent_registry.py`, and `agent_link.py`
returns **nothing** — the backend has no spool concept. `services/agent_link.py:71-85`
`_handle_heartbeat` only refreshes Redis presence, and `dispatch_frame` commits after every handler
(`:341-344`). The `Agent` model (`db/models.py:285-370`) has no spool columns. The migration head is
`0095_agent_host_telemetry` (Task 8 adds `0096`). Frontend: `AgentDetailPage.jsx:365-376` renders
live/stale, last-sample time and source status but no spool indicator, which
`plans/…slice2-host-telemetry.md:206-207` requires.

**Required changes:**
- `internal/frame/frame.go`: add
  `type HeartbeatPayload struct { SpoolDepth int json:"spool_depth"; SpoolBytes int64
  json:"spool_bytes" }` after `CapabilityReadinessPayload` (`:166-168`), documented as additive — an
  older server ignores unknown keys, an older agent sends `{}`.
  **Neither field carries `omitempty`, deliberately (D-12).** A current agent must emit
  `{"spool_depth":0,"spool_bytes":0}` once its backlog clears, or the depth column stays pinned at
  its last non-zero value and the Agent Detail indicator never clears. With `omitempty`, an empty
  spool and an old agent both send `{}` and the two required behaviors below become mutually
  exclusive. `HelloPayload.SpoolDepth` (`frame.go:148`) **keeps** its `omitempty` — hello is the
  at-connect snapshot, the heartbeat is what clears the indicator.
- `internal/link/link.go`: add
  `spoolStats := func() (int, int64) { if opts.Spool == nil { return 0, 0 }; n := opts.Spool.Len();
  size, _ := opts.Spool.SizeBytes(); return n, size }` inside `runOnce`; set
  `helloPayload.SpoolDepth` after `hostinfo.Collect` (`:391`); rewrite `sendHeartbeat` (`:485-493`)
  to marshal `frame.HeartbeatPayload` instead of the `{}` literal.
- `internal/hostinfo/hostinfo.go`: rewrite the doc comment (`:26-28`) — `hostinfo` stays
  deliberately spool-agnostic and `internal/link` stamps `SpoolDepth` from `Options.Spool`, because
  the spool is owned by the link. Update `hostinfo_test.go:69-70`'s message; it keeps asserting zero.
- `schemas/agent_frame.py`: add `class HeartbeatPayload` with `spool_depth: int = 0` and
  `spool_bytes: int = 0`, both optional-with-default so today's `{}` heartbeat still validates
  (the `HelloPayload` convention documented at `:76-80`). Because the Go side has no `omitempty`,
  `"spool_depth" in payload.model_fields_set` is an exact "this agent reports spool state" test.
- `db/models.py`: add to `Agent` (after `connected_since`, `:363`) `spool_depth`, `spool_bytes`
  (BigInteger/Integer, nullable), `spool_reported_at` (`DateTime(timezone=True)`, nullable), with a
  docstring stating **NULL means "never reported"** (an agent predating the change), distinct from
  `0` ("reported, empty").
- New `0097_agent_spool_state.py` (`down_revision = "0096_drop_agent_projection_attempts"`) following
  the guarded-`add_column` style of `0092_agent_pending_update_version.py:20-31`, with a `downgrade`
  dropping all three.
- `agent_registry.py`: add `record_spool_stats(agent, depth, size_bytes) -> bool` that writes the
  three columns **only when the values changed**, returning whether it wrote — this keeps the steady
  state (depth 0, unchanged) from issuing a row UPDATE every 20 s per agent. Call it from
  `update_hello_metadata` (after `:287`) gated on `"spool_depth" in fields_set`, honoring that
  function's documented presence-not-truthiness rule (`:248-257`).
- `services/agent_link.py`: in `_handle_heartbeat` (`:71-85`), validate `frame.payload` against
  `HeartbeatPayload` (swallow `ValidationError` with a debug log — a malformed heartbeat payload must
  not tear down the link, the same posture as `ws_agents.py:548-554` for hello) and call
  `record_spool_stats` **gated on `"spool_depth" in payload.model_fields_set`**, the same
  presence-not-truthiness rule `update_hello_metadata` documents (`agent_registry.py:248-257`). An
  old agent's `{}` therefore leaves the three columns NULL; a current agent's explicit `0` writes 0. No explicit commit; `dispatch_frame` already commits at `:344`.
- `schemas/agents.py`: add `spool_depth`, `spool_bytes`, `spool_reported_at` to `AgentRead`
  (after `:51`).
- `api/agents.py`: add `"spool": {"depth", "bytes", "reported_at"}` to the `get_agent_telemetry`
  response (`:289-304`) — the 30 s-polled endpoint (`AgentDetailPage.jsx:161-165`), so the indicator
  is live without a second poll.
- `AgentDetailPage.jsx`: in the status line (`:370-374`), append a catch-up segment rendered only
  when `telemetry.spool?.depth > 0` — `Catching up · {depth} samples buffered ({formatBytes(bytes)})`
  — with a `title`/`aria-label` explaining that displayed samples may lag while a backlog drains.
  Render nothing when depth is 0 or `spool` is absent.
- `fixtures/agent_frame_corpus.json`: add `heartbeat — with spool state` and
  `hello — with non-zero spool_depth` entries so both language sides pin the shape.

**Tests (failing first):**
- `link_test.go::TestHeartbeatCarriesSpoolStats` — fake link server, two frames enqueued in a real
  spool; decoded heartbeat payload is `{"spool_depth":2,"spool_bytes":<n>}`. Fails: `:487` sends `{}`.
- `link_test.go::TestHelloCarriesSpoolDepthAtConnect` — hello `spool_depth` is 2. Fails:
  `hostinfo.Collect` never sets it and `omitempty` drops it.
- Conformance on both sides consumes the two new corpus entries; **fails on the Python side today**
  because `HeartbeatPayload` does not exist.
- `test_ws_agents_link.py::test_heartbeat_persists_spool_state_on_the_agent_row` — heartbeat with
  `{"spool_depth": 7, "spool_bytes": 8192}` → row updated, `spool_reported_at` set. Fails: no
  columns, and `_handle_heartbeat` ignores the payload.
- `test_hello_persists_spool_depth` — hello `spool_depth: 3` lands on the row. **Fails today: this is
  the exact "parses it but never persists it" defect** (`schemas/agent_frame.py:91` parses,
  `agent_registry.py:271-287` never reads).
- `test_agent_registry.py::test_unchanged_spool_stats_do_not_rewrite_the_row` — second call returns
  `False` and leaves `spool_reported_at` unchanged. Guards per-heartbeat write amplification
  (20 s × fleet size).
- `test_old_agent_heartbeat_with_empty_payload_still_accepted` — `payload: {}` → connection survives,
  columns stay NULL. Pins the additive-only constraint.
- `test_agents_api.py::test_telemetry_endpoint_exposes_spool_state`.
- `agent-detail-page.test.jsx::shows a catch-up indicator while the agent has a spool backlog` —
  `spool: {depth: 120, bytes: 240000}` renders; `depth: 0` does not.

**Depends on:** Tasks 13 (spool `Len`/`SizeBytes` semantics), 3 (corpus harness), 8 (migration
chain). This indicator is the only user-visible evidence for Task 13's bounded catch-up, so the
Task 20 E2E asserts through it.

---

### Task 17: Close the remaining Agent Detail gaps — readiness without a sample, cadence, Docker table

**Closes:** minor items — no Docker container table; cadence computed but never shown. Also the
gap **not** in the review that most directly negates Task 9/11's fix.

**Current state:** `plans/…slice2-host-telemetry.md:202-208` requires "Filesystem, disk, interface,
sensor, and optional Docker tables", "Last sample time, live/stale state, current cadence,
spool/catch-up indicator, and source status", and "Probe-level readiness warnings and remediation".
Of that bullet, last-sample-time and live/stale are implemented (`AgentDetailPage.jsx:365-376`) and
source status is implemented (`:373`); **cadence and spool/catch-up are missing** (spool is Task 16).
`:415-418` renders `DeviceTable` for `filesystems`, `disks`, `interfaces`, `temperatures` — no
Docker, though the collector has produced it since slice 2: `internal/collect/host/docker.go:124`
sets `{"containers": [...], "total": N, "running": M, "truncated": bool}` and degrades sample status
when truncated (`:104-107,125-127`); the payload survives via `HostTelemetryPayload.docker`
(`schemas/agent_frame.py:124`) and `_sample_json`'s `"payload": row.raw` (`api/agents.py:65`).
`:366` computes `const interval = telemetry.capability?.config?.interval_s ?? 30` and uses it only
for the staleness threshold at `:368`. **Most seriously: the readiness-warning block (`:404-414`) is
nested inside the `telemetry?.latest ? (` ternary opened at `:363`, so an agent with readiness rows
but no sample — precisely the unreadable-`/proc` case issue 4 describes — renders only "No host
samples received yet." (`:421`) and shows no warning or remediation at all.** Whatever Tasks 9-11
emit, this page still would not display it. `DeviceTable` (`:56-84`) returns `null` for an empty
`rows` array and derives columns from `Object.keys(rows[0])`.

**Required changes:**
- **Hoist the readiness block (`:404-414`) out of the `telemetry?.latest` ternary** so it renders
  whenever `telemetry?.readiness` has any `degraded`/`unavailable` entry, sample or not. Keep the
  `disabled` exclusion (`:405`) — a disabled collector is not a warning.
- Render the cadence in the status line (`:370-374`) reusing the already-computed `interval`
  (`:366`), e.g. `· Cadence {interval}s`.
- Add a Docker section after the Temperatures table (`:418`): a summary line from
  `telemetry.latest.payload?.docker` (`{running} of {total} containers running`), a `role="alert"`
  note when `docker.truncated` explaining the 100-container cap and the degraded status
  (`docker.go:104-107,125-127`), and
  `<DeviceTable title="Containers" rows={telemetry.latest.payload?.docker?.containers} />`. Render
  nothing when `docker` is absent — the normal case, since `include_docker` defaults to `false`.
- **Do not pass the Docker object itself to `DeviceTable`** — it is a dict, not a row array
  (`docker.go:124`), and `Object.keys(rows[0])` at `:58` would produce a nonsense header row.
- Comment that container rows are collector-shaped (`id`/`name`/`image`/`state`/`status` plus
  optional `cpu_pct`/`memory_*`/`network_*_bytes` from `dockerStatsSummary`, `docker.go:47-78`) and
  that `DeviceTable` derives columns from the first row, so a stats-less first container yields a
  narrower table — acceptable, and identical to the existing four tables.

**Tests (all failing first):**
- `agent-detail-page.test.jsx::renders readiness warnings for an agent that has never produced a
  sample` — `{latest: null, readiness: [{collector: 'host.core', state: 'unavailable', reason:
  '/proc unreadable', remediation: 'check agent permissions'}]}`; assert reason **and** remediation
  render alongside "No host samples received yet.". **This is the case issue 4 is about, currently
  invisible even when the data is correct.**
- `renders the Docker container table and truncation warning` —
  `{containers: [{id:'abc', name:'/web', image:'nginx', state:'running', status:'Up 2 days'}],
  total: 101, running: 1, truncated: true}`.
- `does not render a Docker section when the collector is disabled` — guards against an empty table
  for the default `include_docker: false`.
- `shows the effective cadence alongside the live/stale state` — `interval_s: 60` appears.

**Notes:** Purely presentational and additive. The one behavioral change is that readiness warnings
now render for never-sampled agents, surfacing pre-existing `degraded` `host.thermal`/`host.docker`
rows fleet-wide — that is the intent, not a regression. Forward-compat: slice 3/4 add `probe.*` and
`discovery.*` collectors to the same table and the hoisted block renders them unchanged, which is
what "probe-level readiness warnings" (`plans/…slice2-host-telemetry.md:208`) actually requires.

**Depends on:** Task 16 (shares the status line at `:365-376`).

---

### Task 18: Consume the `capability.readiness` broadcast live in `useTelemetryStream` and Agent Detail

**Closes:** minor item — `capability.readiness` Redis broadcast unconsumed by `useTelemetryStream`

**Current state:** `services/agent_telemetry.py:219-232` publishes
`{"type": "capability.readiness", "agent_id": ..., "readiness": [...]}` to `telemetry:agent:{id}`
whenever readiness actually changes (`changed` computed at `:204-217`). `api/ws_telemetry.py:242-243`
subscribes a client to that channel for `entity_type == "agent"`, so the message **already reaches
the browser**. `hooks/useTelemetryStream.js:154-163` computes
`key = msg.entity_id ?? (msg.agent_id != null ? \`agent:${msg.agent_id}\` : null)` and then stores
and emits **only** when `msg.type === 'telemetry' || msg.type === 'telemetry.host'` — a
`capability.readiness` message falls off the end of `onmessage` and is discarded.
`AgentDetailPage.jsx:127-128` subscribes with `entities: [{entity_type: 'agent', entity_id:
Number(id)}]` and `:173-186` reads `liveTelemetry.get(\`agent:${id}\`)` expecting `update.payload`,
so readiness reaches the page only via the 30 s `setInterval` (`:161-165`).

**Required changes:**
- Restructure the dispatch at `useTelemetryStream.js:154-163`: compute `key` once, then branch on
  `msg.type`. Keep the `telemetry`/`telemetry.host` branch **byte-for-byte**. Add a
  `capability.readiness` branch storing under the namespaced key `readiness:${key}` and emitting
  `` telemetryEmitter.emit(`readiness:${key}`, msg) ``.
- **Do not store readiness under the plain `key`** — `AgentDetailPage.jsx:174-185` reads
  `update.payload` from that slot and would clobber the latest sample, blanking the metric cards.
- Update the hook's file docstring (`:1-17`): `data` is keyed by entity for samples and by
  `readiness:<entity>` for readiness, and **new `telemetry:agent:{id}` message types get their own
  namespaced key rather than sharing the sample slot** — the rule slice 3/4 follow for
  probe/discovery statuses.
- `AgentDetailPage.jsx`: add an effect beside `:173-186` reading
  `` liveTelemetry.get(`readiness:agent:${Number(id)}`) `` and, when present,
  `setTelemetry(current => ({...current, readiness: update.readiness}))`. The broadcast carries the
  **full** readiness list (`agent_telemetry.py:228`), so a whole-array replace is correct — no
  per-collector merge.
- Guard the effect so a readiness push arriving before the first `getAgentTelemetry` resolves does
  not create a `telemetry` object with no `latest`; after Task 17 `{readiness: [...]}` alone is a
  valid renderable state.
- `grep -rn useTelemetryStream apps/frontend/src` before editing — the hook is shared. The change is
  strictly additive, but `data` now contains extra keys, so any consumer **iterating** rather than
  indexing must be checked.

**Tests (failing first):**
- `__tests__/use-telemetry-stream.test.js` (new, on the existing fake-WebSocket harness used by
  `stream-safe-close.test.jsx` / `ws-reconnect.test.js`)
  `::stores capability.readiness under a namespaced key without clobbering the latest sample` —
  push `telemetry.host` for `agent_id: 7`, then `capability.readiness`; assert
  `data.get('agent:7').payload` is still the sample **and** `data.get('readiness:agent:7').readiness`
  is the array. Fails on both halves today.
- `agent-detail-page.test.jsx::renders a degraded readiness warning pushed over the telemetry stream
  without waiting for the 30s poll` — mocked stream map containing `readiness:agent:1` while
  `getAgentTelemetry` resolves with `readiness: []`.
- `a live readiness push does not blank the metric cards` — the regression lock for the clobbering
  hazard the namespaced key exists to prevent.
- Non-regression: `useTelemetryStream({entityIds: [5]})` still sends `{subscribe: [5]}` with bare
  integers while `useTelemetryStream({entities: [{entity_type:'agent', entity_id:3}]})` sends the
  typed form (`useTelemetryStream.js:68-81`), and a `msg` with `entity_id 5` and type `telemetry`
  still lands in the data Map (`:154-163`). Slice 2 modified `:68` with no test; this guards every
  existing Hardware/map caller.

**Depends on:** Task 17 (without the hoist, a readiness push for a never-sampled agent still renders
nothing). Operationally this path only matters once Tasks 9-11 emit readiness on failure and disable.

---

### Task 19: Cover the Agent Detail telemetry UI in React Testing Library

**Closes:** issue 2 (frontend half)

**Current state:** `apps/frontend/src/__tests__/agent-detail-page.test.jsx` (204 lines) stubs
`getAgentTelemetry` to `{latest: null, readiness: []}` (`:29`) and `getAgentTelemetryHistory` to
`{points: []}` (`:30`), so the entire telemetry section (`AgentDetailPage.jsx:361-427`) is only ever
rendered in its "No host samples received yet." branch; its five tests are all about presence/online
state. **Zero assertions exist on summary cards, staleness, history, readiness, device tables, the
capability editor, or the unlinked prompt.** Untested surface: the stale computation
`age > Math.max(interval * 3000, 90000)` (`:365-368`), the eight `SUMMARY_LABELS` cards
(`:36-45,377-384`), the history range select (`:385-395`) driving the effect at `:167-172`, the five
`HistoryChart`s (`:396-403`), the readiness alerts (`:404-414`), the four `DeviceTable`s
(`:415-418`), and the unlinked prompt (`:423-427`).

**Required changes:**
- Extend `agent-detail-page.test.jsx` (or add `agent-detail-telemetry.test.jsx` reusing the same
  `vi.mock('../api/agents')` block and `mockUseAgentLive` hoisting at `:6-58`) with a
  `telemetryFixture()` helper returning the realistic `{latest: {sample_id, collected_at, status,
  summary, payload, projected}, readiness, capability: {enabled, config}, hardware_id, spool}` shape
  matching `api/agents.py:288-303` plus Task 16's `spool` key.

**Tests:**
- **Rendering:** all eight `SUMMARY_LABELS` cards render with `formatMetric` output (percent to one
  decimal, B/s with thousands separators, °C, uptime in whole hours — `:47-55`); a null summary field
  renders "Unavailable" rather than being omitted.
- **Staleness:** `collected_at` within `max(3*interval, 90s)` renders "Live", older renders "Stale"
  **with the last sample's cards still populated** (`:365-375`) — assert both the label and that the
  cards did not clear. The plan's "mark data stale … while preserving the last sample" has no
  coverage today and the branch is trivially breakable. `projected` true/false renders
  "Projected to linked hardware" vs "Agent only".
- **Live update without refresh:** mock `useTelemetryStream` to return a Map containing
  `agent:3 -> {type: 'telemetry.host', agent_id: 3, collected_at, payload}`; assert the cards
  re-render from the pushed payload **without** `getAgentTelemetry` being called again (`:173-186`);
  then assert the 30 s poll (`:162-165`) still refreshes under `vi.useFakeTimers`, proving the
  polling fallback survives stream loss.
- **History:** changing the range from 1h to 24h calls `getAgentTelemetryHistory` with `'24h'`
  exactly once and renders the returned point count; a rejected response leaves `history []` and
  renders "0 history points" without throwing (`:170`); a metric with fewer than two finite values
  renders no chart (`:86-89`).
- **Device tables:** each payload array renders one header cell per key of `row[0]` and one row per
  entry (`:56-84`); an empty or absent array renders nothing.
- **Readiness:** a list mixing all four states renders alerts **only** for `degraded` and
  `unavailable`, each with collector, state, reason, and the em-dash-joined remediation; a partial
  list (collectors absent entirely) renders without error.
- **Capability editing:** `interval_s` of 5 or 1000 calls `toast.error('Cadence must be between 10
  and 900 seconds')` and never calls `setAgentCapabilities` (`:228-234`) — this pins the client guard
  against the Go bounds (`internal/capability/capability.go:14-17`) so the two cannot drift; a valid
  interval calls `setAgentCapabilities` with `{host_telemetry: {enabled, config}}` where config is the
  **fetched** `getCapabilityDefaults().host_telemetry.config` merged with the current config and the
  patch (`:235-250`, post-Task-14 — `HOST_DEFAULTS` no longer exists); a rejected call restores
  the previous agent object and surfaces the server detail (`:252-256`); toggling `include_docker`
  with `window.confirm` stubbed false aborts before any request, true proceeds (`:236-239`).
- **Unlinked prompt:** `presence.hardware` null renders the link prompt **alongside** a fully
  populated telemetry section (`:423-427`); present hides it.

**Depends on:** Tasks 14 (`HOST_DEFAULTS` is deleted and the editor's merge/toggle list/fallbacks
now come from the fetched `getCapabilityDefaults()` map, so the editor tests below must mock it),
16, 17, 18 (their own failing-first tests land with their fixes; this task covers everything else).

---

### Task 20: Docker E2E — host telemetry acceptance, catch-up, and disable

**Closes:** issue 2 (E2E half); proves Tasks 9-13 end to end

**Current state:** `apps/agent/e2e/test_agent_e2e.py` has five `@pytest.mark.e2e` tests and
**nothing asserts a telemetry sample.** `_enroll_agent` approves with `DEFAULT_CAPABILITY_GRANTS`,
which already enable `host_telemetry` (`services/agent_registry.py:31-35`), so the running daemon in
`e2e/docker-compose.yml:76-107` is already collecting every 30 s and nothing checks it. The full
outbound path — collector → spool → Noise → `dispatch_frame` → `AgentHostSample` → REST — has never
been proven end to end.

**The suite is red on `dev` before this task starts:** `_enroll_agent`'s assertion at
`test_agent_e2e.py:358-362` expects bare-boolean `capabilities` from `POST /agents/{id}/approve`,
but that endpoint's `response_model=AgentRead` / `_to_read` (`api/agents.py:471`, `:116-126`) has
returned the structured `{enabled, config}` shape since slice 2. **Task 14 rewrites that assertion**
— it is listed there, not here.

**Required changes:** add one `@pytest.mark.e2e test_agent_host_telemetry_first_sample_catchup_and_disable`
reusing `_up_server`/`_fetch_install_material`/`_write_agent_toml`/`_enroll_agent`/`_agent_status`/
`_agent_network_name`. The module's structure is "five test functions, each bringing up (and tearing
down) its own full stack" and `_up_server` (`:144-150`) is a plain helper, not a fixture, with
`_down` (`:153-158`) running `docker compose down -v` plus `shutil.rmtree(_E2E_DATA_DIR)` — so
**the new test owns exactly one `_up_server`/`_down` pair like the other five, and must not call
`_up_server` more than once within itself.** Reuse `_enroll_agent` rather than re-implementing
enrollment. Factor a `_cut_agent_network` context manager rather than copying the
disconnect/reconnect pattern (`test_agent_e2e.py:944,952`) a third time.

1. **Approval → first sample.** After `up -d cb-agent`, PUT `/agents/{id}/capabilities` with
   `host_telemetry {enabled: true, config: {interval_s: 10, include_filesystems: true,
   include_disks: true, include_network: true, include_temperatures: true, include_docker: false}}`
   per **D-13**; `_wait_until` `GET /agents/{id}/telemetry` returns `latest is not None` within 45 s;
   assert `summary.cpu_pct`, `mem_pct`, `root_disk_pct`, `uptime_s` all non-null and
   `payload.filesystems`/`disks`/`interfaces` non-empty.
2. **Unlinked retention + readiness.** Assert readiness contains `host.core` `ready` and
   `host.docker` `disabled` (no socket is mounted, `e2e/docker-compose.yml:92-94`), and that
   `hardware_id` is null while `latest.projected` is false.
3. **Bounded catch-up without duplicates.** `docker network disconnect` cb-agent from agent-net,
   sleep past four collection intervals, `docker network connect`; assert the `1h` history point
   count grew by at least the number of intervals missed, that every `sample_id` appears once
   (re-issue the same window twice and compare), and that `collected_at` values from the outage
   window are **preserved rather than rewritten to reconnect time**.
   - **Catch-up bound:** assert every missed sample appears within a concrete wall-clock budget of
     `docker network connect` (30 s is generous; Task 13's budget drains a 4-interval backlog in
     well under a second). Add a comment citing Task 13's `drainTickInterval` /
     `drainFramesPerTick` / `drainBytesPerTick` as the justification. **Do not try to read those
     values from the test** — they are unexported package vars in Go's `internal/link` and a Python
     e2e test cannot see them. Do **not** hardcode the old 1:4 expectation either.
   - **Spool depth:** `spool.depth` cannot change *during* the outage — no frame reaches the server
     while the agent is disconnected, so the column keeps its pre-outage value. Poll
     `GET /agents/{id}/telemetry` **immediately** after `docker network connect` and assert
     `spool.depth > 0` at least once (sourced from `hello.spool_depth`, Task 16), then `_wait_until`
     it reads 0 within two heartbeat intervals (~45 s, sourced from the heartbeat). The poll must
     start immediately because the next heartbeat clears it.
   - **Do not assert an exact sample count across the outage** — assert monotonic growth plus
     `sample_id` uniqueness, or the test flakes on timing.
4. **Cadence change without reconnect.** PUT `interval_s: 60`; assert `_agent_status` and the next
   observed sample gap reflect it while `link_state` stays `accepted` and `connected_since` is
   unchanged, mirroring the existing step-6 assertion.
5. **Disable stops collection and reports it.** PUT `host_telemetry` `enabled: false`; record the
   latest `collected_at`, sleep past two former intervals, assert `latest.collected_at` is unchanged
   and that `GET /agents/{id}/telemetry` readiness shows the `host.*` collectors at `disabled`
   (Task 11's fix), not a stale `ready`. Restore `interval_s: 30` before exiting.

**Depends on:** Tasks 11, 13, 16 (the behaviors it asserts) and **14** (which rewrites
`_enroll_agent`'s stale capability assertion at `test_agent_e2e.py:358-362`; without it every e2e
test — including this one — fails during enrollment). Budget ~3-4 minutes of wall clock even at
`interval_s: 10`.

---

### Task 21: Release gate verification

**Closes:** nothing directly — this is the verification-only gate before slice 3 starts.

**Required changes:** none expected. Run every command in the Release Gate below and confirm green.
If a gate fails, **do not fix it inline** — report the specific failure; it routes back to the task
whose area regressed, as a small dedicated follow-up.

**Depends on:** Tasks 1-20.

---

## Issue Coverage Matrix

| Issue | Task(s) | How it is closed |
|---|---|---|
| **1** — Linked-Hardware projection not normalized | 5 | `telemetry_normalize.py` becomes the single normalizer; `write_telemetry`, `_build_metric_row`, and the agent projection all route through `live_metric_fields`; `agent_summary_to_platform` emits platform key names (incl. `mem_used_gb`/`mem_total_gb` with no fallback for `CustomNode.jsx`, and `rootfs_*`/`disk_*_gb` from the `/` filesystems entry) into `Hardware.telemetry_data`, `HardwareLiveMetric.raw`, and the Redis/WS envelope; `last_seen` gated on `_NON_LIVE_STATUSES`. |
| **2** — Slice-2 core has no tests | 1, 2, 4, 19, 20 | Task 1 adds the `FSUsage` seam and full fixture coverage of every `/proc`+`/sys` probe; Task 2 covers `docker.go` against a fake unix socket and the `collect.Runner`; Task 4 creates the backend factories and the ingest/readiness/endpoint matrix (including the D-9 pre-validation pass that makes `ingest_readiness` genuinely all-or-nothing); Task 19 covers the Agent Detail telemetry UI in RTL; Task 20 proves the path end to end in Docker. |
| **3** — Conformance corpus not extended | 3, 12, 16 | Task 3 adds `telemetry.host` (×3), `capability.readiness` (×2), schema-2 `hello`, structured `hello.ack`, and structured/mixed `capabilities.set` entries, typed round-trips on both sides, a `populate_by_name` fix that makes `HostTelemetryPayload` round-trip at all, gate-applied grant assertions, and a self-enforcing coverage test with a shrinking `pendingCorpusTypes`; Task 12 adds the invalid-interval grant entry; Task 16 adds the heartbeat/hello spool entries. |
| **4** — Readiness goes silent when it matters | 9, 11, 17, 18 | Task 9 fixes **both** the `err`- and `EncodeBounded`-guarded paths, makes `host.Collector` report `host.core unavailable` while still evaluating optional probes, and exports `CollectorNames`; Task 11 emits `disabled` for all six on capability disable, adds a reconciliation ticker independent of collection, seeds `agent.identity`, and stops the disconnected budget burn; Task 17 makes readiness render for never-sampled agents; Task 18 delivers it live. |
| **5** — Startup data race on `statusWriter` | 10 | `startDaemonState` extraction fixes ordering (audit → gate → status → spool → applyHostConfig last), `:=` enforces assignment-before-capture, `SetReadiness` becomes `MergeReadiness` (upsert by collector) so identity and collector readiness no longer erase each other, and `make test` runs `go test -race ./...`. |
| **6** — Spool catch-up ≈ 8× the outage | 13 | `DrainInterleaveRatio` deleted; peek/commit spool with a head pointer (fixes FIFO on resend failure and the O(n²) whole-file rewrite/`SizeBytes` re-encode); paced 100 ms / 4-frame / 256 KiB drain arm inside `runOnce`'s select loop, so catch-up no longer depends on live production at all. |
| **7** — `capabilities` has two shapes | 15 | `bulk_structured_grants_dict` replaces `bulk_grants_dict`; `AgentPresenceRead.capabilities` becomes `dict[str, CapabilityGrant]`; `AgentsPage.jsx` routes both `formatCapabilities` and the capability filter through `normalizeCapability`; `CapabilityValue` is retained input-only. |
| **8** — Approval defaults diverge | 14 | One `CAPABILITY_DEFINITIONS` registry with `default_enabled=True` for all three; `normalize_grant` gives every bare-boolean grant its capability's default config (the defect slice 3 would inherit); **both** frontend copies deleted (`NORMAL_PRESET` **and** `AgentDetailPage.jsx`'s `HOST_DEFAULTS`) in favour of `GET /agents/capability-defaults`; approve gains a validator so invalid config is 422 not 500; the stale e2e `_enroll_agent` capability assertion is rewritten to the structured shape. |
| **9** — Spool visibility doesn't exist | 16 | `HeartbeatPayload{spool_depth, spool_bytes}` plus `hello.spool_depth` stamped in `internal/link`; `record_spool_stats` persists to three new `Agent` columns with change detection; `GET /agents/{id}/telemetry` exposes `spool`; Agent Detail renders a catch-up indicator. |
| **10** — History isn't bounded as specified | 7 | Single SQL aggregate with `epoch_bucket` (portable, no `time_bucket`), per-range widths and caps per **D-2** enforced by `LIMIT`, the decimation deleted, `raw_boundary` made scalar, and the hourly merge extended to `7d` so the raw/hourly retention boundary is covered. |
| **11** — One bad config rejects the whole grant set | 12 | Per-capability `GrantFault` isolation in `decode`/`ApplyGrants`/`LoadCached`, a `configNormalizers` registry for slice 3/4, effective-config persistence, and `capability.<name>` `degraded` readiness reporting. |
| *minor* — dead `projection_attempts` column | 8 | Column and `ix_agent_host_samples_projection` dropped from the model and from unreleased 0095, with idempotent `0096`; **all six** of 0095's TimescaleDB-only statements (`create_hypertable` at `:33-37` and `:118-121`, the compress disable/re-enable at `:99`/`:112-117` and the downgrade's `:137`/`:146-150`) gain `_has_timescaledb`/`_is_hypertable` guards in the same commit — today they abort the upgrade on `postgres:16-alpine`. |
| *minor* — retention return dict omits agent rows | 6 | Set-based portable upsert replaces the materialize-and-loop, `uptime_s` added to the hourly summary, discarded rowcounts captured, and the return grows per-domain breakdown keys alongside grand totals. |
| *minor* — `capability.readiness` broadcast unconsumed | 18 | `useTelemetryStream` branches on `msg.type` and stores readiness under `readiness:<entity>`; Agent Detail applies it without waiting for the 30 s poll. |
| *minor* — no Docker table; cadence never shown | 17 | Docker summary + truncation alert + container `DeviceTable` added; cadence rendered from the value already computed for staleness. (Same task hoists readiness out of the `latest` ternary.) |
| *minor* — stale `link.go:566-568` comment | 13 | All **seven** copies of the "no producer exists yet / spool stays idle" claim corrected: `link.go:145-147`, `:153-155`, `:563-567`, `outbound.go:11-23`, `status.go:70-73`, `:169-171`, `hostinfo.go:26-28`. |

---

## Release Gate

Every command must pass before slice 3 starts. **Run each line from the repo root** — every `cd` is
wrapped in a subshell so the working directory does not leak into the next line.

The lint scope is **`src/app`, matching CI** (`.github/workflows/ci.yml:47,50` and
`dev-ci.yml:46,49`). `ruff check .` and `ruff format --check .` are **red at baseline on `dev`**,
before any work in this plan — 6 errors (E501/I001/F401/F841 in `tests/services/test_agent_install.py`
and `tests/unit/test_migration_0091_hardware_machine_id_hash.py`) and 5 files needing reformatting
(including `src/app/services/agent_update.py`). Widening the scope is a separate cleanup, not a gate
for this plan.

After Task 10, the Go, lint and frontend blocks are **also enforced in CI**. The backend `pytest`,
migration, and E2E blocks are **locally enforced only** — see Task 10 for why.

```
# Go agent — the -race flag is mandatory; Task 10 adds the target
(cd apps/agent && make test)                       # go test -race ./...
(cd apps/agent && go vet ./...)
(cd apps/agent && make build-all && make manifest) # amd64 + arm64 match the manifest

# Backend — same scope CI lints
(cd apps/backend && ruff check src/app && ruff format --check src/app)
(cd apps/backend && mypy src)
(cd apps/backend && pytest)                        # full suite, TimescaleDB test container

# Migrations — both dialect configurations. alembic.ini lives at apps/backend/alembic.ini and
# db/session.py raises unless CB_DB_URL is a postgresql:// URL, so both are required.
#
#   TIMESCALE_URL: a database whose server has the timescaledb extension available —
#                  the Dockerfile.mono image (Dockerfile.mono:140) or a timescale/timescaledb
#                  container started for the purpose.
#   PLAIN_PG_URL:  docker compose -f docker-compose.deps.yml up -d postgres
#                  -> postgresql://breaker:breaker@localhost:5432/circuitbreaker
#                  (docker-compose.deps.yml:3 is postgres:16-alpine, no timescaledb)
(cd apps/backend && CB_DB_URL="$TIMESCALE_URL" alembic upgrade head \
   && CB_DB_URL="$TIMESCALE_URL" alembic downgrade -1 \
   && CB_DB_URL="$TIMESCALE_URL" alembic upgrade head)
(cd apps/backend && CB_DB_URL="$PLAIN_PG_URL" alembic upgrade head)
# ^ 0095's new _has_timescaledb/_is_hypertable guards on all six of its Timescale-only
#   statements (Task 8) are what make this second line pass.

# Frontend
(cd apps/frontend && npm run lint && npx vitest run)

# Docker E2E (linux/amd64)
(cd apps/agent/e2e && pytest -m e2e)
```

**Correction to the cohesion review's gate line.** `plans/2026-08-04-cbi-agent-e2e-cohesion-review.md`
requires "SQLite development/migration tests and PostgreSQL production/E2E tests both pass". **There
is no SQLite main database** (`db/session.py:17,23-27`; `db/models.py:20` uses `INET`/`JSONB`
unconditionally; the only SQLite in the tree is the separate CVE database at
`db/cve_session.py:39`). The real portability axis is **PostgreSQL with and without the timescaledb
extension**, and the migration block above replaces that line.

### End-to-end behaviors demonstrated before slice 3 starts

1. A linked agent's Hardware node renders CPU, memory (%, MB **and** GB), root disk, and temperature
   — no blank badges — and `GET /telemetry/entity/hardware/{id}` returns platform key names on both
   the cache and DB-fallback branches. (Issue 1)
2. An agent whose `/proc` is unreadable produces **no** sample **and** a `host.core unavailable`
   readiness row within one interval, visible on Agent Detail with its remediation string even
   though the agent has never produced a sample. (Issues 2, 4)
3. Revoking `host_telemetry` on a connected agent flips all six `host.*` rows to `disabled` within
   one interval; re-granting flips them back to `ready` on the next collection. A disabled agent
   still emits a reconciliation readiness frame within 16 minutes. (Issue 4)
4. `cb-agent` starts clean under `go test -race` with `auditStateDir` preceding every daemon-loop
   state write, and `status.json` carries `agent.identity` **and** the six `host.*` rows
   simultaneously. (Issue 5)
5. A 1-hour network outage at 30 s cadence drains its 120-frame backlog within seconds of reconnect,
   in FIFO order, with **zero** live production required, no duplicate `AgentHostSample` rows, and
   original `collected_at` values preserved; Agent Detail shows the catch-up indicator rising and
   clearing. (Issues 6, 9)
6. `GET /agents/presence` and `GET /agents/{id}` return byte-identical capability maps; the fleet
   table's capability column and filter are correct for a `{enabled: false}` grant. (Issue 7)
7. `POST /agents/{id}/approve` with no body grants all three capabilities, each with its registry
   default config; an invalid `interval_s` returns 422. (Issue 8)
8. `GET /agents/{id}/telemetry/history` issues one aggregate query per range, never selects
   `agent_host_samples.raw`, returns points on the epoch grid within the per-range cap, spans the
   full 7 days after raw retention has purged days 3-7, and emits no Timescale-only SQL. (Issue 10)
9. Setting `host_telemetry.interval_s` to an out-of-range value while granting `remote_probe` leaves
   `remote_probe` granted, keeps the last valid telemetry cadence running, and surfaces
   `capability.host_telemetry degraded` on Agent Detail; a restart preserves all of it. (Issue 11)
10. `fixtures/agent_frame_corpus.json` covers every declared frame type except the **six** in
    `pendingCorpusTypes`, and both language suites fail if a new type is added without fixtures —
    the mechanism that forces slice 3 to ship `probe.assign`/`probe.result` fixtures in the same
    commit as the code, and to ship `probe.cancel`'s fixture in the same commit as its constant
    (it is deliberately **not** pre-exempted). (Issue 3)
