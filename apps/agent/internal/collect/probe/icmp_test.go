package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"sync"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// ---------------------------------------------------------------------------
// Fixtures. Every one of these exists so that not one assertion below can reach
// a real socket: the ICMP checker's only contact with the kernel is its opener,
// and the tests replace it wholesale.
// ---------------------------------------------------------------------------

// icmpTestScope is the scope the ICMP tests run under: one directly connected network per
// family, so both an in-scope target and an out-of-scope one are expressible.
func icmpTestScope() netscope.Scope {
	networks := []string{"10.0.0.0/24", "fd00:abcd::/64"}
	return netscope.Scope{Networks: networks, DirectNetworks: networks, Version: "icmp-test"}
}

func icmpTestResolver(hosts map[string][]string) Resolver {
	return func(_ context.Context, host string) ([]string, error) {
		answers, ok := hosts[host]
		if !ok {
			return nil, fmt.Errorf("no test answer for %q", host)
		}
		return answers, nil
	}
}

type icmpReply struct {
	rtt time.Duration
	ok  bool
	err error
}

type fakeICMPPing struct {
	dst     netip.Addr
	seq     int
	timeout time.Duration
}

type fakeICMPSession struct {
	mu      sync.Mutex
	replies []icmpReply
	pings   []fakeICMPPing
	closed  bool
}

// Ping replays the scripted reply for this echo. Running past the end of the script is loss, not
// an error: it is the shape a test wants when it only cares about the first few packets.
func (s *fakeICMPSession) Ping(_ context.Context, dst netip.Addr, seq int, timeout time.Duration) (time.Duration, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	index := len(s.pings)
	s.pings = append(s.pings, fakeICMPPing{dst: dst, seq: seq, timeout: timeout})
	if index >= len(s.replies) {
		return 0, false, nil
	}
	reply := s.replies[index]
	return reply.rtt, reply.ok, reply.err
}

func (s *fakeICMPSession) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.closed = true
	return nil
}

func (s *fakeICMPSession) sent() []fakeICMPPing {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]fakeICMPPing(nil), s.pings...)
}

type fakeICMPOpener struct {
	mu       sync.Mutex
	networks []string
	session  *fakeICMPSession
	err      error
}

func (o *fakeICMPOpener) open(network string) (EchoSession, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.networks = append(o.networks, network)
	if o.err != nil {
		return nil, o.err
	}
	return o.session, nil
}

func (o *fakeICMPOpener) opened() []string {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]string(nil), o.networks...)
}

// icmpEchoes scripts n successful replies with the given latencies in milliseconds.
func icmpEchoes(latenciesMS ...float64) []icmpReply {
	out := make([]icmpReply, 0, len(latenciesMS))
	for _, ms := range latenciesMS {
		out = append(out, icmpReply{rtt: time.Duration(ms * float64(time.Millisecond)), ok: true})
	}
	return out
}

func newTestICMPChecker(opener *fakeICMPOpener, hosts map[string][]string) *icmpChecker {
	checker, ok := newICMPChecker(Deps{Scope: icmpTestScope, Resolve: icmpTestResolver(hosts)}).(*icmpChecker)
	if !ok {
		panic("newICMPChecker no longer returns *icmpChecker")
	}
	checker.open = opener.open
	return checker
}

func icmpSampleMetrics(samples []frame.ProbeSample) []string {
	out := make([]string, 0, len(samples))
	for _, sample := range samples {
		out = append(out, sample.Metric)
	}
	return out
}

func icmpSampleValue(t *testing.T, samples []frame.ProbeSample, metric string) float64 {
	t.Helper()
	for _, sample := range samples {
		if sample.Metric == metric {
			return sample.Value
		}
	}
	t.Fatalf("no %q sample in %v", metric, icmpSampleMetrics(samples))
	return 0
}

// ---------------------------------------------------------------------------
// Parity with collectors/net.py::collect_icmp.
// ---------------------------------------------------------------------------

func TestICMP_SampleOrderMatchesBackendCollector(t *testing.T) {
	session := &fakeICMPSession{replies: icmpEchoes(10, 20, 30)}
	opener := &fakeICMPOpener{session: session}
	checker := newTestICMPChecker(opener, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"packet_count":3}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}

	// The backend emits avail and packet_loss_pct unconditionally and appends the four latency
	// samples only when a reply arrived — in exactly this order.
	want := []string{"avail", "packet_loss_pct", "latency_ms", "latency_min_ms", "latency_max_ms", "jitter_ms"}
	got := icmpSampleMetrics(outcome.Samples)
	if len(got) != len(want) {
		t.Fatalf("samples = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("samples = %v, want %v", got, want)
		}
	}
	if !outcome.Up {
		t.Fatal("up = false, want true when replies arrived")
	}
	if outcome.Details != nil {
		t.Fatalf("details = %v, want nil (collect_icmp never sets details)", outcome.Details)
	}
	for _, check := range []struct {
		metric string
		want   float64
	}{
		{"avail", 1},
		{"packet_loss_pct", 0},
		{"latency_ms", 20},
		{"latency_min_ms", 10},
		{"latency_max_ms", 30},
		{"jitter_ms", 10},
	} {
		if got := icmpSampleValue(t, outcome.Samples, check.metric); got != check.want {
			t.Errorf("%s = %v, want %v", check.metric, got, check.want)
		}
	}
}

