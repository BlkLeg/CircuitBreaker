package discover

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/frame"
	"circuitbreaker.dev/cb-agent/internal/netscope"
)

// discoveryScope is one directly connected /24. Every target below sits inside it, so a refusal
// in these tests is always the runtime's own doing rather than the evaluator's.
func discoveryScope() netscope.Scope {
	return netscope.Derive(
		[]netscope.InterfaceFacts{{
			Name:  "eth0",
			Flags: []string{"up", "broadcast"},
			Addrs: []string{"10.20.0.5/24"},
		}},
		netscope.Config{},
	)
}

const testDispatchID = "7c2e5a91b4d3406f8a1e9c7d05b2f36a"

// testHostTimeoutMS is the host budget every request below carries. It is a named constant rather
// than a literal inside request() because the cancellation test's bound is *derived* from it: "work
// stops within one host timeout" is a claim about the request, and a bound written as a bare second
// would pass just as well on an implementation that waited out the whole sweep.
const testHostTimeoutMS = 200

var testHostTimeout = time.Duration(testHostTimeoutMS) * time.Millisecond

// harness owns every stub the runtime is allowed to reach. Fields are set before start, never
// after: the runtime reads them from its own goroutines, and a test that mutated one mid-scan
// would be racing its own subject.
type harness struct {
	rt  *Runtime
	out chan frame.Frame

	// sweepNet backs Liveness and bannerDial backs Banner. They are separate dialers so a test
	// can tell a liveness connect from a banner read on the same port.
	sweepNet   *stubNet
	bannerDial *stubDial
	resolver   *stubResolver

	neighbors    []Neighbor
	neighborsErr error
	// neighborCalls counts reads of the kernel cache, so a rejection can assert the collector
	// never even looked.
	neighborCalls atomic.Int64
	// refuseNeighbors fails the test if the cache is read at all.
	refuseNeighbors bool

	validate Validator
	scope    netscope.Scope
	// granted stands in for main.go's applyDiscoveryConfig having seen a real `local_discovery`
	// grant. It defaults to true because almost every test below is about what a *granted* agent
	// does, and it is a field rather than an argument so that a test wanting the fail-closed
	// default has to clear it out loud.
	granted bool
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	return &harness{
		out:        make(chan frame.Frame, 512),
		sweepNet:   &stubNet{},
		bannerDial: &stubDial{},
		resolver:   &stubResolver{},
		scope:      discoveryScope(),
		validate:   func(frame.DiscoveryRequestPayload, netscope.Scope) Rejection { return Rejection{} },
		granted:    true,
	}
}

func (h *harness) start(t *testing.T) *harness {
	t.Helper()
	banner := NewBanner()
	banner.dial = h.bannerDial.dial
	banner.timeout = 200 * time.Millisecond

	h.rt = NewRuntime(h.out, RuntimeOptions{
		Validate:   h.validate,
		Scope:      h.scope,
		Liveness:   newTestLiveness(h.sweepNet),
		ReverseDNS: newTestReverseDNS(h.resolver, 200*time.Millisecond),
		Banner:     banner,
		Neighbors: func(context.Context) ([]Neighbor, error) {
			h.neighborCalls.Add(1)
			if h.refuseNeighbors {
				t.Errorf("read the kernel neighbor cache; this request must never start work")
			}
			return h.neighbors, h.neighborsErr
		},
	})
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	h.rt.Start(ctx)
	t.Cleanup(h.rt.Stop)
	// The grant, said out loud. A freshly constructed Runtime is disabled no matter what its
	// options carried, so this is the same step main.go takes at startup and on every
	// capabilities.set: derive the scope, build the validator, then Configure.
	if h.granted {
		h.rt.Configure(h.scope, h.validate)
	}
	return h
}

// request builds a discovery.request over 10.20.0.0/29 — eight addresses, all inside the scope's
// /24, none of them its broadcast.
func request(t *testing.T, dispatchID string, mutate ...func(*frame.DiscoveryRequestPayload)) json.RawMessage {
	t.Helper()
	payload := frame.DiscoveryRequestPayload{
		DispatchID:         dispatchID,
		ScanJobID:          481,
		Targets:            []string{"10.20.0.0/29"},
		Methods:            []string{MethodNeighborCache, MethodTCPConnect, MethodReverseDNS},
		TCPPorts:           []int{22, 443},
		HostTimeoutMS:      testHostTimeoutMS,
		MaxConcurrentHosts: 4,
		ScopeVersion:       discoveryScope().Version,
		DeadlineAt:         time.Now().UTC().Add(20 * time.Second),
	}
	for _, m := range mutate {
		m(&payload)
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal discovery.request: %v", err)
	}
	return data
}

func cancellation(t *testing.T, dispatchID, reason string) json.RawMessage {
	t.Helper()
	data, err := json.Marshal(frame.DiscoveryCancelPayload{DispatchID: dispatchID, Reason: reason})
	if err != nil {
		t.Fatalf("marshal discovery.cancel: %v", err)
	}
	return data
}

// nextFinding reads one discovery.finding, failing the test on any other frame type: the runtime
// has exactly one outbound frame type, so anything else is a bug rather than noise to skip.
func nextFinding(t *testing.T, out <-chan frame.Frame, timeout time.Duration) frame.DiscoveryFindingPayload {
	t.Helper()
	select {
	case f := <-out:
		if f.Type != frame.TypeDiscoveryFinding {
			t.Fatalf("frame type = %q, want %q", f.Type, frame.TypeDiscoveryFinding)
		}
		var payload frame.DiscoveryFindingPayload
		if err := json.Unmarshal(f.Payload, &payload); err != nil {
			t.Fatalf("decode discovery.finding payload: %v", err)
		}
		return payload
	case <-time.After(timeout):
		t.Fatalf("no discovery.finding within %s", timeout)
	}
	return frame.DiscoveryFindingPayload{}
}

// drainUntilSummary collects every finding up to and including the dispatch's terminal one.
func drainUntilSummary(t *testing.T, out <-chan frame.Frame, timeout time.Duration) (hosts []frame.DiscoveryFindingPayload, summary frame.DiscoveryFindingPayload) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for {
		payload := nextFinding(t, out, time.Until(deadline))
		if payload.Kind == frame.DiscoveryKindSummary {
			return hosts, payload
		}
		hosts = append(hosts, payload)
	}
}

