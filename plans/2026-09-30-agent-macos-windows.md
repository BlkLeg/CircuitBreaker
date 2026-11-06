# cb-agent on macOS and Windows

**Date:** 2026-09-30
**Status:** Planned. No work started.
**Scope:** the Go agent (`apps/agent`) only. The server stays Linux-only, and the npm installer
CLI's own Windows work is ADR 0006's, not this plan's.
**Owner:** shawnji (maintainer)

## Decisions this plan starts from

- **Agent only.** Run `cb-agent` on Mac and Windows machines for host telemetry, monitor probes and
  discovery. Running the Circuit Breaker server on macOS or Windows is out of scope.
- **Windows starts after v0.5.0**, in line with ADR 0006. The maintainer has Windows hardware today;
  it is the primary Windows test machine once the phase opens.
- **macOS starts when an Apple silicon Mac server is rented.** That machine is for functional
  testing and for measuring the agent's performance on Apple silicon.
- **Not a 1.0 support promise.** ADR 0001 and the support contract say macOS and Windows are
  browser/client platforms only for 1.0. Agents on either ship as a preview until a new ADR
  supersedes that line and the support contract gains rows for them (Phase 5).

## What is Linux-specific today

The agent has three OS-specific files (`neigh_linux.go`, `scratch_space_unix.go` and their
stubs). Everything else assumes Linux directly:

| Area | Linux today | macOS | Windows |
|---|---|---|---|
| Host telemetry (`internal/collect/host`) | `/proc/stat`, `/proc/meminfo`, `/proc/diskstats`, `/proc/net/dev`, `/proc/loadavg`, `/proc/uptime`, `/proc/self/mounts`, `syscall.Statfs` | `sysctl` (`vm.*`, `hw.*`, `kern.boottime`), `host_statistics64`, `getfsstat`, interface counters from `getifaddrs`/route sysctl | `GetSystemTimes`, `GlobalMemoryStatusEx`, `GetDiskFreeSpaceEx`, `GetIfTable2`, `GetTickCount64` (via `golang.org/x/sys/windows`) |
| Machine identity (`hostinfo/machineid.go`) | `/etc/machine-id` | `IOPlatformUUID` (IOKit, or `ioreg`) | `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` |
| MACs and network facts (`hostinfo/mac.go`, `netfacts.go`) | `/sys/class/net` | `net.Interfaces` plus route sysctl for the default route | `net.Interfaces` plus `GetBestRoute2` |
| Neighbour discovery (`discover/neigh_linux.go`) | netlink neighbour table | ARP table via `sysctl` `NET_RT_FLAGS` | `GetIpNetTable2` |
| Probe readiness (`probe/readiness.go`) | `CAP_NET_RAW`, `ping_group_range`, `/etc/resolv.conf` | unprivileged ICMP (`SOCK_DGRAM`) is allowed; resolver from `scutil --dns` | `IcmpSendEcho2` needs no admin; resolver from `GetNetworkParams` |
| Service lifecycle (`cmd/cb-agent`: daemon, uninstall, rollback) | systemd unit, `systemctl`, `syscall.Exec` | launchd daemon in `/Library/LaunchDaemons` | Windows service via `golang.org/x/sys/windows/svc`; no `syscall.Exec` |
| Self-update (`internal/update`) | swap binary, re-exec | swap binary, `launchctl kickstart` | a running `.exe` cannot be replaced: rename it aside, write the new one, restart the service |
| Logging (`internal/logging`) | journald | file under `/Library/Logs` (unified logging later if needed) | Windows Event Log, plus a rotated file |
| Config and state (`/etc/circuit-breaker`) | `/etc/circuit-breaker` | `/Library/Application Support/CircuitBreaker` | `%ProgramData%\CircuitBreaker` |
| Build (`Makefile`) | `GOOS=linux`, amd64 and arm64 | `darwin/arm64` (Apple silicon) | `windows/amd64` |

On the server side the pieces already expect more platforms: `AddAgentInstallStep.jsx` lists macOS
and Windows as disabled options, and `agent_install.py` keys binary digests by `<os>-<arch>`. The
install command itself is POSIX shell (`useradd`, `sha256sum`) and needs a Windows counterpart.

