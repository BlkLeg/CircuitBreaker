# cbi-agent Slice 4 — Local Discovery Plan

**Date:** 2026-08-04
**Status:** Reviewed for cross-slice E2E implementation
**Related:** `specs/2026-07-26-cb-agent-design.md`,
`plans/2026-08-04-cbi-agent-slice1-gap-closure.md`,
`plans/2026-08-04-cbi-agent-slice2-host-telemetry.md`,
`plans/2026-08-04-cbi-agent-slice3-remote-probe.md`

## Summary

Add local-network discovery from an enrolled Linux agent while keeping the backend authoritative
for scope, scheduling, job state, result matching, review, and import.

The agent is an additional discovery execution location. It does not create a parallel discovery
system and does not autonomously scan every network it observes. Existing discovery profiles,
`ScanJob`/`ScanResult` history, WebSocket progress events, review queue, matching, and
`discovery_import_service` remain the canonical workflow.

Resolve the design's scope-representation question with an automatic safe baseline plus central
overrides:

- The agent reports directly connected subnets as signed-session readiness metadata.
- The backend automatically derives effective discovery scope from private IPv4 and IPv6 ULA
  unicast networks that are directly connected to the agent.
- Loopback, link-local, multicast, public, default-route, and tunnel/point-to-point networks are
  excluded from automatic scope.
- Administrators can centrally exclude a detected subnet or explicitly add a routed subnet.
- The backend and agent independently enforce effective scope, and the agent requires automatic
  targets to remain directly connected at execution time.

Local discovery is included in the normal approved-agent experience and requires no CIDR, profile,
port, scanner-package, or remote-host configuration. After approval and readiness, the backend
automatically runs an initial bounded scan and creates a conservative recurring profile for that
agent. Slice 4 depends on the Slice 1 gap closure and the structured capability/readiness work in
Slice 2.

## 1. Supported Discovery Depth

### V1 collector

Create `apps/agent/internal/collect/discover` with unprivileged Linux collectors:

- Enumerate active, non-loopback interfaces and directly connected IPv4/IPv6 subnets.
- Read the local neighbor cache (`ip neigh` semantics through netlink, not shell parsing).
- Discover live hosts with bounded ICMP datagram and TCP-connect checks.
- Scan an explicit, small server-provided TCP port set.
- Perform reverse DNS for responsive addresses.
- Collect safe service banners only where the existing discovery result contract can represent
  them and strict byte/time limits are enforced.

The first release deliberately excludes:

- Raw ARP sweeps, SYN scans, and OS fingerprinting requiring `CAP_NET_RAW` or root.
- Bundling or invoking `nmap`, `masscan`, or another external scanner.
- Autonomous passive capture or promiscuous mode.
- Docker socket discovery, DHCP-router credentials, OPNsense access, or other server-local
  integration credentials.
- Arbitrary UDP port scans.

Optional mDNS/SSDP and SNMP discovery should be deferred until the core job/result path is proven.
They introduce multicast behavior and credential handling that are not needed to make the final
slice demonstrable.

### Collector limits

Use conservative defaults in the `local_discovery` grant:

```json
{
  "enabled": true,
  "config": {
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "max_addresses_per_job": 1024,
    "max_concurrent_hosts": 64,
    "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    "host_timeout_ms": 1500,
    "job_timeout_seconds": 300
  }
}
```

Enforce server-side hard ceilings in addition to configurable values. Reject oversized requests;
do not silently truncate them.

## 2. Data Model

### Execution location

Extend `discovery_profiles`:

- `scan_agent_id`: nullable FK to `agents`; `NULL` means the existing server scanner.

Extend `scan_jobs`:

- `scan_agent_id`: nullable FK recording the selected execution location at job creation.
- `dispatch_id`: nullable unique opaque 128-bit identifier for an agent job.
- `dispatch_status`: nullable
  `queued|dispatched|running|completed|execution_error|expired|cancelled`.
- `dispatch_deadline_at`, `last_finding_at`, and `finding_count`.

The job copies `scan_agent_id` from its profile so historical attribution cannot change when a
profile is edited. Use `source_type="agent"` for agent-executed jobs and add `agent` to the
documented allowed values.

Extend `scan_results`:

- `discovery_agent_id`: nullable FK to `agents` for provenance.
- `finding_id`: nullable opaque identifier unique within one dispatch.
- Add `agent` to the documented `source_type` values.

Indexes and constraints:

- Index both new agent foreign keys.
- Composite index `(scan_agent_id, status, created_at)` on jobs for dispatch/recovery queries.
- Unique `(scan_job_id, finding_id)` where `finding_id IS NOT NULL` for idempotent replay.
- Preserve indexed discovery foreign keys required by purge and deletion behavior.