// stubDial is the dialer Banner is given. stubNet already covers the sweep, but a banner capture
// has to answer with a real net.Conn rather than a bare success, so it gets its own.
type stubDial struct {
	mu     sync.Mutex
	dialed []string
	reply  func(ctx context.Context, address string) (net.Conn, error)
}

func (s *stubDial) dial(ctx context.Context, _, address string) (net.Conn, error) {
	s.mu.Lock()
	s.dialed = append(s.dialed, address)
	reply := s.reply
	s.mu.Unlock()
	if reply == nil {
		return nil, errors.New("connection refused")
	}
	return reply(ctx, address)
}

func (s *stubDial) addresses() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.dialed...)
}

// greetingConn is a connection that volunteers one greeting and closes, which is exactly the
// shape Banner.Capture reads. net.Pipe rather than a listener: no port is bound, so the address
// the banner dialer was handed stays the assertion instead of being rewritten to loopback.
func greetingConn(greeting string) net.Conn {
	client, server := net.Pipe()
	go func() {
		_, _ = server.Write([]byte(greeting))
		_ = server.Close()
	}()
	return client
}

func neighbor(t *testing.T, addr, mac string) Neighbor {
	t.Helper()
	return Neighbor{IP: mustParseAddr(t, addr), MAC: mac, State: NeighborReachable}
}

func findingAddresses(findings []frame.DiscoveryFindingPayload) []string {
	out := make([]string, 0, len(findings))
	for _, f := range findings {
		out = append(out, f.IPAddress)
	}
	sort.Strings(out)
	return out
}

func findingFor(findings []frame.DiscoveryFindingPayload, addr string) (frame.DiscoveryFindingPayload, bool) {
	for _, f := range findings {
		if f.IPAddress == addr {
			return f, true
		}
	}
	return frame.DiscoveryFindingPayload{}, false
}

// TestDiscoveryRuntime_EmitsOneFindingPerHostAndExactlyOneSummary is the shape that makes this
// runtime structurally different from probe.Runtime, which emits one result per unit of work.
func TestDiscoveryRuntime_EmitsOneFindingPerHostAndExactlyOneSummary(t *testing.T) {
	h := newHarness(t)
	h.neighbors = []Neighbor{
		neighbor(t, "10.20.0.3", "aa:bb:cc:dd:ee:01"),
		neighbor(t, "10.20.0.6", "aa:bb:cc:dd:ee:02"),
		// Outside the request's /29: the kernel knows about it, this dispatch was not asked
		// about it, and a finding for it would be an address nobody authorized scanning.
		neighbor(t, "10.20.0.99", "aa:bb:cc:dd:ee:03"),
	}
	h.sweepNet.dialReply = func(_ context.Context, address string) error {
		switch address {
		case "10.20.0.3:22", "10.20.0.5:443":
			return nil
		}
		return errors.New("connection refused")
	}
	h.bannerDial.reply = func(context.Context, string) (net.Conn, error) {
		return greetingConn("SSH-2.0-OpenSSH_9.6"), nil
	}
	h.resolver.answer = func(context.Context, string) ([]string, error) {
		return []string{"nas.internal."}, nil
	}
	h.start(t)

	if err := h.rt.Request(request(t, testDispatchID)); err != nil {
		t.Fatalf("Request error = %v", err)
	}

	hosts, summary := drainUntilSummary(t, h.out, 10*time.Second)

	// .3 answered a connect and is in the cache, .5 only answered a connect, .6 is only in the
	// cache. .4 and the rest answered nothing and must produce no finding at all — a /29 sweep
	// that reported silence would be six rows for a reviewer to dismiss.
	want := []string{"10.20.0.3", "10.20.0.5", "10.20.0.6"}
	if got := findingAddresses(hosts); !equalStrings(got, want) {
		t.Fatalf("host findings = %v, want %v", got, want)
	}
	for _, host := range hosts {
		if host.Kind != frame.DiscoveryKindHost {
			t.Errorf("%s kind = %q, want %q", host.IPAddress, host.Kind, frame.DiscoveryKindHost)
		}
		if host.Terminal {
			t.Errorf("%s is marked terminal; only the summary closes a dispatch", host.IPAddress)
		}
		if host.DispatchID != testDispatchID || host.ScanJobID != 481 {
			t.Errorf("%s carries dispatch %q job %d, want %q/481", host.IPAddress, host.DispatchID, host.ScanJobID, testDispatchID)
		}
	}

	cached, _ := findingFor(hosts, "10.20.0.3")
	if cached.MACAddress != "aa:bb:cc:dd:ee:01" {
		t.Errorf("10.20.0.3 mac = %q, want the neighbor cache entry", cached.MACAddress)
	}
	if !equalStrings(cached.Evidence, []string{MethodNeighborCache, MethodTCPConnect}) {
		t.Errorf("10.20.0.3 evidence = %v, want [%s %s]", cached.Evidence, MethodNeighborCache, MethodTCPConnect)
	}
	if cached.Hostname != "nas.internal" {
		t.Errorf("10.20.0.3 hostname = %q, want nas.internal", cached.Hostname)
	}
	if len(cached.OpenPorts) != 1 || cached.OpenPorts[0].Port != 22 || cached.OpenPorts[0].Protocol != "tcp" {
		t.Fatalf("10.20.0.3 open ports = %+v, want one tcp/22", cached.OpenPorts)
	}
	if cached.OpenPorts[0].Banner != "SSH-2.0-OpenSSH_9.6" {
		t.Errorf("10.20.0.3 banner = %q, want the greeting the service volunteered", cached.OpenPorts[0].Banner)
	}

	cacheOnly, _ := findingFor(hosts, "10.20.0.6")
	if !equalStrings(cacheOnly.Evidence, []string{MethodNeighborCache}) {
		t.Errorf("10.20.0.6 evidence = %v, want [%s]", cacheOnly.Evidence, MethodNeighborCache)
	}
	if len(cacheOnly.OpenPorts) != 0 {
		t.Errorf("10.20.0.6 open ports = %+v, want none — nothing answered", cacheOnly.OpenPorts)
	}

	if summary.Outcome != frame.DiscoveryOutcomeCompleted {
		t.Errorf("summary outcome = %q, want %q (msg %q)", summary.Outcome, frame.DiscoveryOutcomeCompleted, summary.Msg)
	}
	if !summary.Terminal {
		t.Error("summary is not marked terminal")
	}
	if summary.HostsFound == nil || *summary.HostsFound != 3 {
		t.Errorf("summary hosts_found = %v, want 3", summary.HostsFound)
	}
	if summary.AddressesScanned == nil || *summary.AddressesScanned != 8 {
		t.Errorf("summary addresses_scanned = %v, want 8 (the whole /29)", summary.AddressesScanned)
	}
	if summary.IPAddress != "" {
		t.Errorf("summary carries ip_address %q; a summary describes the dispatch, not an address", summary.IPAddress)
	}

	// And nothing follows the summary: exactly one terminal frame per dispatch is what lets the
	// backend finalize a job on the first one it sees.
	select {
	case extra := <-h.out:
		t.Fatalf("a frame arrived after the terminal summary: %s", extra.Payload)
	case <-time.After(300 * time.Millisecond):
	}
}