func TestICMP_JitterIsMeanAbsoluteSuccessiveDeltaRoundedToThreePlaces(t *testing.T) {
	// Deltas 1, 2 and 4 average to 7/3 = 2.3333…, which only matches the backend's
	// round(x, 3) if the Go side rounds at the same place.
	session := &fakeICMPSession{replies: icmpEchoes(1, 2, 4, 8)}
	opener := &fakeICMPOpener{session: session}
	checker := newTestICMPChecker(opener, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"packet_count":4}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if got := icmpSampleValue(t, outcome.Samples, "jitter_ms"); got != 2.333 {
		t.Errorf("jitter_ms = %v, want 2.333", got)
	}
	if got := icmpSampleValue(t, outcome.Samples, "latency_ms"); got != 3.75 {
		t.Errorf("latency_ms = %v, want 3.75", got)
	}
}

func TestICMP_LossPercentRoundingMatchesBackend(t *testing.T) {
	cases := []struct {
		name    string
		count   int
		replies []icmpReply
		want    float64
	}{
		{"one third", 3, icmpEchoes(5, 5), 33.33},
		{"two sevenths", 7, icmpEchoes(5, 5, 5, 5, 5), 28.57},
		{"none lost", 4, icmpEchoes(5, 5, 5, 5), 0},
		{"all lost", 5, nil, 100},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			session := &fakeICMPSession{replies: tc.replies}
			checker := newTestICMPChecker(&fakeICMPOpener{session: session}, nil)
			cfg := json.RawMessage(fmt.Sprintf(`{"packet_count":%d}`, tc.count))

			outcome, err := checker.Check(context.Background(), "10.0.0.5", cfg)
			if err != nil {
				t.Fatalf("Check: %v", err)
			}
			if got := icmpSampleValue(t, outcome.Samples, "packet_loss_pct"); got != tc.want {
				t.Errorf("packet_loss_pct = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestICMP_MessageStringsMatchBackendExactly(t *testing.T) {
	t.Run("replies arrived", func(t *testing.T) {
		// 3 of 4 answered: mean 20.0 ms, loss 25.0%. Python renders both as repr floats, so the
		// trailing ".0" is part of the contract.
		session := &fakeICMPSession{replies: []icmpReply{
			{rtt: 10 * time.Millisecond, ok: true},
			{ok: false},
			{rtt: 20 * time.Millisecond, ok: true},
			{rtt: 30 * time.Millisecond, ok: true},
		}}
		checker := newTestICMPChecker(&fakeICMPOpener{session: session}, nil)

		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"packet_count":4}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "20.0ms avg, 25.0% loss" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "20.0ms avg, 25.0% loss")
		}
	})

	t.Run("total loss", func(t *testing.T) {
		checker := newTestICMPChecker(&fakeICMPOpener{session: &fakeICMPSession{}}, nil)

		outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"packet_count":5}`))
		if err != nil {
			t.Fatalf("Check: %v", err)
		}
		if outcome.Msg != "100% packet loss (5 probes)" {
			t.Errorf("msg = %q, want %q", outcome.Msg, "100% packet loss (5 probes)")
		}
		if outcome.Up {
			t.Error("up = true, want false when every probe was lost")
		}
		if got := icmpSampleMetrics(outcome.Samples); len(got) != 2 {
			t.Errorf("samples = %v, want avail and packet_loss_pct only", got)
		}
		if got := icmpSampleValue(t, outcome.Samples, "avail"); got != 0 {
			t.Errorf("avail = %v, want 0", got)
		}
	})
}

func TestICMP_SingleReplyYieldsZeroJitter(t *testing.T) {
	session := &fakeICMPSession{replies: icmpEchoes(12.5)}
	checker := newTestICMPChecker(&fakeICMPOpener{session: session}, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{"packet_count":1}`))
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	if got := icmpSampleValue(t, outcome.Samples, "jitter_ms"); got != 0 {
		t.Errorf("jitter_ms = %v, want 0 for a single latency (_jitter's len < 2 branch)", got)
	}
	if got := icmpSampleValue(t, outcome.Samples, "latency_min_ms"); got != 12.5 {
		t.Errorf("latency_min_ms = %v, want 12.5", got)
	}
	if outcome.Msg != "12.5ms avg, 0.0% loss" {
		t.Errorf("msg = %q, want %q", outcome.Msg, "12.5ms avg, 0.0% loss")
	}
}