Use `ON DELETE RESTRICT` for an agent selected by a profile or retained job/result history. Return
`409` with dependent profile/job counts and require explicit reassignment or retention cleanup.
Revocation does not erase provenance.

No separate agent-findings table is needed. A validated finding is inserted idempotently into the
existing `ScanResult` model and proceeds through the existing matcher and review queue.

### Scope storage

Store policy and overrides in `AgentCapabilityGrant.config`, not a manually maintained copy of
detected networks. Persist the latest normalized interface/subnet report with a generation and
timestamp so the UI, scheduler, and audit trail agree on what produced the effective scope.

Effective scope is the intersection of current agent-reported directly connected private/ULA
networks and server policy, minus exclusions, plus explicit administrator-approved routed
networks. Scope changes are versioned; active requests carry the version and are cancelled if it
changes incompatibly.

## 3. Profile, Job, and Dispatch Flow

### Profile and ad hoc selection

Extend discovery profile and ad hoc scan requests with nullable `scan_agent_id`:

- `NULL`: run with the existing server discovery engine.
- Agent ID: dispatch to that specific agent.

Validation at profile save and job creation requires:

- Active agent with `local_discovery` enabled.
- Compatible collector readiness.
- Every target CIDR contained in the versioned effective scope.
- Requested scan types supported by the selected execution location.
- Address count and port set within configured and hard limits.

Agent profiles expose a focused scan type such as `agent_connect`. Do not send server-only scan
types (`nmap`, `arp`, `docker`, OPNsense, or DHCP-router collection) to an agent. The UI filters or
disables incompatible choices when an execution location is selected, while the API remains the
authoritative validator.

### Automatic bootstrap and recurring discovery

After approval, the first readiness report drives zero-configuration setup:

1. Normalize and validate the directly connected subnet report.
2. Compute effective safe scope.
3. Upsert one system-managed discovery profile per `(agent, subnet)` with conservative defaults.
4. Queue an initial scan after a short jitter so approval produces useful data promptly.
5. Schedule recurring scans every six hours with per-agent jitter.
6. When a subnet appears, create and scan its system profile; when it disappears, disable rather
   than delete the profile and retain history.

Use idempotent upserts and a uniqueness constraint for system-managed `(scan_agent_id,
normalized_cidr)` profiles. User-created profiles remain separate and are never overwritten.
Repeated hello/readiness frames must not create duplicate profiles or scans.

The central UI can pause automatic discovery globally, per agent, or per subnet. It can also edit
cadence and scan depth. None of these controls is required during installation.

### Central scheduling

Keep the existing profile scheduler authoritative:

1. A manual, ad hoc, or scheduled action creates the ordinary `ScanJob`.
2. The existing concurrency gate claims the job.
3. Server jobs enter the current `run_scan_job` path unchanged.
4. Agent jobs create `dispatch_id`, set a deadline, and send one `discovery.request` through the
   Slice 1 live-agent control service.
5. Findings arrive incrementally and become `ScanResult` rows.
6. A terminal finding finalizes counters and job status and emits the existing job-completion and
   review-badge events.

Use a short transaction with a row lock when claiming/finalizing a job. Multi-worker recovery must
be idempotent: only one active dispatch per job, and terminal updates use compare-and-set semantics.
Scheduled profile execution keeps the existing advisory lock.

### Offline and recovery behavior

There is no fallback from agent to server because that would change the discovery vantage point.

- If the agent is offline when a job is claimed, keep the job queued with a clear
  `waiting_for_agent` progress phase until a bounded dispatch deadline.
- On expiry, fail with `error_reason="agent_unavailable"`.
- When the agent reconnects, retry eligible queued jobs once through the normal dispatcher.
- A reconnect does not replay a completed or cancelled request.
- If the connection drops mid-scan, retain accepted findings, mark the job failed or partial with
  an explicit reason, and leave those findings available for review.

Add `partial` to job status only if the product should distinguish incomplete scans from hard
failures. The recommended v1 behavior is `failed` plus retained findings and
`error_reason="agent_disconnected"`, avoiding a broad status-model change.

## 4. Protocol Contract

### `discovery.request`

Server-to-agent control frame, never spooled:

```json
{
  "dispatch_id": "32 lowercase hex characters",
  "scan_job_id": 481,
  "targets": ["192.168.10.0/24"],
  "methods": ["neighbor_cache", "icmp", "tcp_connect", "reverse_dns"],
  "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
  "host_timeout_ms": 1500,
  "max_concurrent_hosts": 64,
  "deadline_at": "2026-08-04T18:05:00Z"
}
```

The agent rejects unknown methods, unapproved targets, invalid prefixes, excessive address counts,
ports outside its grant, and expired requests before starting any network activity.

### `discovery.finding`

Agent-to-server data frame, eligible for the existing spool:

