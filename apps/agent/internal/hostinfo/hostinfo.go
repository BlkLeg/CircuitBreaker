// Package hostinfo collects the real host metadata carried in every `hello` frame — enrollment
// and every link reconnect alike (specs/2026-07-26-cb-agent-design.md §3.4, §4.3, §4.6). It is
// schema-agnostic collection only: nothing here validates or sequences hello frames (see
// internal/enroll and internal/link for that).
package hostinfo

import (
	"os"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// Collect gathers this host's hello metadata fresh on every call, so a long-lived agent never
// reports stale values on reconnect. agentVersion is passed in rather than read here since it's
// build-time state (main.AgentVersion), not host state.
//
// SpoolDepth is left at its zero value: no caller today threads live spool state through to this
// collector, so reporting anything else would be a guess. Task 20's runtime status file is the
// intended real source once it exists.
func Collect(agentVersion string) frame.HelloPayload {
	hostname, _ := os.Hostname()
	osID, osVersion := osRelease()
	machineIDHash := machineIDHash()

	return frame.HelloPayload{
		Hostname:      hostname,
		MachineIDHash: machineIDHash,
		OS:            osID,
		OSVersion:     osVersion,
		Arch:          goArch(),
		AgentVersion:  agentVersion,
		PrimaryMACs:   primaryMACs(),
		Readiness:     identityReadiness(machineIDHash),
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
