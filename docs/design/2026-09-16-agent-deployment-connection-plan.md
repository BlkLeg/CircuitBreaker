# Agent deployment connection resilience plan

**Status:** proposed.  
**Scope:** `apps/agent` self-update deployment over the outbound WebSocket link and
the associated HTTPS binary download.  
**Related code:** `apps/agent/internal/link/link.go`,
`apps/agent/cmd/cb-agent/daemon.go`, `apps/agent/internal/update/update.go`.

## 1. Problem statement

The agent can lose its remote connection while applying an update because the
update callback runs synchronously on `link.runOnce`'s single event-loop
goroutine. The callback downloads and verifies the binary, writes the update
marker, swaps the version symlink, sends status, and re-executes the process.
During that work the event loop cannot send its 20-second heartbeat or process
inbound frames.

The reader goroutine delivers decoded frames through an unbuffered
`incoming` channel. Once the event loop is occupied by the update, the reader
can stop consuming the WebSocket. The backend's dead-link timeout can then
close an otherwise usable connection, particularly because the update download
has a two-minute client timeout while the steady-state link declares 60 seconds
of inbound silence.

The update's `succeeded` status has a separate delivery gap: it is written to
the socket immediately before `syscall.Exec`. A successful local WebSocket
write is not an acknowledgement from the server, so process replacement can
discard the status before the backend receives or handles it. The durable
rollback marker and pending outcome report provide recovery, but the live
status is not guaranteed.

There is no SSH/SCP deployment transport in the agent. “Remote deployment” in
this plan means a server-issued update instruction delivered over `/link`,
followed by the agent's pinned HTTPS download.

## 2. Goals and non-goals

### Goals

1. Keep the link event loop responsive while a potentially long update is in
   progress.
2. Preserve the existing single-writer WebSocket rule, sequence ordering,
   reconnect behavior, rollback marker semantics, and signed-update checks.
3. Make update status delivery resilient to a connection drop immediately
   before re-exec.
4. Ensure only one update is applied at a time and define behavior for a second
   update instruction received during an active update.
5. Preserve bounded shutdown and avoid goroutine leaks across reconnects.
6. Add tests that reproduce the timing failure rather than only testing the
   happy path.

### Non-goals

- Replacing WebSocket/Noise with SSH, SCP, gRPC, or another deployment
  transport.
- Changing TLS pinning, Noise authentication, signed-binary verification, or
  rollback policy.
- Making a long-running binary download itself part of the WebSocket protocol.
- Adding a second concurrent WebSocket writer.

## 3. Proposed design

### 3.1 Move update execution off the link event loop

Change `link.Options.OnUpdate` from an inline operation into a serialized
update-dispatch boundary. The inbound `TypeUpdate` arm should validate and
enqueue the payload, then return to the main select loop immediately.

The daemon owns a single update worker and a bounded queue of one pending
instruction. The worker performs the existing download, signature verification,
marker, swap, and re-exec sequence. A second instruction received while one is
queued or running is not applied concurrently; it is rejected or reported as a
failed update according to the existing update-status contract, with an
explicit reason such as “update already in progress.” The chosen behavior must
be deterministic and tested.

The worker must stop accepting new work when the parent context is cancelled.
If cancellation occurs during a download, the HTTP request must be canceled
through a context-aware request so shutdown does not wait for the full
`downloadTimeout`.

The worker must not write directly to the WebSocket. Status messages should
cross back to the link owner through a connection-scoped status sender or a
control-frame channel that the event loop drains. This retains gorilla
WebSocket's one-writer invariant and keeps sequence numbers owned by the
event-loop goroutine.

### 3.2 Keep liveness and inbound processing independent

While the worker is downloading or installing:

- the reader goroutine continues receiving and decoding frames;
- the event loop continues heartbeats, read-error handling, rekey handling, and
  connection shutdown;
- update progress/status requests are best-effort queued to the active
  connection;
- a connection drop does not cancel the filesystem update unless the update
  context itself is canceled.

The event loop must remain responsive even when the worker blocks on network
I/O or filesystem sync. A test should prove that a heartbeat is emitted while
the update callback is deliberately blocked.

### 3.3 Make update status durable across re-exec

Retain the current durable rollback marker and pending rollback-report file,
and extend the same principle to update outcome reporting where needed:

1. Persist the update phase/version before attempting a status send that must
   survive a connection loss.
2. Attempt to send `started`, `failed`, or `succeeded` through the current
   connection when available.
3. For `succeeded`, do not claim delivery solely from `WriteMessage`.
4. Before re-exec, either wait for the server's existing delivery
   acknowledgement mechanism or persist a pending outcome for the next process
   to report after its first accepted `hello.ack`.
5. Clear the pending outcome only after the status has been written
   successfully on an accepted connection, matching the existing
   rollback-report clearing rule.

The implementation should prefer the existing `data.ack`/watermark mechanism
where it can safely cover `update.status`; otherwise it should add a small
durable update-outcome record rather than inventing a second acknowledgement
protocol. The server-side state machine must remain idempotent for a repeated
`succeeded` report after reconnect.

### 3.4 Preserve update and reconnect ordering

