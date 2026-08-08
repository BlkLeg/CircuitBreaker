package discover

import (
	"context"
	"errors"
	"fmt"

	"circuitbreaker.dev/cb-agent/internal/collect/probe"
	"circuitbreaker.dev/cb-agent/internal/frame"
)

// DiscoverNames is every readiness row this package reports, in the order Readiness emits them.
//
// It is probe.ProbeNames' counterpart and exists for the same reason: the daemon's disable path
// publishes one "disabled" row per name without re-deriving the list, and the backend's
// ingest_readiness only ever *upserts* — it never deletes. A collector added to Readiness but not
// to this list would leave the server showing a row that nothing will ever flip again, so a
// revoked local_discovery grant would keep reading as a discovery-ready vantage forever.
var DiscoverNames = []string{"discovery.neighbor", "discovery.icmp", "discovery.tcp", "discovery.dns"}

// The operator-facing instructions discovery readiness can attach. They are constants because a
// remediation is something someone pastes into a shell, not prose to be reworded per call site.
//
// The ICMP one is probe's, not a second copy: the socket both packages open is the same socket
// and the sysctl that governs it is the same sysctl, so two wordings could only drift into
// telling one operator two different things about one kernel setting.
const (
	neighborReadinessRemediation = "allow the agent to open an AF_NETLINK/NETLINK_ROUTE socket — a seccomp profile or a container without CAP_NET_ADMIN-free netlink access will block the neighbor dump"
	dnsReadinessRemediation      = "configure at least one nameserver in /etc/resolv.conf so discovered addresses can be resolved to names"
)

// Readiness reports whether this host can actually perform each of the four discovery methods
// (plan §6: collector state, whether ICMP datagram probing is usable, neighbor-cache
// availability).
//
// It takes a context where probe.Readiness takes none, because one of the four checks is a real
// kernel round trip: Neighbors bounds itself at neighborDumpTimeout, but this runs on the link's
// own goroutine when a grant arrives, and three seconds of a wedged netlink socket is three
// seconds of no frames being dispatched. The context is the caller's way out.
//
// Every row is reported on every call, healthy ones included: ingest_readiness only upserts, so a
// row the UI should stop showing has to be actively overwritten.
func Readiness(ctx context.Context) []frame.Readiness {
	return evaluateReadiness(ctx, readinessDeps{
		neighbors:     neighbors,
		openICMP:      probe.ListenUnprivilegedICMP,
		systemServers: probe.SystemNameservers,
	})
}

// readinessDeps are the three host facts discovery readiness turns on. They are injected for the
// same reason Liveness' open/dial and ReverseDNS' lookup are: readiness is evaluated on every
// grant push, and no test may open an ICMP socket, dump the kernel's neighbor table or read the
// machine's own resolver configuration to find out what this package would say about it.
type readinessDeps struct {
	neighbors     func(context.Context) ([]Neighbor, error)
	openICMP      func(network string) (probe.EchoSession, error)
	systemServers func() ([]string, error)
}

func evaluateReadiness(ctx context.Context, deps readinessDeps) []frame.Readiness {
	items := make([]frame.Readiness, 0, len(DiscoverNames))
	items = append(items,
		neighborReadiness(ctx, deps.neighbors),
		icmpReadiness(deps.openICMP),
		// TCP connect needs nothing of the host beyond an outbound socket, so it is ready
		// whenever the capability is granted at all. A target that refuses the connect is a
		// discovery *result*, not a readiness state, and the granted port set is a property of
		// the grant rather than of this machine.
		frame.Readiness{Collector: "discovery.tcp", State: "ready"},
		dnsReadiness(deps.systemServers),
	)
	return items
}

// neighborReadiness answers by performing the dump. Inspecting the platform or stat-ing a netlink
// path would re-implement the kernel's own decision and get it wrong on any host where a seccomp
// filter, a namespace or a container runtime decides otherwise — the dump is the check.
//
// An *empty* cache is still ready. A host that has not spoken to any neighbor yet has an empty
// table, which is ordinary rather than broken; flagging it would fire this row on every freshly
// booted agent and teach operators to ignore it.
func neighborReadiness(ctx context.Context, read func(context.Context) ([]Neighbor, error)) frame.Readiness {
	if read == nil {
		read = neighbors
	}
	if _, err := read(ctx); err != nil {
		row := frame.Readiness{
			Collector: "discovery.neighbor",
			State:     "unavailable",
			Reason:    err.Error(),
		}
		// ErrNeighborsUnsupported is a property of the build, not of the host: the agent ships
		// linux/amd64 and linux/arm64 only, and there is nothing an operator on any other
		// platform could paste into a shell. Attaching an instruction that cannot work would be
		// worse than attaching none.
		if !errors.Is(err, ErrNeighborsUnsupported) {
			row.Remediation = neighborReadinessRemediation
		}
		return row
	}
	return frame.Readiness{Collector: "discovery.neighbor", State: "ready"}
}

// icmpReadiness answers by doing the one thing that can fail: opening the socket, exactly as
// probe.Readiness does and against the same kernel condition (net.ipv4.ping_group_range not
// covering the agent's GID).
//
// The state is *unavailable*, not degraded, even though a sweep with no ICMP still runs on TCP
// connect. This row names one method, and that method cannot run at all; folding the sweep's
// fallback into it would leave an operator unable to tell a host where ICMP works from one where
// it does not. The fallback is reported per run instead, on SweepSummary.ICMPUnavailable. And as
// in probe: this row must never become the argument for handing the agent CAP_NET_RAW.
func icmpReadiness(open func(network string) (probe.EchoSession, error)) frame.Readiness {
	if open == nil {
		open = probe.ListenUnprivilegedICMP
	}
	// "udp4" matches what Liveness opens, so this reports on the socket the sweep will actually
	// use rather than on a family it never touches.
	session, err := open("udp4")
	if err != nil {
		return frame.Readiness{
			Collector:   "discovery.icmp",
			State:       "unavailable",
			Reason:      err.Error(),
			Remediation: probe.ICMPReadinessRemediation,
		}
	}
	// The open *was* the probe. Holding the socket afterwards would bind a port for the life of
	// the agent, and readiness runs again on every grant push.
	_ = session.Close()
	return frame.Readiness{Collector: "discovery.icmp", State: "ready"}
}

// dnsReadiness reports on the resolvers ReverseDNS would use for a PTR lookup. Both "no
// nameserver lines" and "the file could not be read at all" are the same operator-visible
// condition — nothing to ask — so both are degraded.
//
// Degraded rather than unavailable, because ReverseDNS.Lookup returns "" on every failure and
// never fails a host: a sweep on a resolver-less agent still completes and still reports every
// address, MAC and open port the backend matches on. It just reports them without names, and
// calling that "unavailable" would tell an operator discovery had stopped when it had not.
func dnsReadiness(servers func() ([]string, error)) frame.Readiness {
	if servers == nil {
		servers = probe.SystemNameservers
	}
	list, err := servers()
	if err != nil {
		return frame.Readiness{
			Collector:   "discovery.dns",
			State:       "degraded",
			Reason:      fmt.Sprintf("this host's resolver configuration could not be read: %v", err),
			Remediation: dnsReadinessRemediation,
		}
	}
	if len(list) == 0 {
		return frame.Readiness{
			Collector:   "discovery.dns",
			State:       "degraded",
			Reason:      "this host has no resolver configured, so a discovered address cannot be resolved to a name",
			Remediation: dnsReadinessRemediation,
		}
	}
	return frame.Readiness{Collector: "discovery.dns", State: "ready"}
}
