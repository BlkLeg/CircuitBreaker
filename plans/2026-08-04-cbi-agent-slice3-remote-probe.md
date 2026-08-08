# cbi-agent Slice 3 — Remote Probe Plan

**Date:** 2026-08-04
**Status:** Reviewed for cross-slice E2E implementation
**Related:** `specs/2026-07-26-cb-agent-design.md`,
`plans/2026-08-04-cbi-agent-slice1-gap-closure.md`,
`plans/2026-08-04-cbi-agent-slice2-host-telemetry.md`

## Summary

Add agent-based execution for existing ICMP, TCP, HTTP(S), and DNS monitors while retaining
the backend as the authoritative scheduler and state machine.

A monitor explicitly selects either:

- Server — current behavior.
- A specific agent — all checks run from that agent's network position.

There is no automatic fallback between vantage points. If an assigned agent is unavailable,
the monitor retains its last target UP/DOWN state and displays a separate probe-unavailable
condition. This avoids false state changes and alert storms.

No software, listener, firewall rule, credential, or local schedule is configured on the remote
subnet. Once the agent is approved, its reported directly connected networks make it immediately
eligible as a monitor vantage. Selecting that vantage while creating a monitor is ordinary monitor
configuration, not agent deployment setup.

Slice 3 depends on the Slice 1 gap closure. It also assumes the collector/readiness framework
and structured capability configuration established by Slice 2.

## 1. Data Model

### Monitor assignment

Add to `monitor_items`:

- `probe_agent_id`: nullable FK to `agents`; `NULL` means server execution.
- `probe_execution_status`: `ready|queued|running|unavailable|stale`.
- `probe_execution_reason`: nullable bounded text.
- `probe_last_dispatched_at`.
- `probe_last_result_at`.

Create a composite index on `(probe_agent_id, enabled, next_due_at)` for assignment listings
and due-monitor scheduling.

Use a restrictive agent FK lifecycle:

- Revocation preserves assignments but makes them unavailable.
- Deleting an agent with assigned monitors returns `409`.
- The user must first reassign, unassign, or delete those monitors.
- Unassigning explicitly changes the vantage to the server; it never happens implicitly.

### Probe runs

Add `monitor_probe_runs` as the durable assignment/lease record:

- Sequential primary key and opaque random 128-bit `run_id`.
- `monitor_id` and `agent_id` indexed FKs.
- `status`: `queued|dispatched|completed|execution_error|expired|cancelled`.
- Scheduled, dispatched, deadline, started, completed timestamps.
- Result outcome, bounded message, error code, and result metadata.
- Attempt count and creation timestamp.

Indexes:

- `(agent_id, status, scheduled_at)` for dispatcher fairness.
- `(monitor_id, created_at DESC)` for monitor history.
- Partial uniqueness preventing multiple active remote runs for one monitor.

Retain probe runs for seven days. Long-term availability remains in `telemetry_timeseries` and
monitor rollups.

## 2. Scheduling and Dispatch

### Centralized scheduling

Keep the existing backend scheduler authoritative:

1. Claim due monitors with `FOR UPDATE SKIP LOCKED`.
2. Advance `next_due_at`.
3. Route server monitors to `mon.poll.item`.
4. Create a run and route agent monitors to `mon.probe.remote`.
5. The remote dispatcher loads monitor configuration from the database and sends
   `probe.assign` through the Slice 1 live-agent control service.

NATS remote messages contain only `run_id`; credentials and complete monitor configuration are
loaded immediately before encrypted delivery.

### Fair sharing

Prevent one agent or vantage from consuming the full scheduler batch:

- Rank due monitors within each `probe_agent_id`, with server execution treated as its own
  vantage.
- Claim no more than 50 monitors per vantage per scheduler tick.
- Preserve the existing global batch limit of 200.
- Use a separate remote-dispatch durable consumer so blocked agents cannot delay server checks.
- Default each agent to 20 concurrent probes, configurable from 1–100 through the
  `remote_probe` grant.

Agents maintain a bounded queue of 100 assignments. When capacity is exhausted, return an
execution error instead of silently dropping work.

### Execution availability

Before dispatch, require:

- Active agent.
- `remote_probe` grant enabled.
- Live agent connection.
- Compatible remote-probe readiness.
- Target permitted by the grant's network scope.
- No active run already exists for the monitor.

If the agent is offline:

