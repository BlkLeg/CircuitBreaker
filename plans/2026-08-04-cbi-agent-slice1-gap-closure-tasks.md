# cbi-agent Slice 1 Gap-Closure — Task Breakdown

**Derived from:** `plans/2026-08-04-cbi-agent-slice1-gap-closure.md` (authoritative for
requirements language — this file only adds task boundaries and current-state notes for
implementer subagents). Also see `specs/2026-07-26-cb-agent-design.md` and
`plans/2026-07-27-cb-agent-slice1.md`.

**Codebase layout:**
- Go agent daemon: `apps/agent/` (`cmd/cb-agent/main.go`, `internal/{config,enroll,frame,noiseconn,link,capability,spool,update,tlsdial}`)
- Backend: `apps/backend/src/app/` (`api/agents.py`, `api/ws_agents.py`, `core/agent_crypto.py`,
  `services/agent_{registry,enrollment,link,update,install}.py`, `schemas/agent_frame.py`,
  `schemas/agents.py`, `db/models.py`)
- Frontend: `apps/frontend/src/` (`pages/AgentsPage.jsx`, `pages/AgentDetailPage.jsx`,
  `components/agents/AgentApprovalModal.jsx`, `hooks/useAgentLive.js`, `api/agents.js`)
- Migrations: `apps/backend/migrations/versions/` (alembic)
- Docker E2E: `apps/agent/e2e/`

## Global Constraints

Apply to every task below; the task reviewer holds implementers to these:

- Keep all existing agent URLs and protocol-v1 frame names backward compatible. Agents lacking
  new `hello` fields must receive safe defaults; the server advertises the minimum supported
  agent version and rejects versions that cannot safely participate.
- Redis is required for live presence, control delivery, rate limiting, pairing, and updates.
  REST stays available when Redis is degraded, but agent enrollment/control operations must fail
  clearly (not silently weaken guarantees).
- The authenticated old Noise channel authorizes device-key rotation; X25519 keys are never
  treated as signing keys.
- Server-key overlap defaults to 7 days; device-key transition defaults to 15 minutes.
- Protocol rekey stays at 15 minutes; heartbeat/dead thresholds stay 20/60 seconds.
- The spool is integrated now but stays idle in heartbeat-only Slice 1 operation — do not spool
  telemetry/probe/discovery frames; those payload types belong to Slices 2-4.
- "No extra setup" means outbound-only HTTPS/WSS from the agent; never listen on a remote-subnet
  port. The install command must use a configured canonical agent URL, never an internal Docker
  hostname.
- Match existing repo conventions: Go code follows `apps/agent`'s existing package/error/test
  style (table-driven tests, `_test.go` per package); Python follows the existing
  service/router/schema layering and alembic migration conventions in
  `apps/backend/migrations/versions/`; frontend follows existing component/hook/test patterns in
  `apps/frontend/src`.
- Every task must add or extend tests covering its behavior (Go table tests, backend pytest,
  frontend RTL tests, as applicable) and must leave the full existing suite for the
  packages/files it touches green.
- Commit at the end of each task with a clear message; do not bundle unrelated tasks.

---

## Task 1: Protocol v1 schema extensions (hello, hello.ack, transport.rekey, key.rotate)

**Current state:** `hello` payload is sent empty (`internal/link/link.go:112`); `enroll.go` sends
partial metadata (hostname, machine_id_hash, arch, version) but `os_version` and `primary_macs`
are hardcoded blank. `hello.ack` is built server-side (`_ack_bytes` in `ws_agents.py`) but has no
matching enriched schema. `transport.rekey` does not exist as a frame type on either side.
`key.rotate` exists as a constant in both `apps/agent/internal/frame/frame.go` and
`apps/backend/src/app/schemas/agent_frame.py` but has no payload structure and is never
sent/handled. There is a cross-language conformance test corpus at
`apps/agent/internal/frame/conformance_test.go` and `apps/backend/tests/test_agent_frame_conformance.py`
that must stay in sync.

**Required changes:**
- Extend `hello` payload with: agent version, OS name/version, architecture, MACs, readiness,
  spool depth.
- Extend `hello.ack` payload with: acceptance (bool/reason), server time, authoritative
  capability grants, agent ID.
- Add a new `transport.rekey` frame type/payload for independent inbound/outbound Noise cipher
  rekeying (direction-tagged; carries whatever the wire needs to identify which cipher is being
  rekeyed — do not implement the rekey mechanism itself here, only the frame type/schema/codec,
  since Task 5 wires the actual rekey behavior).
