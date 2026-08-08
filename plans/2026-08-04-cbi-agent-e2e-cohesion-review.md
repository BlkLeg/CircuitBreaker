# cbi-agent Slices 1–4 — E2E Cohesion Review

**Date:** 2026-08-04
**Status:** Reviewed; plan corrections applied
**Reviewed plans:** Slice 1 gap closure, Slice 2 host telemetry, Slice 3 remote probe, Slice 4
local discovery

## Product Outcome

A Circuit Breaker user can deploy one agent onto another VLAN, home, branch, cloud network, or
external site by running one generated command. After one approval in the main UI, the agent
connects home, reports its host, discovers its safe directly connected networks, and becomes an
eligible monitoring vantage without remote-network configuration.

The experience is tunnel-like:

- Agent initiates and maintains outbound HTTPS/WSS only.
- No inbound port or remote firewall/NAT rule is required.
- No local CIDR, credential, certificate, scanner, schedule, or config-file setup is required.
- All policy and ongoing management live in the central application.
- Temporary WAN loss, NAT rebinding, address changes, and restarts recover automatically.

One unavoidable prerequisite remains: the configured canonical Circuit Breaker agent URL must be
reachable from the remote host. A managed rendezvous/relay for a main installation that is itself
unreachable behind NAT would be a separate product capability.

## Review Findings and Resolutions

### 1. Deployment contract was implicit

Slice 1 covered enrollment and security but did not explicitly require an outbound-only,
zero-configuration remote-network deployment. It now owns the canonical public agent URL,
single-command installation, proxy-aware egress, persistent reconnect, and NAT-isolated E2E gate.

### 2. Discovery required too much setup

The initial Slice 4 plan required an admin to enable discovery, approve CIDRs, create a profile,
and start a scan. It now derives a bounded `direct_private` scope, creates idempotent system-managed
profiles, and runs initial plus recurring discovery automatically after approval. Central
exclusions and routed overrides remain available but optional.

### 3. Probe and discovery scope could drift

Slices 3 and 4 now share one versioned network-scope evaluator. Directly connected private IPv4
and IPv6 ULA networks are safe defaults. Public, default-route, loopback, link-local, multicast,
tunnel, and point-to-point networks are excluded automatically. Both backend and agent enforce the
same contract independently.

### 4. Slice tests did not prove the finished product

Each slice had useful E2E acceptance, but there was no release test spanning the whole user
journey. The cross-slice topology and assertions below are now a release gate.

### 5. Defaults did not produce immediate value

The normal approval preset now enables host telemetry and bounded local discovery. Remote probe
executes only after a monitor is assigned, but its derived safe scope requires no separate agent
setup. Approvers retain an opt-out before activation; upgrades do not silently broaden existing
grants.

## Shared Contracts Across Slices

### Identity and connection

- One agent identity survives daemon, host, backend, and WAN restarts.
- One outbound WSS/Noise session carries control and data for every capability.
- `hello` supplies platform, version, readiness, spool state, and normalized network facts.
- `hello.ack` supplies the complete authoritative grants, configuration, and scope version.
- Capabilities never open listeners or require inbound reachability.

### Configuration and readiness

- The database is authoritative; host-local config contains only bootstrap/server identity data.
- All runtime capability configuration arrives centrally and applies without daemon restart.
- Slice 2's readiness contract is shared by host telemetry, remote probe, and discovery.
- Unsupported optional collectors degrade visibly without blocking core reporting.

### Delivery semantics

- Control/assignment frames are never spooled.
- Telemetry, probe results, and discovery findings are bounded data frames and may spool.
- Every data payload has a stable idempotency identifier and original observation timestamp.
- Replayed data cannot duplicate samples, state transitions, findings, imports, or alerts.
- Late/cancelled assignments are rejected even if their result survived in the spool.

### Scope and provenance

- Network facts are observations, not unrestricted authority.
- Automatic authority is limited to current directly connected private/ULA unicast networks.
- Exceptional routed scope requires an explicit central override.
- Every telemetry sample, probe run/result, discovery job/finding, imported source, event, and
  audit record retains agent attribution.
- No automatic fallback changes a job or monitor's network vantage.

### Lifecycle

- Approval applies the selected default policy and starts useful reporting.
- Capability disable cancels active work and prevents new work without erasing history.
- Revocation closes the live session, stops all capabilities, and rejects later data.
- Uninstall removes the remote service but preserves central audit/provenance records.
- Agent deletion is blocked while referenced by retained operational history or configuration.

## Full-System E2E Release Gate

### Topology

Run the actual backend, frontend, Redis, NATS, database, and release-built Linux agent. Place the
backend on subnet A and the agent plus target fixtures on isolated subnet B. Subnet A must have no
route to the fixtures. Subnet B may initiate HTTPS/WSS to Circuit Breaker but exposes no inbound
path from A.

Include at least:

- One agent host.
- One TCP/HTTP/DNS fixture discoverable only from subnet B.
- A second device that appears after the first discovery scan.
- A controllable WAN boundary for disconnect/reconnect tests.

### Journey

1. Generate and run the one-line installer on subnet B.
2. Confirm no interactive question, local config edit, scanner install, or inbound rule is needed.
3. Observe the pending agent live and approve it with normal defaults.
4. Observe online presence and a host telemetry sample within the promised interval.
5. Confirm safe subnet B scope is derived and exactly one system profile is created.
6. Observe automatic initial discovery and incremental findings in the existing job UI.
7. Accept a finding and verify one attributed Hardware record and topology placement.
8. Create ICMP, TCP, HTTP(S), and DNS monitors from the discovered device with the agent vantage.
9. Verify results enter the existing monitor state, history, retry, uptime, and alert pipeline.
10. Disconnect WAN access while collecting telemetry and completing an eligible in-flight result.
11. Verify central status becomes offline/unavailable without falsely changing target state.
12. Restore WAN access and verify reconnect, bounded spool catch-up, idempotency, and immediate due
    probe recovery without re-enrollment.
13. Add the second device, run/await recurring discovery, and verify only the new device enters
    review while known-device `last_seen` updates.
14. Restart agent and backend independently; verify presence, profiles, schedules, and grants
    reconcile without duplication.
15. Change the agent IP inside subnet B and verify identity/provenance remain stable.
16. Disable discovery during a scan, then revoke the agent; verify cancellation and rejection of
    late frames across all capability handlers.
17. Upgrade the agent and execute the rollback case without losing enrollment or historical data.

### Required assertions

- Zero inbound connections from Circuit Breaker to the remote subnet.
- Zero manual agent-side configuration after running the generated command.
- No duplicate profiles, jobs, findings, Hardware records, samples, probe results, alerts, or
  topology nodes after retries and reconnects.
- Server and agent independently reject out-of-scope, cross-agent, stale, malformed, and oversized
  frames.
- Every remote observation is attributable to the correct agent and original timestamp.
- Existing server-side discovery and monitoring paths still work unchanged.
- SQLite development/migration tests and PostgreSQL production/E2E tests both pass.

## Completeness Assessment

With the corrections applied, the four plans form a cohesive implementation sequence:

1. Slice 1 creates the secure, resilient, outbound-only tunnel and zero-configuration installer.
2. Slice 2 proves continuous data collection, readiness, spooling, and central configuration.
3. Slice 3 adds explicit monitoring work from the remote vantage without changing monitor truth.
4. Slice 4 automatically inventories remote directly connected networks through the existing
   discovery/review/import workflow.

The cbi-agent is E2E complete only when the full-system release gate passes. Completing four sets
of unit tests or four isolated demonstrations is insufficient.
