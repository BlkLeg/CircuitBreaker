package discover

import (
	"context"
	"errors"
	"net/netip"
	"strings"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/collect/probe"
)

// fakeEchoSession is a probe.EchoSession that never touches a socket. Readiness opens one and
// closes it again without probing anything, so Ping is unreachable here and says so rather than
// returning a plausible-looking zero that would hide a readiness check gone wrong.
type fakeEchoSession struct{ closed bool }

func (s *fakeEchoSession) Ping(context.Context, netip.Addr, int, time.Duration) (time.Duration, bool, error) {
	panic("readiness must not probe")
}

func (s *fakeEchoSession) Close() error { s.closed = true; return nil }

// healthyReadinessDeps is a host that can do all four: the kernel answers a neighbor dump, it
// hands out an unprivileged datagram-ICMP socket, and /etc/resolv.conf names a resolver.
func healthyReadinessDeps() readinessDeps {
	return readinessDeps{
		neighbors:     func(context.Context) ([]Neighbor, error) { return nil, nil },
		openICMP:      func(string) (probe.EchoSession, error) { return &fakeEchoSession{}, nil },
		systemServers: func() ([]string, error) { return []string{"10.0.0.1"}, nil },
	}
}

// readinessStates folds a report into a collector -> row map plus the order it was emitted in,
// so a test can assert both the answer and the DiscoverNames ordering the daemon's disable path
// depends on.
func readinessStates(t *testing.T, deps readinessDeps) (map[string]string, []string) {
	t.Helper()
	items := evaluateReadiness(context.Background(), deps)
	states := make(map[string]string, len(items))
	order := make([]string, 0, len(items))
	for _, item := range items {
		states[item.Collector] = item.State
		order = append(order, item.Collector)
	}
	return states, order
}

// TestDiscoverReadiness_ReportsEveryNameInDiscoverNamesOrder pins the contract the daemon's
// disable path leans on: ingest_readiness only upserts, so a row published by Readiness but
// absent from DiscoverNames could never be flipped back to "disabled" when the grant goes away,
// and the server would show this vantage as discovery-ready forever.
func TestDiscoverReadiness_ReportsEveryNameInDiscoverNamesOrder(t *testing.T) {
	states, order := readinessStates(t, healthyReadinessDeps())

	if len(order) != len(DiscoverNames) {
		t.Fatalf("readiness order = %v, want the %d DiscoverNames %v", order, len(DiscoverNames), DiscoverNames)
	}
	for i, name := range DiscoverNames {
		if order[i] != name {
			t.Fatalf("readiness order = %v, want %v", order, DiscoverNames)
		}
	}
	for _, name := range DiscoverNames {
		if states[name] != "ready" {
			t.Errorf("readiness[%q] = %q on a host that can do everything, want %q", name, states[name], "ready")
		}
	}
}

// TestDiscoverReadiness_ICMPIsUnavailableWithAnActionableRemediation pins plan §6's "whether ICMP
// datagram probing is usable". The row names one method, and that method cannot run at all, so it
// is unavailable rather than degraded — an operator who sees "degraded" cannot tell a working
// sweep from a TCP-only one. It must never become the argument for handing the agent CAP_NET_RAW,
// which is why the remediation names the sysctl instead.
func TestDiscoverReadiness_ICMPIsUnavailableWithAnActionableRemediation(t *testing.T) {
	deps := healthyReadinessDeps()
	deps.openICMP = func(string) (probe.EchoSession, error) {
		return nil, errors.New("socket: permission denied")
	}

	items := evaluateReadiness(context.Background(), deps)
	icmp := items[1]
	if icmp.Collector != "discovery.icmp" {
		t.Fatalf("readiness[1] = %q, want %q", icmp.Collector, "discovery.icmp")
	}
	if icmp.State != "unavailable" {
		t.Errorf("discovery.icmp state = %q, want %q", icmp.State, "unavailable")
	}
	if !strings.Contains(icmp.Reason, "permission denied") {
		t.Errorf("discovery.icmp reason = %q, want it to carry the kernel's own error", icmp.Reason)
	}
	if !strings.Contains(icmp.Remediation, "ping_group_range") {
		t.Errorf("discovery.icmp remediation = %q, want it to name net.ipv4.ping_group_range", icmp.Remediation)
	}

	// The other three are independent of the ICMP socket: a sweep still runs on TCP connect, and
	// dragging them down with it would hide which half of the collector is actually broken.
	states, _ := readinessStates(t, deps)
	for _, name := range []string{"discovery.neighbor", "discovery.tcp", "discovery.dns"} {
		if states[name] != "ready" {
			t.Errorf("readiness[%q] = %q with ICMP unavailable, want %q", name, states[name], "ready")
		}
	}
}

// TestDiscoverReadiness_ClosesTheProbeSocket proves the check does not leak the socket it opened.
// Readiness runs again on every grant push, and a descriptor per push is a slow death.
func TestDiscoverReadiness_ClosesTheProbeSocket(t *testing.T) {
	session := &fakeEchoSession{}
	deps := healthyReadinessDeps()
	deps.openICMP = func(string) (probe.EchoSession, error) { return session, nil }

	evaluateReadiness(context.Background(), deps)

	if !session.closed {
		t.Error("the readiness ICMP socket was left open, want it closed as soon as the open succeeded")
	}
}