// TestDiscoveryRuntime_FindingIDsAreReplayStable pins the property that makes the server's
// uq_scan_results_job_finding an idempotency key rather than a race: replaying a spooled frame
// must collide with the row it already wrote, so the id cannot be random per emission.
func TestDiscoveryRuntime_FindingIDsAreReplayStable(t *testing.T) {
	run := func(t *testing.T) map[string]string {
		t.Helper()
		h := newHarness(t)
		h.neighbors = []Neighbor{neighbor(t, "10.20.0.3", "aa:bb:cc:dd:ee:01")}
		h.start(t)
		if err := h.rt.Request(request(t, testDispatchID)); err != nil {
			t.Fatalf("Request error = %v", err)
		}
		hosts, summary := drainUntilSummary(t, h.out, 10*time.Second)
		ids := map[string]string{"summary": summary.FindingID}
		for _, host := range hosts {
			ids[host.IPAddress] = host.FindingID
		}
		return ids
	}

	first := run(t)
	second := run(t)

	if len(first) != 2 {
		t.Fatalf("first run produced ids %v, want one host and one summary", first)
	}
	for key, id := range first {
		if second[key] != id {
			t.Errorf("%s finding_id = %q on replay, want the first run's %q", key, second[key], id)
		}
	}

	digest := sha256.Sum256([]byte(testDispatchID + "|" + frame.DiscoveryKindHost + "|10.20.0.3"))
	if want := hex.EncodeToString(digest[:]); first["10.20.0.3"] != want {
		t.Errorf("host finding_id = %q, want the dispatch|kind|address digest %q", first["10.20.0.3"], want)
	}
	// The server's column is String(64) and its validator demands lowercase hex; an id that
	// misses either becomes a psycopg DataError inside the /link read loop.
	for key, id := range first {
		if len(id) != 64 || strings.ToLower(id) != id {
			t.Errorf("%s finding_id = %q, want 64 lowercase hex characters", key, id)
		}
		if _, err := hex.DecodeString(id); err != nil {
			t.Errorf("%s finding_id = %q is not hex: %v", key, id, err)
		}
	}
	if first["summary"] == first["10.20.0.3"] {
		t.Error("the summary and the host share a finding_id; kind must be part of the digest")
	}
}

// TestDiscoveryRuntime_SecondRequestForALiveDispatchIsRefused mirrors probe.Runtime's duplicate
// handling: the refusal is an error only. Emitting a summary would close a dispatch whose real
// terminal frame is still coming and finalize the job on a rejection.
func TestDiscoveryRuntime_SecondRequestForALiveDispatchIsRefused(t *testing.T) {
	release := make(chan struct{})
	defer close(release)
	dialing := make(chan struct{}, 1)

	h := newHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		select {
		case <-release:
		case <-ctx.Done():
		}
		return errors.New("connection refused")
	}
	h.start(t)

	if err := h.rt.Request(request(t, testDispatchID)); err != nil {
		t.Fatalf("first Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the first dispatch never started work")
	}

	err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.ScanJobID = 999
	}))
	if !errors.Is(err, ErrDuplicateDispatch) {
		t.Fatalf("second Request error = %v, want %v", err, ErrDuplicateDispatch)
	}

	select {
	case f := <-h.out:
		t.Fatalf("the refused duplicate emitted a frame: %s", f.Payload)
	case <-time.After(300 * time.Millisecond):
	}
	if open := h.rt.OpenDispatches(); open != 1 {
		t.Fatalf("OpenDispatches = %d, want 1 — the duplicate must not have been recorded", open)
	}
}

// TestDiscoveryRuntime_CancelStopsWorkAndStillSummarizes pins plan §4: cancellation is
// best-effort at the protocol level but the dispatch still has to close itself out, or the
// backend waits out the whole dispatch deadline for a job that stopped minutes ago.
func TestDiscoveryRuntime_CancelStopsWorkAndStillSummarizes(t *testing.T) {
	dialing := make(chan struct{}, 1)

	h := newHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)

	// A /24 is 256 addresses at four at a time with a testHostTimeout budget: left alone this runs
	// for about thirteen seconds, so finishing promptly can only be the cancellation.
	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the dispatch never started work")
	}

	start := time.Now()
	if err := h.rt.Cancel(cancellation(t, testDispatchID, "job_cancelled")); err != nil {
		t.Fatalf("Cancel error = %v", err)
	}
	_, summary := drainUntilSummary(t, h.out, 5*time.Second)
	elapsed := time.Since(start)

	// One host timeout is the bound, derived from the request rather than restated: the addresses
	// already in flight collapse on the dispatch context and no new one is handed out. Two budgets
	// of tolerance is the -race scheduler's, and nothing more — a cancellation that degraded into
	// waiting out the sweep or the dispatch deadline would take tens of seconds, and one that
	// merely let the in-flight hosts time out would take one budget more than this allows.
	if bound := 2 * testHostTimeout; elapsed > bound {
		t.Errorf("the summary took %s after the cancel, want within %s (two %s host timeouts)",
			elapsed, bound, testHostTimeout)
	}
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Fatalf("summary outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeCancelled)
	}
	if !strings.Contains(summary.Msg, "job_cancelled") {
		t.Errorf("summary msg = %q, want the cancellation reason", summary.Msg)
	}
	if summary.AddressesScanned == nil || *summary.AddressesScanned >= 256 {
		t.Errorf("summary addresses_scanned = %v, want fewer than the whole /24", summary.AddressesScanned)
	}
}