- Do not execute from the server.
- Set `probe_execution_status="unavailable"`.
- Preserve the target's last UP/DOWN state.
- Do not insert an `avail=0` sample or increment target failure retries.
- Schedule the next normal attempt.
- When the agent reconnects, set its assigned monitors due immediately.

"Check now" returns `409` with the availability reason when the selected agent cannot accept
the check.

## 3. Capability and Network Scope

Use one shared agent network-scope evaluator for Slices 3 and 4. It consumes normalized interface
facts and the `direct_private` policy, produces a versioned effective scope, and applies exclusions
and explicit routed overrides. Remote probing and discovery must not implement subtly different
CIDR, special-use, or interface-type rules.

Extend the `remote_probe` capability configuration:

```json
{
  "enabled": true,
  "config": {
    "max_concurrent": 20,
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "additional_hostnames": []
  }
}
```

Rules:

- Remote probing is enabled in the normal approval preset but remains idle until a monitor is
  explicitly assigned. The approved agent receives a derived safe scope automatically from its
  directly connected networks.
- The derived scope contains only private IPv4 and IPv6 ULA unicast networks reported by the agent;
  loopback, link-local, multicast, default routes, public routes, and point-to-point tunnel routes
  are excluded.
- Administrators may narrow or extend the derived scope centrally. Manual scope entry is never
  required for monitors targeting a directly connected remote subnet.
- `0.0.0.0/0` and `::/0` are rejected in v1 rather than treated as convenient shortcuts.
- IP targets must belong to effective scope.
- Hostname targets within a directly connected subnet require no hostname rule: resolve them at
  dispatch and again at the agent, and require every usable resolved IP to belong to effective
  scope. Exact/wildcard `additional_hostnames` apply only to explicitly approved routed use cases.
- Loopback, link-local, multicast, broadcast, unspecified, and cloud metadata destinations remain
  blocked in v1 and cannot be enabled through an override.
- HTTP redirects are validated at every hop.
- Only HTTP and HTTPS URL schemes are permitted.
- DNS resolver destinations are validated like other network targets.

Enforce scope independently:

- Backend validates assignments before saving or dispatching.
- Agent resolves and validates destinations immediately before connecting.
- Violations return an execution error and generate an agent capability-violation event.
- Scope and grant configuration are never host-editable.
- The agent additionally requires a destination to be directly connected unless it is covered by
  an explicit centrally approved override. A compromised route advertisement therefore cannot
  expand the default grant.

Disabling `remote_probe` cancels active runs and marks assigned monitors unavailable without
deleting their assignments.

## 4. Protocol Contract

### `probe.assign`

Server-to-agent control frame:

```json
{
  "run_id": "32 lowercase hex characters",
  "monitor_id": 42,
  "check_type": "http",
  "host": "app.internal.example.com",
  "config": {},
  "scheduled_at": "2026-08-04T18:00:00Z",
  "deadline_at": "2026-08-04T18:00:20Z"
}
```

Assignments are control frames and are never spooled.

### `probe.cancel`

Add a server-to-agent control frame:

```json
{
  "run_id": "…",
  "reason": "monitor_paused"
}
```

Send cancellation when a monitor is paused, deleted, reassigned, its capability is disabled,
or the agent is revoked.

Cancellation is best-effort; the backend remains authoritative and rejects subsequently stale
results.

### `probe.result`

Agent-to-server data frame:

```json
{
  "run_id": "…",
  "monitor_id": 42,
  "outcome": "completed",
  "up": true,
  "started_at": "2026-08-04T18:00:01Z",
  "finished_at": "2026-08-04T18:00:01.124Z",
  "samples": [
    {"metric": "avail", "value": 1},
    {"metric": "latency_ms", "value": 124}
  ],
  "msg": "200 in 124ms",
  "details": {
    "http_status": 200
  }
}
```

Supported outcomes:

- `completed`: a real target result; feed the monitor state machine.
- `execution_error`: agent could not perform the probe; preserve target state.
- `cancelled`: assignment was stopped; preserve target state.
- `rejected`: invalid, unauthorized, out-of-scope, or capacity-limited assignment.

Results are data frames and may spool if the connection drops during execution. The backend
accepts a result only when:

- Run, monitor, and authenticated agent match.
- The run has not already completed.
- It arrives before `deadline_at + 30 seconds`.
- Samples, details, and message satisfy size/type limits.

Late or duplicate results update the run audit state but never change monitor state or uptime.

