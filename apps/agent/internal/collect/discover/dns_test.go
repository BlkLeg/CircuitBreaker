package discover

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

// stubResolver records what was asked and answers with whatever the case needs. Nothing in this
// file may reach a real resolver: the answer to a PTR query is whatever the runner's network
// decided, and half of these cases are about answers no cooperating resolver would ever give.
type stubResolver struct {
	mu      sync.Mutex
	queries []string
	ctxs    []context.Context
	answer  func(ctx context.Context, addr string) ([]string, error)
}

func (s *stubResolver) lookup(ctx context.Context, addr string) ([]string, error) {
	s.mu.Lock()
	s.queries = append(s.queries, addr)
	s.ctxs = append(s.ctxs, ctx)
	answer := s.answer
	s.mu.Unlock()
	if answer == nil {
		return nil, nil
	}
	return answer(ctx, addr)
}

func (s *stubResolver) asked() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.queries...)
}

func (s *stubResolver) contexts() []context.Context {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]context.Context(nil), s.ctxs...)
}

func newTestReverseDNS(stub *stubResolver, timeout time.Duration) *ReverseDNS {
	resolver := NewReverseDNS()
	resolver.lookup = stub.lookup
	resolver.timeout = timeout
	return resolver
}

func answering(names ...string) *stubResolver {
	return &stubResolver{answer: func(context.Context, string) ([]string, error) {
		return names, nil
	}}
}

// TestReverseDNSLimitsMatchThePlanAndTheWireContract pins the two numbers this file's contract is
// made of, and pins them where a regression would pass through.
//
// MaxHostnameLen is asserted against its literal value because that value is the contract seen from
// two sides: 253 is the DNS wire limit *and* the bound DiscoveryFindingPayload.hostname is validated
// against server-side. The whole reason a longer answer is discarded here rather than truncated is
// that a frame carrying it would be refused, losing a host finding over a name. The frame package
// declares no Go constant for it — the limit lives in the pydantic model — so the number is pinned
// here rather than cross-checked.
//
// The constructor is asserted separately for the same reason NewBanner's is: budget()'s <=0
// fallback is the only other reader of DefaultReverseDNSTimeout, so a constructor that installed
// some other positive timeout would leave every constant true and every real lookup wrong.
func TestReverseDNSLimitsMatchThePlanAndTheWireContract(t *testing.T) {
	if DefaultReverseDNSTimeout != 2*time.Second {
		t.Errorf("DefaultReverseDNSTimeout = %s, want plan §1's 2s", DefaultReverseDNSTimeout)
	}
	if MaxHostnameLen != 253 {
		t.Errorf("MaxHostnameLen = %d, want the DNS wire limit 253", MaxHostnameLen)
	}
	if got := NewReverseDNS().budget(); got != DefaultReverseDNSTimeout {
		t.Errorf("NewReverseDNS().budget() = %s, want DefaultReverseDNSTimeout %s", got, DefaultReverseDNSTimeout)
	}
	if got := NewReverseDNS().timeout; got != DefaultReverseDNSTimeout {
		t.Errorf("NewReverseDNS().timeout = %s, want DefaultReverseDNSTimeout %s — the constant has to be installed, not merely declared",
			got, DefaultReverseDNSTimeout)
	}
	if got := (&ReverseDNS{}).budget(); got != DefaultReverseDNSTimeout {
		t.Errorf("a zero ReverseDNS's budget = %s, want the documented %s rather than no bound", got, DefaultReverseDNSTimeout)
	}

	// NewReverseDNS also has to install a resolver, or every lookup returns "" and every host in
	// the product silently loses its name. The nil check is the assertion; calling it is not, since
	// that would reach the runner's real resolver.
	if NewReverseDNS().lookup == nil {
		t.Error("NewReverseDNS() installed no resolver, so every PTR lookup would report no name")
	}

	// The boundary itself, either side of the limit, so the constant is pinned by behavior and not
	// only by its own declaration.
	longest := strings.Repeat("a", MaxHostnameLen)
	if len(longest) != MaxHostnameLen {
		t.Fatalf("test fixture is %d bytes, want %d", len(longest), MaxHostnameLen)
	}
	if got := usableHostname(longest + "."); got != longest {
		t.Errorf("usableHostname of a %d-byte name = %q, want it accepted", MaxHostnameLen, got)
	}
	if got := usableHostname(longest + "a."); got != "" {
		t.Errorf("usableHostname of a %d-byte name = %q, want it discarded", MaxHostnameLen+1, got)
	}
}

func TestReverseDNSReturnsTheFirstUsableName(t *testing.T) {
	stub := answering("nas.internal.", "backup.internal.")

	got := newTestReverseDNS(stub, time.Second).Lookup(
		context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})

	if got != "nas.internal" {
		t.Fatalf("hostname = %q, want %q", got, "nas.internal")
	}
	if asked := stub.asked(); len(asked) != 1 || asked[0] != "192.168.10.24" {
		t.Fatalf("queried %v, want one query for 192.168.10.24", asked)
	}
}

func TestReverseDNSQueriesTheAddressAResolverUnderstands(t *testing.T) {
	cases := []struct {
		name  string
		addr  string
		query string
	}{
		// An IPv4-mapped address has to be unmapped or the query goes to ip6.arpa for an address
		// that only exists in in-addr.arpa.
		{name: "ipv4 mapped into ipv6", addr: "::ffff:192.168.10.24", query: "192.168.10.24"},
		// A zone is a local interface name, not part of the address; LookupAddr cannot parse it.
		{name: "zoned address", addr: "fe80::1%eth0", query: "fe80::1"},
		{name: "plain ipv6", addr: "fd00::5", query: "fd00::5"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := answering("host.internal.")

			newTestReverseDNS(stub, time.Second).Lookup(
				context.Background(), mustParseAddr(t, tc.addr), Options{})

			asked := stub.asked()
			if len(asked) != 1 || asked[0] != tc.query {
				t.Fatalf("queried %v, want one query for %q", asked, tc.query)
			}
		})
	}
}