## Phases

### Phase 1 — platform seams (no new platform yet)

Put every row of the table above behind a small interface with a Linux implementation and a
compile-only stub for the others, using build tags. No behaviour changes on Linux.

- Interfaces: host collector, machine identity, network facts, neighbour table, probe readiness,
  service manager (install, start, stop, restart, uninstall), self-update swap, logger, config
  paths.
- Cross-compile `GOOS=darwin GOARCH=arm64` and `GOOS=windows GOARCH=amd64` in CI with `go vet`, so
  a Linux-only call cannot creep back in.
- **Proof it changed nothing:** the composed agent journey (`make e2e-local`) and the agent unit
  suite pass unchanged on Linux.

This phase changes no user-facing behaviour, so it can run before v0.5.0 without breaking ADR
0006's Windows timing; Windows *development* itself starts in Phase 2.

### Phase 2 — Windows (after v0.5.0, on the maintainer's Windows hardware)

- Implement the Windows column: telemetry, identity, network facts, neighbour table, ICMP probes,
  logging, config paths.
- Run as a Windows service; install, uninstall, self-update (rename-aside swap) and rollback.
- A PowerShell install command from the server (`Invoke-WebRequest`, `Get-FileHash`, service
  registration), served by the same install-command endpoint with a `windows` platform, and the
  Windows button enabled in Add agent.
- Build and publish `windows/amd64` agent binaries with checksums and SBOM, keyed `windows-amd64`
  in the agent manifest.
- **Acceptance, on the Windows machine:** enroll, approve by fingerprint, telemetry arrives,
  a monitor probe runs, discovery reports neighbours, the agent self-updates to a newer build, rolls
  back, and uninstalls cleanly, leaving no service, files or registry keys behind.

### Phase 3 — macOS (when the Apple silicon Mac server is rented)

- Implement the macOS column, run as a launchd daemon, and add a shell install command for macOS
  (the existing script, with launchd instead of systemd and `shasum -a 256`).
- Build and publish `darwin/arm64` binaries, keyed `darwin-arm64`, and enable the macOS button.
- **Acceptance, on the rented Mac:** the same journey as Windows.
- **Performance on Apple silicon**, measured on the rented Mac:
  - baseline first: the same agent build on a Linux arm64 host with the same capabilities and
    sample interval;
  - measure idle and active CPU (average and peak over a 30-minute run), resident memory, and the
    wall-clock cost of one telemetry sample and one discovery sweep;
  - **target:** no measurement worse than 1.5× the Linux arm64 baseline. A miss is a defect to fix
    before Phase 5, not a number to document.

### Phase 4 — CI and release

- Unit tests and builds on macOS and Windows runners. CI is moving to the self-hosted GitLab runner
  (`gitlab.blkleg.app`), so register the rented Mac and the Windows machine as GitLab runners
  tagged `macos-arm64` and `windows-amd64` rather than buying hosted minutes.
- The real-host journey from Phases 2 and 3, scripted and run on those runners before each release
  that changes the agent.
- Release artifacts: per-OS binaries, checksums, SBOM entries, and the manifest keys the server
  reads; the server bundle carries them in `agent-binaries/` as it does for Linux.

### Phase 5 — promote from preview

- A new ADR that supersedes ADR 0001's line on macOS and Windows for the agent, and support-contract
  rows for each OS and architecture with the evidence behind them.
- `docs/agent.md` gains the macOS and Windows install and uninstall sections.

## Choices to make before each phase

| Choice | Needed before | Options |
|---|---|---|
| Host metrics source | Phase 1 | Per-OS code on `golang.org/x/sys` (no new dependency, more code), or `gopsutil` (one dependency, less code, broader surface to audit) |
| Code signing | Phase 2 (Windows), Phase 3 (macOS) | Windows Authenticode certificate, or accept SmartScreen warnings during preview; Apple Developer ID and notarization, which Gatekeeper expects for a daemon |
| Extra architectures | Phase 4 | `windows/arm64` and `darwin/amd64` (Intel Macs) are cheap to build but need a machine to test on |
| Discovery in the first cut | Phase 2 | Ship neighbour discovery with telemetry and probes, or follow in a later release |