- Add a structured `key.rotate` payload for device-key and server-key rotation (fields: rotation
  kind, pending/successor public key material, expiry). Only the schema/codec here — Task 27/28
  wire behavior.
- Update both `apps/agent/internal/frame/frame.go` and `apps/backend/src/app/schemas/agent_frame.py`
  in lockstep; extend the conformance corpus/tests in both `conformance_test.go` and
  `test_agent_frame_conformance.py` to cover the new/extended payloads.
- Preserve backward compatibility: old-shaped `hello` frames (missing new fields) must decode
  with safe defaults, not fail.

**Do not** wire sequence validation, hello.ack gating, rekey timing, or key-rotation state
machines here — those are later tasks. This task is schema/codec only, plus the conformance
tests that pin the wire format.

---

## Task 2: Real agent hello metadata collection

**Current state:** `enroll.go` sends hostname/machine_id_hash/arch/version but `os_version` and
`primary_macs` are hardcoded empty. `link.go:112` sends a fully empty `hello` on every
reconnect — metadata is effectively only ever sent once, at initial enrollment.

**Required changes:**
- Collect `/etc/os-release` name/version.
- Collect normalized primary MAC addresses, excluding loopback and invalid addresses.
- Compute the machine-ID hash from trimmed source data (trim whitespace/newline before hashing).
- Populate build version and architecture.
- Use this real collector for **both** `enroll.Run`'s hello and `link.go`'s reconnect hello (every
  reconnect sends current, not stale, metadata) using the Task 1 schema.
- Unit-test the collector against fixture `/etc/os-release` content and MAC-list edge cases
  (loopback-only, no MACs, malformed lines).

---

## Task 3: Sequence-number validation and replay/version rejection

**Current state:** Sequence numbers are assigned on send (both sides) but never validated on
receive anywhere in `link.go`, `ws_agents.py`, or `agent_link.py`.

**Required changes:**
- Every sender (agent and server) assigns strictly increasing per-session sequence numbers.
- Every receiver (agent and server) rejects duplicate, decreasing, unsupported-protocol-version,
  and malformed frames.
- Record security-relevant violations (rejected frames) — reuse or extend the existing
  agent-events/security-logging pattern used elsewhere in `apps/backend/src/app/services` for an
  auditable record; on the agent side, log via the existing agent logger.
- Table-driven tests: accept strictly increasing sequences; reject same/lower sequence; reject
  malformed frame bodies; reject unsupported version — both agent-side (Go) and server-side
  (pytest).

---

## Task 4: hello.ack-gated link success and backoff reset

**Current state:** `main.go`'s `OnConnected` callback fires immediately after the Noise handshake
completes, not after a `hello.ack`; `link.go`'s incoming-frame switch has no `TypeHelloAck` case.
The 2-minute update-rollback timer in `main.go:72-86` is keyed off this premature `OnConnected`.
Reconnect backoff (`internal/link/backoff.go`) never resets after a successful/stable link — every
reconnect continues the exponential progression from wherever it left off.

