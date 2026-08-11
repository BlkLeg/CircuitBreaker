# AGT-8 — Physical Remote-Site UAT

**Requirements:** AGT-05, AGT-06, AGT-07, AGT-08, AGT-09
**Priority:** P0
**Depends on:** AGT-1 through AGT-7, signed agent RC, RC-02

## Environment

Use at least two physically distinct sites, x86_64 and ARM64, and every supported Debian/Ubuntu,
Fedora/RHEL-family, and minimal/server row. Record hardware, OS image, kernel, firewall/router, DNS,
proxy, server/agent digests, configuration, timestamps, and operator.

## Procedure

1. Install least-privilege package; enroll/approve with no inbound agent port; verify TLS and scope.
2. Exercise telemetry, discovery/import, agent-vantage monitors, disconnect/spool/reconnect, and normal
   CPU/RAM/disk use.
3. Inject latency/loss, DNS failure/change, DHCP address change, reboot, suspend, proxy, firewall
   change, intermittent WAN, and server restart/re-key.
4. Exercise multi-NIC, VLAN, bridge, VPN, Docker, overlapping subnets, and IPv4/IPv6 only to the
   support level. Prove denied ranges are never touched.
5. Upgrade, failed upgrade, rollback, revoke, reinstall/duplicate identity, and uninstall. Confirm
   credentials/files/processes and server state follow the contract.
6. Run idle and discovery load windows; disconnect to spool capacity and confirm bounded backpressure.

## Evidence and done

Use a signed checklist with command output, packet/firewall evidence, server/agent logs, resource
series, screenshots where useful, and incident notes. Redact secrets without removing identifiers
needed for correlation. Done requires both sites and architectures to pass the exact signed artifact;
a simulated Docker environment cannot substitute.