// TestICMP_NoUnprivilegedPingSupportIsAnExecutionErrorNotTargetDown pins the inverse of the
// backend's icmp_unavailable branch. The backend reports up=False there; on the agent that would
// mark every misconfigured host's monitor DOWN, so it must be an execution error instead — which
// leaves the monitor's last known state untouched.
func TestICMP_NoUnprivilegedPingSupportIsAnExecutionErrorNotTargetDown(t *testing.T) {
	opener := &fakeICMPOpener{err: errors.New("socket: permission denied")}
	checker := newTestICMPChecker(opener, nil)

	outcome, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{}`))
	if err == nil {
		t.Fatal("Check returned no error; a kernel that forbids unprivileged ICMP must be an execution error")
	}
	if !errors.Is(err, ErrICMPUnavailable) {
		t.Errorf("error %v does not wrap ErrICMPUnavailable", err)
	}
	if outcome.Up {
		t.Error("up = true on an execution error")
	}
	if len(outcome.Samples) != 0 {
		t.Errorf("samples = %v, want none: an avail=0 sample here would fabricate target DOWN", outcome.Samples)
	}
	if outcome.Msg != "" {
		t.Errorf("msg = %q, want empty: the runtime reports the error text", outcome.Msg)
	}
}

func TestICMP_IPv6TargetUsesICMPv6(t *testing.T) {
	cases := []struct {
		name string
		host string
		want string
	}{
		{"v4 literal", "10.0.0.5", "udp4"},
		{"v6 literal", "fd00:abcd::1", "udp6"},
		{"name resolving to v6", "six.internal", "udp6"},
		{"name resolving to v4", "four.internal", "udp4"},
	}
	hosts := map[string][]string{
		"six.internal":  {"fd00:abcd::2"},
		"four.internal": {"10.0.0.9"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			session := &fakeICMPSession{replies: icmpEchoes(1)}
			opener := &fakeICMPOpener{session: session}
			checker := newTestICMPChecker(opener, hosts)

			if _, err := checker.Check(context.Background(), tc.host, json.RawMessage(`{"packet_count":1}`)); err != nil {
				t.Fatalf("Check: %v", err)
			}
			opened := opener.opened()
			if len(opened) != 1 || opened[0] != tc.want {
				t.Fatalf("opened %v, want [%s]", opened, tc.want)
			}
		})
	}
}

func TestICMP_DefaultsAreCountFiveTimeoutOnePointFive(t *testing.T) {
	// The stored monitor config is sparse (model_dump(exclude_unset=True)), so the collector's
	// own params.get defaults are the real defaults — not pydantic's.
	session := &fakeICMPSession{replies: icmpEchoes(1, 1, 1, 1, 1)}
	checker := newTestICMPChecker(&fakeICMPOpener{session: session}, nil)

	if _, err := checker.Check(context.Background(), "10.0.0.5", json.RawMessage(`{}`)); err != nil {
		t.Fatalf("Check: %v", err)
	}
	sent := session.sent()
	if len(sent) != 5 {
		t.Fatalf("sent %d echoes, want the collector default of 5", len(sent))
	}
	for i, ping := range sent {
		if ping.timeout != 1500*time.Millisecond {
			t.Errorf("echo %d timeout = %v, want 1.5s", i, ping.timeout)
		}
		if ping.dst.String() != "10.0.0.5" {
			t.Errorf("echo %d dst = %v, want 10.0.0.5", i, ping.dst)
		}
	}
}

func TestICMP_TargetOutsideScopeIsNeverPinged(t *testing.T) {
	// Defence in depth: the runtime already judged the assignment's host, but a name can
	// resolve differently by the time the checker runs.
	session := &fakeICMPSession{replies: icmpEchoes(1)}
	opener := &fakeICMPOpener{session: session}
	checker := newTestICMPChecker(opener, map[string][]string{"rebound.internal": {"10.0.0.5", "8.8.8.8"}})

	_, err := checker.Check(context.Background(), "rebound.internal", json.RawMessage(`{"packet_count":1}`))
	if !errors.Is(err, ErrOutOfScope) {
		t.Fatalf("error = %v, want ErrOutOfScope", err)
	}
	if got := opener.opened(); len(got) != 0 {
		t.Errorf("opened %v, want no socket at all", got)
	}
	if got := session.sent(); len(got) != 0 {
		t.Errorf("sent %d echoes, want none", len(got))
	}
}