**Required changes:**
- Add a `hello.ack` handler in `link.go`'s frame switch. Only call the agent's
  successful-link callback (`OnConnected`) after receiving a valid `hello.ack` (using Task 1's
  schema and Task 3's sequence validation), not merely after the Noise handshake.
- Use that `hello.ack` — not handshake completion — as the trigger that clears the update
  rollback marker (coordinate with Task 25, which formalizes the rollback-marker mechanics; this
  task only needs to move the *trigger point* to hello.ack, keeping today's marker-clear call site
  working from the new trigger).
- Reset reconnect backoff (`internal/link/backoff.go`) to its floor once a link has been stable
  (accepted via `hello.ack`) for a reasonable stability window; preserve the existing 1s–5m
  jittered progression for consecutive failures before that point.
- Tests: backoff sequence resets after a simulated stable accepted link and continues
  progressing across consecutive simulated failures; `OnConnected` fires only after `hello.ack`,
  never after bare handshake completion, in a link-loop unit test with a fake transport.

---

## Task 5: Bidirectional timed Noise rekey (15 minutes)

**Current state:** No rekey exists on either side; `core/agent_crypto.py`'s docstring says
"Rekeying is out of scope for this slice." `noiseconn.go` is initiator-only with a single
handshake per session, no rekey hooks.

**Required changes (uses Task 1's `transport.rekey` frame):**
- Every 15 minutes, rekey each outbound Noise cipher:
  - Send `transport.rekey` using the *old* outbound key (so the peer can still decrypt the frame
    announcing the change).
  - Rekey the sender's cipher immediately after sending.
  - Rekey the receiver's matching inbound cipher immediately after decrypting that control frame.
- Implement both directions: the agent rekeys its agent→server cipher and the server rekeys its
  server→agent cipher, independently, each on its own 15-minute timer.
- Reuse `github.com/flynn/noise`'s rekey primitive (or the equivalent derivation) on the Go side
  and the matching `dissononce` primitive on the Python side — keep both sides' key-derivation
  logic verifiably identical (add a cross-language fixture/test if the conformance corpus from
  Task 1 supports it, otherwise a documented shared test vector).
- Tests: multiple rekey intervals in sequence continue to encrypt/decrypt correctly on both Go
  and Python sides (use an accelerated/injectable clock, not real 15-minute waits).

---

## Task 6: WS ping deadlines and heartbeat-based presence

**Current state:** Server relies on the WS heartbeat frame alone; there's no separate WS-level
ping deadline. Any traffic on the socket can currently mask a missed application heartbeat if the
code checks last-any-traffic rather than last-heartbeat.

**Required changes:**
- Add WebSocket ping deadlines in `ws_agents.py`/`agent_link.py` alongside the application
  `heartbeat` frame.
- Ensure a *valid heartbeat* frame refreshes presence (via `agent_registry.mark_presence_connected`)
  — arbitrary non-heartbeat traffic must not indefinitely mask a missed heartbeat (i.e., presence
  freshness tracks heartbeat frames specifically, not "any bytes received").
- Agent side: continue to send heartbeats on the existing cadence; respond to `ping` frames
  (frame type already exists per the survey — verify/complete its handling in `link.go`).
- Tests: presence goes stale/offline if only non-heartbeat frames arrive after the heartbeat
  interval elapses; presence stays fresh when heartbeats arrive on schedule.

---

## Task 7: Persist accepted hello metadata onto the agent row

**Current state:** No code path updates the `Agent` DB row from hello metadata; version/OS/MAC
fields on the row (if any) are stale from enrollment time only.

**Required changes:**
- On every accepted `hello`/`hello.ack` exchange (using Task 1's enriched payloads and Task 3's
  validation), update the `Agent` row (`db/models.py:283`) with the latest reported OS/version,
  architecture, MACs, and the successfully running agent version.
- Add whatever nullable columns are needed via an alembic migration if the current `Agent` model
  lacks fields for this (check current columns first; only add what's missing).
- Tests: a hello with updated OS/version metadata results in the persisted `Agent` row reflecting
  the new values after `hello.ack`.

---

## Task 8: Cross-worker agent connection/control registry (Redis-backed)

**Current state:** Presence pub/sub already exists for the UI stream
(`agent_registry.broadcast_presence`, `ws_agents.py:_redis_agent_listener`, channel
`cb:agents:events`), but there is no registry of *which worker process currently holds the live
socket for a given connected agent* — so nothing can route a control frame to that specific
socket from another worker.

**Required changes:**
- Introduce a Redis-backed registry mapping `agent_id -> worker_id` (or equivalent addressable
  identifier) for the worker currently holding that agent's live `/link` socket.
- Register on connect, remove on disconnect or TTL expiration (mirror the existing
  `agent:presence:{id}` TTL pattern in `agent_registry.py` for consistency).
- Provide a publish/subscribe delivery mechanism keyed by agent ID so any worker can hand a frame
  (`capabilities.set`, `update`, `disconnect`, key-rotation, `ping`) to the worker that owns the
  connection, which then writes it to the actual socket.
- This task adds the registry and delivery primitive only; Task 9-11 wire specific frame types
  through it.
- Tests: registration/removal on connect/disconnect, TTL expiry removes stale entries, a frame
  published for an agent owned by worker B is observed as delivered by a simulated worker B
  listener (not by worker A).

---

## Task 9: Wire immediate control-frame delivery through the registry

**Current state:** Capability grant changes, revoke, and reject currently only update the
database; connected agents learn of them via each worker's local 5-second poll
(`_LINK_POLL_SECONDS` in `ws_agents.py:link_stream`), not immediate push.

**Required changes (builds on Task 8):**
- Route `capabilities.set`, `update`, `disconnect`, key-rotation, and `ping` frames through the
  Task 8 registry so they reach the connected agent's actual socket immediately, regardless of
  which worker holds it.
- Keep the existing DB-status poll as a recovery fallback if pub/sub delivery fails (do not
  remove it — it's the safety net named explicitly in the plan).
- Tests: a capability-set/disconnect frame published from a simulated "other worker" is observed
  arriving on the socket-holding worker's connection within the test's timeout.

---

## Task 10: Enrolled-event broadcast and immediate revoke/reject disconnect

**Current state:** `create_pending_agent` only calls `record_event`, never `broadcast_presence` —
the add-agent panel only sees new pending agents via 30s poll. Revoke/reject flip DB status only.

**Required changes:**
- Broadcast an `enrolled` event immediately after creating a pending agent, over the same
  `cb:agents:events` channel/mechanism the UI stream already consumes, so `AgentsPage` can react
  without polling (frontend consumption is Task 14).
- Make revoke and reject publish an immediate `disconnect` frame through the Task 9 delivery path
  in addition to the DB status change; keep the DB-status poll as recovery if pub/sub delivery
  fails.
- Tests: creating a pending agent produces an `enrolled` event on the stream channel; revoking a
  connected agent results in an immediate `disconnect` frame delivery (via Task 9's mechanism) in
  addition to the DB flip.

---

## Task 11: Push capability changes to connected agents; resend on hello.ack

**Current state:** `agent_registry.set_capability_grants` persists only; nothing pushes to a
connected agent.

**Required changes (builds on Task 9):**
- After committing a capability-grant change, push a `capabilities.set` frame to the connected
  agent via the Task 9 delivery path.
- Database state remains authoritative: resend the complete current grant set on every accepted
  `hello.ack` (this is the durable-delivery guarantee — a missed push is corrected on next
  reconnect). Coordinate with Task 1's `hello.ack` payload (grants field) and Task 4's
  `hello.ack`-gated link-success handling.
- Tests: committing a grant change while the agent is connected results in a `capabilities.set`
  push; a fresh `hello.ack` always carries the complete current grant set regardless of prior
  push success/failure.

---

## Task 12: Bulk presence REST endpoint

**Current state:** No bulk presence endpoint exists in the fleet REST API (`api/agents.py`).
Per-agent presence data (`agent:presence:{id}`) exists in Redis via `agent_registry.py`.

**Required changes:**
- Add a bulk presence lookup to the fleet REST service exposing, per agent: `online`,
  `connected_since`, `last_seen_at`, capability grants, and a linked-hardware summary.
- Prefer a single endpoint that returns this for the whole fleet (or an explicit ID list) rather
  than N+1 per-agent calls, matching how `AgentsPage` will consume it (Task 14).
- Tests: bulk endpoint returns correct online/offline/connected_since/last_seen_at reflecting
  Redis presence state and DB grant/hardware data; TTL-expired presence reflects `online=false`.

---

## Task 13: Agent HTTPS_PROXY/NO_PROXY support

**Current state:** No explicit proxy-environment handling found in `enroll.go`, `link.go`,
`tlsdial.go`, or `update.go`.

**Required changes:**
- Ensure the enrollment dialer, link dialer, and update downloader all honor standard
  `HTTPS_PROXY`/`NO_PROXY` environment variables (Go's `net/http` respects these by default via
  `http.ProxyFromEnvironment` for `http.Client`/`http.Transport` — audit each dialer to confirm it
  actually goes through a `Transport` that uses this, including the WSS dial path, and fix any
  path that bypasses it, e.g. a raw `net.Dial`/`tls.Dial` that skips proxy resolution).
- Tests: a dialer constructed with `HTTPS_PROXY` set in the environment routes through a test
  proxy (or the test verifies `Transport.Proxy` resolves as expected for the given env).

---

## Task 14: Frontend live event consumption and online rendering

**Current state:** `useAgentLive.js` already consumes `WS /api/v1/agents/stream` and exposes a
`Map<agentId, {event_type, detail, ts}>`. `AgentsPage.jsx` renders a fleet table with a 30s poll
but doesn't render online/connected-since/capabilities/hardware-summary, and picks up new pending
agents only via poll, not the live `enrolled` event from Task 10.

**Required changes:**
- Update `AgentsPage` and `AgentDetailPage` to consume connected/disconnected/enrolled events from
  `useAgentLive`, refresh/insert newly enrolled records without waiting for the poll, and render
  accurate online/offline state using the Task 12 bulk presence endpoint.
- Render capability grants, linked-hardware summary, and readiness/spool/update state (data now
  available via Task 12; readiness/spool/update fields from Task 7 status persistence/Task 20's
  status file surfaced through whatever endpoint exposes it — coordinate field names with Task 12
  and Task 20).
- Tests: a simulated `enrolled` stream event causes a new pending row to appear without a poll
  tick; connected/disconnected events toggle rendered online state.

---

## Task 15: Fleet filters and pending-pinning

**Current state:** No status/capability/online filters exist in `AgentsPage`; need to verify
current pending-pinning behavior.

**Required changes:**
- Add status, capability, and online filters to `AgentsPage` as specified in the design spec
  (`specs/2026-07-26-cb-agent-design.md` — read it for the exact filter set expected).
- Keep pending agents pinned above the fleet table regardless of active filters.
- Tests: each filter narrows the rendered table correctly; pending agents remain pinned above the
  table under every filter combination.

---

## Task 16: Alembic migration — Hardware.machine_id_hash

**Current state:** `Hardware` model (`db/models.py:90`) has no `machine_id_hash` column. Existing
agent migrations: `0089_agents.py`, `0090_agent_server_private_key.py`.

**Required changes:**
- Add the minimum `Hardware` schema support required for machine-ID matching: an indexed,
  nullable `machine_id_hash` column.
- Write the alembic migration (upgrade + downgrade) preserving existing `Hardware` records
  (nullable column, no backfill required unless a cheap backfill is obviously correct — do not
  invent unverifiable backfill logic).
- Update the SQLAlchemy `Hardware` model to match.
- Tests: migration upgrade/downgrade round-trips cleanly against a fresh and an existing-data
  fixture DB (follow existing migration test patterns in the backend test suite, if any exist —
  check `apps/backend/tests` for a migration test harness first).

---

## Task 17: Hardware proposal precedence and duplicate warnings

**Current state:** `agent_registry.py:159-180` has basic MAC/hostname matching
(`propose_hardware_match`). Duplicate-machine-id warning already exists at pairing lookup per the
survey — verify its current scope.

**Required changes (depends on Task 16's `machine_id_hash` column and Task 2's real MAC/machine-ID
metadata):**
- Complete hardware proposals in confidence order: machine-ID hash, then MAC address, then
  hostname.
- Return the host proposal and duplicate-machine warning from **both** the agent-detail endpoint
  and the pairing lookup endpoint (verify/fix if agent-detail is currently missing this — the
  survey found it present only at pairing lookup).
- Tests: proposal precedence resolves machine-ID match over MAC-only match over hostname-only
  match; duplicate-machine-id warning appears identically from both endpoints.

---

## Task 18: Approval UI — host-link actions and product-ready grant preset

**Current state:** `AgentApprovalModal.jsx` shows hostname/os/arch/fingerprint and 3 raw
capability checkboxes only — no host-link chooser, no duplicate-warning display, no preset logic.

**Required changes (depends on Task 17's proposal/warning data):**
- Expand the approval UI to support: accept proposed Hardware, select another Hardware record,
  create a new Hardware record from reported facts, leave unlinked, review duplicate-machine
  warnings, and choose initial grants.
- Implement the product-ready "normal" approval preset:
  - `host_telemetry`: enabled with Slice 2 defaults.
  - `local_discovery`: enabled with Slice 4 `direct_private` policy.
  - `remote_probe`: enabled with the same derived safe scope but executes nothing until a user
    explicitly assigns a monitor.
  - The approver can opt out of any capability before activation.
  - Upgrades never silently enable a newly introduced capability on an already-approved agent
    (this constrains any future-capability-introduction code path — for this task, ensure the
    approval-time grant set is explicit and persisted, not implicitly "all capabilities on").
- Wire the approval submission to the backend's approve endpoint with the chosen host-link action
  and grant set (verify/extend the endpoint if it doesn't yet accept an explicit host-link
  action — check `api/agents.py`'s approve handler first).
- Tests: each host-link action (accept/select/create/unlinked) submits the expected payload;
  duplicate warning renders when present; default preset matches the specified capability/policy
  values; opt-out before activation is respected.

---

## Task 19: Host-link editing after approval

**Current state:** Unverified — check whether any host-link edit path exists post-approval.

**Required changes:**
- Permit host-link editing after approval (change which Hardware record an approved agent is
  linked to, or unlink/relink).
- Record host-link changes in `agent_events`.
- Tests: editing an approved agent's host link updates the linkage and records an `agent_events`
  row with the change.

---

## Task 20: Agent runtime status file; truthful `cb-agent status`/`version`

**Current state:** No runtime status file exists. `cb-agent status` currently generates a device
key as a side effect (per the survey) instead of reading daemon state. `cb-agent version` doesn't
print the fingerprint.

**Required changes:**
- Persist an atomic runtime status file in the agent state directory (write-to-temp +ᵣename, or
  equivalent atomicity) including: accepted link state, last connection/error, grants, readiness,
  version, and spool statistics.
- Update this file from the daemon's live state (link accept/reject, disconnect, capability
  changes, spool depth changes) at the relevant transition points established by earlier tasks.
- Make `cb-agent status` read this file and report truthful daemon state **without** generating a
  device key as a side effect (fix the current bug).
- Make `cb-agent version` print version and fingerprint when identity (`device.key`) exists.
- Enforce `0600` permissions on the status file (coordinate with Task 30's broader file-permission
  validation, but set the mode here at creation).
- Tests: `status` reflects a running daemon's real state read from the file, doesn't touch
  `device.key` when none exists; `version` prints the fingerprint only when identity exists.

---

## Task 21: Redis-backed anonymous endpoint protection for enroll/link

**Current state:** `core/rate_limit.py` has generic slowapi profiles but none applied to WS
`/enroll` or `/link`. `agent_enrollment.is_pairing_locked_out` already implements a per-IP
pairing-miss lockout (10/15min) that can be reused/extended, not reinvented.

**Required changes:**
- Add per-IP and global enrollment/link attempt limits before expensive Noise processing begins
  on the unauthenticated `WS /enroll` and `WS /link` endpoints.
- Add a concurrent pending-enrollment limit.
- Reuse the existing per-IP/global pairing-code miss lockout pattern (extend if it doesn't yet
  cover "global", only "per-IP").
- Use expiring Redis counters; return security-safe close/error responses (no information leakage
  about why a request was rejected beyond generic rate-limit signaling) before any Noise
  handshake bytes are processed.
- Tests: exceeding per-IP limit rejects further attempts from that IP; exceeding global limit
  rejects regardless of IP; concurrent-pending-enrollment cap rejects new pending enrollments past
  the limit; counters expire and allow retry after the window.

---

## Task 22: Fail-closed install-command generation

**Current state:** `agent_install.py`'s `_tls_mode_and_pin` falls back to an empty self-signed pin
when the live certificate/SPKI pin can't be obtained (confirmed gap).

**Required changes:**
- Fail closed when generating a self-signed install command if the live certificate/SPKI pin
  cannot be obtained — return a clear error, never emit an empty-pin self-signed configuration.
- Tests: simulate cert/pin retrieval failure and assert the install-command generation errors
  clearly rather than producing an empty-pin script.

---

## Task 23: Update download hardening and semantic-version selection

**Current state:** `internal/update/update.go` downloads via plain `http.Get` (bypassing the
pinned `tlsdial` dialer used elsewhere), compares SHA-256 via naive non-constant-time string
compare, and `agent_update.py`'s `latest_version` uses lexicographic ordering.

**Required changes:**
- Use the configured TLS trust/pin policy for update downloads (route through the same pinned
  dialer/transport used for the link connection, not a bare `http.Get`).
- Apply request timeouts and response-size limits to the download.
- Compare SHA-256 values case-insensitively in constant time (`crypto/subtle`-equivalent on Go
  side; `hmac.compare_digest`-equivalent on Python side if any hash comparison happens
  server-side).
- Replace lexicographic release selection with semantic-version ordering
  (`agent_update.py:latest_version` and `agent_install.py:render_install_script`'s selection
  logic) and reject update requests incompatible with the agent's reported OS/architecture.
- Tests: download rejects on pin mismatch/timeout/oversize response; hash comparison is
  constant-time and case-insensitive (test with mixed-case hex); version selection picks the
  highest semver, not the lexicographically-last string (e.g. `1.9.0` vs `1.10.0`); OS/arch
  mismatch is rejected.

---

## Task 24: Update lifecycle event granularity

**Current state:** Only `version_changed` is recorded, at request time (`api/agents.py:post_update`)
— no `update_queued/started/succeeded/failed/rolled_back` distinction.

**Required changes:**
- Record `update_queued`, `update_started`, `update_succeeded`, `update_failed`, and
  `update_rolled_back` as distinct `agent_events` at their respective real transition points
  (queue-time, download-start, swap-success, failure, rollback), sourced from actual daemon
  status-file transitions (Task 20) or explicit update-flow signals, not all fired at request
  time.
- Do **not** record `version_changed` until the new binary reconnects and reports the target
  version (i.e., derive it from Task 7's hello-metadata persistence reaching the expected version,
  not from the update request itself).
- Tests: a simulated update flow produces the five events at the correct points; `version_changed`
  only appears after a simulated reconnect at the new version, not at request time.

---

## Task 25: Durable update swap and rollback

**Current state:** `internal/update/update.go` does a rename-based swap with a `.previous` backup;
the 2-minute rollback timer in `main.go:72-86` is keyed off the premature `OnConnected` (fixed in
Task 4 to trigger off `hello.ack` instead).

**Required changes:**
- Sync the downloaded file (fsync) before replacement.
- Preserve executable ownership/mode across the swap.
- Atomically write the rollback marker before executing the replacement (not after).
- Retain the previous binary until a successful `hello.ack` is received post-update (using Task
  4's hello.ack-gated trigger).
- Roll back after two minutes without an accepted link.
- Tests: simulated update-then-crash-before-restart leaves the rollback marker in a recoverable
  state; a restart without `hello.ack` within 2 minutes triggers rollback to the previous binary;
  a restart that gets `hello.ack` within 2 minutes retains the new binary and clears the marker.

---

## Task 26: Wire the spool into the daemon's outbound data path

**Current state:** `internal/spool/spool.go` implements bounded append/replay and is tested in
isolation, but is never called from `main.go`/`link.go` — no data frames flow through it.

**Required changes:**
- Spool only data frames (not heartbeat or control traffic — per Global Constraints, no
  telemetry/probe/discovery frames exist yet in Slice 1, so in practice the spool stays idle
  end-to-end today; wire the *mechanism* correctly so it activates automatically once Slice 2+
  introduces data frames).
- Recover valid segments after an unclean shutdown (verify existing spool recovery logic is
  invoked at daemon startup).
- Drop oldest segments at the configured cap (verify existing cap-eviction logic is reachable from
  the live path).
- Drain one stored frame per four live data frames when live data frames are flowing.
- Never spool heartbeat or control traffic — assert this explicitly in the wiring (a heartbeat or
  control frame must never reach the spool's write path).
- Tests: with a fake "data frame" type injected for test purposes (since no real data frame type
  exists yet in Slice 1), verify spool-write on send failure, cap eviction, unclean-shutdown
  recovery, and 1:4 drain ratio all trigger correctly through the wired path; verify heartbeat/
  control frames never reach the spool.

---

## Task 27: Device-key rotation over the authenticated channel

**Current state:** No device-key rotation implementation exists (no schema fields beyond Task 1's
`key.rotate` payload shape, no state machine, no promotion logic).

**Required changes (depends on Task 1's `key.rotate` schema):**
- Store a pending device public key server-side (new nullable column(s) + expiry timestamp on the
  `Agent` model, via alembic migration).
- Acknowledge the pending key before the agent atomically replaces `device.key`.
- Accept either the current or pending identity during the transition window (Noise handshake
  responder logic in `agent_crypto.py` must recognize both).
- Promote the pending identity on its first successful link and record the event in
  `agent_events`.
- Device-key transition window defaults to 15 minutes (Global Constraints).
- Tests: rotation start persists pending key + expiry; handshake succeeds against current key
  before promotion and against the new key after promotion; promotion on first successful link
  with the new key records the event and clears the pending state; expired pending rotation is
  rejected/cleared.

---

## Task 28: Server-key rotation with overlap window

**Current state:** No server-key rotation implementation exists. Server currently has a single
identity key (`core/agent_crypto.py`, vault-persisted).

**Required changes (depends on Task 1's `key.rotate` schema):**
- Support current/successor server keys with an overlap window (default 7 days, Global
  Constraints).
- Advertise the successor key over authenticated links (via `key.rotate`).
- Persist both pins on agents (schema fields via migration).
- Accept Noise handshakes against either private key during the overlap window
  (`agent_crypto.py`'s responder must try both).
- Generate new install scripts with the successor key after activation (coordinate with Task 22's
  install-command generation).
- Retire the previous key only after the configured overlap elapses.
- Add admin server-key rotation status/start endpoints; reject starting a second rotation during
  an active overlap.
- Tests: starting rotation while one is active is rejected; handshakes succeed against both keys
  during overlap; install scripts reflect the successor after activation; the previous key is
  retired (no longer accepted) only after the overlap window elapses (use an injectable/advanceable
  clock, not a real 7-day wait).

---

## Task 29: Self-performing `cb-agent uninstall`

**Current state:** `main.go`'s `runUninstall` sends a best-effort `uninstall` frame, then only
*prints* systemctl/rm commands for the operator — it doesn't require root, doesn't disable the
service, doesn't remove files, doesn't reload systemd.

**Required changes:**
- Require root to run `cb-agent uninstall`.
- Notify the server best-effort (keep the existing `uninstall` frame send).
- Disable the systemd service, remove its unit file/binary/config/state directory, reload
  systemd — actually perform these actions, not print instructions.
- Report exactly what was removed (a clear summary of files/units touched).
- Server side: preserve the agent's server row as revoked for audit (verify current revoke
  behavior already does this via the existing `uninstall` frame handling in `agent_link.py`; fix
  if it doesn't).
- Tests: non-root invocation refuses with a clear error; root invocation removes the expected
  unit/binary/config/state paths and reloads systemd (use a temp-directory/fake-systemctl harness
  matching existing Go test conventions for filesystem-touching commands); server row remains
  present with `revoked` status after uninstall notification.

---

## Task 30: Systemd sandbox and file-permission validation

**Current state:** Systemd sandbox and dedicated-user model already exist per the original Slice 1
plan — this task audits and closes any gaps, it does not build the sandbox from scratch.

**Required changes:**
- Validate state/config directory and file ownership matches the dedicated agent user at daemon
  startup (fail loudly, don't silently continue, if ownership is wrong).
- Enforce `0600` on identity (`device.key`), grant, and status files (status file mode was set at
  creation in Task 20 — this task adds a startup-time audit/enforcement pass covering all three
  file classes, correcting mode if found wrong).
- Tests: daemon startup rejects/corrects wrong ownership and wrong file modes on identity/grant/
  status files; correct ownership/modes pass silently.

---

## Task 31: Docker E2E — full 12-step acceptance flow

**Current state:** `apps/agent/e2e/` has a working single-scenario harness
(Dockerfile, docker-compose.yml, `supervisord-e2e.conf`, `test_agent_e2e.py`) but not yet the full
12-step flow.

**Required changes — expand the harness to cover, in order:**
1. Fetch and verify the install script and binary.
2. Enroll a real Go agent.
3. Observe the pending agent through the UI stream without polling.
4. Approve with default grants and a host-link selection.
5. Observe `online=true` and heartbeats.
6. Change grants and verify the running agent receives them.
7. Perform a successful update and a forced rollback case.
8. Exercise a Noise rekey interval with an accelerated test clock.
9. Revoke and verify immediate socket closure/offline state.
10. Uninstall and verify server audit state.
11. Run the agent behind a separate NAT/network namespace with no inbound route and verify the
    complete enroll, approve, heartbeat, control, and reconnect lifecycle over outbound WSS only.
12. Restart the remote host and backend independently and verify the agent returns without a new
    command, pairing code, certificate action, or configuration edit.

This task depends on essentially every prior task being complete (it is the integration proof for
the whole plan) — do not start it until Tasks 1-30 are done and their individual test suites pass.

**Tests:** the E2E harness itself, run via its existing Docker Compose invocation pattern; each of
the 12 steps must have a clear pass/fail assertion in `test_agent_e2e.py` or equivalent.

---

## Task 32: Release gate verification

**Current state:** N/A — this is a verification-only task, no new implementation expected unless
gate checks surface a real regression.

**Required changes:**
- Run and confirm green: full Go suite (`apps/agent`), full backend suite, full frontend suite.
- Run and confirm green: Docker E2E (Task 31) on linux/amd64.
- Verify cross-compiled amd64/arm64 binaries match the generated manifest (use the project's
  existing cross-compile/manifest tooling — locate it under `apps/agent` build scripts or CI
  config before assuming it needs to be created).
- Verify a fresh mono deployment migrates successfully (run the alembic migration chain against a
  fresh DB).
- Verify existing-agent upgrade from the current Slice 1 build remains enroll/link compatible
  (exercise Task 1's backward-compatibility guarantee: an old-shaped `hello` still gets a valid
  `hello.ack`).
- If any gate fails, do not fix it inline as part of this task — report the specific failure; it
  routes back to the task whose area regressed.

**No commit expected** unless a genuine fix was required and routed back to the owning task's
area; if so, that fix belongs in a small dedicated follow-up, not folded silently into this
verification task.