Limit result details to 64 KiB and messages to 2,000 characters. Never include response bodies,
authorization headers, tokens, or passwords in results or logs.

## 5. Agent Probe Collectors

Add `internal/collect/probe` with one-shot execution and cancellation. Match the existing
backend collector semantics.

### ICMP

- IPv4 and IPv6 unprivileged datagram ICMP.
- Packet count 1–20 and timeout from existing monitor validation.
- Report availability, average/min/max latency, jitter, and packet loss.
- Missing unprivileged ICMP support is an execution error, not target DOWN.
- Continue shipping with no `CAP_NET_RAW`.

### TCP

- Resolve within the permitted scope.
- Connect to configured port or ports with the existing timeout.
- Report availability and successful connection latency.
- Connection refused or timed out is a valid target failure.

### HTTP(S)

Support the current monitor contract:

- Method, headers, request body, basic/bearer authentication.
- Accepted status ranges.
- Keyword and inverted-keyword checks.
- Dotted JSON-path assertions.
- TLS verification and redirect configuration.
- TLS certificate subject, issuer, expiry, and days remaining.
- Bounded one-MiB response inspection for keyword/JSON checks.

Validate every resolved destination and redirect against agent scope. Do not persist assignment
secrets or log request headers/body.

### DNS

Support current record types:

- A, AAAA, CNAME, MX, TXT, NS, SOA, PTR, SRV, and CAA.
- Optional resolver and port.
- Expected-value matching.
- Availability and lookup latency.

### Readiness

Report:

- `probe.icmp`
- `probe.tcp`
- `probe.http`
- `probe.dns`

TCP and HTTP should normally be ready. ICMP reports unavailable when the kernel ping-group
configuration is unusable. DNS reports degraded when no usable resolver is configured.

## 6. Result Processing

Refactor local and remote check completion into one monitor-result service:

- Accept normalized samples, target outcome, message, details, timestamp, source, agent ID,
  and run ID.
- Write `telemetry_timeseries`.
- Apply retry/PENDING/DOWN/UP logic through the existing state machine.
- Publish live monitor status.
- Publish existing recovery/down alerts.
- Preserve maintenance behavior.
- Commit samples, state, events, and run completion atomically.

Server and agent checks must produce the same status, event, history, and alert semantics.

Use `source="monitor"` for availability compatibility and retain remote provenance in
`monitor_probe_runs`. Do not calculate a second uptime path for agent checks.

Execution errors:

- Do not write availability samples.
- Do not increment `consecutive_failures`.
- Do not transition target status.
- Update execution condition and publish a live monitor refresh.
- Record an execution event only when the reason changes, preventing repeated event noise.

Target failures such as timeout, connection refusal, packet loss, DNS failure, HTTP mismatch,
and TLS failure continue through normal retry/down handling.

## 7. API and Frontend

### API changes

Add `probe_agent_id` to monitor create, update, read, overview, and target-monitor schemas.

Monitor responses also include:

```json
{
  "probe_mode": "agent",
  "probe_agent": {
    "id": 7,
    "name": "branch-office"
  },
  "probe_execution_status": "ready",
  "probe_execution_reason": null,
  "probe_last_dispatched_at": null,
  "probe_last_result_at": null
}
```

Add:

- `GET /api/v1/agents/{id}/probes` — assigned monitors with current state.
- `GET /api/v1/monitors/{id}/probe-runs` — bounded recent execution history.
- An eligible-agent listing including online state, grant, readiness, concurrency, and scope
  compatibility.

Assignment writes require editor-level monitor permission. Grant and scope changes remain
admin-only.

Validate tenant compatibility when both the agent and target belong to tenants.

### Monitor UI

Add "Run from" to create/edit forms:

- Circuit Breaker server, default.
- Eligible named agents.
- Online/readiness/scope indicators.
- Warnings for offline agents or changed network vantage.
- Scope validation before saving.

Monitor cards and detail pages show:

- "via Server" or "via Agent Name."
- A secondary `probe unavailable`, `queued`, `running`, or `stale` condition.
- Last successful result time.
- Link to the assigned agent.
- Probe-run history and execution errors separately from target state transitions.

The main UP/DOWN status pill retains the last target state when execution is unavailable.

### Agent UI

Add an Assigned Probes section to Agent Detail:

- Monitor name, type, target, interval, target state, execution condition, and last result.
- Open monitor, check now, reassign, and return-to-server actions.
- Concurrency usage and configured limit.
- Readiness and scope summary.