// TestDiscoveryRuntime_RejectedRequestEmitsOnlyASummary pins the shape of a refusal: one
// terminal frame carrying the validator's machine-readable reason, and no network activity of
// any kind. The reason travels in error_code because that is the field the backend maps onto a
// ScanJob.error_reason; a refusal explained only in prose closes the job as "failed" with
// nothing an operator can act on.
func TestDiscoveryRuntime_RejectedRequestEmitsOnlyASummary(t *testing.T) {
	cases := []struct {
		name     string
		validate Validator
		mutate   func(*frame.DiscoveryRequestPayload)
		wantCode string
	}{
		{
			// A stub validator, which pins only that the runtime carries whatever code it is
			// handed. The constant rather than its spelling: a hand-written string here would keep
			// passing after validate.go renamed the code, and the assertion's whole subject is that
			// the two agree.
			name: "a stub validator's code reaches the summary",
			validate: func(frame.DiscoveryRequestPayload, netscope.Scope) Rejection {
				return Rejection{Code: ErrorCodeScopeVersionMismatch, Msg: "the request's scope version is stale"}
			},
			wantCode: ErrorCodeScopeVersionMismatch,
		},
		{
			// And the real validator, which is what makes the row above more than a tautology: a
			// stub can only report a code someone typed into this file, so nothing here otherwise
			// proves the runtime and the validator name the same refusal. D-16's stale dispatch is
			// the case that matters most — the request was built against an authorization this
			// agent no longer holds.
			name:     "the real validator refuses a scope version the agent no longer holds",
			validate: NewValidator(capability.DefaultLocalDiscoveryConfig(), nil),
			mutate: func(p *frame.DiscoveryRequestPayload) {
				p.ScopeVersion = "5741e5c09ec0"
			},
			wantCode: ErrorCodeScopeVersionMismatch,
		},
		{
			// The same real validator on a target the agent was never attached to, whose code is
			// netscope's own reason carried through verbatim. It is here because it travels a
			// different path than the version check — through the one scope evaluator — and a
			// runtime that flattened every refusal onto one code would still pass the row above.
			name:     "the real validator refuses a target outside the agent's scope",
			validate: NewValidator(capability.DefaultLocalDiscoveryConfig(), nil),
			mutate: func(p *frame.DiscoveryRequestPayload) {
				p.Targets = []string{"10.99.0.0/29"}
			},
			wantCode: netscope.ReasonOutOfScope,
		},
		{
			// A runtime with no validator scans nothing. Defaulting the other way would make a
			// wiring mistake indistinguishable from an approval.
			name:     "no validator is installed",
			validate: nil,
			wantCode: ErrorCodeValidationUnavailable,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			h := newHarness(t)
			h.validate = tc.validate
			h.refuseNeighbors = true
			h.start(t)

			mutate := []func(*frame.DiscoveryRequestPayload){}
			if tc.mutate != nil {
				mutate = append(mutate, tc.mutate)
			}
			err := h.rt.Request(request(t, testDispatchID, mutate...))
			if err == nil {
				t.Fatal("Request returned no error for a refused request")
			}
			if !errors.Is(err, ErrRejected) {
				t.Fatalf("Request error = %v, want it to wrap %v", err, ErrRejected)
			}

			summary := nextFinding(t, h.out, 5*time.Second)
			if summary.Kind != frame.DiscoveryKindSummary || !summary.Terminal {
				t.Fatalf("first frame is kind %q terminal %v, want a terminal summary", summary.Kind, summary.Terminal)
			}
			if summary.Outcome != frame.DiscoveryOutcomeRejected {
				t.Errorf("outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeRejected)
			}
			if summary.ErrorCode != tc.wantCode {
				t.Errorf("error_code = %q, want %q", summary.ErrorCode, tc.wantCode)
			}
			if summary.HostsFound == nil || *summary.HostsFound != 0 {
				t.Errorf("hosts_found = %v, want 0", summary.HostsFound)
			}
			if summary.AddressesScanned == nil || *summary.AddressesScanned != 0 {
				t.Errorf("addresses_scanned = %v, want 0", summary.AddressesScanned)
			}

			select {
			case extra := <-h.out:
				t.Fatalf("a refused request emitted a second frame: %s", extra.Payload)
			case <-time.After(300 * time.Millisecond):
			}
			if dialed := h.sweepNet.addresses(); len(dialed) != 0 {
				t.Errorf("a refused request dialed %v", dialed)
			}
			if calls := h.neighborCalls.Load(); calls != 0 {
				t.Errorf("a refused request read the neighbor cache %d times", calls)
			}
			if open := h.rt.OpenDispatches(); open != 0 {
				t.Errorf("OpenDispatches = %d after a refusal, want 0", open)
			}
		})
	}
}

