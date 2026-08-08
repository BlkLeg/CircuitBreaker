# cbi-agent Slice 1 Gap-Closure Plan

**Date:** 2026-08-04
**Status:** Reviewed for cross-slice E2E implementation
**Related:** `specs/2026-07-26-cb-agent-design.md`, `plans/2026-07-27-cb-agent-slice1.md`

## Summary

Bring Slice 1 into full conformance with the approved design: a user can install an agent, see
it appear instantly, approve and link it, observe accurate presence, manage capabilities,
update or uninstall it safely, and rely on the specified Noise security and recovery
guarantees.

The deployment experience is one generated copy/paste command on the remote Linux host. The
installer writes all server identity and enrollment configuration, installs and starts the
service, and the daemon maintains one outbound WSS connection home. The remote subnet requires no
inbound port, firewall rule, scanner package, CIDR entry, certificate copy, or recurring operator
action. Approval in the Circuit Breaker UI is the only required post-install security step.

Implementation order is protocol correctness, live control plane, enrollment and UI
completeness, security and lifecycle, then release validation.

## Implementation Changes

### 1. Protocol and link correctness

- Extend protocol v1 with:
  - A real `hello` payload containing agent version, OS/version, architecture, MACs,
    readiness, and spool depth.
  - `hello.ack` containing acceptance, server time, authoritative grants, and agent ID.
  - `transport.rekey` for independent inbound/outbound Noise cipher rekeying.
  - Structured `key.rotate` payloads for device and server-key rotation.
- Make every sender assign strictly increasing per-session sequence numbers. Reject duplicate,
  decreasing, unsupported-version, and malformed frames; record security-relevant violations.
- Call the agent's successful-link callback only after a valid `hello.ack`. Use that
  acknowledgment, not completion of the Noise handshake, to clear an update rollback marker.
- Reset reconnect backoff after a stable accepted link; preserve the 1-second to 5-minute
  jittered progression for consecutive failures.
- Rekey each outbound Noise cipher every 15 minutes:
  - Send `transport.rekey` with the old outbound key.
  - Rekey the sender immediately after sending.
  - Rekey the receiver's matching inbound cipher immediately after decrypting the control
    frame.
- Add WebSocket ping deadlines alongside application heartbeats. A valid heartbeat refreshes
  presence; arbitrary traffic must not indefinitely mask missed heartbeats.
- Update the agent row from accepted `hello` metadata, including the successfully running
  version.

### 2. Live control plane and presence

- Introduce a cross-worker agent connection/control service backed by Redis pub/sub:
  - Register the worker owning each connected agent.
  - Deliver `capabilities.set`, `update`, `disconnect`, key-rotation, and ping frames
    immediately.
  - Remove connection registrations on disconnect or TTL expiration.
- Broadcast an `enrolled` event immediately after creating a pending agent so the add-agent
  panel updates without polling.
- Push capability changes to connected agents after committing them. Preserve database state
  as authoritative and resend the complete set on every `hello.ack`.
- Make revoke and reject publish `disconnect` immediately; keep the database-status poll as
  recovery if pub/sub delivery fails.
- Add bulk presence lookup to the fleet REST service and expose:
  - `online`
  - `connected_since`
  - `last_seen_at`
  - capability grants
  - linked-hardware summary
- Update `AgentsPage` and `AgentDetailPage` to consume connected/disconnected/enrolled events,
  refresh newly enrolled records, and render accurate online/offline state.
- Add the specified status, capability, and online filters. Keep pending agents pinned above
  the fleet table.
- Treat the agent link as a long-lived outbound tunnel-like control/data channel:
  - Use only outbound HTTPS/WSS from the agent; never listen on a remote-subnet port.
  - Carry every later capability request and data frame over that connection.
  - Reconnect indefinitely across address changes, NAT rebinding, backend restarts, and temporary
    WAN loss without re-enrollment.
  - Honor standard `HTTPS_PROXY`/`NO_PROXY` behavior so egress-controlled remote sites do not
    require agent-specific proxy configuration.

### 3. Enrollment, host linkage, and agent state

- Collect real enrollment metadata:
  - `/etc/os-release` name/version
  - normalized primary MAC addresses, excluding loopback and invalid addresses
  - machine-ID hash with trimmed source data
  - build version and architecture
- Complete hardware proposals in confidence order:
  - machine-ID hash
  - MAC address
  - hostname
- Add the minimum Hardware schema support required for machine-ID matching, with an indexed
  nullable hash and a migration that preserves existing records.
- Return the host proposal and duplicate-machine warning from agent detail as well as pairing
  lookup.
- Expand the approval UI to support:
  - Accept proposed Hardware
  - Select another Hardware record
  - Create a new Hardware record from reported facts
  - Leave unlinked
  - Review duplicate-machine warnings
  - Choose initial grants
- Make the normal approval preset product-ready:
  - `host_telemetry`: enabled with Slice 2 defaults.
  - `local_discovery`: enabled with Slice 4 `direct_private` policy.
  - `remote_probe`: enabled with the same derived safe scope but executes nothing until a user
    explicitly assigns a monitor.
  - The approver can opt out of any capability before activation; upgrades never silently enable
    a newly introduced capability on an already approved agent.
- Permit host-link editing after approval and record changes in `agent_events`.
- Persist an atomic runtime status file in the agent state directory. Include accepted link
  state, last connection/error, grants, readiness, version, and spool statistics.
- Make `cb-agent status` read this state and report truthful daemon state without generating a
  device key as a side effect.
- Make `cb-agent version` print version and fingerprint when identity exists.

### 4. Security, rotation, updates, spool, and uninstall