// TestDiscoverReadiness_NeighborCacheUnavailability pins plan §6's "neighbor-cache availability".
// The unsupported-platform sentinel gets no remediation: the agent only ships Linux binaries and
// there is nothing an operator could paste into a shell. Every other failure is something on this
// host blocking the netlink socket, which is actionable, so that one carries an instruction.
func TestDiscoverReadiness_NeighborCacheUnavailability(t *testing.T) {
	for _, tc := range []struct {
		name            string
		err             error
		wantRemediation bool
	}{
		{"platform has no neighbor cache", ErrNeighborsUnsupported, false},
		{"netlink socket refused", errors.New("discover: open netlink socket: operation not permitted"), true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			deps := healthyReadinessDeps()
			deps.neighbors = func(context.Context) ([]Neighbor, error) { return nil, tc.err }

			items := evaluateReadiness(context.Background(), deps)
			neighbor := items[0]
			if neighbor.Collector != "discovery.neighbor" {
				t.Fatalf("readiness[0] = %q, want %q", neighbor.Collector, "discovery.neighbor")
			}
			if neighbor.State != "unavailable" {
				t.Errorf("discovery.neighbor state = %q, want %q", neighbor.State, "unavailable")
			}
			if !strings.Contains(neighbor.Reason, tc.err.Error()) {
				t.Errorf("discovery.neighbor reason = %q, want it to carry %q", neighbor.Reason, tc.err)
			}
			if got := neighbor.Remediation != ""; got != tc.wantRemediation {
				t.Errorf("discovery.neighbor remediation = %q, want a remediation: %v", neighbor.Remediation, tc.wantRemediation)
			}
		})
	}
}

// TestDiscoverReadiness_AnEmptyNeighborCacheIsStillReady is the other half of the same rule. An
// empty cache is an ordinary state on a host that has not spoken to anything yet; reporting it as
// a fault would make the row fire on a freshly booted agent and teach operators to ignore it.
func TestDiscoverReadiness_AnEmptyNeighborCacheIsStillReady(t *testing.T) {
	deps := healthyReadinessDeps()
	deps.neighbors = func(context.Context) ([]Neighbor, error) { return []Neighbor{}, nil }

	states, _ := readinessStates(t, deps)
	if states["discovery.neighbor"] != "ready" {
		t.Errorf("discovery.neighbor state = %q with an empty cache, want %q", states["discovery.neighbor"], "ready")
	}
}

// TestDiscoverReadiness_DNSIsDegradedWithoutAResolver pins the state exactly: degraded, not
// unavailable. ReverseDNS.Lookup returns "" rather than an error on every failure, so a host with
// no resolver still completes every sweep — it just reports findings without hostnames. Calling
// that unavailable would tell an operator discovery had stopped when it had not.
func TestDiscoverReadiness_DNSIsDegradedWithoutAResolver(t *testing.T) {
	for _, tc := range []struct {
		name    string
		servers func() ([]string, error)
	}{
		{"no nameserver lines", func() ([]string, error) { return nil, nil }},
		{"unreadable resolv.conf", func() ([]string, error) { return nil, errors.New("open /etc/resolv.conf: no such file or directory") }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			deps := healthyReadinessDeps()
			deps.systemServers = tc.servers

			items := evaluateReadiness(context.Background(), deps)
			dns := items[len(items)-1]
			if dns.Collector != "discovery.dns" {
				t.Fatalf("last readiness row = %q, want %q", dns.Collector, "discovery.dns")
			}
			if dns.State != "degraded" {
				t.Errorf("discovery.dns state = %q, want %q", dns.State, "degraded")
			}
			if dns.Reason == "" {
				t.Error("discovery.dns reason is empty, want it to say why no PTR lookup can be answered")
			}
			if dns.Remediation == "" {
				t.Error("discovery.dns remediation is empty, want an operator-actionable instruction")
			}
		})
	}
}

// TestDiscoverReadiness_UsesTheRealHostSeamsByDefault proves the exported entry point is wired to
// this host rather than to a zero value: a nil dep must fall back to the production seam, not
// silently report "ready" for a collector nothing checked. It asserts the shape only, because the
// answers depend on the machine the suite runs on.
func TestDiscoverReadiness_UsesTheRealHostSeamsByDefault(t *testing.T) {
	items := Readiness(context.Background())
	if len(items) != len(DiscoverNames) {
		t.Fatalf("Readiness() reported %d rows, want the %d DiscoverNames", len(items), len(DiscoverNames))
	}
	for i, name := range DiscoverNames {
		if items[i].Collector != name {
			t.Errorf("Readiness()[%d].Collector = %q, want %q", i, items[i].Collector, name)
		}
		switch items[i].State {
		case "ready", "degraded", "unavailable":
		default:
			t.Errorf("Readiness()[%d].State = %q, want one of ready/degraded/unavailable", i, items[i].State)
		}
	}
}