// TestDiscoveryRuntime_FreshRuntimeRefusesUntilAGrantEnablesIt pins the fail-closed default plan
// §7 rests on: construction is not authorization. This Runtime holds a working validator and a
// real derived scope — every ingredient of an approval except the approval — and it still scans
// nothing, because the only thing allowed to say "granted" is a capabilities.set grant arriving
// through Configure.
//
// Defaulting the other way would make a caller that forgot the grant check scan before any grant
// existed, and it would do so silently: the request would simply succeed.
func TestDiscoveryRuntime_FreshRuntimeRefusesUntilAGrantEnablesIt(t *testing.T) {
	h := newHarness(t)
	h.granted = false
	h.neighbors = []Neighbor{neighbor(t, "10.20.0.3", "aa:bb:cc:dd:ee:01")}
	h.start(t)

	err := h.rt.Request(request(t, testDispatchID))
	if !errors.Is(err, ErrNotEnabled) {
		t.Fatalf("Request on an ungranted runtime error = %v, want it to wrap %v", err, ErrNotEnabled)
	}

	// A refusal, not silence. The backend's job is waiting on a terminal frame; without one it
	// hangs until the dispatch deadline expires and the operator is told nothing useful.
	refusal := nextFinding(t, h.out, 5*time.Second)
	if refusal.Kind != frame.DiscoveryKindSummary || !refusal.Terminal {
		t.Fatalf("first frame is kind %q terminal %v, want a terminal summary", refusal.Kind, refusal.Terminal)
	}
	if refusal.Outcome != frame.DiscoveryOutcomeRejected {
		t.Errorf("outcome = %q, want %q", refusal.Outcome, frame.DiscoveryOutcomeRejected)
	}
	// capability_disabled, and specifically not validation_unavailable: the two are different
	// failures that the backend maps to different D-4 error_reasons — "this agent was never
	// granted local_discovery" is an authorization answer an operator can act on, while "this
	// agent has no validator" is a build or wiring fault. Collapsing them would hide the second
	// behind the first for every ungranted request.
	if refusal.ErrorCode != ErrorCodeCapabilityDisabled {
		t.Errorf("error_code = %q, want %q", refusal.ErrorCode, ErrorCodeCapabilityDisabled)
	}
	if refusal.ErrorCode == ErrorCodeValidationUnavailable {
		t.Errorf("error_code = %q; a valid validator was installed, so this is not a validation fault",
			refusal.ErrorCode)
	}
	if calls := h.neighborCalls.Load(); calls != 0 {
		t.Errorf("an ungranted request read the neighbor cache %d times", calls)
	}
	if dialed := h.sweepNet.addresses(); len(dialed) != 0 {
		t.Errorf("an ungranted request dialed %v", dialed)
	}
	if open := h.rt.OpenDispatches(); open != 0 {
		t.Errorf("OpenDispatches = %d after an ungranted refusal, want 0", open)
	}

	// Now the grant arrives, carrying the same scope and the same validator the constructor was
	// already handed. Replaying the identical request proves the refusal above was the missing
	// grant and nothing else about the payload.
	h.rt.Configure(h.scope, h.validate)
	if err := h.rt.Request(request(t, testDispatchID)); err != nil {
		t.Fatalf("Request after a grant error = %v", err)
	}
	hosts, summary := drainUntilSummary(t, h.out, 10*time.Second)
	if got := findingAddresses(hosts); !equalStrings(got, []string{"10.20.0.3"}) {
		t.Errorf("host findings after a grant = %v, want [10.20.0.3]", got)
	}
	if summary.Outcome != frame.DiscoveryOutcomeCompleted {
		t.Errorf("summary outcome after a grant = %q, want %q (msg %q)",
			summary.Outcome, frame.DiscoveryOutcomeCompleted, summary.Msg)
	}
}

// TestDiscoveryRuntime_DisableRefusesAndStopsWork pins plan §7's "capability disable stops
// current and future discovery": an in-flight dispatch closes out as cancelled and the next
// request is refused with a reason the backend can act on.
func TestDiscoveryRuntime_DisableRefusesAndStopsWork(t *testing.T) {
	dialing := make(chan struct{}, 1)

	h := newHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)

	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the dispatch never started work")
	}

	h.rt.Disable("capability_disabled")

	_, summary := drainUntilSummary(t, h.out, 5*time.Second)
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Fatalf("in-flight summary outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeCancelled)
	}

	err := h.rt.Request(request(t, "0123456789abcdef0123456789abcdef"))
	if !errors.Is(err, ErrNotEnabled) {
		t.Fatalf("Request after Disable error = %v, want %v", err, ErrNotEnabled)
	}
	refusal := nextFinding(t, h.out, 5*time.Second)
	if refusal.Outcome != frame.DiscoveryOutcomeRejected || refusal.ErrorCode != ErrorCodeCapabilityDisabled {
		t.Fatalf("refusal outcome = %q error_code = %q, want %q/%q",
			refusal.Outcome, refusal.ErrorCode, frame.DiscoveryOutcomeRejected, ErrorCodeCapabilityDisabled)
	}
}

// TestDiscoveryRuntime_ExpiredRequestIsAnExecutionErrorNotASilentDrop pins the one deadline the
// runtime owns itself: the validator refuses a request that was already stale on arrival, but a
// dispatch can also sit in the queue past its deadline, and that has to close the job too.
func TestDiscoveryRuntime_ExpiredRequestIsAnExecutionErrorNotASilentDrop(t *testing.T) {
	h := newHarness(t)
	h.refuseNeighbors = true
	h.start(t)

	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.DeadlineAt = time.Now().UTC().Add(-time.Second)
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}

	summary := nextFinding(t, h.out, 5*time.Second)
	if summary.Kind != frame.DiscoveryKindSummary {
		t.Fatalf("first frame kind = %q, want a summary", summary.Kind)
	}
	if summary.Outcome != frame.DiscoveryOutcomeExecutionError {
		t.Errorf("outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeExecutionError)
	}
	if summary.ErrorCode != ErrorCodeDeadlineExceeded {
		t.Errorf("error_code = %q, want %q", summary.ErrorCode, ErrorCodeDeadlineExceeded)
	}
	if dialed := h.sweepNet.addresses(); len(dialed) != 0 {
		t.Errorf("an expired dispatch dialed %v", dialed)
	}
}