Disabling remote probing with assignments requires confirmation and explains that monitors
will retain their last target state while becoming probe-unavailable.

Offer “Create monitor from this agent” actions for devices found in Slice 4. These preselect the
agent vantage and target while leaving monitor type, interval, and alert policy under user control.

## 8. Failure and Lifecycle Behavior

- Agent disconnects before dispatch: no target result; execution becomes unavailable.
- Agent disconnects during a check: result may spool; accept only within the result deadline.
- Monitor pauses/deletes/reassigns: cancel active run and reject later results.
- Agent reconnects: assigned monitors become immediately due.
- Agent revokes: cancel runs and preserve assignments as unavailable.
- Agent deletion: blocked while assignments remain.
- Capability scope shrinks: incompatible assignments become unavailable; do not silently modify
  their targets.
- Duplicate result: idempotent no-op.
- Spoofed monitor/run ID: reject and record a capability violation.
- Backend restart: queued/dispatched runs are reconciled; expired runs become unavailable
  without target transitions.
- NATS publication failure: mark dispatch failure and retry scheduling soon without counting it
  as target failure.
- Result timeout: expire the run, preserve target state, and release agent concurrency.

## 9. Test Plan

### Go tests

- Cross-language assignment/result conformance corpus.
- ICMP/TCP/HTTP/DNS parity fixtures matching backend collector expectations.
- IPv4/IPv6 and DNS resolution.
- CIDR, hostname wildcard, special-use, redirect, and DNS-rebinding enforcement.
- HTTP authentication redaction and response-size limits.
- Concurrency and queue limits.
- Cancellation before and during execution.
- Deadline handling and spooled-result recovery.
- Capability disable and scope changes.

### Backend tests

- Migration, FK behavior, and assignment indexes.
- Fair due-claiming across server and multiple agents.
- Separate local/remote NATS routing.
- No overlapping active run per monitor.
- Offline/revoked/unready agent behavior.
- Reconnect makes assigned monitors immediately due.
- Result authentication, idempotency, deadline, and spoof protection.
- Shared local/remote state transitions and alerts.
- Execution errors do not affect target status, retries, or uptime.
- Target failures do affect the existing state machine.
- Cancellation and restart reconciliation.
- Tenant, role, grant, and scope enforcement.
- Query plans use assignment/due indexes at fleet scale.

### Frontend tests

- Server/agent assignment and eligibility filtering.
- Offline and out-of-scope warnings.
- Secondary execution condition independent of target state.
- Agent assigned-probe list and actions.
- Disable-capability confirmation.
- Live result and unavailable-state updates.

### End-to-end acceptance

1. Place a target where the backend cannot reach it but an agent can.
2. Assign an ICMP, TCP, HTTP, and DNS monitor to that agent.
3. Verify checks use the agent and enter the existing monitor history/state pipeline.
4. Confirm alerts and retries match server-executed checks.
5. Disconnect the agent and verify target state is retained while probe-unavailable appears.
6. Reconnect and verify an immediate check clears the execution warning.
7. Change network scope and verify out-of-scope assignments are refused on both ends.
8. Run concurrent checks and verify per-agent fairness and limits.
9. Reassign a monitor to another agent and reject the old agent's late result.
10. Return the monitor to server execution only through an explicit user action.
11. Provision the agent with only the Slice 1 install command and verify a monitor for a directly
    connected target can select it without first editing agent scope.

## Assumptions and Defaults

- Central backend scheduling is authoritative; agents never maintain local monitor schedules.
- No automatic fallback between server and agent vantage points.
- Agent unavailability is operationally distinct from target failure.
- Slice 3 supports the four currently implemented monitor types: ICMP, TCP, HTTP(S), and DNS.
- Default remote concurrency is 20, configurable from 1–100.
- Remote probes are dispatched only for explicitly assigned monitors. Safe directly connected
  scope is derived automatically; only routed or exceptional targets require an explicit override.
- Existing monitor intervals, retries, maintenance, alerts, history, and uptime semantics remain
  authoritative.
- Probe assignments are never spooled; eligible results may spool temporarily.
- The schema uses indexed FKs, composite due indexes, atomic upserts, and `SKIP LOCKED` claims
  to keep scheduler performance predictable.
- Slice 3 consumes the same canonical agent URL, outbound-only live connection, readiness model,
  normalized network facts, and scope version established by Slices 1, 2, and 4.