```json
{
  "dispatch_id": "...",
  "scan_job_id": 481,
  "finding_id": "...",
  "kind": "host",
  "observed_at": "2026-08-04T18:01:12Z",
  "ip_address": "192.168.10.24",
  "mac_address": "00:11:22:33:44:55",
  "hostname": "nas.internal",
  "open_ports": [{"port": 443, "protocol": "tcp"}],
  "evidence": ["neighbor_cache", "tcp_connect"],
  "terminal": false
}
```

Send terminal progress through the same type with `kind="summary"`, counts, outcome, and bounded
error details. A summary has its own `finding_id`, making spool replay idempotent.

Validation rules:

- Require the dispatch to belong to the authenticated agent and an active job.
- Require the finding address to fall within the job target and current approved scope.
- Reject findings after cancellation or a terminal state.
- Bound all strings, arrays, port counts, evidence values, and total frame size.
- Normalize IP and MAC values server-side.
- Treat agent-provided hostname, banner, and evidence as untrusted observations.
- Never accept a client-supplied matched entity, merge state, tenant, or agent ID.

### Cancellation

Add `discovery.cancel` as a server-to-agent control frame containing `dispatch_id` and reason.
Send it when the job is cancelled, the profile is disabled, scope changes invalidate the job, the
capability is disabled, or the agent is revoked. Cancellation is best-effort; the backend rejects
late findings independently.

## 5. Backend Integration

Add a discovery-specific handler registered by `agent_link.py`; keep `agent_link.py` itself free of
domain logic.

The handler should:

1. Validate the protocol schema and grant.
2. Lock and authenticate the dispatch/job relationship.
3. Insert the finding idempotently into `ScanResult` with agent provenance.
4. Reuse the same hardware match/conflict classification used by `_scan_import`.
5. Commit before broadcasting existing `result_added`, job-progress, and badge events.
6. On terminal summary, finalize the existing job counters/status and write the ordinary discovery
   audit entry.

Refactor the current `_scan_import` row-building and match logic into a small reusable service
rather than calling a private phase function with fabricated raw scan data. Feed resulting rows to
the existing `discovery_import_service` only when the user accepts/batch-imports them, preserving
the current review workflow and idempotent Hardware upsert behavior.

The design document's reference to “the reconciler” means the existing discovery
match/conflict/merge flow. Do not route agent findings into `discovery_reconciler.py`; that service
only reconciles server-host discovery capabilities.

## 6. Agent Readiness and Scope UX

### Readiness reporting

Extend agent readiness with:

- Collector supported/running state and last error.
- Active interface names, addresses, and directly connected candidate CIDRs.
- Whether ICMP datagram probing is usable.
- Neighbor-cache availability.
- Effective concurrency and address ceilings.

Do not report routing-table secrets, Wi-Fi SSIDs, DNS search domains, or interface counters unless
another capability already requires them.

### Agent detail

Complete the Slice 4 “Discovery scope” section on `AgentDetailPage`:

- Local discovery is on after normal approval unless the approver explicitly opts out.
- Show automatically included directly connected subnets, excluded subnets, and explicit routed
  overrides with visibly different provenance.
- Let an admin exclude an automatic subnet or add a routed CIDR centrally.
- Show effective CIDRs and their automatic/override provenance, port set, limits, readiness,
  active job, and recent job history.
- Require confirmation for scopes larger than the normal hard-safe range.
- Explain that disabling the capability cancels active work but retains results/history.

Grant updates must support structured `config`, not only booleans. Validate and normalize the
configuration in the backend and send the effective grant through `capabilities.set`.

### Discovery page

Add “Scan from” to profile and new-scan forms:

- Server (existing behavior).
- Eligible active agents with local discovery granted.

Show the execution location on job cards/history and link the agent name to its detail page. Filter
scan methods based on location, show why an agent is ineligible, and preserve the existing review
queue unchanged.

## 7. Security and Safety

- Pending, rejected, and revoked agents can never scan. Normal approval grants the bounded
  `direct_private` policy; the approver can opt out before activation.
- A reported subnet is eligible automatically only when it is private IPv4 or IPv6 ULA unicast,
  directly connected, within hard prefix/address limits, and still present when a request runs.
- Backend validates scope at configuration, job creation, dispatch, and finding ingest.
- Agent validates its effective grant immediately before each request and target connection.
- Reject `0.0.0.0/0`, `::/0`, loopback, multicast, link-local, and non-unicast targets in v1.
- Do not follow HTTP redirects or make application-level authenticated requests in discovery v1.
- Use bounded concurrency, deadlines, response bytes, frame sizes, and spool quotas.
- Stop quickly on cancellation or grant change.
- Emit `capability_violation` events for rejected agent behavior without logging sensitive banner
  contents.
- Keep the service non-root and do not add `CAP_NET_RAW` for Slice 4.

## 8. Testing and Verification

### Go unit and integration tests