// TestDiscoveryRuntime_DeadlineReachedMidSweepIsAnExecutionErrorWithPartialFindings closes the
// other half of the deadline story, and it is the half a completed-looking summary hides.
//
// The runtime checks req.DeadlineAt once, before the sweep starts. A dispatch that was live on
// arrival and *ran out of time mid-sweep* leaves that check untouched, and the only signal is the
// error Liveness.Sweep returns — whose sole source is ctx.Err(). Discarding it reports
// outcome="completed" for a scan that covered a fraction of its targets: the backend finalizes the
// job as a clean success, the operator sees a /24 with four hosts in it, and Task 5's
// execution_error arm of the closed outcome vocabulary is unreachable by construction.
//
// The counts are retained rather than zeroed, per D-4's spirit: the hosts observed before the
// deadline were still observed, and the job keeps them and is reviewable. What changes is the
// outcome, which is what tells an operator the coverage is partial.
func TestDiscoveryRuntime_DeadlineReachedMidSweepIsAnExecutionErrorWithPartialFindings(t *testing.T) {
	// Short enough that a /24 cannot finish inside it, long enough that the dispatch certainly
	// starts work: the pre-sweep check must not be what fires, or this test would be a second copy
	// of the expired-on-arrival one above.
	const budget = 600 * time.Millisecond
	// A tenth of the default, so the sweep turns over several waves of hosts inside the budget and
	// addresses_scanned is unambiguously partial rather than zero.
	const hostTimeoutMS = 100

	h := newHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, address string) error {
		// One host answers, so the summary has a non-zero hosts_found to retain. It is in the first
		// wave of a /24 scanned in ascending order, so it is reached well inside the budget.
		if address == "10.20.0.3:22" {
			return nil
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)

	started := time.Now()
	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
		p.HostTimeoutMS = hostTimeoutMS
		p.DeadlineAt = time.Now().UTC().Add(budget)
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}

	hosts, summary := drainUntilSummary(t, h.out, 10*time.Second)
	elapsed := time.Since(started)

	if summary.Outcome != frame.DiscoveryOutcomeExecutionError {
		t.Fatalf("summary outcome = %q, want %q — a scan that blew its deadline mid-sweep did not complete (msg %q)",
			summary.Outcome, frame.DiscoveryOutcomeExecutionError, summary.Msg)
	}
	if summary.ErrorCode != ErrorCodeDeadlineExceeded {
		t.Errorf("error_code = %q, want %q", summary.ErrorCode, ErrorCodeDeadlineExceeded)
	}
	if !summary.Terminal || summary.Kind != frame.DiscoveryKindSummary {
		t.Errorf("kind = %q terminal = %v, want a terminal summary", summary.Kind, summary.Terminal)
	}
	// The message has to name the deadline: error_code says which limit, msg says which value, and
	// an operator whose scans keep coming back partial has to be able to tell a too-short job
	// timeout from a too-large target.
	if !strings.Contains(summary.Msg, "deadline") {
		t.Errorf("summary msg = %q, want it to name the deadline that ran out", summary.Msg)
	}

	// Partial, both directions. Zero would mean the pre-sweep check fired and this test is
	// exercising the wrong path; the whole /24 would mean the sweep finished and the deadline was
	// never reached at all.
	if summary.AddressesScanned == nil {
		t.Fatal("addresses_scanned is absent; a partial scan has to report how far it got")
	}
	if scanned := *summary.AddressesScanned; scanned == 0 || scanned >= 255 {
		t.Fatalf("addresses_scanned = %d, want a partial count of the /24's 255 scannable addresses", scanned)
	}
	// And the findings themselves survive the deadline, which is the whole reason the outcome
	// changes rather than the counts.
	if summary.HostsFound == nil || *summary.HostsFound != 1 {
		t.Errorf("hosts_found = %v, want the one host observed before the deadline", summary.HostsFound)
	}
	if got := findingAddresses(hosts); !equalStrings(got, []string{"10.20.0.3"}) {
		t.Errorf("host findings = %v, want the host that answered before the deadline", got)
	}

	// A deadline is a deadline: it must not be honoured only after the sweep would have finished
	// anyway. Two budgets of tolerance covers the enrichment drain and the -race scheduler; a /24
	// at this host timeout would take some twenty-five seconds.
	if bound := 2 * budget; elapsed > bound {
		t.Errorf("the summary took %s, want within %s of the request", elapsed, bound)
	}
}

// TestDiscoveryRuntime_CancellationOutranksAnExpiredDeadline pins the distinction the arm above
// must not blur. A cancelled dispatch reports outcome="cancelled" even when its deadline ran out in
// the same moment: the backend closes the job as cancelled, not as an agent fault, and misreporting
// a deliberate stop as an execution error would put the blame on the wrong side of an incident.
func TestDiscoveryRuntime_CancellationOutranksAnExpiredDeadline(t *testing.T) {
	dialing := make(chan struct{}, 1)

	h := newHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)

	// A deadline short enough to be racing the cancellation below, over a /24 that cannot finish
	// inside it either way.
	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
		p.HostTimeoutMS = 100
		p.DeadlineAt = time.Now().UTC().Add(300 * time.Millisecond)
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the dispatch never started work")
	}
	if err := h.rt.Cancel(cancellation(t, testDispatchID, "job_cancelled")); err != nil {
		t.Fatalf("Cancel error = %v", err)
	}

	_, summary := drainUntilSummary(t, h.out, 10*time.Second)
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Fatalf("summary outcome = %q, want %q — a cancelled dispatch is not an agent fault (msg %q)",
			summary.Outcome, frame.DiscoveryOutcomeCancelled, summary.Msg)
	}
	if summary.ErrorCode != "" {
		t.Errorf("error_code = %q, want none: cancellation is not a failure the operator has to act on", summary.ErrorCode)
	}
	if !strings.Contains(summary.Msg, "job_cancelled") {
		t.Errorf("summary msg = %q, want the cancellation reason", summary.Msg)
	}
}

// TestDiscoveryRuntime_NeighborCacheFailureDegradesRatherThanFailing pins plan §1's four-method
// design: the cache is one source of evidence, and a kernel that will not give one up must not
// cost the operator the ICMP and TCP results.
func TestDiscoveryRuntime_NeighborCacheFailureDegradesRatherThanFailing(t *testing.T) {
	h := newHarness(t)
	h.neighborsErr = ErrNeighborsUnsupported
	h.sweepNet.dialReply = func(_ context.Context, address string) error {
		if address == "10.20.0.3:22" {
			return nil
		}
		return errors.New("connection refused")
	}
	h.start(t)

	if err := h.rt.Request(request(t, testDispatchID)); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	hosts, summary := drainUntilSummary(t, h.out, 10*time.Second)

	if got := findingAddresses(hosts); !equalStrings(got, []string{"10.20.0.3"}) {
		t.Fatalf("host findings = %v, want just the host that answered a connect", got)
	}
	if hosts[0].MACAddress != "" {
		t.Errorf("mac = %q with no cache to read it from", hosts[0].MACAddress)
	}
	if summary.Outcome != frame.DiscoveryOutcomeCompleted {
		t.Errorf("outcome = %q, want %q — a missing cache is a degradation", summary.Outcome, frame.DiscoveryOutcomeCompleted)
	}
	if !strings.Contains(summary.Msg, "neighbor") {
		t.Errorf("summary msg = %q, want it to name the collector that was unavailable", summary.Msg)
	}
}

