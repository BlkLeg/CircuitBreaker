package probe

import (
	"fmt"

	"circuitbreaker.dev/cb-agent/internal/frame"
)

// ProbeNames is every readiness row this package reports, in the order Readiness emits them.
//
// It mirrors internal/collect/host's CollectorNames and exists for the same reason: the daemon's
// disable path publishes one "disabled" row per name without re-deriving the list, and the
// backend's ingest_readiness only ever *upserts* — it never deletes. A check type added to
// Readiness but not to this list would leave the server showing a row that nothing will ever
// flip again, which is the stale-"Live" defect in a different coat.
var ProbeNames = []string{"probe.icmp", "probe.tcp", "probe.http", "probe.dns"}

// The two operator-facing instructions probe readiness can attach. They are constants because a
// remediation is an instruction someone will paste into a shell, not prose to be reworded per
// call site.
const (
	icmpReadinessRemediation = `allow unprivileged ICMP for the cb-agent user's group, e.g. sysctl -w net.ipv4.ping_group_range="0 2147483647"`
	dnsReadinessRemediation  = "configure at least one nameserver in /etc/resolv.conf, or set an explicit resolver on each DNS monitor"
)

// readinessDeps are the only two host facts probe readiness turns on. They are injected for the
// same reason icmpChecker's opener and dnsChecker's systemServers are: readiness is evaluated on
// every grant push, and no test may open a socket or read the machine's own resolver
// configuration to find out what this package would say about it.
type readinessDeps struct {
	openICMP      icmpOpener
	systemServers func() ([]string, error)
}

// Readiness reports whether this host can actually perform each of the four checks (§5).
//
// TCP and HTTP need nothing of the host beyond an outbound socket, so they are ready whenever
// the capability is granted at all — an unreachable *target* is a monitor result, not a
// readiness state. ICMP is unavailable when the kernel will not hand out an unprivileged
// datagram-ICMP socket (net.ipv4.ping_group_range not covering the agent's GID), the same
// condition icmpChecker turns into ErrICMPUnavailable; the agent ships with no CAP_NET_RAW and
// this row must never become the argument for adding it. DNS is *degraded* rather than
// unavailable when this host has no resolver of its own, because a DNS monitor that names its
// own resolver still runs.
//
// Every row is reported on every call, including the healthy ones: ingest_readiness only
// upserts, so a row the UI should stop showing has to be actively overwritten.
func Readiness() []frame.Readiness {
	return evaluateReadiness(readinessDeps{
		openICMP:      listenUnprivilegedICMP,
		systemServers: systemNameservers,
	})
}

func evaluateReadiness(deps readinessDeps) []frame.Readiness {
	items := make([]frame.Readiness, 0, len(ProbeNames))
	items = append(items,
		icmpReadiness(deps.openICMP),
		frame.Readiness{Collector: "probe.tcp", State: "ready"},
		frame.Readiness{Collector: "probe.http", State: "ready"},
		dnsReadiness(deps.systemServers),
	)
	return items
}

// icmpReadiness answers by doing the one thing that can fail: opening the socket. Probing the
// sysctl by reading /proc/sys/net/ipv4/ping_group_range and comparing it against the process GID
// would re-implement the kernel's own check and get it wrong on any host where a capability, a
// namespace or a seccomp filter decides otherwise — the open is the check.
func icmpReadiness(open icmpOpener) frame.Readiness {
	if open == nil {
		open = listenUnprivilegedICMP
	}
	session, err := open("udp4")
	if err != nil {
		return frame.Readiness{
			Collector:   "probe.icmp",
			State:       "unavailable",
			Reason:      err.Error(),
			Remediation: icmpReadinessRemediation,
		}
	}
	// The open *was* the probe. Holding the socket afterwards would bind a port for the life of
	// the agent, and readiness runs again on every grant push.
	_ = session.Close()
	return frame.Readiness{Collector: "probe.icmp", State: "ready"}
}

// dnsReadiness reports on the resolvers this host would fall back to for a monitor that names
// none. Both "no nameserver lines" and "the file could not be read at all" are the same
// operator-visible condition — nothing to fall back to — so both are degraded.
func dnsReadiness(servers func() ([]string, error)) frame.Readiness {
	if servers == nil {
		servers = systemNameservers
	}
	list, err := servers()
	if err != nil {
		return frame.Readiness{
			Collector:   "probe.dns",
			State:       "degraded",
			Reason:      fmt.Sprintf("this host's resolver configuration could not be read: %v", err),
			Remediation: dnsReadinessRemediation,
		}
	}
	if len(list) == 0 {
		return frame.Readiness{
			Collector:   "probe.dns",
			State:       "degraded",
			Reason:      "this host has no resolver configured, so a monitor that names none cannot be answered",
			Remediation: dnsReadinessRemediation,
		}
	}
	return frame.Readiness{Collector: "probe.dns", State: "ready"}
}