The update worker must capture the trust policy once per update, as the current
implementation does, and must not start a second update after `syscall.Exec`.
A link reconnect during an in-progress update may report the prior process's
pending outcome, but it must not cause the old process to execute the update
again.

The update marker remains written before the swap. `MarkSwapped` remains the
transition that records the actual previous version and confirmation deadline.
No change should weaken signature enforcement, path validation, fsync, atomic
symlink replacement, or startup rollback handling.

## 4. Implementation phases

### Phase 1: Define the ownership and wire contract

- Introduce an update-job type containing the raw instruction and a
  cancellation/context handle.
- Define queue capacity, duplicate-update behavior, shutdown behavior, and the
  status event shape.
- Document which goroutine owns sequence numbers and WebSocket writes.
- Confirm whether the existing `data.ack` contract covers control/status frames;
  if not, use a durable pending-outcome file for the pre-reexec gap.

### Phase 2: Refactor agent link dispatch

- Replace synchronous `opts.OnUpdate` execution in the `TypeUpdate` switch with
  enqueue-only dispatch.
- Add a context-aware update result/status path back to the event loop.
- Ensure queue-full and worker-start errors are surfaced as update failures, not
  silently dropped.
- Keep all existing heartbeat, rekey, read-deadline, and reconnect behavior
  unchanged outside the dispatch boundary.

### Phase 3: Refactor daemon update execution

- Move the current `onUpdate` body into the serialized worker.
- Add cancellation propagation to binary and signature downloads.
- Persist any outcome that must survive re-exec or connection loss.
- Attempt acknowledged/durable success reporting before `syscall.Exec`.
- Reuse the existing startup pending-outcome report and clear it only after a
  successful send.

### Phase 4: Backend idempotency and observability

- Verify repeated `update.status` reports do not regress a terminal update
  state or create duplicate alerts.
- Preserve the current version/phase/error semantics exposed to the UI.
- Add structured logs for update queued, rejected as duplicate, canceled,
  status deferred, status replayed, and re-exec started.
- Do not log credentials, binary contents, tokens, or signing material.

### Phase 5: Test and rollout

- Run targeted agent unit tests, integration tests, and the repository's
  required verification tier for backend or frontend changes.
- Exercise a real remote-like deployment with an induced network drop during
  download and immediately before re-exec.
- Roll out behind the existing update channel controls, monitor reconnects and
  update status convergence, then remove any temporary test-only hooks if the
  implementation introduces them.

## 5. Required tests

### Link lifecycle tests

- A blocked update worker does not prevent heartbeats from being written.
- Inbound frames continue to be read and dispatched while an update is active.
- A read deadline or server disconnect still terminates the connection while
  the update worker is blocked.
- A reconnect does not start a second update worker for the same instruction.
- Queue-full behavior produces an explicit failed status.
- Context cancellation stops the worker and does not leave a goroutine blocked
  on an unbuffered channel.
- WebSocket writes remain serialized through the event-loop owner.

### Update and durability tests

- Download cancellation interrupts a stalled HTTP response.
- A connection drop after `succeeded` is staged still produces a pending outcome
  that the next process reports.
- A repeated pending outcome is cleared only after a successful accepted-link
  send.
- Existing marker states (`pending-swap`, `pending-confirm`, expired
  rollback) retain their current behavior.
- A failed signature, hash, swap, or marker operation never reports success and
  leaves no misleading pending outcome.

### End-to-end deployment tests

- Start an agent and server, issue an update, and verify heartbeats continue
  during a deliberately slow binary response.
- Disconnect the network during the download; verify reconnect and eventual
  update outcome without data-loss or crash-loop behavior.
- Disconnect immediately before process replacement; verify the new process
  reconnects and reports the outcome.
- Verify the server accepts an idempotent replay without duplicating the
  update record or incorrectly regressing its state.

## 6. Acceptance criteria

The change is ready when all of the following are true:

1. A slow or stalled update cannot occupy the link event loop long enough to
   miss heartbeats or stop inbound frame processing.
2. A connection drop during any update phase results in reconnect/backoff
   rather than a permanently stuck link or duplicate concurrent update.
3. Update outcomes converge on the server after a drop before or during
   re-exec, using acknowledged delivery or durable replay.
4. Existing signed-update, TLS pinning, Noise, spool, rollback, and shutdown
   tests remain green.
5. Logs and UI state distinguish queued, active, failed, deferred, replayed,
   and confirmed update outcomes without exposing secret material.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Two goroutines write WebSocket frames concurrently | Route all status/control writes through the existing event-loop writer. |
| Update worker outlives a canceled link and leaks | Give it a context, bounded queue, explicit shutdown path, and cancellation test. |
| Replaying success creates duplicate server state | Make the backend update-status transition idempotent and test repeated reports. |
| Waiting for an acknowledgement delays re-exec indefinitely | Use a bounded acknowledgement wait, then persist the outcome for replay. |
| A failed persistence write hides the real update result | Log the persistence error explicitly and keep the existing rollback safety behavior; never emit a false success. |
| A second server instruction races the first update | Serialize updates and return an explicit duplicate/in-progress result. |
| Refactor changes frame ordering or sequence ownership | Keep sequence assignment and encryption in the link event-loop goroutine and add ordering assertions. |