// TestDiscoveryRuntime_TargetsAreFilteredThroughTheOneScopeEvaluator pins the package doc's rule
// that this collector holds no CIDR opinion: a request whose prefix reaches an address netscope
// refuses must not probe it, even though the backend approved the prefix.
func TestDiscoveryRuntime_TargetsAreFilteredThroughTheOneScopeEvaluator(t *testing.T) {
	h := newHarness(t)
	h.start(t)

	// 10.20.0.248/29 covers .248-.255, and .255 is the scope /24's directed broadcast.
	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.248/29"}
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	_, summary := drainUntilSummary(t, h.out, 10*time.Second)

	if summary.AddressesScanned == nil || *summary.AddressesScanned != 7 {
		t.Fatalf("addresses_scanned = %v, want 7 — the /24's broadcast is not a host", summary.AddressesScanned)
	}
	for _, address := range h.sweepNet.addresses() {
		if strings.HasPrefix(address, "10.20.0.255:") {
			t.Fatalf("dialed the directed broadcast %s", address)
		}
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// --- Back-pressure: a terminal summary is the one frame that may never be dropped -------------

// fillerDispatchID stands for a dispatch whose host findings are already queued ahead of the
// summaries these tests are about. It is never requested, so nothing else in the runtime knows it.
const fillerDispatchID = "f111e222d333c444b555a66677788899"

// nonBlockingBudget is how long a handler bound under link's enqueue-only contract is allowed to
// take. It is generous on purpose: the assertion is "does not wait on a consumer", and a consumer
// in these tests is stalled for the whole test, so anything that waits on one waits forever. A
// tighter bound would only make the test flaky on a loaded machine without pinning anything more.
const nonBlockingBudget = 2 * time.Second

// stalledHarness is a harness whose outbound channel nobody reads.
//
// An unbuffered `out` with no reader is what the link looks like between connections — and,
// because link's runOnce reads inbound frames and Options.DataFrames from the *same* select, it is
// also what the link looks like for the entire time a discovery.request handler is running. That
// coupling is why back-pressure is not a rare condition here: the goroutine that would have to
// drain `out` is the goroutine calling Request.
func stalledHarness(t *testing.T) *harness {
	t.Helper()
	h := newHarness(t)
	h.out = make(chan frame.Frame)
	return h
}

// saturateFindings fills the finding buffer and reports how many frames it parked there.
//
// It writes to the buffer directly instead of running a 128-host sweep into it: the condition
// under test is "the buffer is full", and reaching it through a real sweep would make the sweep's
// concurrency the test's subject. Once the pump is blocked on the unread `out` the buffer cannot
// drain again, so "full" stays true for the rest of the test.
func saturateFindings(t *testing.T, h *harness) int {
	t.Helper()
	filler := h.rt.findingFrame(fillerDispatchID, frame.DiscoveryFindingPayload{
		DispatchID: fillerDispatchID,
		ScanJobID:  481,
		FindingID:  findingID(fillerDispatchID, frame.DiscoveryKindHost, "10.20.0.9"),
		Kind:       frame.DiscoveryKindHost,
		ObservedAt: time.Now().UTC(),
		IPAddress:  "10.20.0.9",
	})
	for parked := 0; parked <= findingBufferSize*2; parked++ {
		select {
		case h.rt.findings <- filler:
		default:
			if parked < findingBufferSize {
				t.Fatalf("parked only %d frames before the buffer refused more, want at least %d",
					parked, findingBufferSize)
			}
			return parked
		}
	}
	t.Fatal("the finding buffer never filled; something is draining it")
	return 0
}

// summaryFor drains `out` until the terminal summary for dispatchID arrives, skipping the frames
// saturateFindings parked and every other dispatch's traffic.
//
// It fails if a *non*-terminal frame for dispatchID shows up first, which is the ordering half of
// the contract: the backend finalizes a job on the first terminal frame it sees, so a host finding
// that overtook the summary would be rejected as late.
func summaryFor(t *testing.T, out <-chan frame.Frame, dispatchID string, timeout time.Duration) frame.DiscoveryFindingPayload {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case f := <-out:
			if f.Type != frame.TypeDiscoveryFinding {
				t.Fatalf("frame type = %q, want %q", f.Type, frame.TypeDiscoveryFinding)
			}
			var payload frame.DiscoveryFindingPayload
			if err := json.Unmarshal(f.Payload, &payload); err != nil {
				t.Fatalf("decode discovery.finding payload: %v", err)
			}
			if payload.DispatchID != dispatchID {
				continue
			}
			if payload.Kind != frame.DiscoveryKindSummary || !payload.Terminal {
				t.Fatalf("dispatch %s sent a non-terminal %s finding before its summary",
					dispatchID, payload.Kind)
			}
			return payload
		case <-deadline:
			t.Fatalf("no terminal summary for dispatch %s within %s — a summary dropped under "+
				"back-pressure leaves the scan job hanging until its dispatch deadline expires",
				dispatchID, timeout)
		}
	}
}

// withinBudget runs fn on another goroutine and fails if it has not returned within budget.
//
// What it pins is worth naming: Request and Cancel are bound under link's enqueue-only contract and
// run on the inbound goroutine that also drives the heartbeat, the rekey and the drain tickers, so
// one that waits on a consumer stalls all three; Stop is the daemon's exit path, so one that waits
// on a consumer hangs the process instead of one scan job.
//
// fn must not touch t: it outlives the assertion when the budget blows. That is the point — the
// failure mode being pinned is a call that never returns, and a t.Fatal from a goroutine still
// parked inside the subject would report the wrong thing.
func withinBudget(t *testing.T, what string, budget time.Duration, fn func()) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		defer close(done)
		fn()
	}()
	select {
	case <-done:
	case <-time.After(budget):
		t.Fatalf("%s did not return within %s: it is waiting on a consumer that nobody is reading",
			what, budget)
	}
}