- Interface/subnet enumeration excludes loopback and normalizes CIDRs.
- Neighbor-cache parsing through netlink fixtures.
- CIDR containment, reserved-range rejection, port allowlist, and request-size limits.
- Bounded host concurrency, deadlines, cancellation, and no goroutine leaks.
- TCP-connect/ICMP/reverse-DNS findings against local test fixtures.
- Stable `finding_id` and terminal summary behavior.
- Findings spool across reconnect; requests and cancellation do not spool.
- Capability disable stops current and future discovery.

### Python service and API tests

- Profile/ad hoc validation for agent status, grant, readiness, method compatibility, and scope.
- Scheduled and manual dispatch use the same job path.
- Duplicate findings insert one `ScanResult` and emit no duplicate review event.
- Cross-agent, out-of-scope, late, malformed, and oversized findings are rejected and audited.
- Findings reuse existing match/conflict classification and review/import flows.
- Job cancellation, timeout, disconnect, reconnect, revoke, and scope-change behavior.
- Concurrent terminal summaries finalize only once.
- Agent/job/result foreign-key deletion behavior and retention purge.
- Tenant context is derived from the job/agent, never accepted from a finding.

### Frontend tests

- Safe directly connected subnet becomes automatically included after readiness; unsafe and
  tunnel/default-route networks do not.
- Capability config validation and readiness warnings.
- Server/agent execution selection and incompatible scan-method handling.
- Job cards/history show execution location and partial-findings failure messaging.
- Review queue handles agent findings without a separate UI path.

### End-to-end gate

In the real-agent compose harness:

1. Put the agent and discoverable fixtures on a network namespace unreachable from the backend.
2. Install with the single Slice 1 command and approve in the central UI with normal defaults.
3. Confirm the agent reports its directly connected test subnet and the backend creates exactly
   one system-managed profile without CIDR entry or local configuration.
4. Confirm an initial scan starts automatically and observe incremental progress.
5. Confirm the discovered fixture enters the ordinary review queue.
6. Import it and verify one Hardware record is created.
7. Replay findings and verify no duplicate result or Hardware row.
8. Disable the capability during a second scan and verify cancellation plus late-result rejection.
9. Restart both sides, change the agent address, and verify reconnect plus recurring discovery
   without re-enrollment or profile duplication.
10. Add a second isolated agent/subnet and verify its findings and provenance remain distinct.
11. On the recurring scan, auto-update known unchanged Hardware `last_seen` state and place only
    genuinely new or conflicting devices back into the review queue.

## 9. Delivery Order

1. Add migration, ORM/schema fields, indexes, FK behavior, and protocol schemas.
2. Add structured local-discovery grant validation and candidate-subnet readiness reporting.
3. Implement the unprivileged Go collector with scope enforcement and cancellation.
4. Add agent job dispatch/recovery and the reusable finding-ingest/match service.
5. Route findings through the existing WebSocket, review, and import workflow.
6. Add agent-detail discovery scope and discovery-page execution-location UI.
7. Add unit, cross-language, service, frontend, and E2E coverage.
8. Run migration checks on SQLite, PostgreSQL, upgrade, and fresh-volume bootstrap paths.

## 10. Definition of Done

- A user runs one generated install command on a machine in another home, VLAN, site, or external
  network and performs only the normal central approval.
- The agent uses outbound WSS only; no inbound remote-network rule, CIDR entry, scanner install,
  certificate copy, or agent-side configuration is required.
- Safe directly connected networks become bounded effective scope automatically.
- The backend creates an initial and recurring system-managed profile without duplication.
- The backend sends a bounded one-shot request; the non-root agent discovers reachable fixtures.
- Incremental findings survive reconnect and appear in the existing job history and review queue.
- Accepting findings uses the existing idempotent import/match workflow.
- Duplicate, late, cross-agent, and out-of-scope findings cannot mutate discovery state.
- Offline agents never cause silent server fallback or a changed vantage point.
- Disabling/revoking local discovery stops active work and blocks new work without erasing history.
- Agent attribution is visible in agent detail, discovery jobs, results, audit logs, and tests.
- No raw-socket privilege, network relay, or autonomous network scanning is introduced.
- The complete cross-slice remote-subnet release gate passes, including installation, telemetry,
  automatic discovery, import, agent-based monitors, outage, spool catch-up, and restart recovery.

## 11. Remaining Product Decision

The proposed v1 intentionally defers SNMP and mDNS/SSDP. If the final slice must include richer
device identification on day one, add them as a second milestone after the connect-scan path is
complete; do not make them prerequisites for the first end-to-end local-discovery demonstration.

The main Circuit Breaker agent URL must be reachable from an external agent over HTTPS. Supporting
a main installation that is itself private behind NAT with no public/VPN path requires a managed
rendezvous/relay service. That is a separate architectural slice; the agent's remote subnet still
requires only outbound access in either model.
