# cb-agent Production-Readiness Specification

**Status:** Draft; release-blocking
**Priority:** P0

## Outcome

The signed cb-agent can be installed, enrolled, operated, upgraded, rolled back, revoked, and
removed across the supported host and network matrix. Its UI communicates state and risk clearly,
and the core remote-site claim is proven outside a single-host simulation.

## Automated composed gate

| ID | Requirement | Acceptance |
|---|---|---|
| AGT-01 | Run the existing full composed Docker journey against every RC and on a schedule. | Release workflow is required; logs, traces, timing, container diagnostics, and seed are retained. |
| AGT-02 | Keep enrollment, telemetry, discovery/import, agent-vantage monitoring, outage/spool recovery, independent restarts, capability changes, revocation, and upgrade in one continuous journey. | State composes without duplication or loss; discovered hardware is the target of ICMP/TCP/HTTP(S)/DNS monitors. |
| AGT-03 | Add forced rollback plus malformed and oversized wire-frame behavior at the appropriate E2E boundary. | Delegated coverage is explicitly linked only if it exercises the same signed artifact and production transport. |
| AGT-04 | Resolve the uninstall/systemd-container xfail and establish flake tolerance. | Repeated runs with deterministic network faults meet the approved pass-rate and duration budget; no unexplained xfail remains. |

## Real remote-site UAT

| ID | Requirement | Acceptance |
|---|---|---|
| AGT-05 | Test Debian/Ubuntu, Fedora/RHEL-family, and one minimal/server distribution on x86_64 and arm64 where supported by RC-02. | Exact signed packages are installed on clean hosts; evidence identifies hardware and OS image. |
| AGT-06 | Exercise a physically separate site behind NAT with no inbound port using realistic DNS/TLS, packet loss, latency, DHCP changes, reboot, suspend, firewall, proxy, and intermittent WAN. | At least two physical sites and both supported architectures have signed checklists. |
| AGT-07 | Exercise least-privilege install, enroll, approve, revoke, uninstall, update, failed update, rollback, server reinstall, and re-key. | Operations complete or fail with documented recovery and no leaked credentials. |
| AGT-08 | Validate network-scope accuracy on multi-NIC, VLAN, bridge, VPN, Docker, IPv4/IPv6 as supported, and overlapping subnet hosts. | Disallowed scope is never scanned or probed; allowed scope remains stable through route changes. |
| AGT-09 | Enforce idle CPU/RAM, discovery-load, and disconnected-spool disk ceilings. | Measurements meet REL-21 limits and fail gracefully at bounds. |

## Installed-artifact defects and issue closure

| ID | Requirement | Acceptance |
|---|---|---|
| AGT-10 | Resolve the ARM64 Pillow/AVIF startup crash by repairing, excluding, or compatibly replacing AVIF support. | Current ARM64 package starts all services, exercises supported image handling, restarts repeatedly, and retains journal/PyInstaller diagnostics. |
| AGT-11 | Use an application-owned PyInstaller extraction/runtime location and clean only stale Circuit Breaker-owned state. | Crash loops, reboot, concurrent start, permissions, disk-full, and upgrade tests show no unbounded `_MEI*` accumulation. |
| AGT-12 | Resolve saved environment names to numeric IDs only after environments load; stale/deleted values produce an unfiltered or explicit safe state. | Unit and browser tests cover valid name, deleted name, stale storage, numeric selection, and unfiltered requests; no string reaches the integer API field. |

Issue #66, #68, #74, #75, #81, and #87 closure is owned by ACC-16 because each requires
clean-host installed-artifact evidence. AGT-10 through AGT-12 own the unresolved #101 defects.

## Operator experience and safety

| ID | Requirement | Acceptance |
|---|---|---|
| AGT-13 | A discovered/imported device can create a monitor with the discovering agent visibly preselected as vantage. | Browser E2E proves the resulting monitor targets the imported hardware through that agent. |
| AGT-14 | UI defines last-seen freshness, clock skew, offline/revoked/disabled, stale telemetry, pending config/update, and degraded capability states. | Each state has fixture coverage, accessible text, and a documented operator action. |
| AGT-15 | Install/enrollment errors are actionable without exposing keys or protocol internals. | Error corpus and redaction tests cover expected operational failures. |
| AGT-16 | Revoke, uninstall, scope expansion, remote-probe/discovery grants, and update dispatch require explicit confirmation and audited actor/target/outcome. | UI/API tests prove authorization, confirmation, cancellation, and audit records. |
| AGT-17 | Fleet views support filtering, version drift, upgrade status/failure, spool pressure, and capability health. | Large-fleet browser and API tests demonstrate usable filtering and accurate state. |
| AGT-18 | Publish recovery runbooks for lost server key, cloned machine ID, duplicate agent, hostname/IP change, expired pairing code, and restored server. | Each runbook is exercised in a tabletop or automated scenario and linked from diagnostics. |

## Non-goals

- Claiming remote-site readiness from one-host Docker tests alone.
- Weakening the service sandbox to make lifecycle tests pass.
- Supporting an OS, architecture, or network mode absent from RC-02.