func TestReverseDNSFailureYieldsNoHostname(t *testing.T) {
	cases := []struct {
		name   string
		answer func(context.Context, string) ([]string, error)
	}{
		{
			name: "no PTR record",
			answer: func(context.Context, string) ([]string, error) {
				return nil, errors.New("lookup 192.168.10.24: no such host")
			},
		},
		{
			name: "the resolver itself is unreachable",
			answer: func(context.Context, string) ([]string, error) {
				return nil, errors.New("read udp 10.0.0.2:53: i/o timeout")
			},
		},
		{
			name:   "an empty answer",
			answer: func(context.Context, string) ([]string, error) { return nil, nil },
		},
		{
			name: "an answer alongside an error",
			answer: func(context.Context, string) ([]string, error) {
				return []string{"nas.internal."}, errors.New("partial answer")
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := &stubResolver{answer: tc.answer}

			got := newTestReverseDNS(stub, time.Second).Lookup(
				context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})

			if got != "" {
				t.Fatalf("hostname = %q, want none", got)
			}
		})
	}
}

func TestReverseDNSIsBounded(t *testing.T) {
	stub := &stubResolver{answer: func(ctx context.Context, _ string) ([]string, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}}

	// Lookup runs off the test goroutine so a lookup with no budget of its own fails here in
	// seconds instead of hanging until the whole package times out.
	done := make(chan string, 1)
	go func() {
		done <- newTestReverseDNS(stub, 100*time.Millisecond).Lookup(
			context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})
	}()

	select {
	case got := <-done:
		if got != "" {
			t.Fatalf("hostname = %q, want none", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Lookup did not return; the resolver call carried no budget of its own")
	}

	// The budget has to reach the resolver, not just wrap it: net.Resolver honours the context
	// it is given, and a caller-supplied context with no deadline is the normal case.
	ctxs := stub.contexts()
	if len(ctxs) != 1 {
		t.Fatalf("resolver called %d times, want 1", len(ctxs))
	}
	if _, ok := ctxs[0].Deadline(); !ok {
		t.Fatal("the resolver was handed a context with no deadline")
	}
}

func TestReverseDNSRejectsUntrustedAnswers(t *testing.T) {
	// The PTR answer comes from a resolver on the network being scanned, and lands in
	// ScanResult.hostname, which the review queue renders and the matcher compares. Anything that
	// is not plausibly a DNS name is discarded rather than sanitised: a hostname is optional
	// evidence, so dropping it costs nothing.
	cases := []struct {
		name   string
		answer string
	}{
		{name: "empty", answer: ""},
		{name: "the root", answer: "."},
		{name: "an empty label", answer: "nas..internal."},
		{name: "a leading dot", answer: ".nas.internal."},
		{name: "an embedded space", answer: "nas internal."},
		{name: "an embedded newline", answer: "nas.internal\nSet-Cookie: x=1."},
		{name: "a control byte", answer: "nas\x00.internal."},
		{name: "a terminal escape", answer: "\x1b[31mnas.internal."},
		{name: "invalid utf8", answer: "nas\xff.internal."},
		{name: "a slash", answer: "nas/internal."},
		{name: "over 253 bytes", answer: strings.Repeat("a", 254) + "."},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := newTestReverseDNS(answering(tc.answer), time.Second).Lookup(
				context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})

			if got != "" {
				t.Fatalf("hostname = %q, want none", got)
			}
		})
	}
}

func TestReverseDNSSkipsRejectedAnswersForAUsableOne(t *testing.T) {
	got := newTestReverseDNS(answering("nas internal.", "nas.internal."), time.Second).Lookup(
		context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})

	if got != "nas.internal" {
		t.Fatalf("hostname = %q, want %q", got, "nas.internal")
	}
}

func TestReverseDNSAcceptsRealWorldNames(t *testing.T) {
	cases := []struct {
		answer string
		want   string
	}{
		{answer: "nas.internal.", want: "nas.internal"},
		{answer: "NAS.Internal.", want: "NAS.Internal"},
		{answer: "printer-2.lan.", want: "printer-2.lan"},
		{answer: "wpad_proxy.home.arpa.", want: "wpad_proxy.home.arpa"},
		{answer: "xn--pnhb.example.", want: "xn--pnhb.example"},
		{answer: "host", want: "host"},
		{answer: strings.Repeat("a", 253), want: strings.Repeat("a", 253)},
	}

	for _, tc := range cases {
		t.Run(tc.answer, func(t *testing.T) {
			got := newTestReverseDNS(answering(tc.answer), time.Second).Lookup(
				context.Background(), mustParseAddr(t, "192.168.10.24"), Options{})

			if got != tc.want {
				t.Fatalf("hostname = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestReverseDNSSkipsWhenTheMethodIsNotSelected(t *testing.T) {
	stub := answering("nas.internal.")

	got := newTestReverseDNS(stub, time.Second).Lookup(
		context.Background(), mustParseAddr(t, "192.168.10.24"),
		Options{Methods: []string{MethodICMP, MethodTCPConnect}})

	if got != "" {
		t.Fatalf("hostname = %q for a request that did not select %s", got, MethodReverseDNS)
	}
	if asked := stub.asked(); len(asked) != 0 {
		t.Fatalf("queried %v; an unselected method performs no lookup", asked)
	}
}