// TestDiscoveryRuntime_RefusalSummarySurvivesASaturatedConsumer pins the frame this collector may
// never drop. A refusal's terminal summary is what closes the scan job; lose it and the backend
// waits out the whole dispatch deadline and then closes the job with the wrong reason — precisely
// the hanging job the slice exists to prevent.
func TestDiscoveryRuntime_RefusalSummarySurvivesASaturatedConsumer(t *testing.T) {
	h := stalledHarness(t)
	h.validate = func(frame.DiscoveryRequestPayload, netscope.Scope) Rejection {
		return Rejection{Code: ErrorCodeScopeVersionMismatch, Msg: "the scope moved under this request"}
	}
	h.refuseNeighbors = true
	h.start(t)
	saturateFindings(t, h)

	if err := h.rt.Request(request(t, testDispatchID)); !errors.Is(err, ErrRejected) {
		t.Fatalf("Request error = %v, want it to wrap %v", err, ErrRejected)
	}

	summary := summaryFor(t, h.out, testDispatchID, 5*time.Second)
	if summary.Outcome != frame.DiscoveryOutcomeRejected {
		t.Errorf("outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeRejected)
	}
	if summary.ErrorCode != ErrorCodeScopeVersionMismatch {
		t.Errorf("error_code = %q, want %q", summary.ErrorCode, ErrorCodeScopeVersionMismatch)
	}
}

// TestDiscoveryRuntime_CancelledQueuedDispatchSummarySurvivesASaturatedConsumer covers the other
// path that closes a dispatch from off the scan goroutines: a cancellation that arrives while the
// dispatch is still queued. Nothing will ever run it, so this summary is the only frame that
// dispatch will ever produce, and dropping it hangs the job exactly as a dropped refusal does.
//
// It also times Cancel, because Cancel is bound under the same enqueue-only contract as Request.
func TestDiscoveryRuntime_CancelledQueuedDispatchSummarySurvivesASaturatedConsumer(t *testing.T) {
	const queuedDispatchID = "0d1c2b3a49586776859493a2b1c0d0e0"
	dialing := make(chan struct{}, 1)

	h := stalledHarness(t)
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)

	// The dispatcher is serial, so a dispatch that is busy dialing a /24 is what keeps the second
	// request in the queue rather than running it.
	if err := h.rt.Request(request(t, testDispatchID, func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
	})); err != nil {
		t.Fatalf("Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the first dispatch never started work")
	}
	if err := h.rt.Request(request(t, queuedDispatchID)); err != nil {
		t.Fatalf("queued Request error = %v", err)
	}
	saturateFindings(t, h)

	withinBudget(t, "Cancel", nonBlockingBudget, func() {
		_ = h.rt.Cancel(cancellation(t, queuedDispatchID, "profile_disabled"))
	})

	summary := summaryFor(t, h.out, queuedDispatchID, 5*time.Second)
	if summary.Outcome != frame.DiscoveryOutcomeCancelled {
		t.Errorf("outcome = %q, want %q", summary.Outcome, frame.DiscoveryOutcomeCancelled)
	}
	if !strings.Contains(summary.Msg, "profile_disabled") {
		t.Errorf("msg = %q, want it to name the cancellation reason", summary.Msg)
	}
}

// TestDiscoveryRuntime_RequestNeverBlocksOnASaturatedConsumerAndLosesNoSummary is the invariant
// most easily broken while fixing the drop: the obvious repair is to make the refusal *wait* for
// room, and that wait would land on link's inbound goroutine.
//
// The burst is deliberately longer than DispatchQueueCapacity. A fixed-size second buffer would
// pass the one-refusal test above and start dropping here, which is the realistic shape of the
// failure: refusals arrive back-to-back on the one goroutine that link would otherwise be draining
// `out` with, so none of them can be forwarded until the last of them returns.
func TestDiscoveryRuntime_RequestNeverBlocksOnASaturatedConsumerAndLosesNoSummary(t *testing.T) {
	const burst = DispatchQueueCapacity * 2

	h := stalledHarness(t)
	h.granted = false // every request is refused with ErrorCodeCapabilityDisabled, and none of them works
	h.refuseNeighbors = true
	h.start(t)
	saturateFindings(t, h)

	ids := make([]string, burst)
	for i := range ids {
		ids[i] = fmt.Sprintf("%032x", i+1)
	}
	errs := make([]error, burst)
	withinBudget(t, fmt.Sprintf("a burst of %d Request calls", burst), nonBlockingBudget, func() {
		for i, id := range ids {
			errs[i] = h.rt.Request(request(t, id))
		}
	})
	for i, err := range errs {
		if !errors.Is(err, ErrNotEnabled) {
			t.Fatalf("Request %d error = %v, want it to wrap %v", i, err, ErrNotEnabled)
		}
	}

	for _, id := range ids {
		summary := summaryFor(t, h.out, id, 5*time.Second)
		if summary.Outcome != frame.DiscoveryOutcomeRejected {
			t.Fatalf("dispatch %s outcome = %q, want %q", id, summary.Outcome, frame.DiscoveryOutcomeRejected)
		}
	}
}

// TestDiscoveryRuntime_StopDoesNotWaitForUnsentSummaries pins the shutdown half. Moving the wait
// off link's goroutine puts it somewhere, and if that somewhere is joined by Stop then a saturated
// consumer at shutdown hangs the daemon's exit instead of hanging one scan job.
func TestDiscoveryRuntime_StopDoesNotWaitForUnsentSummaries(t *testing.T) {
	dialing := make(chan struct{}, 1)

	h := stalledHarness(t)
	h.granted = false
	h.sweepNet.dialReply = func(ctx context.Context, _ string) error {
		select {
		case dialing <- struct{}{}:
		default:
		}
		<-ctx.Done()
		return ctx.Err()
	}
	h.start(t)
	saturateFindings(t, h)

	// Two summaries with nowhere to go, from both off-scan paths: a refusal here and, in Stop
	// itself, the cancellation of everything still open.
	if err := h.rt.Request(request(t, testDispatchID)); !errors.Is(err, ErrNotEnabled) {
		t.Fatalf("Request error = %v, want it to wrap %v", err, ErrNotEnabled)
	}
	h.rt.Configure(h.scope, h.validate)
	if err := h.rt.Request(request(t, "0123456789abcdef0123456789abcdef", func(p *frame.DiscoveryRequestPayload) {
		p.Targets = []string{"10.20.0.0/24"}
	})); err != nil {
		t.Fatalf("granted Request error = %v", err)
	}
	select {
	case <-dialing:
	case <-time.After(5 * time.Second):
		t.Fatal("the granted dispatch never started work")
	}

	withinBudget(t, "Stop", nonBlockingBudget, h.rt.Stop)
}
