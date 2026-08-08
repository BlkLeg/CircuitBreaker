package probe

import (
	"errors"
	"strings"
	"testing"
)

// readinessStates folds a readiness report into a collector -> state map plus the order the
// evaluator emitted it in, so a test can assert both the answer and the ProbeNames ordering the
// daemon's disable path depends on.
func readinessStates(t *testing.T, deps readinessDeps) (map[string]string, []string) {
	t.Helper()
	items := evaluateReadiness(deps)
	states := make(map[string]string, len(items))
	order := make([]string, 0, len(items))
	for _, item := range items {
		states[item.Collector] = item.State
		order = append(order, item.Collector)
	}
	return states, order
}

// isClosed reports whether the fixture socket from icmp_test.go was released.
func (s *fakeICMPSession) isClosed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.closed
}

// healthyReadinessDeps is a host that can do everything: the kernel hands out an unprivileged
// datagram-ICMP socket and /etc/resolv.conf names a resolver.
func healthyReadinessDeps() readinessDeps {
	return readinessDeps{
		openICMP:      func(string) (EchoSession, error) { return &fakeICMPSession{}, nil },
		systemServers: func() ([]string, error) { return []string{"10.0.0.1"}, nil },
	}
}

// TestProbeReadiness_TCPAndHTTPAreReadyByDefault pins §5's baseline: neither check needs anything
// of the host beyond an outbound socket, so on a working host all four rows are reported and TCP
// and HTTP are ready. The report must also cover exactly ProbeNames, in ProbeNames order — the
// daemon's disable path iterates that list, so a name that only one of the two knows about is a
// row that never gets flipped.
func TestProbeReadiness_TCPAndHTTPAreReadyByDefault(t *testing.T) {
	states, order := readinessStates(t, healthyReadinessDeps())

	for _, name := range []string{"probe.tcp", "probe.http"} {
		if states[name] != "ready" {
			t.Errorf("readiness[%q] = %q, want %q", name, states[name], "ready")
		}
	}
	if len(order) != len(ProbeNames) {
		t.Fatalf("readiness order = %v, want the %d ProbeNames %v", order, len(ProbeNames), ProbeNames)
	}
	for i, name := range ProbeNames {
		if order[i] != name {
			t.Errorf("readiness order = %v, want %v", order, ProbeNames)
			break
		}
	}
}

// TestProbeReadiness_ICMPIsUnavailableWhenPingGroupRangeIsUnusable pins the one host condition
// §5 names for ICMP. It is the same condition icmpChecker turns into ErrICMPUnavailable, and it
// must be reported as unavailable — not degraded, and never as a reason to hand the agent
// CAP_NET_RAW — with a remediation an operator can act on.
func TestProbeReadiness_ICMPIsUnavailableWhenPingGroupRangeIsUnusable(t *testing.T) {
	deps := healthyReadinessDeps()
	deps.openICMP = func(string) (EchoSession, error) {
		return nil, errors.New("listen ip4:1 0.0.0.0: socket: permission denied")
	}

	items := evaluateReadiness(deps)
	icmpRow := items[0]
	if icmpRow.Collector != "probe.icmp" {
		t.Fatalf("first readiness row = %q, want %q", icmpRow.Collector, "probe.icmp")
	}
	if icmpRow.State != "unavailable" {
		t.Errorf("probe.icmp state = %q, want %q", icmpRow.State, "unavailable")
	}
	if !strings.Contains(icmpRow.Reason, "permission denied") {
		t.Errorf("probe.icmp reason = %q, want it to carry the kernel's own error", icmpRow.Reason)
	}
	if !strings.Contains(icmpRow.Remediation, "ping_group_range") {
		t.Errorf("probe.icmp remediation = %q, want it to name net.ipv4.ping_group_range", icmpRow.Remediation)
	}

	// The other three are independent of the ICMP socket and must not be dragged down with it.
	states, _ := readinessStates(t, deps)
	for _, name := range []string{"probe.tcp", "probe.http", "probe.dns"} {
		if states[name] != "ready" {
			t.Errorf("readiness[%q] = %q with ICMP unavailable, want %q", name, states[name], "ready")
		}
	}
}

// TestProbeReadiness_DNSIsDegradedWhenNoUsableResolverIsConfigured pins §5's DNS wording exactly:
// degraded, not unavailable. A DNS monitor that names its own resolver still runs on a host with
// an empty /etc/resolv.conf, so reporting the capability as gone would be a lie that costs the
// operator every DNS monitor on that vantage.
func TestProbeReadiness_DNSIsDegradedWhenNoUsableResolverIsConfigured(t *testing.T) {
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

			items := evaluateReadiness(deps)
			dns := items[len(items)-1]
			if dns.Collector != "probe.dns" {
				t.Fatalf("last readiness row = %q, want %q", dns.Collector, "probe.dns")
			}
			if dns.State != "degraded" {
				t.Errorf("probe.dns state = %q, want %q", dns.State, "degraded")
			}
			if dns.Reason == "" {
				t.Error("probe.dns reason is empty, want it to say why no resolver is usable")
			}
			if dns.Remediation == "" {
				t.Error("probe.dns remediation is empty, want an operator-actionable instruction")
			}
		})
	}
}

// TestProbeReadiness_DNSIsReadyWithAConfiguredResolver is the other half of the same rule: the
// degraded row must clear itself once the host has a resolver again, since ingest_readiness only
// ever upserts.
func TestProbeReadiness_DNSIsReadyWithAConfiguredResolver(t *testing.T) {
	states, _ := readinessStates(t, healthyReadinessDeps())
	if states["probe.dns"] != "ready" {
		t.Errorf("probe.dns state = %q with a configured resolver, want %q", states["probe.dns"], "ready")
	}
	if states["probe.icmp"] != "ready" {
		t.Errorf("probe.icmp state = %q on a host that can open the socket, want %q", states["probe.icmp"], "ready")
	}
}

// TestProbeReadiness_ClosesTheProbeSocket proves the readiness check does not leak the socket it
// opened: readiness runs on every grant push, and a leaked descriptor per push is a slow death.
func TestProbeReadiness_ClosesTheProbeSocket(t *testing.T) {
	session := &fakeICMPSession{}
	deps := healthyReadinessDeps()
	deps.openICMP = func(string) (EchoSession, error) { return session, nil }

	evaluateReadiness(deps)

	if !session.isClosed() {
		t.Error("the readiness ICMP socket was left open, want it closed as soon as the open succeeded")
	}
}