- Add Redis-backed anonymous endpoint protection before expensive Noise processing:
  - Per-IP and global enrollment/link attempt limits
  - Concurrent pending-enrollment limits
  - Per-IP and global pairing-code miss lockouts
  - Expiring counters and security-safe close/error responses
- Fail closed when generating a self-signed install command if the live certificate/SPKI pin
  cannot be obtained. Never emit an empty-pin self-signed configuration.
- Use the configured TLS trust/pin policy for update downloads, apply request timeouts and
  response-size limits, and compare SHA-256 values case-insensitively in constant time.
- Replace lexicographic release selection with semantic-version ordering and reject update
  requests incompatible with the agent OS/architecture.
- Record `update_queued`, `update_started`, `update_succeeded`, `update_failed`, and
  `update_rolled_back` separately. Do not record `version_changed` until the new binary
  reconnects and reports the target version.
- Make update swapping durable:
  - Sync the downloaded file before replacement.
  - Preserve executable ownership/mode.
  - Atomically write the rollback marker before executing the replacement.
  - Retain the previous binary until successful `hello.ack`.
  - Roll back after two minutes without an accepted link.
- Wire the spool into the daemon's outbound data path:
  - Spool only data frames.
  - Recover valid segments after an unclean shutdown.
  - Drop oldest segments at the configured cap.
  - Drain one stored frame per four live data frames.
  - Never spool heartbeat or control traffic.
- Add device-key rotation over the authenticated old-key channel:
  - Store a pending device public key server-side.
  - Acknowledge it before the agent atomically replaces `device.key`.
  - Accept current or pending identity during the transition.
  - Promote the pending identity on its first successful link and record the event.
- Add server-key rotation with current/successor keys and an overlap window:
  - Advertise the successor over authenticated links.
  - Persist both pins on agents.
  - Accept Noise handshakes against either private key during overlap.
  - Generate new install scripts with the successor after activation.
  - Retire the previous key only after the configured overlap.
- Make `cb-agent uninstall` require root, notify the server best-effort, disable the service,
  remove its unit/binary/config/state, reload systemd, and report exactly what was removed.
  Preserve the server row as revoked for audit.
- Keep the systemd sandbox and dedicated-user model. Validate state/config ownership and
  enforce `0600` identity/grant/status files.

## Public Interfaces and Data Changes

- Protocol additions: enriched `hello`, authoritative `hello.ack`, `transport.rekey`, and
  structured `key.rotate`.
- Fleet responses gain `online`, `connected_since`, capabilities, linked-hardware summary,
  readiness, and spool status.
- Approval accepts an explicit host-link action: existing ID, create from reported facts, or
  unlinked.
- Add admin server-key rotation status/start endpoints; reject starting a second rotation
  during an active overlap.
- Add nullable Hardware machine-ID hash support and agent pending-device-key rotation fields
  with expiry timestamps.
- Keep all existing agent URLs and protocol-v1 frame names backward compatible. Agents lacking
  the new hello fields receive safe defaults; the server advertises the minimum supported
  agent version and rejects versions that cannot safely participate.

## Test and Acceptance Plan

### Go unit tests

- Hello/ack acceptance and rejection
- Monotonic sequences and replay rejection
- Bidirectional timed rekey across multiple intervals
- Backoff reset after a stable link
- Metadata collection
- TLS-pinned update download
- Successful update, timeout rollback, and restart during update
- Spool integration, cap enforcement, recovery, and 1:4 draining
- Device/server key overlap
- Status and uninstall behavior

### Backend tests

- Anonymous socket rate/global limits
- Enrolled-event broadcast
- Bulk presence and TTL transitions
- Immediate grant/revoke delivery across workers
- Hello metadata/version persistence
- Host proposal precedence and duplicate warnings
- Semantic update selection and lifecycle events
- Device/server rotation promotion, expiry, and overlap
- Migration upgrade/downgrade and fresh-volume bootstrap exclusions

### Frontend tests

- New pending agent appears from a live event
- Connected/disconnected rendering
- Filters and pending pinning
- Host proposal/create/unlinked approval
- Capability delivery feedback
- Readiness/spool/update state rendering

### Docker end-to-end acceptance

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

### Release gates

- Full Go, backend, and frontend suites pass.
- Docker E2E passes on linux/amd64.
- Cross-compiled amd64/arm64 binaries match the generated manifest.
- Fresh mono deployment migrates successfully.
- Existing-agent upgrade from the current Slice 1 build remains enroll/link compatible.
- The cross-slice remote-subnet journey in
  `plans/2026-08-04-cbi-agent-e2e-cohesion-review.md` passes before the agent feature is declared
  complete.

## Assumptions and Defaults

- "Complete Slice 1" means full approved-spec closure; host telemetry, remote-probe execution,
  and local-discovery collectors remain in Slices 2-4.
- Redis is required for live presence, control delivery, rate limiting, pairing, and updates.
  REST remains available when Redis is degraded, but agent enrollment/control operations fail
  clearly rather than silently weakening guarantees.
- The authenticated old Noise channel authorizes device-key rotation; X25519 keys are not
  treated as signing keys.
- Server-key overlap defaults to seven days; device-key transition defaults to 15 minutes.
- Protocol rekey remains at 15 minutes and heartbeat/dead thresholds remain 20/60 seconds.
- The spool is integrated now but remains idle in heartbeat-only Slice 1 operation.
- “No extra setup” means no configuration on the remote subnet beyond running the generated
  install command. Circuit Breaker's advertised agent URL must still be reachable from the remote
  host over HTTPS. A hosted rendezvous/relay that makes a private main installation reachable is a
  separate product capability and is not silently assumed by these slices.
- The install command must use a configured canonical agent URL when present, not blindly derive
  an internal Docker hostname or request host that external agents cannot reach. The UI validates
  that URL and explains the single outbound-HTTPS prerequisite before displaying the command.
