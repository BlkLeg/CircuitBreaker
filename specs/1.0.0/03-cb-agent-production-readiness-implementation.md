# cb-agent Production Readiness — Sprint Implementation Slices

**Companion spec:** [03-cb-agent-production-readiness.md](./03-cb-agent-production-readiness.md)
**Status:** Ready for estimation
**Priority:** P0

## Standalone slice plans

- [AGT-1 — Composed release gate](./slices/agt-1-composed-release-gate.md)
- [AGT-2 — ARM64 AVIF defect](./slices/agt-2-arm64-avif.md)
- [AGT-3 — PyInstaller containment](./slices/agt-3-pyinstaller-containment.md)
- [AGT-4 — Environment-filter correctness](./slices/agt-4-environment-filter.md)
- [AGT-5 — Agent-created monitor](./slices/agt-5-agent-created-monitor.md)
- [AGT-6 — Agent state and errors](./slices/agt-6-state-errors.md)
- [AGT-7 — Fleet safety and recovery](./slices/agt-7-fleet-safety-recovery.md)
- [AGT-8 — Physical remote-site UAT](./slices/agt-8-remote-site-uat.md)

## Slice AGT-1 — Stabilize the composed release gate

**Requirements:** AGT-01, AGT-02, AGT-03, AGT-04
**Depends on:** Existing composed Docker journey

- [ ] Baseline repeated gate runs and classify every failure by product, harness, environment, or
  unsupported systemd-in-container behavior.
- [ ] Preserve one continuous enrollment-to-revocation journey and assert state at every boundary.
- [ ] Join discovery/imported hardware to ICMP, TCP, HTTP(S), and DNS monitors using agent vantage.
- [ ] Exercise independent agent/backend restart with live telemetry, profiles, grants, and schedules.
- [ ] Incorporate forced rollback and production-transport malformed/oversized frame coverage or
  link equivalent signed-artifact coverage with explicit rationale.
- [ ] Resolve the uninstall xfail; add deterministic network faults, time budgets, seeds, and
  per-test logs/traces/container diagnostics.
- [ ] Add scheduled and required-RC workflow entry points without making the slow gate a PR blocker
  unless maintainers explicitly choose that policy.

**Verification:** Repeated full runs meet the approved reliability threshold and one deliberate
fault produces sufficient retained evidence for diagnosis.

## Slice AGT-2 — ARM64 AVIF release defect

**Requirements:** AGT-10
**Depends on:** Current ARM64 packaging workflow

- [ ] Reproduce #101 from the signed/current package on a clean Raspberry Pi-class host.
- [ ] Determine whether AVIF is supported; repair its binary compatibility or exclude/replace it.
- [ ] Add image-handling, service-start, health, restart-loop, and diagnostic retention tests to the
  ARM64 artifact workflow.
- [ ] Verify x86_64 behavior is unchanged and document format support.

**Verification:** Exact ARM64 candidate package repeatedly starts and handles every supported image
format without `_avif` failure.

## Slice AGT-3 — PyInstaller runtime containment

**Requirements:** AGT-11
**Depends on:** Can run alongside AGT-2; coordinate packaging changes

- [ ] Select a dedicated application-owned extraction/runtime directory and lifecycle policy.
- [ ] Prevent concurrent unsafe starts and identify Circuit Breaker-owned stale state precisely.
- [ ] Clean stale state without broad `/tmp` deletion or touching active/foreign directories.
- [ ] Test normal exit, forced crash loops, reboot, permission failure, disk full, and upgrade.

**Verification:** Repeated crash/restart cycles produce bounded, attributable state and clean recovery.

## Slice AGT-4 — Environment-filter request correctness

**Requirements:** AGT-12
**Depends on:** None

- [ ] Trace settings, environment loading, selector conversion, storage, and API request construction.
- [ ] Resolve saved names to numeric IDs only after the environment list loads.
- [ ] Define safe behavior for deleted/stale names and validate the API boundary.
- [ ] Add unit and browser cases for valid/deleted/stale/numeric/unfiltered states.

**Verification:** No string `environment_id` request is emitted during initial load or interaction.

## Slice AGT-5 — Agent-created monitor workflow

**Requirements:** AGT-13
**Depends on:** AGT-1 fixtures may be reused

- [ ] Select the action placement from the agent design rather than inventing a new navigation path.
- [ ] Carry imported/discovered device target and discovering-agent ID into the monitor form.
- [ ] Visibly preselect the agent vantage while allowing an authorized user to change it.
- [ ] Add component and browser tests through saved monitor execution and result display.

**Verification:** The composed journey monitors the discovered device from the intended agent.

## Slice AGT-6 — State semantics and actionable errors

**Requirements:** AGT-14, AGT-15
**Depends on:** Stable backend state model

- [ ] Define server-clock-based freshness thresholds and state precedence for offline, revoked,
  disabled, stale telemetry, pending config/update, clock skew, and degraded capabilities.
- [ ] Expose stable machine states and accessible human explanations with next actions.
- [ ] Map install/enrollment failures to safe error codes and redact keys/protocol internals.
- [ ] Add fixtures and tests for every state, transition, redaction, and recovery action.

**Verification:** Operators can distinguish and act on every state without consulting raw logs.

## Slice AGT-7 — Safety, fleet operations, and recovery

**Requirements:** AGT-16, AGT-17, AGT-18
**Depends on:** AGT-6

- [ ] Add confirmation, authorization, and audit behavior to revoke, uninstall, scope expansion,
  probe/discovery grants, and update dispatch.
- [ ] Add fleet filtering and aggregate version drift, upgrade status/failures, spool pressure, and
  capability health using bounded queries.
- [ ] Write and exercise recovery runbooks for lost server key, cloned ID, duplicate agent,
  hostname/IP changes, expired pairing, and restored server.
- [ ] Add large-fleet browser/API coverage and recovery tabletop records.

**Verification:** Safety tests, audit records, large-fleet performance budget, and runbook exercises pass.

## Slice AGT-8 — Physical remote-site UAT

**Requirements:** AGT-05, AGT-06, AGT-07, AGT-08, AGT-09
**Depends on:** AGT-1 through AGT-7 and RC-02 support matrix

- [ ] Prepare clean hosts and named operators at two physically distinct sites.
- [ ] Execute the supported OS/architecture lifecycle matrix using signed artifacts.
- [ ] Apply NAT/no-inbound, DNS/TLS, latency/loss, DHCP, reboot/suspend, firewall, proxy, and WAN faults.
- [ ] Exercise network scopes across supported NIC/VLAN/bridge/VPN/Docker/IP combinations.
- [ ] Record CPU/RAM/discovery/spool measurements and confirm bounded behavior.

**Verification:** Two-site signed checklist, immutable evidence, and requirement-ledger review complete.
