// Package hostinfo collects the real host metadata carried in every `hello` frame — enrollment
// and every link reconnect alike (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6). It is
// schema-agnostic collection only: nothing here validates or sequences hello frames (see
// internal/enroll and internal/link for that).
//
// HelloPayload.OS vs HelloPayload.OSVersion: OS is the GOOS-style platform string (runtime.GOOS,
// e.g. "linux") that the backend's self-update binary lookup keys release manifests on
// (agent_update.get_binary_sha256(version, agent.os, agent.arch) against "<os>-<arch>" manifest
// entries) — it must never be a distro identifier. OSVersion carries the human-useful distro
// detail instead (distro ID + VERSION_ID from /etc/os-release, e.g. "fedora 44"). Do not swap
// these: populating OS from os-release breaks self-update for every host whose distro ID isn't
// literally "linux".
package hostinfo

import (
	"os"
	"runtime"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// Collect gathers this host's hello metadata fresh on every call, so a long-lived agent never
// reports stale values on reconnect. agentVersion is passed in rather than read here since it's
// build-time state (main.AgentVersion), not host state.
//
// SpoolDepth is left at its zero value here by design: the outbound spool is owned by
// internal/link (Options.Spool), not by host collection, so this collector has no access to it
// and would only be guessing. internal/link's runOnce stamps the real at-connect depth onto the
// returned payload immediately after calling Collect (D-12), and reports it live thereafter on
// every heartbeat (frame.HeartbeatPayload) — the heartbeat, not the hello, is what lets the
// server see a backlog drain to zero without waiting for a reconnect. Callers other than
// internal/link get a zero here and should not read it.
func Collect(agentVersion string) frame.HelloPayload {
	hostname, _ := os.Hostname()
	distroID, distroVersion := osRelease()
	machineIDHash := machineIDHash()

	return frame.HelloPayload{
		Hostname:         hostname,
		MachineIDHash:    machineIDHash,
		OS:               runtime.GOOS,
		OSVersion:        formatOSVersion(distroID, distroVersion),
		Arch:             goArch(),
		AgentVersion:     agentVersion,
		PrimaryMACs:      primaryMACs(),
		Networks:         networkFacts(),
		Readiness:        identityReadiness(machineIDHash),
		CapabilitySchema: 2,
	}
}

// identityReadiness reports the one readiness signal cheaply available at this stage: whether a
// stable machine identity could be derived. Task 20's real collector readiness (host.docker,
// host.hwmon, ...) supersedes this once those collectors exist (spec §4.3).
func identityReadiness(machineIDHash string) []frame.Readiness {
	if machineIDHash == "" {
		return []frame.Readiness{{
			Collector:   "agent.identity",
			State:       "degraded",
			Reason:      "could not read /etc/machine-id or /var/lib/dbus/machine-id",
			Remediation: "ensure the host has a machine ID (systemd-machine-id-setup)",
		}}
	}
	return []frame.Readiness{{Collector: "agent.identity", State: "ready"}}
}
